"""Student journey — a career-discovery interviewer (Phase B: interview loop + understanding gate).
The student never has to name a career. One question at a time; the next question depends on what is still unclear,
on contradictions, and on what the student asked for. Nothing is persisted and no external tool is called before the understanding gate.

Profile fields hold Evidence (value + the student's quote + which turn), never bare labels, so every later recommendation can cite
what the student actually said ([p:field:i] refs) and the reviewer can check it."""
from __future__ import annotations
import json, re, time, uuid
from typing import Annotated, Literal, Optional, TypedDict
import operator
from langgraph.types import interrupt
from langgraph.config import get_stream_writer
from tools.schema import Card
from . import llm
from .state import merge_dicts

MAX_TURNS = 14; TARGET_TURNS = (8, 12)
FIELDS = ["interests", "energizing_activities", "demonstrated_strengths", "claimed_strengths", "growth_areas", "not_yet_learned", "dislikes", "work_preferences",
          "values", "desired_impact", "lifestyle_preferences", "education_constraints", "financial_constraints", "location_constraints", "time_constraints",
          "existing_career_ideas", "uncertainties"]
PIDTH = ["people", "ideas", "data", "technology", "hands_on"]
CORE = ["interests_or_energizing", "strengths", "negatives", "pidth", "constraints", "values_or_impact"]   # what must be ≥ moderate to be ready

class Evidence(TypedDict): value: str; quote: str; source_turn: int; kind: Literal["stated", "inferred"]

class StudentProfile(TypedDict, total=False):
    interests: list[Evidence]; energizing_activities: list[Evidence]; demonstrated_strengths: list[Evidence]; claimed_strengths: list[Evidence]
    growth_areas: list[Evidence]; not_yet_learned: list[Evidence]; dislikes: list[Evidence]; work_preferences: list[Evidence]
    pidth: dict; values: list[Evidence]; desired_impact: list[Evidence]; lifestyle_preferences: list[Evidence]
    education_constraints: list[Evidence]; financial_constraints: list[Evidence]; location_constraints: list[Evidence]; time_constraints: list[Evidence]
    existing_career_ideas: list[Evidence]; uncertainties: list[Evidence]; important_quotes_or_examples: list[str]
    confidence_by_field: dict; unresolved_questions: list[str]; contradictions: list[dict]
    summary_sections: dict          # the 9 sections shown (and possibly edited) at the understanding gate

class Turn(TypedDict, total=False): i: int; goal: str; question: str; answer: str; action: str; fields_touched: list[str]

class StudentState(TypedDict, total=False):
    door: str; thread_id: str; first_name: str
    profile: StudentProfile; turns: list[Turn]; completeness: dict; max_turns: int; last_action: str; pending: dict
    # later phases (C–E) reuse the professional gatherers, so the same reducers live here
    targets: list[dict]; candidates: list[dict]; reactions: list[dict]; discriminators: list[Turn]; shortlist: list[str]; rejected: list[dict]; selected: Optional[str]; deep_dive: dict
    experiments_planned: list[str]; exploration_log: list[dict]
    explorer_seed: Optional[dict]; seed_questions: list[str]      # from the Career Explorer: saved careers + reactions (evidence, never a choice) and templated comparison questions
    evidence_stage: str; deep_socs: list[str]; deep_done_socs: list[str]; deep_dives: dict; pending_after_deep: Optional[str]; evidence_meta: dict
    evidence: Annotated[list[Card], operator.add]; unknowns: Annotated[list[str], operator.add]; errors: Annotated[list[str], operator.add]
    source_status: Annotated[dict, merge_dicts]; tool_calls: Annotated[int, operator.add]; cost_usd: Annotated[float, operator.add]
    refs: dict; disagreements: list[dict]; forecast_context: list[str]; outlooks: dict; changes: dict
    reviewed: Optional[dict]; skeptic: dict; views: dict; approvals: dict; exported_path: Optional[str]; prior_snapshot: Optional[dict]

def _say(t: str):
    try: get_stream_writer()({"say": t, "t": time.time()})
    except Exception: pass

def _phase(key: str, **kw):
    """Structured 'what is being worked on now' event for the journey indicator. Emitted at the START of a node — real current work only."""
    try: get_stream_writer()({"phase": key, **kw, "t": time.time()})
    except Exception: pass

