"""Plain-language and technical copy for the "Behind the scenes" panel. Pure strings — no Streamlit, no model calls — so tests can pin every
factual claim to the code constant it describes (tests/test_copy_facts.py). Tags: [you] a person decides · [code] a fixed rule · [AI] a language model."""
from __future__ import annotations
from graph.student import MAX_TURNS, TARGET_TURNS
from graph.nodes import UNCITED_LIMIT
from graph import llm

from ui.student_ui import BOUNDARY  # single source of truth for the boundary line
INTRO = f"{BOUNDARY} Seven steps; two of them are yours."
LEGEND = "[you] a person decides · [code] a fixed rule, the same every time · [AI] a language model writes or interprets"

# ───────────────────────────── How NextShift works (7 steps) ─────────────────────────────
def steps(door: str) -> list[dict]:
    """[{n, title, tags, body, more_title, more}] — body is 1–2 sentences; anything longer sits behind `more`."""
    student = door != "professional"
    s1 = {"n": 1, "title": "We listen before recommending", "tags": ["AI"],
          "body": ("NextShift asks one question at a time. After each answer, it updates a structured understanding of your interests, demonstrated strengths, preferences, constraints, and uncertainties."
                   if student else "Four short questions in plain language: your role, what a normal week actually looks like, your industry, and what's on your mind. Titles are ambiguous; tasks aren't."),
          "more_title": "What this is not",
          "more": ("It is not a personality test and it does not decide your \"perfect career.\" Everything it records about you is written as *what you said* — you can read it, correct it, or remove it by editing an earlier answer. "
                   "If you say you're bad at something, that is recorded as a skill you haven't built yet, never as a permanent limit."
                   if student else "It does not judge your performance or predict your job. It uses your week to find the official occupation whose task list is closest to your real work.")}
    s2 = {"n": 2, "title": "We decide what to ask next" if student else "We match your work to an official occupation", "tags": ["code"] if student else ["code", "AI"],
          "body": (f"After every answer, a fixed rule (not the AI) checks which important parts of your profile are still unclear and picks the next question from a curated set for that topic. The AI writes a question only when a topic's set runs out. "
                   f"The interview stops when the rule says there is enough (usually after {TARGET_TURNS[0]}–{TARGET_TURNS[1]} answers), when you press *Recommend careers now*, or at {MAX_TURNS} questions — whichever comes first."
                   if student else "Your title is matched to the U.S. occupation list — exact title first, then by meaning. When no official category exists (many \"Product…\" roles), NextShift assembles a composite from official task statements and shows you the task list to untick."),
          "more_title": "Why a rule and not the AI" if student else "Exact, closest, composite",
          "more": ("Completeness and the question limit are deterministic controls: the same conversation always stops at the same point, and no model can decide to keep you talking."
                   if student else "**Exact** — the government tracks this job under this name. **Closest match** — matched by meaning; we say which occupation. **Composite** — assembled from the tasks of several official occupations; every number is labelled as coming from the pieces.")}
    s3 = {"n": 3, "title": "You confirm what we understood", "tags": ["you"],
          "body": ("Before researching any career, NextShift shows you what it understood in nine short sections. You can correct it, go back to the interview, or stop."
                   if student else "Before it spends a single lookup, NextShift restates what it understood about you and shows the occupation it will analyze. You can fix the summary, change the horizon, pick another occupation, or stop."),
          "more_title": "What has happened by this point", "more": "No career data has been looked up and nothing has been added to your saved record. This is a human checkpoint: the analysis does not start until you say so."}
    s4 = {"n": 4, "title": "We connect possibilities to real careers", "tags": ["AI", "code"],
          "body": ("NextShift proposes 8–10 varied directions — strong matches, worth exploring, unexpected possibilities, and your own ideas reconsidered — and matches each to an official U.S. occupation so you get real numbers."
                   if student else "Each occupation is looked up in the official statistics so the plan rests on real numbers, not impressions."),
          "more_title": "Exact, proxy, composite",
          "more": "**Exact** — the government tracks this job under this name. **Proxy** — the numbers come from the closest official category, and we say which. **Composite** — for modern jobs with no official category, we assemble the job from official task statements and label every number as coming from the pieces. At most two directions may be composites."}
    s5 = {"n": 5, "title": "We gather evidence", "tags": ["code"],
          "body": ("Two levels. First, for every direction: **BLS** (projected growth, yearly openings, wages, typical entry education) and the **O\\*NET** description, plus **your own answers** (why a direction fits *you*). "
                   "Then, only for the careers you react to: **Anthropic Economic Index** (which tasks AI is already used for), **AIOE** (an academic measure of AI exposure) and the detailed task list. **Forecasting platforms** (how fast people expect AI to progress — a range, never averaged) are read once per session."
                   if student else "For your occupation, in parallel: **BLS** (projected growth, yearly openings, wages, typical entry education) · **O\\*NET** (what people actually do) · **Anthropic Economic Index** (which of those tasks AI is already used for) · "
                   "**AIOE** (an academic measure of AI exposure) · **forecasting platforms** (how fast people expect AI to progress — shown as a range, never averaged)."),
          "callout": "Current AI use is not treated as proof that a career will disappear. It tells us where AI already helps; what that means for jobs is marked as interpretation.",
          "more_title": "When a source is down", "more": "A source that fails is marked *unavailable* and the result carries a partial-evidence badge. Missing numbers stay \"unknown\" — nothing is estimated to fill a gap."}
    s6 = {"n": 6, "title": "We check the recommendations", "tags": ["code", "AI"],
          "body": "Two checks, in order. First a fixed rule removes any statement that doesn't point at a source — a piece of career data" + (" or something you said" if student else "") + ". "
                  "Then a separate AI reviewer (a different model from the writer) reads every remaining line against its source and removes what doesn't hold up" + (", including advice that ignores a constraint you stated or presents an opinion as fact. The short first-round cards get a fast reviewer; the detailed cards, shortlist and deep dive get the stronger, slower one." if student else f"; if more than {UNCITED_LIMIT:.0%} is removed the plan is rewritten once."),
          "more_title": "If the reviewer fails",
          "more": "Everything you see is marked **UNVERIFIED** — on screen, on the journey indicator, and in the saved file's name. We never claim a check happened when it didn't. What was removed is always listed under *How we reached this*."}
    s7 = {"n": 7, "title": "You decide what happens next", "tags": ["you"],
          "body": ("You react to each direction and say why; that becomes part of your profile. You narrow a shortlist, go deep on one, and try \"what-ifs.\" NextShift supports the decision; it does not make it."
                   if student else "You read the plan, edit it if you like, and approve or reject it. NextShift supports the decision; it does not make it."),
          "more_title": "When memory is written",
          "more": ("Nothing is added to your saved record until you press *Save my exploration*. You can stop at any point with nothing saved."
                   if student else "Nothing is added to your saved record until you press *Approve & save*. Reject, and nothing is written.")}
    return [s1, s2, s3, s4, s5, s6, s7]

