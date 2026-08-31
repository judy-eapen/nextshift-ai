"""Career page — grounded hybrid. Four typed layers that cannot be mixed by accident:
  1 SourcedFacts        raw facts from the authoritative files, every field a Sourced{value, source, as_of, retrieved, url} or None (+ `unavailable`)
  2 DerivedValues       deterministic derivations, each a Derived{value, rule, inputs} — fixed code over layer 1
  3 Interpretation      model-written explanation of ONE career (or a comparison of ≤4), generated ONLY from the layer-1 evidence table, every factual line
                        cites [cNN], deterministic lints (certainty · absolute 'good fit' language · numbers must sit on a cited card), then the existing
                        reviewer model; disk-cached by (career, catalog version, model, prompt version) — generic, never personal
  4 PersonalizedGuidance anything that uses the student's own answers, saved careers or reactions — produced by the student graph (profile refs, reviewer,
                        gates); this module only carries the seed and the label
The model is never the source of a labor-market fact: it cannot add a number that is not on a cited card, and the UI renders layer 1/2 from the catalog,
not from model text. A missing field is reported as "Data not available from the current sources." — never estimated."""
from __future__ import annotations
import json, os, re, time
from pathlib import Path
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field
from tools import catalog as C
from tools.schema import Card

UNAVAILABLE = "Data not available from the current sources."
PROMPT_VERSION = "p2"   # p2: narrative brief — the model tells the career's story in plain language, folding the numbers in
ILLUSTRATIVE = "An illustrative day based on common O*NET tasks. Actual work varies by employer and specialization."
NARRATIVE_TITLES = {"what_is_it": "What is this job?", "typical_day": "A typical day", "outlook_story": "How does the outlook look?", "who_thrives": "Who tends to enjoy this work?", "ai_story": "Where does AI fit in?", "get_ready": "How could you start preparing?"}
MODEL_LABEL = "Written by an AI model from the sourced facts on this page and checked line by line by a separate reviewer. An interpretation to help you read the data — not an official BLS or O*NET conclusion."
FIT_LABEL = "About the work, not about you: each line points at a task or work characteristic. People develop skills, and jobs vary by employer."
AI_LABEL = "Task-level reasoning from observed AI use today (Anthropic Economic Index) and the task list (O*NET). Uncertain by nature: current use is not automation, and heavy AI use in tasks does not mean fewer jobs — the employment outlook is a separate, official figure above."

# ───────────────────────────── layer 1 · sourced facts ─────────────────────────────
class Sourced(BaseModel):
    value: Any
    source: str                 # key in catalog.SOURCES
    source_name: str; as_of: Optional[str] = None; retrieved: Optional[str] = None; url: Optional[str] = None
    note: Optional[str] = None  # e.g. "figures are for the broader official category"

class TaskFact(BaseModel):
    task: str; task_type: str = ""; penetration: Optional[float] = None   # penetration: AEI observed use (None = not observed / not in the file)

class SourcedFacts(BaseModel):
    id: str; kind: Literal["direct", "detailed", "composite"]
    title: Sourced; classification: Sourced; description: Optional[Sourced] = None
    tasks: Optional[Sourced] = None                  # value: list[TaskFact]
    employment_2025: Optional[Sourced] = None; employment_2035: Optional[Sourced] = None; growth_pct: Optional[Sourced] = None; emp_change: Optional[Sourced] = None; openings_annual: Optional[Sourced] = None
    education_entry: Optional[Sourced] = None; experience_entry: Optional[Sourced] = None; training_entry: Optional[Sourced] = None; median_wage: Optional[Sourced] = None
    job_zone: Optional[Sourced] = None; bls_factors: Optional[Sourced] = None
    work_activities: Optional[Sourced] = None; work_context: Optional[Sourced] = None; knowledge: Optional[Sourced] = None; interests: Optional[Sourced] = None; related: Optional[Sourced] = None
    aioe: Optional[Sourced] = None; observed_exposure: Optional[Sourced] = None
    industries: Optional[Sourced] = None; licensing: Optional[Sourced] = None     # not supported by the current sources — always None, listed in `unavailable`
    proxies: list[dict] = []
    unavailable: list[str] = []                      # field names with no authoritative value → UI shows UNAVAILABLE

def _retrieved(*files: str) -> Optional[str]:
    ts = [os.path.getmtime(C.RAW / f) for f in files if (C.RAW / f).exists()]
    return time.strftime("%Y-%m-%d", time.localtime(max(ts))) if ts else None