# ───────────────────────────── question goals + fallback bank ─────────────────────────────
GOALS = {   # goal → (priority, fields it informs, fallback questions in order of use)
    "energizing": (1, ["energizing_activities", "interests"], ["What do you find yourself doing when you lose track of time — in school or outside it?", "Think of the last project or activity you actually enjoyed. What were you doing, exactly?"]),
    "interests": (2, ["interests"], ["Which subjects or topics do you keep coming back to, even when nobody asks you to?", "If you could spend a semester on one subject only, which one — and what about it?"]),
    "strengths_example": (3, ["demonstrated_strengths", "claimed_strengths"], ["What's something people come to you for help with? Can you think of a time it happened?", "Tell me about something you made, fixed, organized or figured out that you were quietly proud of."]),
    "negatives": (4, ["dislikes", "growth_areas", "not_yet_learned"], ["What kind of work or schoolwork drains you — and is that because you dislike it, or because it's hard right now?", "Is there anything you'd want to avoid in a job, even if it paid well?"]),
    "pidth": (5, ["pidth", "work_preferences"], ["When you picture a good workday, which sounds closest: working with people, working with ideas, working with data, working with technology, or working with your hands? Pick one or two and say why.",
                                                 "Think of a school project you'd happily do again. Was the good part the people, the problem, the numbers, the tools, or making something with your hands?"]),
    "work_style": (6, ["work_preferences", "lifestyle_preferences"], ["Do you do your best work with a clear plan and structure, or when you can figure things out your own way? Alone, or on a team?",
                                                                    "When a group project goes well, what role did you end up playing — the organizer, the idea person, the one who finishes, the one who keeps everyone talking?"]),
    "constraints": (7, ["education_constraints", "financial_constraints", "location_constraints", "time_constraints"], ["Practically speaking — how much school are you open to after high school, and does cost or staying near home matter a lot?",
                                                                                                                       "If you had to choose: start earning in about two years, or spend four or more years in school first? And would cost or being far from home change that answer?"]),
    "values_impact": (8, ["values", "desired_impact"], ["When you imagine work that feels worth doing, what does it do for other people — or for you?", "What matters more to you right now: stability, creativity, helping people, making things, being an expert, earning well? Pick two."]),
    "lifestyle": (9, ["lifestyle_preferences"], ["What kind of life do you want work to fit around — travel, a steady schedule, working from anywhere, being outdoors, building something of your own?",
                                                 "Picture yourself at 30 on a normal Tuesday. Where are you, and what does the day look like?"]),
    "existing_ideas": (3, ["existing_career_ideas"], ["Are any careers already on your mind — even half-formed ones — or something a parent or teacher suggested?",
                                                     "Is there a job you've ruled out, or one you'd secretly like if you thought you could do it?"]),
    "uncertainties": (11, ["uncertainties"], ["What are you most unsure about when you think about all this?", "If you could get one question about your future answered right now, what would it be?"]),
    "clarify": (0, [], ["I noticed two things that seem to pull in different directions — can you help me understand how they fit together?"]),
    "saved_careers": (2, ["work_preferences", "existing_career_ideas"], ["Looking at the careers you saved while browsing, what do you think they have in common for you?", "Which of the careers you saved would you most want to try for a week, and why that one?"]),
}

def _coverage(profile: StudentProfile) -> dict:
    def lvl(items):
        items = items or []; stated = [e for e in items if e.get("kind") == "stated"]; quoted = [e for e in items if e.get("quote")]
        return "strong" if len(items) >= 2 and quoted else "moderate" if items and (stated or quoted) else "weak" if items else "none"
    cov = {f: lvl(profile.get(f)) for f in FIELDS}
    cov["strengths"] = max(cov["demonstrated_strengths"], cov["claimed_strengths"], key=["none", "weak", "moderate", "strong"].index)
    cov["negatives"] = max(cov["dislikes"], cov["growth_areas"], cov["not_yet_learned"], key=["none", "weak", "moderate", "strong"].index)
    p = profile.get("pidth") or {}; strong_keys = [k for k in PIDTH if abs(p.get(k, 0)) > 0.3]
    cov["pidth"] = "strong" if len(strong_keys) >= 2 else "moderate" if strong_keys else "none"
    cov["constraints"] = max(cov["education_constraints"], cov["financial_constraints"], cov["location_constraints"], key=["none", "weak", "moderate", "strong"].index)
    cov["values_or_impact"] = max(cov["values"], cov["desired_impact"], key=["none", "weak", "moderate", "strong"].index)
    cov["interests_or_energizing"] = max(cov["interests"], cov["energizing_activities"], key=["none", "weak", "moderate", "strong"].index)
    return cov

