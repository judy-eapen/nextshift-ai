"""Latency diagnostics. Events are emitted on the LangGraph custom stream ({"diag": ...}) so consumers (UI, evals, CLI) collect them
per run without touching graph state or writing files. Outside a graph run (plain function calls) events go to a process-local list.
Never logs prompt text, answers or credentials — only names, roles, models, durations, token counts, SOCs and cache/retry flags."""
from __future__ import annotations
import functools, threading, time
from contextlib import contextmanager
from langgraph.config import get_stream_writer

FALLBACK: list[dict] = []          # events emitted outside a graph run (CLI/tests) land here
_local = threading.local()          # writer captured for worker threads spawned inside a node (reviewer batches)

def _writer():
    try: return get_stream_writer()
    except Exception: return getattr(_local, "writer", None)

def emit(kind: str, **kw):
    ev = {"diag": kind, "t": time.time(), **kw}
    w = _writer()
    if w:
        try: w(ev); return
        except Exception: pass
    FALLBACK.append(ev)

def capture_writer():
    """Call inside a node before spawning threads; the threads then call bind_writer(w)."""
    return _writer()

def bind_writer(w):
    _local.writer = w

@contextmanager
def span(kind: str, **kw):
    """with diag.span('tool', name='BLS', soc=...): ... → emits one event with ms and ok."""
    t0 = time.perf_counter(); info = dict(kw)
    try:
        yield info; info.setdefault("ok", True)
    except Exception:
        info["ok"] = False; raise
    finally:
        emit(kind, ms=round((time.perf_counter() - t0) * 1000), **info)

def timed(name: str, fn):
    """Wrap a graph node so every execution emits node_start / node_end with duration. Interrupt exceptions propagate untouched."""
    @functools.wraps(fn)
    def wrapper(*a, **k):
        emit("node_start", name=name); t0 = time.perf_counter()
        try:
            out = fn(*a, **k); emit("node_end", name=name, ms=round((time.perf_counter() - t0) * 1000), ok=True); return out
        except BaseException as e:   # GraphInterrupt is a BaseException subclass in some versions; record and re-raise
            emit("node_end", name=name, ms=round((time.perf_counter() - t0) * 1000), ok=type(e).__name__ in ("GraphInterrupt", "Interrupt", "NodeInterrupt"), interrupted=True); raise
    return wrapper

# ───────────────────────────── summaries (pure) ─────────────────────────────
def summarize(events: list[dict], segments: list[dict] | None = None) -> dict:
    """Concise perf record from a run's diag events. segments = [{"kind": interrupt kind, "wall_s": seconds the graph ran until that interrupt}] from the consumer."""
    nodes, llm, tools, cache = {}, [], [], {"hit": 0, "miss": 0}
    for e in events:
        k = e.get("diag")
        if k == "node_end":
            d = nodes.setdefault(e["name"], {"count": 0, "ms": 0}); d["count"] += 1; d["ms"] += e.get("ms", 0)
        elif k == "llm": llm.append(e)
        elif k == "tool": tools.append(e)
        elif k == "cache": cache[e.get("result", "miss")] = cache.get(e.get("result", "miss"), 0) + 1
    by_role = {}
    for e in llm:
        r = by_role.setdefault(e.get("role", "?"), {"calls": 0, "ms": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "retries": 0, "failed": 0, "model": e.get("model")})
        r["calls"] += 1; r["ms"] += e.get("ms", 0); r["tokens_in"] += e.get("tokens_in", 0) or 0; r["tokens_out"] += e.get("tokens_out", 0) or 0; r["cost_usd"] += e.get("cost_usd", 0) or 0
        r["retries"] += e.get("retries", 0) or 0; r["failed"] += 0 if e.get("ok", True) else 1
    for r in by_role.values(): r["cost_usd"] = round(r["cost_usd"], 4)
    top = sorted(([f"node:{n}", d["ms"]] for n, d in nodes.items()), key=lambda x: -x[1])[:5]
    return {"total_graph_ms": sum(d["ms"] for d in nodes.values()), "nodes_ms": dict(sorted(nodes.items(), key=lambda kv: -kv[1]["ms"])),
            "llm_calls": len(llm), "llm_ms": sum(e.get("ms", 0) for e in llm), "llm_by_role": by_role, "reviewer_calls": by_role.get("skeptic", {}).get("calls", 0), "reviewer_ms": by_role.get("skeptic", {}).get("ms", 0),
            "tool_calls": len(tools), "tool_ms": sum(e.get("ms", 0) for e in tools), "tools_failed": sum(1 for e in tools if not e.get("ok", True)),
            "tokens_in": sum((e.get("tokens_in") or 0) for e in llm), "tokens_out": sum((e.get("tokens_out") or 0) for e in llm), "cost_usd": round(sum((e.get("cost_usd") or 0) for e in llm), 4),
            "cache": cache, "top5": top, "segments": segments or []}

def phase_view(events: list[dict]) -> list[dict]:
    """Ordered node timeline for developer mode: [{name, ms, t}]."""
    return [{"name": e["name"], "ms": e.get("ms", 0), "t": e["t"]} for e in events if e.get("diag") == "node_end"]
