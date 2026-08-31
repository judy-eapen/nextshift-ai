"""Career catalog — a normalized, cached, deterministic record for every occupation the local data supports.
Built OUTSIDE the request path from the raw files already in data/raw/ (O*NET 31.0 · BLS Employment Projections 2025–35 · OES 2025 ·
Anthropic Economic Index task penetration · AIOE) plus the curated composites. No network, no model — browsing, searching, filtering and
career pages read this file only. Coverage = the O*NET-SOC codes in occupation_data.csv (1,016) + curated composites; it is NOT "every career".

Storage: data/processed/catalog/catalog_<VERSION>.parquet (+ manifest.json), gitignored like the other caches; written atomically; rebuilt on
demand when missing or when VERSION changes (a few seconds). Nested fields (tasks, ratings, provenance) are stored as JSON per row.

Honesty rules baked in: figures are never borrowed — a detailed O*NET specialty (e.g. 15-1255.01) shows the parent 6-digit BLS row and says so;
composites carry no BLS/AIOE/AEI numbers; a missing field is None and the UI says "not reported". Growth and AI-use classes use the SAME
thresholds as the graph (graph/nodes.py `_reading_demand`, `_reading_change`) so the explorer and the interview never disagree."""
from __future__ import annotations
import json, math, os, re, time, random
from functools import lru_cache
from pathlib import Path
from typing import Optional
import pandas as pd
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]; RAW = ROOT / "data" / "raw"; PROC = ROOT / "data" / "processed"; DIR = PROC / "catalog"
VERSION = "cat1"
CONFIG = json.loads((ROOT / "data" / "career_families.json").read_text())
FAMILIES = {f["id"]: f for f in CONFIG["families"]}
TRAITS = CONFIG["traits"]; SUBJECTS = CONFIG["subjects"]

NATIONAL_GROWTH = 3.5   # BLS Table 1.1, all occupations 2025–35 (same constant as tools/outlook.py)
AI_ASSIST_THRESHOLD = 0.60   # same as graph/nodes.py: a task "already shows heavy AI use" at ≥ 0.60 observed penetration

# Provenance shown next to every figure. as_of values match the ones the evidence tools already put on Cards.
SOURCES = {
    "onet": {"name": "O*NET 31.0", "as_of": "2025-08-01", "url": "https://www.onetonline.org/", "kind": "official database", "note": "Occupation descriptions, tasks, work activities, work context, interests, knowledge, job zones, related occupations (U.S. Department of Labor)."},
    "bls_ep": {"name": "BLS Employment Projections 2025–35", "as_of": "2025-12-01", "url": "https://www.bls.gov/emp/tables/occupational-projections-and-characteristics.htm", "kind": "official projection", "note": "Employment 2025 and projected 2035, percent and numeric change, annual openings, typical entry education. A projection, not a guarantee."},
    "bls_oes": {"name": "BLS OES 2025", "as_of": "2025-05-01", "url": "https://www.bls.gov/oes/", "kind": "official statistic", "note": "Median annual wage."},
    "aei": {"name": "Anthropic Economic Index (labor_market_impacts)", "as_of": "2025-03-27", "url": "https://huggingface.co/datasets/Anthropic/EconomicIndex", "kind": "observed AI use", "note": "Share of observed AI conversations touching each O*NET task, on one vendor's platform. Measures current use — not automation, not a forecast."},
    "aioe": {"name": "AIOE (Felten, Raj & Seamans)", "as_of": "2023-01-01", "url": "https://github.com/AIOE-Data/AIOE", "kind": "academic exposure index", "note": "Links AI capability progress to the abilities an occupation uses. Exposure ≠ job loss."},
    "nextshift": {"name": "NextShift rule", "as_of": None, "url": None, "kind": "deterministic rule", "note": "Templated from the ratings above by fixed code; no model involved."},
}

# ───────────────────────────── schema ─────────────────────────────
class CatalogRecord(BaseModel):
    """One canonical occupation record. Stable id = O*NET-SOC code (e.g. '15-1252.00', '15-1255.01') or 'composite:<slug>'."""
    id: str; soc: str; onet_soc: str; title: str; description: str
    kind: str                                   # direct (6-digit SOC, .00) | detailed (O*NET specialty within a SOC) | composite (no official category)
    residual: bool = False                      # "…, All Other" catch-all categories
    lay_titles: list[str] = []
    tasks: list[dict] = []                      # [{task, task_type, penetration}] core tasks first
    n_tasks: int = 0; n_tasks_observed: int = 0; ai_task_share: Optional[float] = None; ai_change_class: str = "unknown"
    # BLS (6-digit level; for detailed codes these are the parent category's figures — see bls_note)
    bls_soc: Optional[str] = None; bls_title: Optional[str] = None; bls_note: Optional[str] = None
    emp_2025: Optional[float] = None; emp_2035: Optional[float] = None; growth_pct: Optional[float] = None; emp_change: Optional[float] = None; openings_annual: Optional[float] = None
    growth_class: str = "unknown"; education_entry: Optional[str] = None; experience_entry: Optional[str] = None; training_entry: Optional[str] = None; median_wage: Optional[float] = None
    job_zone: Optional[int] = None; job_zone_name: Optional[str] = None
    # exposure
    aioe: Optional[float] = None; aioe_pct: Optional[float] = None; aioe_lm: Optional[float] = None; observed_exposure: Optional[float] = None; observed_exposure_pct: Optional[float] = None
    # O*NET ratings
    riasec: dict = {}; interest_high_points: list[str] = []; work_activities: dict = {}; work_context: dict = {}; knowledge: dict = {}
    related: list[dict] = []                    # [{id, title, tier}]
    # explorer facets
    families: list[str] = []; subjects: list[str] = []; traits: dict = {}      # trait → {score, evidence}
    familiar: bool = False; human_intensive: bool = False
    proxies: list[dict] = []                    # composites: [{soc, title}] the figures would come from — shown as labelled proxies only
    bls_factors: list[dict] = []                # BLS Table 1.12 'factors affecting occupational utilization' — official, qualitative: [{industry, text}]
    note: Optional[str] = None
    provenance: dict = {}                       # field group → source key
    sources: dict = SOURCES

# ───────────────────────────── classifiers (same thresholds as the graph) ─────────────────────────────
def growth_class(pct: Optional[float]) -> str:
    if pct is None or (isinstance(pct, float) and math.isnan(pct)): return "unknown"
    return "growing" if pct >= 5.0 else "declining" if pct < 0 else "stable"

