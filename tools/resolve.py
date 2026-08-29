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
    occ = occ[~occ.title.str.contains("All Other")].reset_index(drop=True); occ["soc"] = occ.onet_soc.str[:7]  # keep detailed codes (15-1299.09 IT Project Managers…); residual "All Other" categories match anything — exclude
    jt = pd.read_csv(RAW / "onet_job_titles.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Job Title": "alias"})
    aliases = jt.groupby("onet_soc").alias.apply(lambda a: "; ".join(a.head(25))).to_dict()   # fold known lay titles into each occupation's text
    occ["text"] = [f"{t}. {d} Also called: {aliases.get(o, '')}" for t, d, o in zip(occ.title, occ.desc, occ.onet_soc)]
    cache = PROC / "occupation_embeddings_v3.npy"
    if cache.exists() and np.load(cache).shape[0] == len(occ): vecs = np.load(cache)
    else:
        vecs = _embed(list(occ.text)); np.save(cache, vecs)
    return occ, vecs

def describe_title(title: str, about: str = "") -> str:
    """Cheap LLM step: turn a bare title into a 2-sentence description of the work, so the embedder has something to match."""
    key = os.environ["NEBIUS_API_KEY"]; base = os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1/").rstrip("/")
    model = os.environ.get("EXTRACTOR_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")
    prompt = (f"Job title: {title}. " + (f"The person says: {about}. " if about else "") +
              "In two plain sentences, describe the day-to-day work of this job in the style of a US Bureau of Labor Statistics occupation description "
              "(what they plan, direct, analyze, coordinate, build). No preamble.")
    r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 120, "temperature": 0.2}, timeout=60)
    r.raise_for_status(); return r.json()["choices"][0]["message"]["content"].strip()

def semantic_match(text: str, k: int = 5) -> list[dict]:
    """text = a description of the work (use describe_title first for bare titles)."""
    occ, vecs = _occ_index(); q = _embed([text])[0]
    sims = vecs @ q; top = np.argsort(-sims)[:k]
    return [{"soc": occ.soc[i], "onet_soc": occ.onet_soc[i], "title": occ.title[i], "similarity": float(sims[i]), "description": occ.desc[i][:160]} for i in top]

OVERRIDES = json.loads((RAW.parent / "title_overrides.json").read_text()) if (RAW.parent / "title_overrides.json").exists() else {}

def _curated(title: str) -> dict | None:
    key = title.strip().lower()
    for entry in OVERRIDES.get("entries", []):
        if key in entry["titles"]:
            occ, _ = _occ_index(); rows = {r.onet_soc: r for r in occ.itertuples()}
            matches = [{"soc": c[:7], "onet_soc": c, "title": rows[c].title if c in rows else c, "description": (rows[c].desc[:160] if c in rows else ""), "curated": True} for c in entry["candidates"]]
            return {"tier": 0, "confident": False, "matches": matches, "explanation": entry["note"]}
    return None

def with_composites(result: dict, title: str, about: str = "") -> dict:
    """Prepend composite options: a curated one if this title has it, and a description-built one if the person described their work."""
    from . import composite
    comps = []
    if (c := composite.curated(title)): comps.append(c)
    if about.strip() and len(about.strip()) > 20: comps.append(composite.from_description(title, about))
    result["composites"] = comps; return result

def resolve(title: str, about: str = "", k: int = 3) -> dict:
    """Returns {tier, matches:[...], confident:bool, explanation}. Tier 0 curated · 1 exact title · 2 semantic (always when `about` is given) · 3 web hook."""
    if not about.strip() and (cur := _curated(title)): return cur
    exact = search_occupations(title, k)
    if exact and exact[0]["exact"] and not about.strip():
        return {"tier": 1, "confident": True, "matches": exact, "explanation": f"“{title}” is a listed job title under {exact[0]['title']} (O*NET)."}
    desc = describe_title(title, about); sem = semantic_match(f"{title}. {about or desc}", k)
    sem = semantic_match(f"{title}. {about or desc}", max(k, 2)) if len(sem) < 2 else sem   # need two for the margin test
    conf = bool(sem) and sem[0]["similarity"] >= 0.60 and (len(sem) < 2 or (sem[0]["similarity"] - sem[1]["similarity"]) >= 0.03)
    expl = (f"No official category lists “{title}”. By meaning it is closest to {sem[0]['title']} (similarity {sem[0]['similarity']:.2f})"
            + (f", then {sem[1]['title']} ({sem[1]['similarity']:.2f})" if len(sem) > 1 else "") + ". Confirm which fits.")
    if about.strip() and exact and exact[0]["exact"]:   # merge: what O*NET files the title under, after what the description matches
        seen = {m["onet_soc"] for m in sem}; sem += [dict(e, similarity=None) for e in exact[:2] if e["onet_soc"] not in seen]
        expl = f"Matched on what you do, not the title alone (O*NET files “{title}” under {exact[0]['title']}, shown too). " + expl
    return {"tier": 2, "confident": conf, "matches": sem, "explanation": expl, "inferred_description": desc, "needs_web_research": not conf}