def _learned_summary(profile: StudentProfile) -> list[str]:
    out = []
    for f in FIELDS:
        vals = [e["value"] for e in (profile.get(f) or [])][:4]
        if vals: out.append(f"{f.replace('_', ' ')}: " + "; ".join(vals))
    p = profile.get("pidth") or {}
    if p: out.append("leans toward: " + ", ".join(f"{k} {'+' if v > 0 else ''}{v:.1f}" for k, v in sorted(p.items(), key=lambda kv: -abs(kv[1])) if abs(v) > 0.2))
    return out

# ───────────────────────────── nodes ─────────────────────────────
def init_interview(state: StudentState) -> dict:
    prof: StudentProfile = {f: [] for f in FIELDS}; prof.update({"pidth": {}, "important_quotes_or_examples": [], "confidence_by_field": {}, "unresolved_questions": [], "contradictions": [], "summary_sections": {}})
    seed = state.get("explorer_seed") or None; seed_qs: list[str] = []
    if seed:   # from the Career Explorer: saved careers become evidence the student can see and edit; saving is never treated as a decision
        from .student_seed import seed_evidence, seed_questions
        for f, items in seed_evidence(seed).items(): prof[f] = prof.get(f, []) + items
        seed_qs = seed_questions(seed); _say(f"Starting from the {len(seed.get('saved', []))} career(s) you saved while browsing — as things you noticed, not as a choice.")
    else: _say("Starting the conversation — no career names needed.")
    return {"explorer_seed": seed, "seed_questions": seed_qs, "door": "student", "thread_id": state.get("thread_id") or str(uuid.uuid4()), "profile": prof, "turns": [], "max_turns": MAX_TURNS, "completeness": {"ready": False, "coverage": _coverage(prof), "next_question_goal": "energizing"},
            "last_action": "", "candidates": [], "reactions": [], "shortlist": [], "rejected": [], "exploration_log": [], "experiments_planned": [], "evidence": [], "unknowns": [], "errors": [], "tool_calls": 0, "cost_usd": 0.0, "source_status": {}}

QUESTION_SYS = """You are a warm, plain-spoken career-discovery interviewer talking with a high-school or early-college student. You are given a BASE QUESTION that targets a specific goal.
Rewrite the base question in one natural sentence. You MAY start with a lead-in of at most eight words that acknowledges what the student just said (e.g. "Editing videos for friends — nice."), then ask the base question's topic EXACTLY.
Never drift back to earlier topics, never ask about the same moment again, never turn it into a follow-up on their last answer. Everyday language; no survey tone; no more than five options if the base offers options. Return {"question": "..."}"""

def select_question(state: StudentState) -> dict:
    _phase("question"); prof, turns, comp = state["profile"], state["turns"], state["completeness"]; goal = comp.get("next_question_goal") or "energizing"
    asked = sum(1 for t in turns if t.get("goal") == goal); bank = GOALS[goal][2]
    fallback = bank[min(asked, len(bank) - 1)]
    if goal == "clarify" and prof.get("contradictions"): c = prof["contradictions"][-1]; fallback = f"Earlier you said “{c.get('quote_a', '')[:80]}”, and also “{c.get('quote_b', '')[:80]}”. How do those fit together for you?"
    if goal == "saved_careers":   # templated from the saved careers' catalog profiles (graph/student_seed.py) — deterministic, then the curated bank
        bank = list(state.get("seed_questions") or []) + bank; fallback = bank[min(asked, len(bank) - 1)]
    if not turns: return {"pending": {"goal": goal, "question": bank[0], "source": "curated"}}    # the fixed opener — no model call before the student has said anything
    # Normal path is deterministic: code picked the goal, the curated bank supplies the wording (contradiction clarifiers are templated from the quotes above).
    # The model writes a question ONLY when this goal's bank is exhausted and we still need to ask about it — a genuinely new angle is required.
    already = {t.get("question", "") for t in turns}
    if goal == "clarify" or asked < len(bank):
        if fallback in already: fallback = next((q for q in bank if q not in already), fallback)   # never show the same sentence twice
        return {"pending": {"goal": goal, "question": fallback, "source": "curated"}}
    last = turns[-1]
    ctx = f"GOAL: {goal} (about: {', '.join(GOALS[goal][1])}).\nQUESTIONS ALREADY ASKED ON THIS TOPIC (do not repeat their angle): {bank}\nBASE QUESTION: {fallback}\nStudent's last answer (for an optional ≤8-word lead-in only; if it is '(not sure)' or '(skipped)' use NO lead-in): {last.get('answer', '')[:200]}"
    try:
        out, cost = llm.chat_json("planner", QUESTION_SYS, ctx, max_tokens=120, temperature=0.3, purpose="question_new_angle"); q = (out.get("question") or fallback).strip()
        if len(q) > 260 or "?" not in q or q in already: q = fallback
    except Exception: q, cost = fallback, 0.0
    if q in already: q = "Let me ask that a different way — " + q[0].lower() + q[1:]   # last resort: still never an identical repeat
    return {"pending": {"goal": goal, "question": q, "source": "model"}, "cost_usd": cost}