def ai_change_class(share: Optional[float], n_tasks: int) -> str:
    if share is None or not n_tasks: return "unknown"
    return "substantial" if share >= 0.4 else "moderate" if share >= 0.2 else "limited"

GROWTH_LABEL = {"growing": "Projected to grow", "stable": "Projected roughly stable", "declining": "Projected to decline", "unknown": "No official projection"}
AI_LABEL = {"substantial": "AI already used in many tasks", "moderate": "AI already used in some tasks", "limited": "AI rarely used in its tasks so far", "unknown": "No task-level AI-use data"}
ZONE_SHORT = {1: "Little or no preparation", 2: "Some preparation (high school + short training)", 3: "Medium preparation (vocational training, apprenticeship or associate's)", 4: "Considerable preparation (usually a bachelor's)", 5: "Extensive preparation (graduate or professional degree)"}
EDU_LEVELS = ["No formal educational credential", "High school diploma or equivalent", "Postsecondary nondegree award", "Some college, no degree", "Associate's degree", "Bachelor's degree", "Master's degree", "Doctoral or professional degree"]

# ───────────────────────────── build ─────────────────────────────
def _num(v):
    try:
        f = float(v); return None if math.isnan(f) else f
    except Exception: return None

def _read(name, **kw): return pd.read_csv(RAW / name, **kw)

def _importance(df: pd.DataFrame, scale: str = "IM") -> dict[str, dict[str, float]]:
    """{onet_soc: {element: value}} for one scale."""
    d = df[df["Scale ID"] == scale]
    out: dict[str, dict[str, float]] = {}
    for code, el, v in zip(d["O*NET-SOC Code"], d["Element Name"], d["Data Value"]):
        out.setdefault(code, {})[el] = float(v)
    return out

def _families_for(code: str, kind: str) -> list[str]:
    soc6, minor, major = code[:7], code[:4], code[:2]; fams = []
    for f in CONFIG["families"]:
        if code in f["codes"] or soc6 in f["codes"] or minor in f["minor"] or major in f["major"]: fams.append(f["id"])
    if kind == "composite" and "emerging" not in fams: fams.append("emerging")
    return fams

def _traits_for(wa: dict, cx: dict, ri: dict, kn: dict) -> dict:
    src = {"wa": (wa, 5.0), "cx": (cx, 5.0), "ri": (ri, 7.0), "kn": (kn, 5.0)}
    out = {}
    for tid, t in TRAITS.items():
        best = None
        for s, el, mn in t["any_of"]:
            vals, top = src[s]; v = vals.get(el)
            if v is None or v < mn: continue
            score = v / top
            if best is None or score > best["score"]: best = {"score": round(score, 3), "evidence": f"{el}: {v:.1f} of {top:.0f} (O*NET {'work activity' if s == 'wa' else 'work context' if s == 'cx' else 'interest profile' if s == 'ri' else 'knowledge'})"}
        if best: out[tid] = best
    return out

def _subjects_for(kn: dict) -> list[str]:
    return [s for s, cfg in SUBJECTS.items() if any(kn.get(e, 0) >= cfg["min"] for e in cfg["elements"])]