def _src(key: str, value, files: tuple[str, ...], note: str | None = None) -> Sourced:
    s = C.SOURCES[key]; return Sourced(value=value, source=key, source_name=s["name"], as_of=s["as_of"], retrieved=_retrieved(*files), url=s["url"], note=note)

ONET_FILES = ("onet_occupation_data.csv", "onet_task_statements.csv"); BLS_FILES = ("bls_occupation_projections.xlsx",); AEI_FILES = ("aei/task_penetration.csv", "aei/job_exposure.csv"); AIOE_FILES = ("aioe_AIOE_DataAppendix.xlsx",)

def facts_for(rid: str) -> Optional[SourcedFacts]:
    r = C.get(rid)
    if not r: return None
    note = r.bls_note; un = []
    def bls(field, value, files=BLS_FILES, key="bls_ep"):
        if value is None: un.append(field); return None
        return _src(key, value, files, note)
    f = SourcedFacts(id=r.id, kind=r.kind, title=_src("onet", r.title, ONET_FILES), classification=_src("onet", {"soc": r.soc, "onet_soc": r.onet_soc, "kind": r.kind, "bls_title": r.bls_title}, ONET_FILES),
                     description=_src("onet", r.description, ONET_FILES) if r.description else None,
                     tasks=_src("onet", [TaskFact(**{k: t.get(k) for k in ("task", "task_type", "penetration")}).model_dump() for t in r.tasks], ONET_FILES + AEI_FILES, "penetration = Anthropic Economic Index observed AI use per task") if r.tasks else None,
                     employment_2025=bls("employment_2025", r.emp_2025), employment_2035=bls("employment_2035", r.emp_2035), growth_pct=bls("growth_pct", r.growth_pct), emp_change=bls("emp_change", r.emp_change), openings_annual=bls("openings_annual", r.openings_annual),
                     education_entry=bls("education_entry", r.education_entry), experience_entry=(_src("bls_ep", r.experience_entry, BLS_FILES) if r.experience_entry else None), training_entry=(_src("bls_ep", r.training_entry, BLS_FILES) if r.training_entry else None),
                     median_wage=bls("median_wage", r.median_wage, ("bls_occupation_projections.xlsx",), "bls_oes"), job_zone=(_src("onet", {"zone": r.job_zone, "name": r.job_zone_name}, ("onet_job_zones.csv",)) if r.job_zone else None),
                     bls_factors=(_src("bls_ep", r.bls_factors, BLS_FILES, "BLS Table 1.12: the projection team's stated factors") if r.bls_factors else None),
                     work_activities=(_src("onet", r.work_activities, ("onet_work_activities.csv",)) if r.work_activities else None), work_context=(_src("onet", r.work_context, ("onet_work_context.csv",)) if r.work_context else None),
                     knowledge=(_src("onet", r.knowledge, ("onet_knowledge.csv",)) if r.knowledge else None), interests=(_src("onet", {"scores": r.riasec, "high_points": r.interest_high_points}, ("onet_career_interest_types.csv",)) if r.riasec else None),
                     related=(_src("onet", r.related, ("onet_related_occupations.csv",)) if r.related else None),
                     aioe=(_src("aioe", {"score": r.aioe, "percentile": r.aioe_pct, "lm": r.aioe_lm}, AIOE_FILES) if r.aioe is not None else None),
                     observed_exposure=(_src("aei", {"share": r.observed_exposure, "percentile": r.observed_exposure_pct}, AEI_FILES) if r.observed_exposure is not None else None),
                     proxies=r.proxies, unavailable=[])
    for name in ("description", "tasks", "job_zone", "work_activities", "work_context", "knowledge", "interests", "related", "aioe", "observed_exposure", "bls_factors"):
        if getattr(f, name) is None: un.append(name)
    un += ["industries", "licensing"]      # the current project has no authoritative source for these (BLS Table 1.8 in the workbook holds links only; O*NET has no licensing file)
    f.unavailable = sorted(set(un)); return f

# ───────────────────────────── layer 2 · derived values ─────────────────────────────
class Derived(BaseModel):
    value: Any; rule: str; inputs: list[str]        # inputs = layer-1 field names the rule read

class DerivedValues(BaseModel):
    id: str
    growth_class: Derived; ai_task_share: Derived; ai_change_class: Derived; task_groups: Derived; human_intensive: Derived
    families: Derived; subjects: Derived; traits: Derived
    workday_hints: Derived; enjoy_hints: Derived; strengths_hints: Derived; test_ideas: Derived; trajectory: Derived