def interview_gate(state: StudentState) -> dict:
    """⏸ One question. Resume: {"action": "answer"|"skip"|"unsure"|"more"|"recommend"|"edit", "text": str, "edit_turn": int}."""
    q = state["pending"]; turns = list(state["turns"]); comp = state["completeness"]
    d = interrupt({"kind": "interview", "turn": len(turns) + 1, "max_turns": state["max_turns"], "goal": q["goal"], "question": q["question"], "learned": _learned_summary(state["profile"]),
                   "coverage": comp.get("coverage", {}), "profile": {f: state["profile"].get(f, []) for f in FIELDS} | {"pidth": state["profile"].get("pidth", {}), "contradictions": state["profile"].get("contradictions", [])}, "can_recommend": len(turns) >= 2, "previous": [{"i": t["i"], "question": t["question"], "answer": t.get("answer", "")} for t in turns]})
    action = d.get("action", "answer"); text = (d.get("text") or "").strip()
    if action == "edit":
        i = int(d.get("edit_turn", -1));
        for t in turns:
            if t["i"] == i: t["answer"] = text; t["action"] = "edit"
        return {"turns": turns, "last_action": "edit", "pending": {**q, "edited_turn": i}}
    if action in ("recommend", "more") and not text: return {"turns": turns, "last_action": action}
    turns.append({"i": len(turns) + 1, "goal": q["goal"], "question": q["question"], "answer": text if action == "answer" else ("(not sure)" if action == "unsure" else "(skipped)"), "action": action, "fields_touched": []})
    return {"turns": turns, "last_action": action}

UPDATE_SYS = """You maintain a structured profile of a student from an interview. You receive the current profile and ONE new question/answer (or an edited answer).
Return ONLY what changes, as JSON:
{"add": {"<field>": [{"value": "short label", "quote": "the student's words (verbatim fragment)", "kind": "stated|inferred"}]},
 "pidth": {"people": -1..1, "ideas": ..., "data": ..., "technology": ..., "hands_on": ...}   (only keys this answer informs; these REPLACE the old values),
 "contradictions": [{"fields": ["a","b"], "quote_a": "...", "quote_b": "...", "note": "..."}],
 "unresolved_questions": ["..."], "quotes": ["a memorable example worth keeping"]}
Fields: interests · energizing_activities · demonstrated_strengths (ONLY with a concrete example) · claimed_strengths (said, no example) · growth_areas ("hard but I want to improve") ·
not_yet_learned ("haven't tried/learned") · dislikes ("don't want to do this") · work_preferences · values · desired_impact · lifestyle_preferences · education_constraints · financial_constraints · location_constraints · time_constraints · existing_career_ideas · uncertainties.
Be careful: "I'm bad at X" is claimed weakness → growth_areas or not_yet_learned, never a permanent limit. "I don't know" → uncertainties, nothing else. A skipped question adds nothing. Do not invent; do not stereotype from gender, background or school."""

CONTRA_SYS = """You spot tensions in a student's career profile. Given what they are drawn to and the negatives/constraints they just added, list pairs that pull in different directions for career choice —
e.g. drawn to medicine but faints at blood; loves biology labs but wants no more than 2 years of school; wants to help people but dislikes talking to strangers. Only real tensions, max 2. Return {"contradictions":[{"fields":["interests","dislikes"],"quote_a":"...","quote_b":"...","note":"one line"}]}"""