def build(force: bool = False) -> Path:
    """Assemble the catalog from local files and write it atomically. Returns the parquet path."""
    DIR.mkdir(parents=True, exist_ok=True); out = DIR / f"catalog_{VERSION}.parquet"
    if out.exists() and not force: return out
    t0 = time.time()
    occ = _read("onet_occupation_data.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Title": "title", "Description": "desc"})
    tasks = _read("onet_task_statements.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Task": "task", "Task Type": "task_type"})
    pen = _read("aei/task_penetration.csv").drop_duplicates("task").set_index("task")["penetration"]
    tasks["penetration"] = tasks.task.map(pen); tasks["_order"] = (tasks.task_type != "Core").astype(int)
    tasks = tasks.sort_values(["onet_soc", "_order", "Task ID"])
    land = pd.read_parquet(PROC / "landscape.parquet").set_index("soc")
    wa = _importance(_read("onet_work_activities.csv")); kn = _importance(_read("onet_knowledge.csv"))
    cx_df = _read("onet_work_context.csv", usecols=["O*NET-SOC Code", "Element Name", "Scale ID", "Data Value"]); cx = _importance(cx_df, "CX")
    ci = _read("onet_career_interest_types.csv"); ri = _importance(ci, "OI")
    hp = ci[ci["Scale ID"] == "IH"]; RI_NAMES = {1: "Realistic", 2: "Investigative", 3: "Artistic", 4: "Social", 5: "Enterprising", 6: "Conventional"}
    high = {}
    for code, el, v in zip(hp["O*NET-SOC Code"], hp["Element Name"], hp["Data Value"]):
        if not math.isnan(v): high.setdefault(code, []).append((el, RI_NAMES.get(int(v), str(v))))
    high = {k: [n for _, n in sorted(v)] for k, v in high.items()}
    jz = _read("onet_job_zones.csv").set_index("O*NET-SOC Code")["Job Zone"].to_dict()
    rel = _read("onet_related_occupations.csv"); rel = rel[rel["Relatedness Tier"].str.startswith("Primary")].sort_values(["O*NET-SOC Code", "Index"])
    related = {c: [{"id": r, "title": t, "tier": "close" if tier == "Primary-Short" else "related"} for r, t, tier in zip(g["Related O*NET-SOC Code"], g["Related Title"], g["Relatedness Tier"])] for c, g in rel.groupby("O*NET-SOC Code")}
    jt = _read("onet_job_titles.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Job Title": "alias"})
    rt = _read("onet_reported_titles.csv").rename(columns={"O*NET-SOC Code": "onet_soc", "Reported Job Title": "alias"})
    lay = {}
    for code, g in pd.concat([rt[["onet_soc", "alias"]], jt[["onet_soc", "alias"]]]).groupby("onet_soc"): lay[code] = list(dict.fromkeys(a for a in g.alias if isinstance(a, str)))[:25]
    aei_pct_base = land["observed_exposure"].dropna()
    factors: dict[str, list[dict]] = {}
    try:   # BLS Table 1.12 — the projection team's own stated reasons an occupation's share of employment changes (e.g. AI tools, consolidation, demand shifts)
        t12 = pd.read_excel(RAW / "bls_occupation_projections.xlsx", "Table 1.12", header=1); t12.columns = ["occ_title", "occ_code", "industry", "ind_code", "text"]
        for code, ind, txt in zip(t12.occ_code, t12.industry, t12.text):
            code, ind, txt = str(code), str(ind), str(txt)
            if len(code) == 7 and txt and txt != "nan": factors.setdefault(code, []).append({"industry": ind, "text": txt.strip()})
        for k in factors: factors[k] = sorted(factors[k], key=lambda d: (d["industry"] != "Total, all industries", d["industry"]))[:4]
    except Exception: factors = {}
    familiar = set(CONFIG["familiar"])
    records = []
    for r in occ.itertuples(index=False):
        code, soc6 = r.onet_soc, r.onet_soc[:7]; kind = "direct" if code.endswith(".00") else "detailed"; residual = "All Other" in r.title
        tk = tasks[tasks.onet_soc == code]
        tlist = [{"task": t, "task_type": tt if isinstance(tt, str) else "", "penetration": _num(p)} for t, tt, p in zip(tk.task, tk.task_type, tk.penetration)]
        observed = [x for x in tlist if x["penetration"] is not None]
        share = (sum(1 for x in observed if x["penetration"] >= AI_ASSIST_THRESHOLD) / len(tlist)) if tlist and observed else None
        L = land.loc[soc6] if soc6 in land.index else None
        g = _num(L.growth_pct_10y) if L is not None else None
        rec = CatalogRecord(id=code, soc=soc6, onet_soc=code, title=r.title, description=r.desc, kind=kind, residual=residual, lay_titles=lay.get(code, [])[:12],
            tasks=tlist[:14], n_tasks=len(tlist), n_tasks_observed=len(observed), ai_task_share=None if share is None else round(share, 3), ai_change_class=ai_change_class(share, len(tlist)),
            bls_soc=soc6 if L is not None else None, bls_title=(str(L.title) if L is not None else None),
            bls_note=(None if L is None else (f"Employment figures are for the broader official category “{L.title}” ({soc6}); the government does not track this specialty separately." if kind == "detailed" else None)),
            emp_2025=(_num(L.emp_2025_k) * 1000 if L is not None and _num(L.emp_2025_k) is not None else None), emp_2035=(_num(L.emp_2035_k) * 1000 if L is not None and _num(L.emp_2035_k) is not None else None),
            growth_pct=g, emp_change=(_num(L.emp_change_k_10y) * 1000 if L is not None and _num(L.emp_change_k_10y) is not None else None),
            openings_annual=(_num(L.openings_annual_k) * 1000 if L is not None and _num(L.openings_annual_k) is not None else None), growth_class=growth_class(g),
            education_entry=(L.education_entry if L is not None and isinstance(L.education_entry, str) else None), experience_entry=(L.experience_entry if L is not None and isinstance(L.experience_entry, str) and L.experience_entry != "None" else None),
            training_entry=(L.training_entry if L is not None and isinstance(L.training_entry, str) and L.training_entry != "None" else None), median_wage=(_num(L.median_wage) if L is not None else None),
            job_zone=(int(jz[code]) if code in jz else None), job_zone_name=(ZONE_SHORT.get(int(jz[code])) if code in jz else None),
            aioe=(_num(L.aioe) if L is not None else None), aioe_pct=(_num(L.aioe_pct) if L is not None else None), aioe_lm=(_num(L.aioe_lm) if L is not None else None),
            observed_exposure=(_num(L.observed_exposure) if L is not None else None), observed_exposure_pct=(round(float((aei_pct_base < L.observed_exposure).mean()), 3) if L is not None and _num(L.observed_exposure) is not None else None),
            riasec={k: round(v, 2) for k, v in ri.get(code, {}).items()}, interest_high_points=high.get(code, []), work_activities={k: round(v, 2) for k, v in wa.get(code, {}).items()},
            work_context={k: round(v, 2) for k, v in cx.get(code, {}).items() if k in CX_KEEP}, knowledge={k: round(v, 2) for k, v in kn.get(code, {}).items()}, related=related.get(code, [])[:10],
            bls_factors=factors.get(soc6, []), familiar=soc6 in familiar, provenance={"description_tasks_ratings": "onet", "employment_projection_education": "bls_ep", "wage": "bls_oes", "ai_task_use": "aei", "aioe": "aioe", "classes_traits_families": "nextshift"})
        rec.families = _families_for(code, kind); rec.subjects = _subjects_for(rec.knowledge); rec.traits = _traits_for(rec.work_activities, cx.get(code, {}), rec.riasec, rec.knowledge)
        rec.human_intensive = _human_intensive(rec, cx.get(code, {}))
        records.append(rec)
    records += _composite_records(tasks, land)
    df = pd.DataFrame([_flatten(r) for r in records])
    tmp = out.with_suffix(f".{os.getpid()}.tmp"); df.to_parquet(tmp, index=False); os.replace(tmp, out)
    manifest = {"version": VERSION, "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - t0, 1), "records": len(records), "direct": sum(r.kind == "direct" for r in records), "detailed": sum(r.kind == "detailed" for r in records), "composite": sum(r.kind == "composite" for r in records),
                "coverage": {k: round(sum(1 for r in records if getattr(r, k) is not None) / len(records), 3) for k in ("emp_2025", "growth_pct", "openings_annual", "education_entry", "job_zone", "aioe", "observed_exposure", "ai_task_share", "median_wage")},
                "with_related": sum(bool(r.related) for r in records), "with_bls_factors": sum(bool(r.bls_factors) for r in records), "with_riasec": sum(bool(r.riasec) for r in records), "with_tasks": sum(r.n_tasks > 0 for r in records), "sources": SOURCES, "families": {f: sum(f in r.families for r in records) for f in FAMILIES},
                "traits": {t: sum(t in r.traits for r in records) for t in TRAITS}, "subjects": {s: sum(s in r.subjects for r in records) for s in SUBJECTS}, "human_intensive": sum(r.human_intensive for r in records), "familiar": sum(r.familiar for r in records)}
    mtmp = DIR / f"manifest.{os.getpid()}.tmp"; mtmp.write_text(json.dumps(manifest, indent=1)); os.replace(mtmp, DIR / "manifest.json")
    return out

CX_KEEP = {"Outdoors, Exposed to All Weather Conditions", "Outdoors, Under Cover", "Indoors, Environmentally Controlled", "Contact With Others", "Deal With External Customers or the Public in General", "Face-to-Face Discussions with Individuals and Within Teams",
           "Work With or Contribute to a Work Group or Team", "Physical Proximity", "Spend Time Sitting", "Spend Time Standing", "Spend Time Using Your Hands to Handle, Control, or Feel Objects, Tools, or Controls", "Time Pressure", "Freedom to Make Decisions",
           "Importance of Being Exact or Accurate", "Importance of Repeating Same Tasks", "Telephone Conversations", "E-Mail", "Public Speaking", "Consequence of Error", "Exposed to Hazardous Conditions", "Wear Common Protective or Safety Equipment such as Safety Shoes, Glasses, Gloves, Hearing Protection, Hard Hats, or Life Jackets"}