def derived_for(rid: str) -> Optional[DerivedValues]:
    r = C.get(rid)
    if not r: return None
    d = C.detail(rid)
    return DerivedValues(id=r.id,
        growth_class=Derived(value=r.growth_class, rule="growing if BLS projected change ≥ +5%; declining if < 0; stable otherwise; unknown without a projection (same thresholds as the graph)", inputs=["growth_pct"]),
        ai_task_share=Derived(value=r.ai_task_share, rule=f"share of the occupation's tasks with observed AI penetration ≥ {C.AI_ASSIST_THRESHOLD}", inputs=["tasks"]),
        ai_change_class=Derived(value=r.ai_change_class, rule="substantial if that share ≥ 0.40; moderate ≥ 0.20; limited otherwise; unknown without task data", inputs=["tasks"]),
        task_groups=Derived(value={k: [t["task"] for t in v] for k, v in d["ai"].items() if k in ("heavy", "mid", "low")}, rule="heavy ≥ 0.60 observed use · mid 0.25–0.60 · low < 0.25 or not observed", inputs=["tasks"]),
        human_intensive=Derived(value=r.human_intensive, rule="≤ 5% of tasks with heavy observed AI use AND an in-person / physical / public-facing work activity rated ≥ 4.0 of 5", inputs=["tasks", "work_activities", "work_context"]),
        families=Derived(value=r.families, rule="SOC major/minor group rules plus explicit overrides in data/career_families.json", inputs=["classification"]),
        subjects=Derived(value=r.subjects, rule="knowledge area importance ≥ the subject's threshold (data/career_families.json)", inputs=["knowledge"]),
        traits=Derived(value=r.traits, rule="any listed work-activity / interest / knowledge rating ≥ its threshold (data/career_families.json)", inputs=["work_activities", "work_context", "interests", "knowledge"]),
        workday_hints=Derived(value=d["workday"], rule="templated sentences from work-context ratings, each with its rating", inputs=["work_context"]),
        enjoy_hints=Derived(value=d["enjoy"], rule="templated from the interest high-points and traits, each with its rating", inputs=["interests", "work_activities", "knowledge"]),
        strengths_hints=Derived(value=d["strengths"], rule="the five highest-rated work activities and knowledge areas", inputs=["work_activities", "knowledge"]),
        test_ideas=Derived(value=d["test"], rule="generic suggestions chosen by Job Zone and family (data/career_families.json)", inputs=["job_zone", "classification"]),
        trajectory=Derived(value=d["trajectory"], rule="four separate readings: jobs today (BLS) · projected direction (BLS) · observed AI use (AEI) · top-rated knowledge (O*NET)", inputs=["employment_2025", "growth_pct", "openings_annual", "tasks", "knowledge"]))

