"""Cross-session memory: one evidence snapshot per approved run (episodic) + a small profile (semantic). SQLite, same file as checkpoints' neighbour.
`record` is the only writer; `load_memory` the reader; `diff_snapshots` is a pure function the 'Since you last looked' screen renders."""
from __future__ import annotations
import json, sqlite3, time
from pathlib import Path
from tools.schema import Card

DB = Path(__file__).resolve().parents[1] / "data" / "processed" / "memory.sqlite"

def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True); c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, thread_id TEXT, soc TEXT, horizon INT, ts REAL, payload TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS profile (key TEXT PRIMARY KEY, value TEXT, ts REAL)")
    return c

def save_snapshot(thread_id: str, soc: str, horizon, cards: list[Card], extra: dict, persona: dict) -> int:
    """One snapshot per APPROVED run: every card + whatever the journey wants to remember (plan, profile, shortlist, reactions…)."""
    payload = {"ts": time.time(), "persona": persona, "cards": [c.model_dump() for c in cards], **(extra or {})}
    with _conn() as c:
        cur = c.execute("INSERT INTO snapshots (thread_id, soc, horizon, ts, payload) VALUES (?,?,?,?,?)", (thread_id, soc, horizon, payload["ts"], json.dumps(payload)))
        return cur.lastrowid

def load_latest(soc: str, horizon: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT payload FROM snapshots WHERE soc=? AND horizon=? ORDER BY ts DESC LIMIT 1", (soc, horizon)).fetchone()
    return json.loads(row[0]) if row else None

def save_profile(**kv):
    with _conn() as c:
        for k, v in kv.items(): c.execute("INSERT OR REPLACE INTO profile VALUES (?,?,?)", (k, json.dumps(v), time.time()))

def load_profile() -> dict:
    with _conn() as c: return {k: json.loads(v) for k, v in c.execute("SELECT key, value FROM profile")}

def diff_snapshots(prior: dict | None, cards: list[Card]) -> list[dict]:
    """What moved since last time. Compares by card id; a forecast that moved ≥2 points, a new source, a vanished card."""
    if not prior: return []
    old = {c["id"]: c for c in prior["cards"]}; new = {c.id: c for c in cards}; out = []
    for cid, c in new.items():
        if cid not in old: out.append({"kind": "new", "card_id": cid, "claim": c.claim, "source": c.source}); continue
        ov, nv = old[cid].get("value"), c.value
        if ov is not None and nv is not None and abs(nv - ov) >= (0.02 if c.unit == "probability" else abs(ov) * 0.02 + 1e-9):
            out.append({"kind": "moved", "card_id": cid, "claim": c.claim, "source": c.source, "from": ov, "to": nv, "unit": c.unit})
    for cid, c in old.items():
        if cid not in new: out.append({"kind": "gone", "card_id": cid, "claim": c["claim"], "source": c["source"]})
    return out