# journey step index → explanation step number, so the panel can say "you are here"
STUDENT_JOURNEY_TO_STEP = {0: 1, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 7, 7: 7, 8: 7}
PRO_JOURNEY_TO_STEP = {0: 1, 1: 3, 2: 5, 3: 5, 4: 6, 5: 6, 6: 7}

# ───────────────────────────── What is saved? ─────────────────────────────
def saved_copy(door: str, tracing_on: bool) -> dict:
    student = door != "professional"
    trace = ("and — because developer mode is on — to LangSmith for developer tracing" if tracing_on else "and nowhere else (developer tracing is off)")
    return {
        "while": ("**While you work** — Your answers live in this browser session and in a resumable session file on the computer running NextShift (`checkpoints.sqlite`), so you can go back a step without losing work. "
                  f"That file is not your saved record and is not read by later sessions. Your answers are sent to the AI model provider (Nebius) to be interpreted, {trace}. No career data is looked up before you confirm your profile."),
        "after": ("**When you press Save** — A short exploration file and a snapshot are written on this computer: your confirmed profile, career reactions, shortlist, the career you explored, your planned experiments, and the evidence used. "
                  "If the review step had failed, the file name says UNVERIFIED."
                  if student else "**When you press Approve & save** — Your plan is written as a file on this computer, with a snapshot of the evidence so a later run can show what changed, and your role and horizon are remembered for next time. If the review step had failed, the file name says UNVERIFIED."),
        "never": "**Nothing is published or sent to an employer, school, or other person.** NextShift has no accounts; the files stay on the machine it runs on. Reject at either checkpoint and nothing is written.",
    }