# ───────────────────────────── evidence table (what the model is allowed to know) ─────────────────────────────
def evidence_cards(f: SourcedFacts) -> list[Card]:
    """Layer-1 facts as Cards — the same contract the graph's reviewer uses. Only these reach the model."""
    cards: list[Card] = []; t = f.title.value; occ = f.id
    def add(id_, claim, family, source, as_of, value=None, unit="", url=None, conf=0.95): cards.append(Card(id=id_, family=family, occ=occ, claim=claim, value=value, unit=unit, source=source, url=url, as_of=as_of, confidence=conf))
    if f.description: add(f"onet:desc:{occ}", f"{t}: {f.description.value}", "exposure", "O*NET", f.description.as_of, unit="text", url=f.description.url)
    add(f"onet:class:{occ}", f"{t} is " + {"direct": f"an official U.S. occupation (SOC {f.classification.value['soc']})", "detailed": f"an O*NET specialty ({f.classification.value['onet_soc']}) within the official occupation “{f.classification.value.get('bls_title')}”", "composite": "a composite role with no official U.S. category, assembled from official task statements"}[f.kind], "statistics", "O*NET", f.classification.as_of, unit="text")
    if f.employment_2025: add(f"bls:emp2025:{occ}", f"{t}: {f.employment_2025.value:,.0f} people employed in 2025 (BLS projections base year)" + (f" — {f.employment_2025.note}" if f.employment_2025.note else ""), "statistics", "BLS", f.employment_2025.as_of, f.employment_2025.value, "jobs", f.employment_2025.url)
    if f.growth_pct: add(f"bls:growth:{occ}", f"{t}: BLS projects employment to change {f.growth_pct.value:+.1f}% from 2025 to 2035 (all occupations {C.NATIONAL_GROWTH:+.1f}%)", "statistics", "BLS", f.growth_pct.as_of, f.growth_pct.value, "percent", f.growth_pct.url)
    if f.emp_change: add(f"bls:change:{occ}", f"{t}: BLS projects {f.emp_change.value:+,.0f} jobs added or lost, 2025–35", "statistics", "BLS", f.emp_change.as_of, f.emp_change.value, "jobs", f.emp_change.url)
    if f.openings_annual: add(f"bls:openings:{occ}", f"{t}: about {f.openings_annual.value:,.0f} openings per year on average, 2025–35 (growth plus replacement)", "statistics", "BLS", f.openings_annual.as_of, f.openings_annual.value, "jobs", f.openings_annual.url)
    if f.education_entry: add(f"bls:education:{occ}", f"{t}: typical education needed for entry is {f.education_entry.value}" + (f"; work experience: {f.experience_entry.value}" if f.experience_entry else "") + (f"; on-the-job training: {f.training_entry.value}" if f.training_entry else ""), "statistics", "BLS", f.education_entry.as_of, unit="text", url=f.education_entry.url)
    if f.median_wage: add(f"bls:wage:{occ}", f"{t}: median annual wage ${f.median_wage.value:,.0f} (OES 2025)", "statistics", "BLS", f.median_wage.as_of, f.median_wage.value, "usd", f.median_wage.url)
    if f.job_zone: add(f"onet:zone:{occ}", f"{t}: O*NET Job Zone {f.job_zone.value['zone']} — {f.job_zone.value['name']}", "statistics", "O*NET", f.job_zone.as_of, float(f.job_zone.value['zone']), "zone")
    if f.bls_factors:
        for i, x in enumerate(f.bls_factors.value[:3]): add(f"bls:factor:{occ}:{i}", f"BLS projection note for {t} ({x['industry']}): {x['text']}", "statistics", "BLS", f.bls_factors.as_of, unit="text", url=f.bls_factors.url, conf=0.9)
    if f.tasks:
        for i, x in enumerate(f.tasks.value[:14]):
            p = x.get("penetration"); add(f"onet:task:{occ}:{i}", x["task"], "exposure", "O*NET + Anthropic Economic Index", C.SOURCES["aei"]["as_of"], p, "penetration", conf=0.75 if p is not None else 0.4)
    if f.observed_exposure: add(f"aei:job:{occ}", f"{f.observed_exposure.value['share']:.0%} of {t} tasks show observed AI usage (percentile {f.observed_exposure.value['percentile']:.0%} of occupations) — observed use, not a forecast", "exposure", "Anthropic Economic Index", f.observed_exposure.as_of, f.observed_exposure.value["share"], "share", f.observed_exposure.url, 0.8)
    if f.aioe: add(f"aioe:{occ}", f"{t}: AI Occupational Exposure score {f.aioe.value['score']:.2f} (percentile {f.aioe.value['percentile']:.0%}); exposure is not job loss", "exposure", "AIOE", f.aioe.as_of, f.aioe.value["score"], "score", f.aioe.url, 0.85)
    if f.work_activities:
        top = sorted(f.work_activities.value.items(), key=lambda kv: -kv[1])[:8]; add(f"onet:wa:{occ}", f"{t}: most important work activities (O*NET, 1–5): " + "; ".join(f"{k} {v:.1f}" for k, v in top), "exposure", "O*NET", f.work_activities.as_of, unit="text")
    if f.work_context:
        cx = f.work_context.value; keys = ["Outdoors, Exposed to All Weather Conditions", "Indoors, Environmentally Controlled", "Contact With Others", "Deal With External Customers or the Public in General", "Spend Time Sitting", "Spend Time Standing", "Spend Time Using Your Hands to Handle, Control, or Feel Objects, Tools, or Controls", "Time Pressure", "Consequence of Error", "Work With or Contribute to a Work Group or Team", "Freedom to Make Decisions", "Physical Proximity"]
        add(f"onet:cx:{occ}", f"{t}: work context (O*NET, 1–5): " + "; ".join(f"{k} {cx[k]:.1f}" for k in keys if k in cx), "exposure", "O*NET", f.work_context.as_of, unit="text")
    if f.knowledge:
        top = sorted(f.knowledge.value.items(), key=lambda kv: -kv[1])[:6]; add(f"onet:kn:{occ}", f"{t}: most important knowledge areas (O*NET, 1–5): " + "; ".join(f"{k} {v:.1f}" for k, v in top), "exposure", "O*NET", f.knowledge.as_of, unit="text")
    if f.interests: add(f"onet:ri:{occ}", f"{t}: O*NET interest profile (1–7): " + "; ".join(f"{k} {v:.1f}" for k, v in f.interests.value["scores"].items()) + f"; high points {', '.join(f.interests.value['high_points'])}", "exposure", "O*NET", f.interests.as_of, unit="text")
    if f.related: add(f"onet:related:{occ}", f"{t}: related occupations (O*NET): " + ", ".join(x["title"] for x in f.related.value[:8]), "exposure", "O*NET", f.related.as_of, unit="text")
    for name in f.unavailable: cards.append(Card(id=f"unknown:{occ}:{name}", family="statistics", occ=occ, claim=f"{name.replace('_', ' ')}: {UNAVAILABLE}", source="NextShift", as_of=None, confidence=1.0, unit="unknown"))
    return cards