def update_profile(state: StudentState) -> dict:
    _phase("profile"); prof = json.loads(json.dumps(state["profile"])); turns = state["turns"]; act = state.get("last_action")
    if act in ("skip", "recommend", "more") or not turns: return {"profile": prof}
    if act == "edit":
        i = state["pending"].get("edited_turn")
        for f in FIELDS: prof[f] = [e for e in prof.get(f, []) if e.get("source_turn") != i]     # re-derive: drop what that answer produced
        t = next(t for t in turns if t["i"] == i)
    else: t = turns[-1]
    if t["action"] == "unsure": prof["uncertainties"].append({"value": f"unsure about: {t['goal']}", "quote": "(not sure)", "source_turn": t["i"], "kind": "stated"}); return {"profile": prof}
    known = {f: [e["value"] for e in prof.get(f, [])] for f in FIELDS if prof.get(f)}
    try:
        out, cost = llm.chat_json("planner", UPDATE_SYS, f"Current profile (values only): {json.dumps(known)}\nCurrent leanings: {prof.get('pidth')}\n\nQ: {t['question']}\nA: {t['answer']}", max_tokens=900, temperature=0.1, purpose="profile_update")
    except Exception as e: out, cost = {}, 0.0; _say(f"(profile update skipped: {e})")
    touched = []
    for f, items in (out.get("add") or {}).items():
        if f in FIELDS:
            for e in items[:4]:
                if isinstance(e, dict) and e.get("value"): prof[f].append({"value": str(e["value"])[:80], "quote": str(e.get("quote", ""))[:160], "source_turn": t["i"], "kind": e.get("kind", "stated")}); touched.append(f)
    for k, v in (out.get("pidth") or {}).items():
        if k in PIDTH:
            try: prof["pidth"][k] = max(-1.0, min(1.0, float(v)))
            except Exception: pass
    for c in out.get("contradictions") or []: prof["contradictions"].append({**c, "turn": t["i"], "status": "open"})
    # cross-turn check: ONLY when a deterministic screen finds a high-value possible conflict the primary extraction did not already report
    if _needs_contra_check(prof, touched, t["i"], bool(out.get("contradictions"))):
        try:
            likes = [f"{e['value']} — “{e['quote']}”" for f in ("interests", "energizing_activities", "existing_career_ideas") for e in prof.get(f, [])]
            negs = [f"{f}: {e['value']} — “{e['quote']}”" for f in ("dislikes", "growth_areas", "not_yet_learned", "education_constraints", "financial_constraints", "location_constraints") for e in prof.get(f, []) if e.get("source_turn") == t["i"]]
            out2, c2 = llm.chat_json("extractor", CONTRA_SYS, f"Drawn to:\n" + "\n".join(likes) + "\n\nNew negatives/constraints this turn:\n" + "\n".join(negs), max_tokens=300, temperature=0.0, purpose="contradiction_check"); cost += c2
            known = {(c.get("quote_a", "")[:40], c.get("quote_b", "")[:40]) for c in prof["contradictions"]}
            for c in out2.get("contradictions") or []:
                if isinstance(c, dict) and (c.get("quote_a", "")[:40], c.get("quote_b", "")[:40]) not in known: prof["contradictions"].append({**c, "turn": t["i"], "status": "open"})
        except Exception: pass
    prof["unresolved_questions"] = (prof.get("unresolved_questions") or [])[-4:] + [u for u in (out.get("unresolved_questions") or []) if isinstance(u, str)][:2]
    prof["important_quotes_or_examples"] = (prof.get("important_quotes_or_examples") or []) + [q for q in (out.get("quotes") or []) if isinstance(q, str)][:2]
    prof["confidence_by_field"] = _coverage(prof)
    for tt in turns:
        if tt["i"] == t["i"]: tt["fields_touched"] = sorted(set(touched))
    _say(f"Learned: {', '.join(sorted(set(touched))) or 'nothing new'}")
    return {"profile": prof, "turns": turns, "cost_usd": cost}