# ───────────────────────────── For builders ─────────────────────────────
STUDENT_ARCH = ["Adaptive interview (curated questions; one extraction call per answer)", "structured profile (evidence: value · quote · turn)", "code-based completeness decision", "⏸ human confirmation", "career generation", "occupation resolution (exact → semantic → composite; cached)",
                "Level A: official outlook + O*NET description per direction (parallel, local data) → deterministic cards → fast review", "⏸ student reactions", "Level B: task-level AI-use evidence for the reacted-to careers only → detailed cards → thinking review",
                "⏸ discriminating questions", "⏸ shortlist and deep dive (what-ifs loop; deep dives reused until reactions or constraints change)", "⏸ final approval and memory"]
PRO_ARCH = ["Guided intake", "occupation resolution (exact → semantic → composite)", "restate what was understood", "⏸ human confirmation", "parallel evidence gathering (outlook · exposure · forecasts · research)",
            "reconcile (dedupe · disagreements · unknowns · deltas vs last snapshot)", "outlook + three task groups (code)", "plan writer", "independent reviewer (rewrite once if > 30 % removed)", "⏸ plan approval and memory"]

MODEL_WORK = ["Interpreting substantive free-text answers into profile evidence", "Wording the next interview question (topic chosen by code)", "Generating candidate careers with cited rationales",
              "Writing fit rationales, card prose and the plan", "Comparing tradeoffs (shortlist, what-ifs)", "Producing deep dives", "Reviewing interpretive claims (a different model from the writer)"]
DETERMINISTIC = [f"Interview completeness, the next-question goal and the curated question itself", f"Maximum interview turns ({MAX_TURNS})", "Which careers get deep evidence (the reacted-to set) and cache keys (dataset versions + TTL)", "Graph routing between nodes and gates", "Occupation-data lookup and composite assembly",
                 "Employment-outlook readings (BLS projection only) and the three task groups (observed AI use thresholds)", "Citation/reference validation — uncited lines removed before any model judges them; rationale lines must cite the student's own words",
                 "Certainty-wording lint (\"will disappear\", \"perfect fit\" …) regardless of citations", "Practical-mismatch lines (entry education vs stated limits)", "Cache keys for embeddings and source calls", "Approval requirements: no analysis before gate 1, no write before the final gate",
                 "Write boundary: `record` is the only node that writes", "Failure flags: unavailable sources, unknowns, UNVERIFIED review"]
STATE_MEMORY = ["LangGraph holds the workflow state on one thread per session; each gate is an `interrupt` and resuming continues from the checkpoint.",
                "Checkpoints are written to SQLite after every step, which is what lets you go back a step or edit an earlier answer without redoing work.",
                "Student answers are stored as traceable profile evidence — `{value, quote, source_turn, kind}` — so every recommendation line can point at what you said (`[p:field:i]`).",
                "Persistent memory (`memory.sqlite`, exploration/plan files) is written only by `record`, after the final approval.",
                "Returning to earlier stages reuses completed work: the evidence gathered once is kept on the thread; only the changed step re-runs."]
FAILURE = ["A failed source produces a partial-evidence warning; the run continues with what exists.", "Missing data remains \"unknown\" — never estimated.",
           "A reviewer failure produces an UNVERIFIED result: banner, journey flag, filename tag; the rewrite loop is skipped rather than looping on an absent reviewer.",
           "Loops are bounded: ≤ 14 interview turns, one plan rewrite, two reviewer attempts per batch, ≤ 2 composites, ≤ 2 candidates per occupation.",
           "You can reject or stop at any gate; nothing is written."]

def model_roles() -> dict:
    return {"planner (writer)": llm.model_name("planner"), "skeptic (reviewer)": llm.model_name("skeptic"), "extractor (filters, embeddings' descriptions)": llm.model_name("extractor")}