def refs_for(cards: list[Card]) -> tuple[dict, str]:
    """[cNN] → card id (unknowns get [uNN]) and the table text the model sees."""
    refs, lines, nc, nu = {}, [], 0, 0
    for c in cards:
        if c.id.startswith("unknown:"): nu += 1; k = f"u{nu:02d}"
        else: nc += 1; k = f"c{nc:02d}"
        refs[k] = c.id; lines.append(f"[{k}] ({c.source}, {c.as_of or 'n.d.'}) {c.claim}" + (f" — value {c.value:g} {c.unit}" if c.value is not None and c.unit != "text" else ""))
    return refs, "\n".join(lines)

# ───────────────────────────── layer 3 · interpretation ─────────────────────────────
class Interpretation(BaseModel):
    kind: Literal["career", "comparison"]; ids: list[str]; model: str; reviewer: str; prompt_version: str; catalog_version: str; generated_at: str
    sections: dict                              # section → list[str] (paragraphs stored as sentences); every factual line cites [cNN]/[uNN]; reflective lines end [advice]
    labels: dict = Field(default_factory=lambda: {"model": MODEL_LABEL, "day_in_the_life": ILLUSTRATIVE, "fit": FIT_LABEL, "ai": AI_LABEL})
    refs: dict = {}                             # [cNN] → card id
    cards: list[dict] = []                      # the evidence the model received (Card dumps) — provenance for every citation
    review: dict = {}                           # {status, stripped:[{path, sentence, reason}], total, kept, lint_removed}
    cached: bool = False

SECTIONS = ["what_is_it", "typical_day", "outlook_story", "who_thrives", "ai_story", "get_ready"]
FACTUAL = {"what_is_it", "typical_day", "outlook_story", "ai_story"}   # reviewed by the model reviewer
SUBJECTIVE = {"who_thrives", "get_ready"}   # deterministic lints only (citation + language), not model-reviewed
FIT_SECTIONS = ("who_thrives",)             # fit lines must point at a task or work characteristic

INTERPRET_SYS = """You tell a student the story of ONE occupation, in warm plain language, from an evidence table — like a knowledgeable counselor summarizing it out loud. Fold the numbers INTO the sentences and say what they suggest ("about 31,300 people do this today, and it's projected to grow 11% by 2035 — well above the 3.5% average for all jobs, so demand looks healthy").
You are NOT a source of facts: use ONLY the table. Never add a number, employer, school, course, wage or statistic that is not on a cited card; if something is not in the table, leave it out — never estimate. Every sentence that states or implies a fact ends with the refs it rests on, like [c03] or [c03] [c07]. Reasoned readings ("looks healthy", "suggests steady demand") are welcome when the cited cards support them — hedged with "looks/suggests/may", never guaranteed.
Language rules: no absolute fit claims (never "perfect", "ideal", "only for", "you must be", "not suited"); no personality labels; say "people who enjoy X tend to like this" and point at the task or rating card. Never "automated/replaced/eliminated/safe/AI-proof/doomed", no risk scores; keep the employment outlook (BLS) separate from AI task use (observed today, not a forecast) — if both are notable, say explicitly that heavy AI use does not mean fewer jobs.
Short and scannable: 2-4 sentences per part, no filler, no repeating the same number twice.
Return JSON: {"what_is_it": "2-3 conversational sentences: what this job actually is and what you'd spend your time doing",
 "typical_day": ["2-3 short lines sketching one illustrative day, each drawn from a cited task or work-context card"],
 "outlook_story": "2-4 sentences interpreting the outlook numbers: jobs today, projected change vs the all-occupations average, yearly openings, typical education — and what that adds up to for someone considering it",
 "who_thrives": ["3-4 bullets: 'People who enjoy … tend to do well here' — each tied to a task, activity, interest or knowledge card, ending [advice]"],
 "ai_story": "2-4 sentences: where AI is already used in the tasks (with the observed numbers), which parts stay strongly human, and what that may mean — clearly separated from the jobs outlook",
 "get_ready": ["3-4 bullets: what to start building or trying now — a skill from the cited knowledge/activity cards, and one low-cost way to test interest — ending [advice]"]}"""

