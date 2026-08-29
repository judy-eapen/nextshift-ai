"""Latency diagnostics: node/llm/tool events summarize correctly; nothing sensitive is recorded; no files written."""
import time
from graph import diag

def test_timed_wrapper_emits_start_end(monkeypatch):
    diag.FALLBACK.clear()
    f = diag.timed("n1", lambda s: {"x": 1}); assert f({}) == {"x": 1}
    kinds = [e["diag"] for e in diag.FALLBACK]; assert kinds == ["node_start", "node_end"] and diag.FALLBACK[1]["name"] == "n1" and "ms" in diag.FALLBACK[1]

def test_summary_counts_roles_tools_cache_and_top5():
    ev = [{"diag": "node_end", "name": "a", "ms": 100, "t": 1}, {"diag": "node_end", "name": "b", "ms": 300, "t": 2}, {"diag": "node_end", "name": "a", "ms": 50, "t": 3},
          {"diag": "llm", "role": "planner", "model": "m1", "ms": 900, "tokens_in": 10, "tokens_out": 5, "cost_usd": 0.001, "ok": True, "t": 4},
          {"diag": "llm", "role": "skeptic", "model": "m2", "ms": 2000, "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.002, "ok": True, "t": 5},
          {"diag": "tool", "name": "BLS", "ms": 30, "ok": True, "t": 6}, {"diag": "tool", "name": "Polymarket", "ms": 400, "ok": False, "t": 7},
          {"diag": "cache", "result": "hit", "t": 8}, {"diag": "cache", "result": "miss", "t": 9}, {"diag": "cache", "result": "hit", "t": 10}]
    s = diag.summarize(ev, [{"kind": "interview", "wall_s": 1.2}])
    assert s["total_graph_ms"] == 450 and s["nodes_ms"]["a"] == {"count": 2, "ms": 150} and s["top5"][0] == ["node:b", 300]
    assert s["llm_calls"] == 2 and s["reviewer_calls"] == 1 and s["reviewer_ms"] == 2000 and s["llm_by_role"]["planner"]["tokens_in"] == 10
    assert s["tool_calls"] == 2 and s["tools_failed"] == 1 and s["cache"] == {"hit": 2, "miss": 1} and s["segments"][0]["kind"] == "interview"
    assert s["cost_usd"] == 0.003

def test_events_carry_no_text_or_secrets(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "SECRET-XYZ"); diag.FALLBACK.clear()
    with diag.span("tool", name="BLS", soc="15-1252"): pass
    diag.emit("llm", role="planner", model="m", ms=1, ok=True, tokens_in=1, tokens_out=1)
    import json; blob = json.dumps(diag.FALLBACK)
    assert "SECRET-XYZ" not in blob and "prompt" not in blob and "answer" not in blob

def test_span_records_failure():
    diag.FALLBACK.clear()
    try:
        with diag.span("tool", name="X"): raise ValueError("boom")
    except ValueError: pass
    assert diag.FALLBACK[-1]["ok"] is False and diag.FALLBACK[-1]["ms"] >= 0

def test_worker_thread_events_are_collected_and_flushed():
    import threading
    diag.FALLBACK.clear(); buf = []
    def work():
        diag.bind_collector(buf); diag.emit("llm", role="skeptic", model="m", ms=5, ok=True); diag.bind_collector(None)
    th = threading.Thread(target=work); th.start(); th.join()
    assert len(buf) == 1 and diag.FALLBACK == []
    diag.flush(buf); assert buf == [] and diag.FALLBACK[-1]["role"] == "skeptic"

def test_thinking_reviewer_uses_small_parallel_batches(monkeypatch):
    from graph import review as rv
    seen = []
    def fake(chunk, system, max_tokens, role="skeptic"): seen.append(len(chunk)); return {j: {"verdict": "keep"} for j in range(len(chunk))}, 0.0
    monkeypatch.setattr(rv, "_judge_batch", fake)
    rv.judge_lines([(i, f"line {i}") for i in range(20)], "sys", batch=16, role="skeptic"); assert max(seen) <= 8
    seen.clear(); rv.judge_lines([(i, f"line {i}") for i in range(20)], "sys", batch=30, role="extractor"); assert seen == [20]
