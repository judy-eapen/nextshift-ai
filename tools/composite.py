"""Composite occupations — for jobs the SOC taxonomy doesn't have (Product Manager, Head of Product, …).
Instead of forcing a category, assemble the job from O*NET task statements across ALL occupations, matched to the person's own description.
Every task statement carries Anthropic Economic Index penetration, so the task-diff board, scenarios and skeptic run unchanged.
Job-level statistics (wage, employment, AIOE) are reported as 'no official statistics exist' — never borrowed from a neighbouring category."""
from __future__ import annotations
import json, re
import numpy as np, pandas as pd
from pathlib import Path
from functools import lru_cache
from .resolve import _embed
from .schema import Card, SourceResult

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"; PROC = RAW.parent / "processed"; CUR = RAW.parent / "composites"

@lru_cache(maxsize=1)
def _task_index():
    """(DataFrame[task, onet_soc, title, penetration], unit-norm embeddings). Built once (~18K statements), cached to disk."""
    t = pd.read_csv(RAW / "onet_task_statements.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Title": "title", "Task": "task"})
    pen = pd.read_csv(RAW / "aei" / "task_penetration.csv").drop_duplicates("task").set_index("task")["penetration"]
    t = t.drop_duplicates("task").reset_index(drop=True); t["penetration"] = t.task.map(pen)
    cache = PROC / "task_embeddings_v1.npy"
    if cache.exists() and np.load(cache, mmap_mode="r").shape[0] == len(t): vecs = np.load(cache)
    else: vecs = _embed(list(t.task)); np.save(cache, vecs)
    return t, vecs

def match_tasks(description: str, k: int = 20, min_sim: float = 0.45) -> list[dict]:
    """Closest task statements to a free-text description of someone's work, across every occupation."""
    t, vecs = _task_index(); sents = [s.strip() for s in re.split(r"[.;\n]| and ", description) if len(s.strip()) > 12] or [description]
    q = _embed(sents); sims = (vecs @ q.T).max(axis=1)              # best match over the person's sentences
    top = np.argsort(-sims)[: k * 2]; out, seen = [], set()
    for i in top:
        r = t.iloc[i]
        if sims[i] < min_sim or r.task in seen: continue
        seen.add(r.task); out.append({"task": r.task, "onet_soc": r.onet_soc, "title": r.title, "penetration": None if pd.isna(r.penetration) else float(r.penetration), "similarity": float(sims[i])})
        if len(out) >= k: break
    return out

def curated(title: str) -> dict | None:
    """Hand-curated composite (data/composites/*.json): a list of exact O*NET task statements chosen by a human."""
    key = re.sub(r"[^a-z]+", "-", title.strip().lower()).strip("-")
    for f in CUR.glob("*.json"):
        spec = json.loads(f.read_text())
        if key in spec["titles"]:
            t, _ = _task_index(); rows = t.set_index("task")
            tasks = [{"task": s, "onet_soc": rows.loc[s, "onet_soc"], "title": rows.loc[s, "title"], "penetration": None if pd.isna(rows.loc[s, "penetration"]) else float(rows.loc[s, "penetration"]), "similarity": None}
                     for s in spec["tasks"] if s in rows.index]
            return {"name": spec["name"], "slug": spec["slug"], "tasks": tasks, "note": spec["note"], "kind": "curated"}
    return None

def expand_description(title: str, about: str) -> list[str]:
    """Cheap LLM step: a two-line self-description → 8-10 O*NET-style task sentences, so each can be matched to real task statements."""
    import os, httpx
    key = os.environ["NEBIUS_API_KEY"]; base = os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.com/v1/").rstrip("/")
    prompt = (f"Job title: {title}. The person describes their work: \"{about}\"\n"
              "Rewrite this as 8-10 task statements in the style of the US O*NET database — each one sentence, starts with a verb, concrete, one activity per line "
              "(e.g. 'Analyze user feedback and usage data to identify product improvements.'). Cover everything they mentioned; add only what the job title plainly implies. One per line, no numbering, no preamble.")
    r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": os.environ.get("EXTRACTOR_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507"), "messages": [{"role": "user", "content": prompt}], "max_tokens": 400, "temperature": 0.2}, timeout=60)
    r.raise_for_status(); return [l.strip(" -•\t") for l in r.json()["choices"][0]["message"]["content"].splitlines() if len(l.strip()) > 15][:10]

def from_description(title: str, about: str, k: int = 18, per_sentence: int = 2, min_sim: float = 0.62) -> dict:
    """Expand → match each task-shaped sentence to its nearest real O*NET statements → dedupe. Knowledge-work descriptions are kept to management/business/computer/design/sales major groups."""
    sents = expand_description(title, about); t, vecs = _task_index(); q = _embed(sents); sims = vecs @ q.T
    allowed = t.onet_soc.str[:2].isin(["11", "13", "15", "17", "19", "27", "41", "43"]).values
    tasks, seen = [], set()
    for j, sent in enumerate(sents):
        col = np.where(allowed, sims[:, j], -1); top = np.argsort(-col)[:per_sentence]
        for i in top:
            r = t.iloc[i]
            if col[i] < min_sim or r.task in seen: continue
            seen.add(r.task); tasks.append({"task": r.task, "onet_soc": r.onet_soc, "title": r.title, "penetration": None if pd.isna(r.penetration) else float(r.penetration), "similarity": float(col[i]), "from": sent})
    tasks = sorted(tasks, key=lambda x: -x["similarity"])[:k]
    return {"name": f"{title.strip().title()} (composite)", "slug": re.sub(r"[^a-z]+", "-", title.lower()).strip("-"), "tasks": tasks, "kind": "described",
            "note": f"Assembled from the {len(tasks)} O*NET task statements closest to your description, across {len({x['onet_soc'] for x in tasks})} official occupations."}

def persona_from(comp: dict, horizon: int) -> dict:
    """Persona the graph understands. soc is 'composite:<slug>' so job-level tools know to report 'no official statistics'."""
    return {"soc": f"composite:{comp['slug']}", "onet_soc": f"composite:{comp['slug']}", "title": comp["name"], "matched_via": comp["kind"], "horizon": horizon,
            "composite": True, "tasks": comp["tasks"], "source_occupations": sorted({x["title"] for x in comp["tasks"]}), "note": comp["note"]}

def task_cards(persona: dict) -> SourceResult:
    """The composite's task list as evidence cards — same shape onet_task_diff produces, so the task-diff board is unchanged."""
    cards = [Card(id=f"onet:task:{re.sub(r'[^a-z0-9]+', '-', x['task'].lower())[:60]}", family="exposure", claim=x["task"], value=x["penetration"], unit="penetration", source="O*NET",
                  url=f"https://www.onetonline.org/link/summary/{x['onet_soc']}", as_of="2025-03-27", confidence=0.8,
                  notes=f"from {x['title']} ({x['onet_soc']}); penetration = share of observed AI conversations touching this task (None = not observed)") for x in persona["tasks"]]
    return SourceResult(source="O*NET", ok=True, cards=cards)

def no_official_stats(source: str, persona: dict) -> SourceResult:
    return SourceResult(source=source, ok=True, cards=[], unknowns=[f"{source}: no official statistics exist for “{persona['title']}” — the SOC taxonomy has no such occupation; job-level figures are not borrowed from a neighbouring category"])