COMPARE_SYS = """You explain how 2-4 careers differ for a student, from evidence tables (one per career). You are NOT a source of facts: use ONLY the tables; never add numbers or facts that are not on a cited card; if a figure is not available for one career, say so. Every sentence ends with refs like [c03]. Never pick a winner, never score them, never say a career is safe, AI-proof, doomed or perfect; keep employment outlook (BLS) separate from AI task use (observed today, not a forecast). Use "may", "tends to".
Return JSON: {"what_they_share": ["2-3 cited bullets"], "how_they_differ": ["3-5 cited bullets, each naming the careers it compares"], "questions_to_ask_yourself": ["2-3 reflective questions ending [advice]"]}"""

ABSOLUTE = re.compile(r"\b(perfect (fit|match|career|for you)|ideal (career|job|fit) for you|only for (creative|analytical|social|technical|extrover|introver|people who)|you must be an?|you are (an? )?(introvert|extrovert|not suited|unsuited)|not suited (for|to) you|you (are|would be) (a )?natural|guaranteed|100% safe|ai-proof|ai proof|safe from ai|safe career|job safety|replacement risk|will be (automated|replaced|eliminated)|will disappear|doomed|obsolete)\b", re.I)
_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")

def lint_reasons(text: str) -> list[str]:
    from graph import review as rv
    out = []
    if rv.certainty_violation(text): out.append("certainty about the future (lint)")
    if ABSOLUTE.search(text): out.append("absolute fit / safety language (lint)")
    return out

def _numbers_supported(text: str, cited: list[str], refs: dict, cards: dict) -> bool:
    """Every number in a model line must appear on one of the cards it cites (formatting-insensitive). Prevents the model from being the source of a statistic."""
    nums = [n.replace(",", "").replace("$", "").rstrip("%") for n in _NUM.findall(text)]
    nums = [n for n in nums if n and n not in ("2025", "2035", "1", "2", "3", "4", "5", "7")]   # years and the 1–5 / 1–7 rating scales are on every card's face
    if not nums: return True
    claims = " ".join(cards[refs[r]].claim.replace(",", "") + f" {cards[refs[r]].value:g}" if cards[refs[r]].value is not None else cards[refs[r]].claim.replace(",", "") for r in cited if r in refs and refs[r] in cards)
    return all(any(n.rstrip("0").rstrip(".") in claims or n in claims for _ in [0]) for n in nums)

