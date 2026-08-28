"""Occupation resolver — tier 1 exact/alias, tier 2 semantic match on O*NET descriptions (Nebius embeddings),
tier 3 (TODO Saturday): web-research fallback → duties → tier 2. Never says just 'not found'."""
import os, json, numpy as np, pandas as pd, httpx
from pathlib import Path
from functools import lru_cache
from .occupations import search_occupations
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"; PROC = RAW.parent / "processed"
EMB_MODEL = "Qwen/Qwen3-Embedding-8B"

def _embed(texts: list[str]) -> np.ndarray:
    key = os.environ["NEBIUS_API_KEY"]; base = os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1/").rstrip("/")
    out = []
    for i in range(0, len(texts), 64):
        r = httpx.post(f"{base}/embeddings", headers={"Authorization": f"Bearer {key}"}, json={"model": EMB_MODEL, "input": texts[i:i+64]}, timeout=120)
        r.raise_for_status(); out += [d["embedding"] for d in r.json()["data"]]
    v = np.array(out, dtype=np.float32); return v / np.linalg.norm(v, axis=1, keepdims=True)

@lru_cache(maxsize=1)
def _occ_index():
    occ = pd.read_csv(RAW / "onet_occupation_data.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Title": "title", "Description": "desc"})
    occ = occ[occ.onet_soc.str.endswith(".00")].reset_index(drop=True); occ["soc"] = occ.onet_soc.str[:7]
    cache = PROC / "occupation_embeddings.npy"
    if cache.exists() and np.load(cache).shape[0] == len(occ): vecs = np.load(cache)
    else:
        vecs = _embed([f"{t}. {d}" for t, d in zip(occ.title, occ.desc)]); np.save(cache, vecs)
    return occ, vecs

def semantic_match(text: str, k: int = 5) -> list[dict]:
    """text = a job title and/or a sentence about what the person does."""
    occ, vecs = _occ_index(); q = _embed([text])[0]
    sims = vecs @ q; top = np.argsort(-sims)[:k]
    return [{"soc": occ.soc[i], "onet_soc": occ.onet_soc[i], "title": occ.title[i], "similarity": float(sims[i]), "description": occ.desc[i][:160]} for i in top]

def resolve(title: str, about: str = "", k: int = 3) -> dict:
    """Returns {tier, matches:[...], confident:bool, explanation}. Tier 3 hook left for web research."""
    exact = search_occupations(title, k)
    if exact and exact[0]["exact"]:
        return {"tier": 1, "confident": True, "matches": exact, "explanation": f"“{title}” is a listed job title under {exact[0]['title']} (O*NET)."}
    sem = semantic_match(f"{title}. {about}".strip(), k)
    conf = sem[0]["similarity"] >= 0.60 and (sem[0]["similarity"] - sem[1]["similarity"]) >= 0.03
    expl = (f"No official category lists “{title}”. By meaning it is closest to {sem[0]['title']} (similarity {sem[0]['similarity']:.2f})"
            + (f", then {sem[1]['title']} ({sem[1]['similarity']:.2f})" if len(sem) > 1 else "") + ". Confirm which fits.")
    return {"tier": 2, "confident": conf, "matches": sem, "explanation": expl, "needs_web_research": not conf}