def _human_intensive(rec: CatalogRecord, cx: dict) -> bool:
    """Deterministic rule: AI is rarely observed in this occupation's tasks today (≤5% heavy-use tasks, with task data) AND in-person / hands-on work rates ≥4.0 of 5 in O*NET.
    An interpretation about the present, not a safety claim about the future."""
    if rec.ai_task_share is None or rec.ai_task_share > 0.05 or rec.n_tasks_observed == 0: return False
    wa = rec.work_activities
    return any(v >= 4.0 for v in (wa.get("Assisting and Caring for Others", 0), wa.get("Performing General Physical Activities", 0), wa.get("Handling and Moving Objects", 0), wa.get("Repairing and Maintaining Mechanical Equipment", 0), cx.get("Physical Proximity", 0), wa.get("Performing for or Working Directly with the Public", 0)))

def _composite_records(tasks: pd.DataFrame, land: pd.DataFrame) -> list[CatalogRecord]:
    out = []
    rows = tasks.drop_duplicates("task").set_index("task")
    for f in sorted((ROOT / "data" / "composites").glob("*.json")):
        spec = json.loads(f.read_text()); tl = []
        for s in spec["tasks"]:
            if s in rows.index: tl.append({"task": s, "task_type": "composite", "penetration": _num(rows.loc[s, "penetration"]), "from": rows.loc[s, "onet_soc"]})
        observed = [x for x in tl if x["penetration"] is not None]; share = (sum(1 for x in observed if x["penetration"] >= AI_ASSIST_THRESHOLD) / len(tl)) if tl and observed else None
        counts = pd.Series([x["from"][:7] for x in tl]).value_counts().head(3)
        proxies = [{"soc": s, "title": (land.loc[s, "title"] if s in land.index else s)} for s in counts.index]
        rec = CatalogRecord(id=f"composite:{spec['slug']}", soc=f"composite:{spec['slug']}", onet_soc=f"composite:{spec['slug']}", title=spec["name"], description=spec["note"], kind="composite", lay_titles=[t.replace("-", " ").title() for t in spec["titles"]][:12],
            tasks=tl, n_tasks=len(tl), n_tasks_observed=len(observed), ai_task_share=None if share is None else round(share, 3), ai_change_class=ai_change_class(share, len(tl)), proxies=proxies,
            note="No official U.S. category exists for this job, so it is assembled from official task statements of several occupations. Employment, wage and exposure figures are not borrowed; the closest official categories are listed as labelled proxies.",
            provenance={"description_tasks": "onet", "ai_task_use": "aei", "classes_traits_families": "nextshift"})
        rec.families = _families_for(rec.id, "composite") + [fid for fid in ("business", "tech") if fid not in _families_for(rec.id, "composite")]
        out.append(rec)
    return out

JSON_COLS = ("lay_titles", "tasks", "riasec", "interest_high_points", "work_activities", "work_context", "knowledge", "related", "families", "subjects", "traits", "proxies", "bls_factors", "provenance")
def _flatten(r: CatalogRecord) -> dict:
    d = r.model_dump(exclude={"sources"})
    for k in JSON_COLS: d[k] = json.dumps(d[k], ensure_ascii=False)
    return d

def _inflate(row: dict) -> CatalogRecord:
    d = dict(row)
    for k in JSON_COLS: d[k] = json.loads(d[k]) if isinstance(d[k], str) else d[k]
    for k, v in list(d.items()):
        if isinstance(v, float) and math.isnan(v): d[k] = None
    return CatalogRecord(**d)

# ───────────────────────────── load + access ─────────────────────────────
@lru_cache(maxsize=1)
def _frame() -> pd.DataFrame:
    p = DIR / f"catalog_{VERSION}.parquet"
    if not p.exists(): build()
    return pd.read_parquet(p)

@lru_cache(maxsize=1)
def records() -> dict[str, CatalogRecord]:
    return {r["id"]: _inflate(r) for r in _frame().to_dict("records")}

def manifest() -> dict:
    p = DIR / "manifest.json"
    if not p.exists(): build()
    return json.loads(p.read_text())

def get(rid: str) -> Optional[CatalogRecord]:
    rs = records()
    if rid in rs: return rs[rid]
    if re.fullmatch(r"\d{2}-\d{4}", rid or ""): return rs.get(f"{rid}.00")
    return None

def coverage_line() -> str:
    m = manifest()
    return (f"{m['records']:,} careers: {m['direct']} official U.S. occupations, {m['detailed']} O*NET specialties within them, and {m['composite']} composite role(s) with no official category — "
            f"every occupation in O*NET {SOURCES['onet']['name'].split()[-1]}, not every job that exists. Employment projections cover {m['coverage']['growth_pct']:.0%} of them.")

# ───────────────────────────── search ─────────────────────────────
_STOP = {"the", "and", "or", "of", "to", "in", "for", "with", "a", "an", "on", "at", "by", "as", "is", "are", "be", "that", "this", "from", "into", "than", "other", "such", "using", "use", "work", "working", "job", "jobs", "career", "careers", "like", "want", "i", "im", "me", "my", "who", "someone", "something", "things", "do", "doing", "get", "make", "making", "about", "all", "good", "goods", "great", "best", "better", "bad", "really", "very", "am", "love", "loves", "loved", "enjoy", "enjoys", "enjoying", "interested", "stuff", "kind", "kinds"}   # fit/filler words ("I am good at…", "I love…") never decide a match; "goods" shares a stem with "good" so it goes too
_SYN = {"helping": "care assist counsel teach support", "help": "care assist counsel teach support", "kids": "children", "kid": "children", "child": "children", "teens": "adolescents", "animals": "animal", "pets": "animal", "vet": "veterinarian", "computers": "computer", "coding": "programming", "code": "programming", "programmer": "programming",
        "videogames": "video games", "gaming": "video games", "games": "game", "movies": "film", "movie": "film", "music": "musical", "drawing": "draw", "art": "artistic", "outdoors": "outdoor", "outside": "outdoor", "nature": "outdoor wildlife environmental",
        "planes": "aircraft", "airplanes": "aircraft", "cars": "automotive vehicles", "car": "automotive vehicles", "plants": "nursery greenhouse landscaping horticulture garden", "gardening": "landscaping greenhouse nursery garden", "drawing": "illustrate artistic sketch design", "draw": "illustrate artistic sketch design", "marine": "marine aquatic ocean wildlife", "fixing": "repair", "fix": "repair", "building": "construct", "build": "construct", "math": "mathematics", "maths": "mathematics", "space": "astronomy",
        "environment": "environmental", "climate": "environmental", "cooking": "cook", "food": "cook", "photos": "photograph", "photography": "photograph", "writing": "write", "stories": "write", "law": "legal",
        "police": "law enforcement", "doctor": "physician", "doctors": "physician", "nurse": "nursing", "teaching": "teach", "teacher": "teach", "money": "financial", "finance": "financial", "sports": "athletic", "fitness": "athletic",
        "ocean": "marine aquatic ocean", "sea": "marine aquatic ocean", "robots": "robotic", "robot": "robotic", "ai": "artificial intelligence", "data": "data", "psychology": "psychological", "brain": "neurological", "health": "medical", "hospital": "medical"}
