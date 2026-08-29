"""Structured review: the reviewer judges the *structured objects* the UI renders, not a Markdown shadow of them.
flatten() turns nested dict/list objects into (path, text) leaves; apply_removals() deletes the failing leaves in place, so
what reaches the UI is exactly what survived review. Any Markdown export is generated afterwards from the reviewed object."""
from __future__ import annotations
import re
from typing import Any

REF = re.compile(r"\[([cu]\d{2,3})\]")
TAGS = ("[interpretation]", "[advice]")
# deterministic lint: certainty about the future is never allowed, regardless of citations
CERTAINTY = re.compile(r"\b(will be (automated|replaced|eliminated)|will disappear|will vanish|is safe from AI|guaranteed|100% safe|doomed|(is|are|become) obsolete|perfect (fit|match|career)|perfect for you|ideal career for you)\b", re.I)

PARAGRAPH_KEYS = ("direct_answer", "for_you", "our_read", "outlook_takeaway", "why_fit", "what_work_is_like", "how_ai_may_reshape", "human_capabilities", "tradeoff", "note", "what_people_do", "education_and_entry", "outlook", "how_ai_may_change", "risks_tradeoffs_uncertainty", "summary")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")

def split_sentences(text: str) -> list[str]: return [x for x in _SENT.split(text.strip()) if x.strip()]