def _check(obj: dict, refs: dict, cards: dict, factual_paths, reviewer_role: str = "skeptic") -> tuple[dict, dict, float]:
    """Deterministic lints first (uncited factual line · number not on its cards · certainty · absolute fit), then the existing reviewer over the factual lines. Returns (reviewed obj, record, cost)."""
    from graph import review as rv
    for k, v in list(obj.items()):   # paragraphs are judged one sentence at a time, so one bad sentence never takes the paragraph with it
        if isinstance(v, str): obj[k] = rv.split_sentences(v)
    ref_re = re.compile(r"\[([cu]\d{2,3})\]"); leaves = rv.flatten(obj); removed, to_check, kept = [], [], 0
    for p, t in leaves:
        section = p.split(".")[0].split("[")[0]; cited = [r for r in ref_re.findall(t) if r in refs]
        why = lint_reasons(t)
        if why: removed.append({"path": p, "sentence": t, "reason": why[0]}); continue
        if not cited and section in FIT_SECTIONS: removed.append({"path": p, "sentence": t, "reason": "fit line does not point at a task or work characteristic"}); continue
        if not cited and "[advice]" in t and not _NUM.search(t): kept += 1; continue
        if not cited: removed.append({"path": p, "sentence": t, "reason": "no evidence ref"}); continue
        if not _numbers_supported(t, cited, refs, cards): removed.append({"path": p, "sentence": t, "reason": "number not on the cited evidence card"}); continue
        if section in factual_paths: to_check.append((p, t, cited))
        else: kept += 1
    verdicts, cost, status = {}, 0.0, "verified"
    if to_check:
        from graph.nodes import SKEPTIC_SYS
        items = [(i, f"{t}\n   cards: " + " | ".join(f"[{r}] {cards[refs[r]].claim}" + (f" (value {cards[refs[r]].value} {cards[refs[r]].unit})" if cards[refs[r]].value is not None else "") for r in cited if refs[r] in cards)) for i, (p, t, cited) in enumerate(to_check)]
        verdicts, cost, status = rv.judge_lines(items, SKEPTIC_SYS, role=reviewer_role)
    for i, (p, t, _) in enumerate(to_check):
        v = verdicts.get(i, {"verdict": "keep", "reason": "cited; reviewer did not object" if status == "verified" else "UNVERIFIED"})
        if v.get("verdict") == "strip": removed.append({"path": p, "sentence": t, "reason": v.get("reason", "")})
        else: kept += 1
    rv.apply_removals(obj, [r["path"] for r in removed])
    total = kept + len(removed)
    return obj, {"status": status, "stripped": removed, "total": total, "kept": kept, "lint_removed": sum(1 for r in removed if "(lint)" in r["reason"] or r["reason"].startswith(("no evidence", "number not"))), "model_removed": sum(1 for r in removed if not ("(lint)" in r["reason"] or r["reason"].startswith(("no evidence", "number not"))))}, cost

def _cache_key(kind: str, ids: list[str]) -> str:
    from tools import cache; from graph import llm
    return cache.key_for("interpretation", kind=kind, ids=sorted(ids), catalog=C.VERSION, prompt=PROMPT_VERSION, model=llm.model_name("planner"), reviewer=llm.model_name("skeptic"))

def cached_interpretation(kind: str, ids: list[str]) -> Optional[Interpretation]:
    """Cache lookup only — never generates. Lets the UI show an existing explanation with zero model calls."""
    from tools import cache
    if cache.disabled(): return None
    hit = cache.get("interpretation", _cache_key(kind, ids))
    if not hit: return None
    it = Interpretation(**hit); it.cached = True; return it

def generate_interpretation(rid: str, force: bool = False, progress=None) -> Interpretation:
    """Layer 3 for one career. Cache → else: evidence table from layer 1 → model → lints → reviewer → cache. `progress(text)` reports steps to the UI."""
    from tools import cache; from graph import llm
    say = progress or (lambda t: None)
    if not force and (hit := cached_interpretation("career", [rid])): say("Reusing the explanation generated earlier — no model call"); return hit
    f = facts_for(rid); cards = evidence_cards(f); refs, table = refs_for(cards); by_id = {c.id: c for c in cards}
    say(f"Handing the model {len(cards)} sourced facts (and only those)…")
    out, cost = llm.chat_json("planner", INTERPRET_SYS, f"EVIDENCE TABLE for {f.title.value}:\n{table}", max_tokens=2200, temperature=0.3, purpose="career_interpretation")
    STRINGY = ("what_is_it", "outlook_story", "ai_story")
    sections = {k: out.get(k, "" if k in STRINGY else []) for k in SECTIONS}
    for k in SECTIONS:   # shape hygiene: strings vs lists
        if k in STRINGY: sections[k] = sections[k] if isinstance(sections[k], str) else " ".join(str(x) for x in sections[k])
        else: sections[k] = [str(x) for x in (sections[k] if isinstance(sections[k], list) else [sections[k]]) if str(x).strip()]
    say("Checking every line: citations, numbers, language — then the independent reviewer…")
    reviewed, record, c2 = _check(sections, refs, by_id, FACTUAL)
    it = Interpretation(kind="career", ids=[rid], model=llm.model_name("planner"), reviewer=llm.model_name("skeptic"), prompt_version=PROMPT_VERSION, catalog_version=C.VERSION, generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        sections=reviewed, refs=refs, cards=[c.model_dump() for c in cards], review=record)
    if record["status"] == "verified" and not cache.disabled(): cache.put("interpretation", _cache_key("career", [rid]), it.model_dump())
    say(f"Done — {record['total']} lines checked, {len(record['stripped'])} removed" + (" — UNVERIFIED (reviewer unavailable)" if record["status"] == "unverified" else "")); return it