_SUFFIXES = ("ists", "ist", "ians", "ian", "ers", "er", "ing", "ings", "ies", "es", "s", "ed", "al", "ly")

def _stem(w: str, syn: bool = True) -> str:
    w = _SYN.get(w, w) if syn else w
    if " " in w: return w
    for s in _SUFFIXES:
        if w.endswith(s) and len(w) - len(s) >= 4: return w[: -len(s)]
    return w

def token_groups(text: str, syn: bool = True) -> list[tuple[str, list[str]]]:
    """[(original word, [index tokens it expands to])]. Synonyms are applied to QUERIES only (syn=True); documents are indexed on their own stemmed words,
    so 'drawing' in a query reaches artistic/design work without turning a 'Drawing Out Machine' title into art. Coverage is counted per original query word."""
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9\-']+", (text or "").lower()):
        w = w.strip("-'")
        if not w or w in _STOP or len(w) < 2: continue
        m = _SYN.get(w, w) if syn else w
        out.append((w, sorted({_stem(x, syn) for x in m.split()})))
    return out

def tokens(text: str, syn: bool = True) -> list[str]: return [t for _, ts in token_groups(text, syn) for t in ts]

FIELD_WEIGHT = {"title": 6.0, "lay": 3.0, "desc": 2.0, "task": 1.0, "rating": 1.4, "facet": 2.0}

@lru_cache(maxsize=1)
def _index():
    """Inverted index: token → {id: weight}. Built once per process from the catalog (≈1k docs); deterministic."""
    idx: dict[str, dict[str, float]] = {}; doclen: dict[str, int] = {}
    def add(rid, field, text):
        for t in tokens(text, syn=False):
            d = idx.setdefault(t, {}); d[rid] = d.get(rid, 0.0) + FIELD_WEIGHT[field]; doclen[rid] = doclen.get(rid, 0) + 1
    for rid, r in records().items():
        add(rid, "title", r.title); [add(rid, "lay", a) for a in r.lay_titles[:12]]; add(rid, "desc", r.description)
        [add(rid, "task", t["task"]) for t in r.tasks[:10]]
        [add(rid, "rating", k) for k, v in r.work_activities.items() if v >= 3.6]; [add(rid, "rating", k) for k, v in r.knowledge.items() if v >= 3.4]
        [add(rid, "facet", FAMILIES[f]["label"]) for f in r.families]; [add(rid, "facet", TRAITS[t]["label"]) for t in r.traits]; [add(rid, "facet", s) for s in r.subjects]
    n = len(records()); idf = {t: math.log(1 + n / (1 + len(d))) for t, d in idx.items()}
    return idx, idf, doclen

def search_title(q: str, limit: int = 12) -> list[dict]:
    """Exact title/alias → prefix → substring; returns [{id, title, matched, exact}]."""
    ql = " ".join(q.lower().split())
    if not ql: return []
    hits, seen = [], set()
    def push(r, matched, rank):
        if r.id in seen: return
        seen.add(r.id); hits.append({"id": r.id, "title": r.title, "matched": matched, "exact": rank == 0, "rank": rank})
    rs = list(records().values())
    for r in rs:
        if r.title.lower() == ql: push(r, r.title, 0)
    for r in rs:
        if any(a.lower() == ql for a in r.lay_titles): push(r, next(a for a in r.lay_titles if a.lower() == ql), 0)
    for r in rs:
        if r.title.lower().startswith(ql): push(r, r.title, 1)
    for r in rs:
        if ql in r.title.lower(): push(r, r.title, 2)
    qs = set(tokens(ql, syn=False))
    if qs:
        for r in rs:
            if qs <= set(tokens(r.title, syn=False)): push(r, r.title, 2)
    for r in rs:
        a = next((a for a in r.lay_titles if ql in a.lower()), None)
        if a: push(r, a, 3)
    rs_ = records(); emp = {rid: (r.emp_2025 or 0) for rid, r in rs_.items()}
    hits.sort(key=lambda h: (h["rank"], rs_[h["id"]].residual, rs_[h["id"]].kind == "detailed", -emp.get(h["id"], 0), h["title"])); return hits[:limit]   # same rank: real occupations before "…, All Other" catch-alls, official before specialties, then the larger one

def search_text(q: str, limit: int = 20) -> list[dict]:
    """Plain-language search over description, tasks, ratings and facets. Returns [{id, title, score, why:[matched terms]}]; deterministic, no model."""
    idx, idf, doclen = _index(); groups = token_groups(q)
    if not groups: return []
    scores: dict[str, float] = {}; why: dict[str, set] = {}; covered: dict[str, set] = {}
    for word, ts in groups:
        for t in ts:
            for rid, w in idx.get(t, {}).items():
                scores[rid] = scores.get(rid, 0.0) + idf.get(t, 1.0) * (1 + math.log(w)) / math.log(3 + doclen.get(rid, 1)) * 10
                why.setdefault(rid, set()).add(word); covered.setdefault(rid, set()).add(word)
    rs = records(); ranked = sorted(scores.items(), key=lambda kv: (rs[kv[0]].residual, -kv[1], rs[kv[0]].title)); n_words = len({w for w, _ in groups})   # "…, All Other" catch-alls never outrank a real occupation
    out = []
    for rid, sc in ranked:
        r = rs[rid]
        if r.residual and len(out) >= 5: continue
        out.append({"id": rid, "title": r.title, "score": round(sc, 2), "why": sorted(why[rid]), "coverage": round(len(covered[rid]) / n_words, 2)})
        if len(out) >= limit: break
    # prefer results that match more of the query's distinct terms
    out.sort(key=lambda h: (-h["coverage"], -h["score"], h["title"])); return out