NEG_FIELDS = ("dislikes", "growth_areas", "not_yet_learned", "education_constraints", "financial_constraints", "location_constraints")
LIKE_FIELDS = ("interests", "energizing_activities", "existing_career_ideas")
LIMIT_WORDS = ("no more than", "at most", "max", "only", "can't afford", "cannot afford", "no grad", "not grad", "short", "quick", "2-year", "two-year", "certificate", "no college", "not college", "avoid")
_STOP = {"about", "really", "would", "which", "there", "their", "thing", "things", "school", "people", "working", "something", "because", "don't", "doesn't"}

def _words(*texts) -> set[str]: return {w for w in re.findall(r"[a-z]{5,}", " ".join(texts).lower()) if w not in _STOP}

def _needs_contra_check(prof: dict, touched: list[str], turn_i: int, primary_found: bool) -> bool:
    """Deterministic screen for the extra contradiction call. True only if this turn added a negative/constraint AND either (a) it shares a substantive word with
    something the student is drawn to, or (b) it is an education/cost limit while the student has named careers — AND the primary extraction reported nothing."""
    if primary_found or not any(f in touched for f in NEG_FIELDS): return False
    new_negs = [(f, e) for f in NEG_FIELDS for e in prof.get(f, []) if e.get("source_turn") == turn_i]
    likes = [e for f in LIKE_FIELDS for e in prof.get(f, [])]
    if not new_negs or not likes: return False
    like_words = _words(*(e.get("value", "") + " " + e.get("quote", "") for e in likes))
    for f, e in new_negs:
        text = e.get("value", "") + " " + e.get("quote", "")
        if _words(text) & like_words: return True
        if f in ("education_constraints", "financial_constraints") and prof.get("existing_career_ideas") and any(w in text.lower() for w in LIMIT_WORDS): return True
    return False

def evaluate_completeness(state: StudentState) -> dict:
    """Code decides readiness and the next goal; no model call. Returns the structured Completeness object the UI can show."""
    _phase("completeness"); prof, turns, act = state["profile"], state["turns"], state.get("last_action"); cov = _coverage(prof); rank = ["none", "weak", "moderate", "strong"]
    substantive = sum(1 for t in turns if t.get("action") == "answer")
    missing = [c for c in CORE if rank.index(cov[c]) < 2]
    open_contra = [c for c in prof.get("contradictions", []) if c.get("status") == "open"]
    # next goal: value × gap; contradictions first; don't repeat a goal asked twice; don't repeat the last goal
    asked = {}; [asked.__setitem__(t["goal"], asked.get(t["goal"], 0) + 1) for t in turns]
    last_goal = turns[-1]["goal"] if turns else None
    def score(g):
        pr, fields, bank = GOALS[g]
        if g == "clarify": return 100 if open_contra and asked.get("clarify", 0) < 2 else -1
        if asked.get(g, 0) >= 2 or g == last_goal: return -1
        if asked.get(g, 0) >= len(bank): return -0.5   # curated questions for this topic are used up — only if nothing else is left (then the model writes a new angle)
        gap = 3 - min(rank.index(cov.get(f, "none")) if f != "pidth" else rank.index(cov["pidth"]) for f in fields) if fields else 0
        core_bonus = 2 if any(f in ("energizing_activities", "interests", "demonstrated_strengths", "dislikes", "pidth", "education_constraints", "values") for f in fields) else 0
        if g == "existing_ideas" and asked.get(g, 0) == 0 and len(turns) >= 2: core_bonus = 0 if state.get("explorer_seed") else 3      # always ask once, early — unless the explorer seed already lists their ideas
        if g == "saved_careers":
            n_seed = len(state.get("seed_questions") or [])
            if not n_seed or asked.get(g, 0) >= min(2, n_seed): return -1     # only with a seed; at most two targeted questions
            return 20 if len(turns) >= 1 else -1                               # early, right after the opener (contradiction clarifiers still win at 100)
        return gap * 3 + core_bonus - pr * 0.2
    goals = sorted((g for g in GOALS), key=score, reverse=True); nxt = goals[0] if score(goals[0]) > 0 else (goals[0] if score(goals[0]) == -0.5 and rank.index(cov.get(GOALS[goals[0]][1][0], "none")) < 2 else None)
    ready = (not missing and (asked.get("existing_ideas", 0) >= 1 or bool(state.get("explorer_seed"))) and not any(c.get("blocking") for c in open_contra) and (nxt is None or substantive >= TARGET_TURNS[0])) or act == "recommend" or len(turns) >= state["max_turns"]
    if act == "more" and len(turns) < state["max_turns"]: ready = False
    reason = ("You asked for recommendations" if act == "recommend" else f"Reached the {state['max_turns']}-question limit" if len(turns) >= state["max_turns"] else
              "Enough information to generate a varied, defensible shortlist." if ready else f"Still unclear: {', '.join(missing) or 'a few details'}")
    comp = {"ready": ready, "coverage": cov, "missing_high_value_fields": missing, "contradictions": [c.get("note", "") for c in open_contra], "next_question_goal": None if ready else (nxt or "uncertainties"),
            "reason": reason, "substantive_turns": substantive, "thin": ready and bool(missing)}
    if open_contra and not ready and asked.get("clarify", 0) < 2: comp["next_question_goal"] = "clarify"
    return {"completeness": comp}

