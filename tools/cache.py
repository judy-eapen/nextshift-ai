"""Versioned disk cache for STABLE, non-personal evidence (occupation resolution, O*NET web-service detail, forecast-market searches, research
context). Keys carry the dataset/resolver version and, for live sources, a TTL. Never used for anything containing a student's words —
personalized objects are memoised in graph/review.py only by content hash within the process.
Files: data/processed/cache/<namespace>/<sha>.json — atomic writes (tmp + os.replace); corrupt or missing entries read as a miss."""
from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path
from typing import Any, Callable

DIR = Path(__file__).resolve().parents[1] / "data" / "processed" / "cache"

# dataset / code versions that participate in keys — bump when the underlying data or logic changes
VERSIONS = {"onet": "31.0", "bls": "ep2025-35", "exposure": "aei-2025-03+aioe-2023", "resolver": "r3", "forecasts": "f1", "research": "r1"}
TTL = {"forecasts": 6 * 3600, "research": 6 * 3600, "onet_ws": 30 * 24 * 3600, "resolver": None}   # None = no expiry (data-versioned)

def _emit(ns: str, result: str, key: str):
    try:
        from graph import diag; diag.emit("cache", ns=ns, result=result, key=key[:12])
    except Exception: pass

def key_for(ns: str, **parts) -> str:
    """Stable key: namespace + sorted parts + the namespace's version. Titles are normalised (lower, collapsed spaces)."""
    norm = {k: (" ".join(str(v).lower().split()) if k in ("title", "about", "query") else v) for k, v in parts.items()}
    norm["_v"] = VERSIONS.get(ns.split("_")[0], VERSIONS.get(ns, "0"))
    return hashlib.sha256(json.dumps({"ns": ns, **norm}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def _path(ns: str, key: str) -> Path: return DIR / ns / f"{key}.json"

def get(ns: str, key: str) -> Any | None:
    p = _path(ns, key)
    try:
        if not p.exists(): _emit(ns, "miss", key); return None
        d = json.loads(p.read_text())
        ttl = TTL.get(ns)
        if ttl is not None and time.time() - d.get("_t", 0) > ttl: _emit(ns, "expired", key); return None
        _emit(ns, "hit", key); return d.get("value")
    except Exception:
        _emit(ns, "corrupt", key)
        try: p.unlink()
        except Exception: pass
        return None

def put(ns: str, key: str, value: Any) -> None:
    p = _path(ns, key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True); tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"_t": time.time(), "value": value}, ensure_ascii=False)); os.replace(tmp, p)
    except Exception: pass   # a cache write failure must never fail the run

def cached(ns: str, key: str, compute: Callable[[], Any], serialize: Callable = None, deserialize: Callable = None) -> Any:
    hit = get(ns, key)
    if hit is not None: return deserialize(hit) if deserialize else hit
    val = compute(); put(ns, key, serialize(val) if serialize else val); return val

def disabled() -> bool: return os.environ.get("NEXTSHIFT_NO_CACHE") == "1"

# SourceResult helpers (tools.schema) — cards round-trip through model_dump
def dump_result(r) -> dict: return r.model_dump()
def load_result(d):
    from .schema import SourceResult; return SourceResult(**d)