def search(q: str, limit: int = 20) -> dict:
    """Title matches first, then meaning matches (deduplicated)."""
    t = search_title(q, limit); seen = {h["id"] for h in t}
    m = [h for h in search_text(q, limit + len(seen)) if h["id"] not in seen][: max(0, limit - len(t))]
    return {"query": q, "title_matches": t, "meaning_matches": m, "total": len(t) + len(m)}

# ───────────────────────────── browse: filters + collections ─────────────────────────────
def _sort_key(r: CatalogRecord): return (r.residual, r.kind == "detailed", -(r.emp_2025 or 0), r.title)

def browse(family: str | None = None, subject: str | None = None, trait: str | None = None, growth: str | None = None, education: str | None = None, zone: int | None = None,
           ai: str | None = None, human_intensive: bool | None = None, include_residual: bool = True, sort: str = "employment") -> list[CatalogRecord]:
    """Deterministic filter over the catalog. growth ∈ growing|stable|declining|unknown · ai ∈ substantial|moderate|limited|unknown · education = a BLS entry-education string · zone = Job Zone 1–5."""
    out = []
    for r in records().values():
        if family and family not in r.families: continue
        if subject and subject not in r.subjects: continue
        if trait and trait not in r.traits: continue
        if growth and r.growth_class != growth: continue
        if ai and r.ai_change_class != ai: continue
        if education and (r.education_entry or "") != education: continue
        if zone is not None and r.job_zone != zone: continue
        if human_intensive is not None and r.human_intensive != human_intensive: continue
        if not include_residual and r.residual: continue
        out.append(r)
    if sort == "growth": out.sort(key=lambda r: (r.growth_pct is None, -(r.growth_pct or 0), r.title))
    elif sort == "title": out.sort(key=lambda r: r.title)
    elif sort == "ai": out.sort(key=lambda r: (r.ai_task_share is None, -(r.ai_task_share or 0), r.title))
    else: out.sort(key=_sort_key)
    return out

COLLECTIONS = {
    "unknown": {"label": "Careers you may not know exist", "emoji": "🔭", "blurb": "Smaller or newer occupations most students never hear about. Reshuffle to see more.",
                "explain": "Excludes about 100 widely known careers and 'All Other' catch-all categories; favours occupations with under 100,000 jobs, specialties within a category, and emerging roles."},
    "fast_growing": {"label": "Fast-growing careers", "emoji": "📈", "blurb": "Occupations BLS projects to grow at least 10% from 2025 to 2035 (all occupations: +3.5%).",
                     "explain": "Sorted by projected percent growth. Growth is a projection about the number of jobs — it says nothing about how AI may change the work itself."},
    "ai_changes_tasks": {"label": "Careers where AI already touches many tasks", "emoji": "🤖", "blurb": "At least 40% of the occupation's tasks already show heavy AI use in observed AI conversations.",
                         "explain": "From the Anthropic Economic Index (observed use on one platform, 2025). This measures where AI is used today — not whether jobs will be lost. Many of these careers are also projected to grow."},
    "human_intensive": {"label": "Careers where in-person and hands-on work is central", "emoji": "🫶", "blurb": "AI is rarely observed in these tasks so far (5% or fewer show heavy use), and O*NET rates caring for, being near, or physically working with people and things as highly important.",
                        "explain": "A NextShift rule over O*NET work-activity ratings and today's observed AI use. It describes the present shape of the work; it is not a promise that a career is 'safe'."},
    "growing_and_ai": {"label": "Growing and AI-heavy at the same time", "emoji": "↗️🤖", "blurb": "Projected to grow while AI is already used in many of their tasks — the two things are different.",
                       "explain": "Intersection of the two collections above: BLS projects growth ≥ 5% and ≥ 40% of tasks show heavy observed AI use. Shown so the difference between demand and task change is visible."},
    "declining": {"label": "Careers projected to shrink", "emoji": "📉", "blurb": "BLS projects fewer jobs in 2035 than in 2025. Many still have thousands of openings a year as people retire or move.",
                  "explain": "Sorted by projected percent change. Decline in total jobs does not mean no openings — the openings figure is shown on every card."},
}

def collection(name: str, seed: int = 0, limit: int | None = None) -> list[CatalogRecord]:
    rs = [r for r in records().values() if not r.residual]
    if name == "unknown":
        pool = [r for r in rs if not r.familiar and r.kind != "composite" and (r.emp_2025 is None or r.emp_2025 < 100_000 or r.kind == "detailed")]
        first = [r for r in pool if r.kind == "detailed" or r.growth_class == "growing" or (r.job_zone or 0) >= 3]; rest = [r for r in pool if r not in first]
        rnd = random.Random(seed); rnd.shuffle(first); rnd.shuffle(rest); out = first + rest
    elif name == "fast_growing": out = sorted([r for r in rs if (r.growth_pct or -99) >= 10], key=lambda r: (-r.growth_pct, r.title))
    elif name == "ai_changes_tasks": out = sorted([r for r in rs if r.ai_change_class == "substantial"], key=lambda r: (-(r.ai_task_share or 0), r.title))
    elif name == "human_intensive": out = sorted([r for r in rs if r.human_intensive], key=_sort_key)
    elif name == "growing_and_ai": out = sorted([r for r in rs if r.growth_class == "growing" and r.ai_change_class == "substantial"], key=lambda r: (-r.growth_pct, r.title))
    elif name == "declining": out = sorted([r for r in rs if r.growth_class == "declining"], key=lambda r: (r.growth_pct, r.title))
    else: raise KeyError(name)
    return out[:limit] if limit else out

def family_summary() -> list[dict]:
    rs = records().values(); out = []
    for fid, f in FAMILIES.items():
        mine = [r for r in rs if fid in r.families and not r.residual]
        growing = sum(r.growth_class == "growing" for r in mine); ex = sorted(mine, key=_sort_key)[:3]
        out.append({"id": fid, "label": f["label"], "emoji": f["emoji"], "blurb": f["blurb"], "count": len(mine), "growing": growing, "examples": [r.title for r in ex]})
    return out

def related(rid: str, limit: int = 8) -> list[CatalogRecord]:
    r = get(rid); rs = records()
    if not r: return []
    out = [rs[x["id"]] for x in r.related if x["id"] in rs][:limit]
    if not out and r.kind == "composite": out = [rs[f"{p['soc']}.00"] for p in r.proxies if f"{p['soc']}.00" in rs]
    return out

# ───────────────────────────── career page view-model (deterministic) ─────────────────────────────
def _fmt_int(v): return "not reported" if v is None else f"{int(round(v)):,}"

