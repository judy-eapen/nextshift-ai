"""Structured review: the reviewer judges the *structured objects* the UI renders, not a Markdown shadow of them.
flatten() turns nested dict/list objects into (path, text) leaves; apply_removals() deletes the failing leaves in place, so
what reaches the UI is exactly what survived review. Any Markdown export is generated afterwards from the reviewed object."""
from __future__ import annotations
import re
from typing import Any

REF = re.compile(r"\[([cu]\d{2,3})\]")
TAGS = ("[interpretation]", "[advice]")
# deterministic lint: certainty about the future is never allowed, regardless of citations
CERTAINTY = re.compile(r"\b(will be (automated|replaced|eliminated)|will disappear|will vanish|is safe from AI|guaranteed|100% safe|doomed|obsolete)\b", re.I)

PARAGRAPH_KEYS = ("direct_answer", "for_you", "our_read", "outlook_takeaway", "why_fit", "what_work_is_like", "summary")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“\"(])")

def split_sentences(text: str) -> list[str]: return [x for x in _SENT.split(text.strip()) if x.strip()]

def flatten(obj: Any, path: str = "", out: list | None = None, skip_keys=("card_id", "ref", "soc", "url", "id", "key", "penetration", "task")) -> list[tuple[str, str]]:
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