def after_completeness(state: StudentState) -> str:
    return "understanding" if state["completeness"]["ready"] else "ask"

UNDERSTAND_SYS = """You write back to a student what a career-discovery interviewer understood, so they can check it. Second person, warm, plain, specific — quote their own words where you can.
Nine short sections (1-3 sentences each). Each section may ONLY use these profile fields — if they are empty write exactly "You didn't mention this yet.":
energizes ← energizing_activities, interests · strengths_demonstrated ← demonstrated_strengths (+ claimed_strengths, marked "you said") · skills_to_build ← growth_areas, not_yet_learned · avoid ← dislikes · how_you_work ← work_preferences, leanings ·
what_matters ← values, desired_impact, lifestyle_preferences · constraints ← education/financial/location/time_constraints · already_on_your_mind ← existing_career_ideas ONLY · unresolved ← uncertainties, contradictions, unresolved_questions.
Never diagnose, never label a personality type, never call anything a permanent weakness. Return {"sections": {"energizes": "...", "strengths_demonstrated": "...", "skills_to_build": "...", "avoid": "...", "how_you_work": "...", "what_matters": "...", "constraints": "...", "already_on_your_mind": "...", "unresolved": "..."}}"""
SECTION_TITLES = {"energizes": "What energizes you", "strengths_demonstrated": "Strengths you have shown", "skills_to_build": "Skills you want to build", "avoid": "What you want to avoid", "how_you_work": "How you prefer to work",
                  "what_matters": "What matters in your future", "constraints": "Practical constraints", "already_on_your_mind": "Careers or directions already on your mind", "unresolved": "Questions that remain unresolved"}

def render_understanding(state: StudentState) -> dict:
    _phase("understanding"); prof = state["profile"]; dump = {f: [{"value": e["value"], "quote": e.get("quote", "")} for e in prof.get(f, [])] for f in FIELDS if prof.get(f)}
    try: out, cost = llm.chat_json("planner", UNDERSTAND_SYS, f"Profile: {json.dumps(dump)}\nLeanings: {prof.get('pidth')}\nContradictions: {prof.get('contradictions')}\nUnresolved: {prof.get('unresolved_questions')}\nThin conversation: {state['completeness'].get('thin')}", max_tokens=900, purpose="understanding")
    except Exception as e: out, cost = {"sections": {k: "(could not write this section)" for k in SECTION_TITLES}}, 0.0
    sections = {k: (out.get("sections") or {}).get(k, "You didn't mention this yet.") for k in SECTION_TITLES}
    prof = {**prof, "summary_sections": sections}
    _say("Wrote back what I understood — your turn to check it.")
    return {"profile": prof, "cost_usd": cost}

def understanding_gate(state: StudentState) -> dict:
    """⏸ Gate 1. Resume: {"action": "confirm"|"edit"|"back"|"reject", "sections": {...edited}}. Nothing external has run yet."""
    d = interrupt({"kind": "understanding", "sections": state["profile"]["summary_sections"], "titles": SECTION_TITLES, "completeness": state["completeness"], "turns": len(state["turns"])})
    action = d.get("action", "confirm"); prof = dict(state["profile"])
    if action == "edit" and d.get("sections"): prof["summary_sections"] = {**prof["summary_sections"], **d["sections"]}
    return {"profile": prof, "last_action": action, "approvals": {**state.get("approvals", {}), "understanding": {"action": action, "at": time.time(), "edited": action == "edit"}}}

def after_understanding(state: StudentState) -> str:
    a = state["approvals"]["understanding"]["action"]
    return "back" if a == "back" else "end" if a == "reject" else "candidates"