def workday_sentences(r: CatalogRecord) -> list[dict]:
    """Templated from O*NET work-context ratings (1–5). Every sentence carries the rating it rests on."""
    cx = r.work_context; out = []
    def line(text, key, v): out.append({"text": text, "evidence": f"O*NET work context “{key}”: {v:.1f} of 5"})
    o = cx.get("Outdoors, Exposed to All Weather Conditions"); i = cx.get("Indoors, Environmentally Controlled")
    if o is not None and o >= 3.5: line("Much of the work happens outdoors, in whatever weather there is.", "Outdoors, Exposed to All Weather Conditions", o)
    elif i is not None and i >= 4.5: line("Almost all of the work happens indoors in a controlled environment.", "Indoors, Environmentally Controlled", i)
    elif i is not None and i >= 3.5: line("Most of the work happens indoors.", "Indoors, Environmentally Controlled", i)
    c = cx.get("Contact With Others")
    if c is not None: line("Constant contact with other people is part of the day." if c >= 4.5 else "Frequent contact with other people." if c >= 3.8 else "Long stretches of the day can be spent working alone." if c <= 3.0 else "A mix of working with others and working alone.", "Contact With Others", c)
    p = cx.get("Deal With External Customers or the Public in General")
    if p is not None and p >= 4.0: line("Dealing with customers, clients or the public is a big part of the job.", "Deal With External Customers or the Public in General", p)
    s = cx.get("Spend Time Sitting"); st_ = cx.get("Spend Time Standing"); h = cx.get("Spend Time Using Your Hands to Handle, Control, or Feel Objects, Tools, or Controls")
    if s is not None and s >= 4.0: line("Most of the day is spent sitting.", "Spend Time Sitting", s)
    elif st_ is not None and st_ >= 3.8: line("Much of the day is spent on your feet.", "Spend Time Standing", st_)
    if h is not None and h >= 4.0: line("Hands-on work with tools, controls or materials fills much of the day.", "Spend Time Using Your Hands to Handle, Control, or Feel Objects, Tools, or Controls", h)
    t = cx.get("Time Pressure")
    if t is not None and t >= 4.0: line("Deadlines and time pressure are a regular feature.", "Time Pressure", t)
    e = cx.get("Consequence of Error")
    if e is not None and e >= 4.0: line("Mistakes can have serious consequences, so care and accuracy matter a lot.", "Consequence of Error", e)
    f = cx.get("Freedom to Make Decisions")
    if f is not None and f >= 4.3: line("People in this job have a lot of freedom to decide how to do their work.", "Freedom to Make Decisions", f)
    rep = cx.get("Importance of Repeating Same Tasks")
    if rep is not None and rep >= 4.0: line("The same kinds of tasks repeat often.", "Importance of Repeating Same Tasks", rep)
    tm = cx.get("Work With or Contribute to a Work Group or Team")
    if tm is not None and tm >= 4.5: line("Working as part of a team is extremely important.", "Work With or Contribute to a Work Group or Team", tm)
    return out[:6]

RIASEC_COPY = {"Realistic": "practical, hands-on work with tools, machines, plants or animals", "Investigative": "figuring things out — asking questions, researching, analyzing", "Artistic": "creative, expressive work with fewer fixed rules",
               "Social": "working with and helping people — teaching, caring, advising", "Enterprising": "leading, persuading and starting things, often with some risk", "Conventional": "organized work with clear procedures, data and detail"}

def who_may_enjoy(r: CatalogRecord) -> list[dict]:
    out = []
    for hp in r.interest_high_points[:3]:
        v = r.riasec.get(hp)
        if v is not None: out.append({"text": f"People who enjoy {RIASEC_COPY.get(hp, hp.lower())}.", "evidence": f"O*NET interest profile: {hp} {v:.1f} of 7"})
    for tid, t in r.traits.items():
        out.append({"text": f"Those drawn to {TRAITS[tid]['label'].lower()}.", "evidence": t["evidence"]})
    return out[:5]

def strengths(r: CatalogRecord) -> list[dict]:
    wa = sorted(r.work_activities.items(), key=lambda kv: -kv[1])[:5]; kn = sorted(r.knowledge.items(), key=lambda kv: -kv[1])[:5]
    return {"activities": [{"text": k, "evidence": f"importance {v:.1f} of 5 (O*NET work activities)"} for k, v in wa], "knowledge": [{"text": k, "evidence": f"importance {v:.1f} of 5 (O*NET knowledge)"} for k, v in kn]}

def ai_task_groups(r: CatalogRecord) -> dict:
    """Same buckets as the graph's WorkChange: ≥0.60 heavy observed use · 0.25–0.60 uncertain · <0.25 or unobserved = little observed use today."""
    heavy = [t for t in r.tasks if (t["penetration"] or 0) >= AI_ASSIST_THRESHOLD]; mid = [t for t in r.tasks if 0.25 <= (t["penetration"] or 0) < AI_ASSIST_THRESHOLD]
    low = [t for t in r.tasks if (t["penetration"] or 0) < 0.25]
    return {"heavy": sorted(heavy, key=lambda t: -t["penetration"]), "mid": sorted(mid, key=lambda t: -t["penetration"]), "low": low,
            "method": f"Observed AI use = share of AI conversations touching this task ({SOURCES['aei']['name']}, {SOURCES['aei']['as_of']}). It measures current use on one platform — not automation, not a forecast. “Little observed use” may reflect measurement limits as much as the work itself."}

def human_side(r: CatalogRecord) -> list[dict]:
    """Deterministic: work-activity / work-context ratings that describe in-person, physical, judgment or relationship work — shown WITH the rating; labelled interpretation."""
    out = []; wa = r.work_activities; cx = r.work_context
    for key, text in (("Assisting and Caring for Others", "Caring for and assisting people"), ("Establishing and Maintaining Interpersonal Relationships", "Building and keeping relationships"), ("Performing General Physical Activities", "Physical work"),
                      ("Handling and Moving Objects", "Handling and moving real objects"), ("Repairing and Maintaining Mechanical Equipment", "Repairing mechanical equipment"), ("Making Decisions and Solving Problems", "Making decisions and solving problems"),
                      ("Resolving Conflicts and Negotiating with Others", "Resolving conflicts and negotiating"), ("Guiding, Directing, and Motivating Subordinates", "Guiding and motivating people"), ("Performing for or Working Directly with the Public", "Working directly with the public"),
                      ("Coaching and Developing Others", "Coaching and developing others"), ("Judging the Qualities of Objects, Services, or People", "Judging quality with expertise")):
        v = wa.get(key)
        if v is not None and v >= 3.8: out.append({"text": text, "evidence": f"O*NET work activity importance {v:.1f} of 5"})
    pp = cx.get("Physical Proximity")
    if pp is not None and pp >= 3.8: out.append({"text": "Being physically present with others", "evidence": f"O*NET work context “Physical Proximity” {pp:.1f} of 5"})
    return sorted(out, key=lambda x: -float(x["evidence"].split()[-3]))[:6]