def flatten(obj: Any, path: str = "", out: list | None = None, skip_keys=("card_id", "ref", "soc", "url", "id", "key", "penetration", "task", "label", "group", "title", "name", "resolution", "kind", "verdict", "separates")) -> list[tuple[str, str]]:
    """Every non-empty string leaf that is a *claim* (skip identifiers and verbatim task statements, which come from cards).
    Paragraph fields are emitted one sentence at a time as path#i, so one bad sentence doesn't take the paragraph with it."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip_keys or k.startswith("_"): continue
            if k in PARAGRAPH_KEYS and isinstance(v, str):
                for i, sent in enumerate(split_sentences(v)): out.append((f"{path}.{k}#{i}" if path else f"{k}#{i}", sent))
                continue
            flatten(v, f"{path}.{k}" if path else k, out, skip_keys)
    elif isinstance(obj, list):
        for i, v in enumerate(obj): flatten(v, f"{path}[{i}]", out, skip_keys)
    elif isinstance(obj, str) and len(obj.strip()) > 0: out.append((path, obj))
    return out

def _resolve(obj: Any, path: str):
    """Return (container, key) for a path like a.b[2].c."""
    tokens = re.findall(r"\[(\d+)\]|\.?([^.\[\]]+)", path); cur = obj; parent, key = None, None
    for idx, name in tokens:
        parent, key = cur, (int(idx) if idx else name)
        cur = cur[key]
    return parent, key

def apply_removals(obj: Any, paths: list[str]) -> Any:
    """Delete failing leaves. List items are removed (highest index first so earlier indices stay valid); dict leaves become ''."""
    list_removals: dict[str, list[int]] = {}; sent_removals: dict[str, set[int]] = {}
    for p in paths:
        ms = re.fullmatch(r"(.*)#(\d+)", p)
        if ms: sent_removals.setdefault(ms.group(1), set()).add(int(ms.group(2))); continue
        m = re.fullmatch(r"(.*)\[(\d+)\]", p)
        if m: list_removals.setdefault(m.group(1), []).append(int(m.group(2)))
        else:
            parent, key = _resolve(obj, p); parent[key] = ""
    for pp, idxs in sent_removals.items():
        parent, key = _resolve(obj, pp); parent[key] = " ".join(sn for i, sn in enumerate(split_sentences(parent[key])) if i not in idxs)
    for lp, idxs in list_removals.items():
        parent, key = _resolve(obj, lp) if lp else (None, None); lst = parent[key] if parent is not None else obj
        for i in sorted(set(idxs), reverse=True):
            if i < len(lst): del lst[i]
    return obj

def classify(text: str, refs: dict) -> str:
    """'heading' (exempt) · 'unknown_only' (cites only unknowns — self-evidently true) · 'advice' (tagged, no number, no card) · 'uncited' · 'fact'."""
    if text.startswith(("#", "**", "_")): return "heading"
    cited = [r for r in REF.findall(text) if r in refs]
    if cited and all(refs[r].startswith("unknown:") for r in cited): return "unknown_only"
    if not cited and any(t in text for t in TAGS) and not re.search(r"\d", text): return "advice"
    if not cited: return "uncited"
    return "fact"

def certainty_violation(text: str) -> bool: return bool(CERTAINTY.search(text))


def _judge_batch(chunk: list[tuple[int, str]], system: str, max_tokens: int, role: str = "skeptic") -> tuple[dict, float]:
    import json as _json
    from . import llm
    local = {j: idx for j, (idx, _) in enumerate(chunk)}
    listing = "\n\n".join(f"{j}. {txt}" for j, (_, txt) in enumerate(chunk))
    text, c = llm.chat(role, system + "\nRespond with valid JSON only: {\"verdicts\":[{\"i\":0,\"verdict\":\"keep\",\"reason\":\"...\"}]}", listing, max_tokens=max_tokens, temperature=0.0, purpose="review_batch")
    try: got = {int(v["i"]): v for v in _json.loads(re.search(r"\{.*\}", text, flags=re.S).group(0)).get("verdicts", []) if "i" in v}
    except Exception:
        got = {int(i): {"verdict": v, "reason": (rs or "")[:200]} for i, v, rs in re.findall(r'"i"\s*:\s*(\d+)\s*,\s*"verdict"\s*:\s*"(keep|strip)"(?:\s*,\s*"reason"\s*:\s*"([^"]*))?', text)}
        if not got: raise ValueError(f"no verdicts parseable; raw: {text[:160]!r}")
    return {local[j]: v for j, v in got.items() if j in local}, c

REVIEW_MEMO: dict = {}   # content-hash → (removed paths, status); process-local; same text + same sources ⇒ same verdicts. Never persisted.

def judge_lines(items: list[tuple[int, str]], system: str, batch: int = 16, max_tokens: int = 12000, workers: int = 4, role: str = "skeptic") -> tuple[dict, float, str]:
    """items = [(index, listing_text)]. Batches run in parallel; a failed batch is retried once in halves. Any batch still failing → 'unverified' (loud).
    Raw output of a failing batch is written to data/processed/review_failures.log for diagnosis."""
    from concurrent.futures import ThreadPoolExecutor
    import pathlib as _pl, time as _t
    from . import diag
    verdicts, cost, status = {}, 0.0, "verified"; judge_lines.last_error = None; _t0 = _t.perf_counter(); _buf: list = []
    if role == "skeptic" and batch > 8: batch, workers = 8, max(workers, 6)   # thinking model: latency grows with batch size — small batches in parallel finish sooner for the same cost
    chunks = [items[b:b + batch] for b in range(0, len(items), batch)]
    def one(chunk):
        diag.bind_collector(_buf)
        try: return _judge_batch(chunk, system, max_tokens, role), None
        except Exception as e:
            out, err = {}, f"{type(e).__name__}: {str(e)[:300]}"; c_total = 0.0
            diag.emit("retry", what="review_batch", size=len(chunk), error=err[:80])
            for half in (chunk[: len(chunk) // 2 or 1], chunk[len(chunk) // 2 or 1:]):
                if not half: continue
                try: got, c = _judge_batch(half, system, max_tokens, role); out.update(got); c_total += c
                except Exception as e2:
                    err = f"{type(e2).__name__}: {str(e2)[:300]}"
                    try: (_pl.Path(__file__).resolve().parents[1] / "data" / "processed" / "review_failures.log").open("a").write(f"\n[{_t.strftime('%Y-%m-%d %H:%M:%S')}] {err}\n")
                    except Exception: pass
                    return (out, c_total), err
            return (out, c_total), None
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (got, c), err in ex.map(one, chunks):
            verdicts.update(got); cost += c
            if err: status = "unverified"; judge_lines.last_error = err
    diag.flush(_buf)
    diag.emit("review", lines=len(items), batches=len(chunks), batch_size=batch, role=role, ms=round((_t.perf_counter() - _t0) * 1000), status=status)
    return verdicts, cost, status