def generate_comparison(ids: list[str], force: bool = False, progress=None) -> Interpretation:
    from tools import cache; from graph import llm
    say = progress or (lambda t: None); ids = ids[:4]
    if not force and (hit := cached_interpretation("comparison", ids)): say("Reusing the comparison generated earlier — no model call"); return hit
    cards = []; tables = []
    for rid in ids:
        f = facts_for(rid); cs = evidence_cards(f); cards += cs
    refs, table = refs_for(cards); by_id = {c.id: c for c in cards}
    say(f"Handing the model {len(cards)} sourced facts across {len(ids)} careers…")
    out, cost = llm.chat_json("planner", COMPARE_SYS, f"EVIDENCE TABLES:\n{table}", max_tokens=1600, temperature=0.3, purpose="career_comparison")
    sections = {k: [str(x) for x in (out.get(k) or []) if str(x).strip()] for k in ("what_they_share", "how_they_differ", "questions_to_ask_yourself")}
    say("Checking every line, then the independent reviewer…")
    reviewed, record, c2 = _check(sections, refs, by_id, {"what_they_share", "how_they_differ"})
    it = Interpretation(kind="comparison", ids=ids, model=llm.model_name("planner"), reviewer=llm.model_name("skeptic"), prompt_version=PROMPT_VERSION, catalog_version=C.VERSION, generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        sections=reviewed, refs=refs, cards=[c.model_dump() for c in cards], review=record)
    if record["status"] == "verified" and not cache.disabled(): cache.put("interpretation", _cache_key("comparison", ids), it.model_dump())
    say(f"Done — {record['total']} lines checked, {len(record['stripped'])} removed"); return it

def strip_refs(text: str) -> str: return re.sub(r"\s*\[(?:[cu]\d{2,3}|[a-z][a-z_ ]{2,30})\]", "", str(text or "")).strip()   # refs, [advice]/[interpretation] and any stray section tag the model echoes

def cited_sources(text: str, it: Interpretation) -> list[str]:
    """Human-readable provenance for one line: the source names behind its refs."""
    by = {c["id"]: c for c in it.cards}; out = []
    for r in re.findall(r"\[([cu]\d{2,3})\]", text or ""):
        c = by.get(it.refs.get(r))
        if c: out.append(f"{c['source']}" + (f" {c['as_of'][:4]}" if c.get("as_of") else ""))
    return list(dict.fromkeys(out))

# ───────────────────────────── layer 4 · personalized guidance (carried, not produced here) ─────────────────────────────
class PersonalizedGuidance(BaseModel):
    """Anything grounded in the student's own words. Produced by the student graph (graph/student*.py): profile refs [p:field:i], reviewer, gates.
    The explorer only hands over the seed and labels the result. Never disk-cached (contains the student's choices)."""
    seed: dict                                   # {"saved": [{id, title, reaction}], "at": ts}
    source: Literal["interview"] = "interview"
    label: str = "Personal to you — built from your answers, your saved careers and your reactions, and checked against them. Saving a career was treated as noticing it, not choosing it."

class CareerPage(BaseModel):
    facts: SourcedFacts; derived: DerivedValues; interpretation: Optional[Interpretation] = None; personalized: Optional[PersonalizedGuidance] = None

def page(rid: str, with_cached_interpretation: bool = True) -> Optional[CareerPage]:
    f = facts_for(rid)
    if not f: return None
    return CareerPage(facts=f, derived=derived_for(rid), interpretation=cached_interpretation("career", [rid]) if with_cached_interpretation else None)


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv; load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    ids = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--popular" in sys.argv:   # the careers students hit first: big occupations + one per family's top example
        ids += sorted({r.id for r in sorted(C.records().values(), key=lambda r: -(r.emp_2025 or 0))[:6] if not r.residual} | {C.browse(family=f, include_residual=False)[0].id for f in C.FAMILIES})
    for i, rid in enumerate(dict.fromkeys(ids)):
        t0 = time.time(); it = generate_interpretation(rid, progress=lambda t: None)
        print(f"[{i+1}/{len(ids)}] {rid} {C.get(rid).title[:40]:40} {'cached' if it.cached else f'{time.time()-t0:5.0f}s'} · {it.review['status']} · {len(it.review['stripped'])} removed", flush=True)