def test_ideas(r: CatalogRecord) -> list[str]:
    cfg = CONFIG["test_ideas"]; out = list(cfg["always"][:2])
    if r.job_zone in (1, 2): out += cfg["zone_1_2"]
    elif r.job_zone == 3: out += cfg["zone_3"]
    elif r.job_zone in (4, 5): out += cfg["zone_4_5"][:1]
    for f in r.families[:2]: out += cfg["family"].get(f, [])
    out.append(cfg["always"][2]); return list(dict.fromkeys(out))[:6]

def trajectory(r: CatalogRecord) -> dict:
    today = f"{_fmt_int(r.emp_2025)} jobs in 2025" + (f" · typical entry: {r.education_entry.lower()}" if r.education_entry else "") if r.emp_2025 is not None else ("No official employment count" + (" (composite — see proxies)" if r.kind == "composite" else ""))
    direction = (f"{GROWTH_LABEL[r.growth_class]}: {r.growth_pct:+.1f}% by 2035 (all occupations {NATIONAL_GROWTH:+.1f}%)" + (f" · about {_fmt_int(r.openings_annual)} openings a year" if r.openings_annual is not None else "")) if r.growth_pct is not None else "No official projection for this occupation"
    if r.ai_task_share is not None: ai = f"{AI_LABEL[r.ai_change_class]}: {int(round(r.ai_task_share * r.n_tasks))} of {r.n_tasks} tasks show heavy observed AI use today"
    else: ai = "No task-level AI-use data for this occupation"
    skills = [k for k, v in sorted(r.knowledge.items(), key=lambda kv: -kv[1])[:3]] + [k for k, v in sorted(r.work_activities.items(), key=lambda kv: -kv[1]) if k in ("Thinking Creatively", "Making Decisions and Solving Problems", "Assisting and Caring for Others", "Establishing and Maintaining Interpersonal Relationships", "Working with Computers", "Analyzing Data or Information")][:2]
    return {"today": today, "direction": direction, "ai_shaped": ai, "skills": skills,
            "labels": {"today": "official statistic (BLS)", "direction": "official projection (BLS 2025–35)", "ai_shaped": "observed use, not a forecast (Anthropic Economic Index)", "skills": "top-rated knowledge and activities (O*NET) — a starting point, not personalized"}}

def detail(rid: str) -> dict:
    """Everything the career page shows, computed from the record. No model, no network."""
    r = get(rid)
    if not r: return {}
    return {"record": r, "workday": workday_sentences(r), "enjoy": who_may_enjoy(r), "strengths": strengths(r), "ai": ai_task_groups(r), "human": human_side(r), "related": [{"id": x.id, "title": x.title, "growth_class": x.growth_class, "kind": x.kind} for x in related(rid)],
            "test": test_ideas(r), "trajectory": trajectory(r), "families": [FAMILIES[f] for f in r.families if f in FAMILIES], "coverage": coverage_line()}

# ───────────────────────────── compare ─────────────────────────────
COMPARE_ROWS = [("What the work involves", "involves"), ("Representative tasks", "tasks"), ("Work environment", "environment"), ("Preparation or education", "education"), ("Current employment", "employment"), ("Projected growth or decline", "growth"),
                ("Annual openings", "openings"), ("AI task exposure (observed use today)", "ai"), ("Human-intensive parts of the work", "human"), ("Related careers", "related"), ("Low-cost ways to test it", "test")]

def compare(ids: list[str]) -> dict:
    """Consistent rows for up to four careers. No winner, no score — cells are facts with their source label or short templated text."""
    rs = [get(i) for i in ids[:4]]; rs = [r for r in rs if r]
    rows = []
    for label, key in COMPARE_ROWS:
        cells = []
        for r in rs:
            if key == "involves": cells.append(r.description.split(". ")[0].rstrip(".") + ".")
            elif key == "tasks": cells.append(" · ".join(t["task"] for t in r.tasks[:3]) or "not reported")
            elif key == "environment": cells.append(" ".join(x["text"] for x in workday_sentences(r)[:3]) or "not reported")
            elif key == "education": cells.append((r.education_entry or "not reported") + (f" · Job Zone {r.job_zone}: {r.job_zone_name}" if r.job_zone else "") + (" · figures for the broader category" if r.kind == "detailed" else "") + (" · no official figures (composite)" if r.kind == "composite" else ""))
            elif key == "employment": cells.append(_fmt_int(r.emp_2025) + (" (2025)" if r.emp_2025 is not None else ""))
            elif key == "growth": cells.append(f"{GROWTH_LABEL[r.growth_class]}" + (f" · {r.growth_pct:+.1f}% 2025–35" if r.growth_pct is not None else ""))
            elif key == "openings": cells.append(_fmt_int(r.openings_annual) + (" a year" if r.openings_annual is not None else ""))
            elif key == "ai": cells.append(AI_LABEL[r.ai_change_class] + (f" · {int(round(r.ai_task_share * r.n_tasks))} of {r.n_tasks} tasks" if r.ai_task_share is not None else ""))
            elif key == "human": cells.append(" · ".join(x["text"] for x in human_side(r)[:3]) or "no high-rated in-person or hands-on activities")
            elif key == "related": cells.append(" · ".join(x.title for x in related(r.id, 3)) or "not reported")
            elif key == "test": cells.append(test_ideas(r)[0])
        rows.append({"label": label, "cells": cells})
    return {"ids": [r.id for r in rs], "titles": [r.title for r in rs], "rows": rows, "sources": {"involves/tasks/environment/human": "O*NET 31.0", "education": "BLS EP 2025–35 + O*NET Job Zone", "employment/growth/openings": "BLS Employment Projections 2025–35", "ai": SOURCES["aei"]["name"], "test": "general suggestions (not personalized)"}}

if __name__ == "__main__":
    import sys
    p = build(force="--force" in sys.argv); m = manifest()
    print(f"wrote {p} · {m['records']} records in {m['seconds']}s"); print(json.dumps({k: v for k, v in m.items() if k != 'sources'}, indent=1))
