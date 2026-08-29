"""Pure helpers behind the "Behind the scenes" panel and the sidebar journey indicator. No Streamlit import, no model calls —
everything here is derived from state the graph already produced (stage, interrupt payload, phase events, reviewed views).
Tested in tests/test_journey.py."""
from __future__ import annotations
import re

# ───────────────────────────── journey steps ─────────────────────────────
STUDENT_STEPS = ["Learning what matters to you", "Checking that we understood", "Finding career directions", "Comparing real-world evidence",
                 "Checking the recommendations", "Learning from your reactions", "Narrowing your shortlist", "Exploring one career deeply", "Waiting for your approval"]
PRO_STEPS = ["Understanding your role", "Checking that we understood", "Gathering employment evidence", "Examining how work is changing",
             "Building your preparation plan", "Checking the recommendations", "Waiting for your approval"]

# Streamlit stage → index of the step the person is AT (between graph runs)
STUDENT_STAGE = {"s_interview_run": 0, "s_interview": 0, "s_understanding": 1, "s_results": 5, "s_discriminate": 5, "s_shortlist": 6, "s_deep": 7, "s_save": 8}
PRO_STAGE = {"intake": 0, "understanding_run": 1, "understanding": 1, "working": 2, "plan": 6}
# phase event (emitted by graph nodes while running) → step index currently being worked on
STUDENT_PHASE = {"question": 0, "profile": 0, "completeness": 0, "understanding": 0, "candidates": 2, "resolve": 2, "gather": 3, "outlook": 3, "fit": 3, "review": 4,
                 "reactions": 5, "shortlist": 6, "whatif": 6, "deep": 7, "save": 8}
PRO_PHASE = {"understanding": 0, "gather": 2, "outlook": 3, "plan": 4, "review": 5, "save": 6}
# a review phase belongs to the thing being reviewed
STUDENT_REVIEW_OF = {"career cards": 4, "shortlist": 6, "deep dive": 7, "what-if": 6}

# plain-language copy for what is happening right now (one line per phase; {of} is filled from the event)
PHASE_COPY = {"question": "Choosing the next useful question…", "profile": "Adding what you shared to your profile…", "completeness": "Checking what remains unclear…",
              "understanding": "Writing back what we understood…", "candidates": "Finding patterns in what you shared and identifying career directions…",
              "resolve": "Matching them to official occupations…", "gather": "Comparing job outlook, education and where AI is already used…",
              "outlook": "Reading the employment outlook…", "fit": "Writing the career cards…", "plan": "Building your preparation plan…",
              "review": "Checking the {of}…", "reactions": "Learning from your reactions…", "shortlist": "Comparing tradeoffs across your shortlist…",
              "deep": "Writing the deep dive — daily work, AI use, ways to test it…", "whatif": "Reconsidering your shortlist…", "save": "Saving what you approved…"}

STATES = ("done", "current", "todo", "attention", "unverified", "stopped")


def phase_copy(ev: dict | None) -> str:
    if not ev or not ev.get("phase"): return ""
    return PHASE_COPY.get(ev["phase"], "Working…").format(of=ev.get("of", "recommendations"))


def journey_steps(door: str, stage: str, phase: dict | None = None, views: dict | None = None, payload: dict | None = None, approvals: dict | None = None,
                  exported: bool = False, completeness: dict | None = None) -> list[dict]:
    """→ [{label, state, note}] for the sidebar. Never fakes progress: the current step comes from the stage or, while the graph runs, the last phase event."""
    student = door == "student"; labels = STUDENT_STEPS if student else PRO_STEPS
    views = views or {}; approvals = approvals or {}; payload = payload or {}
    cur = (STUDENT_STAGE if student else PRO_STAGE).get(stage)
    ended = stage in ("s_done", "done")
    if phase and phase.get("phase"):
        key = phase["phase"]
        if student and key == "review": cur = STUDENT_REVIEW_OF.get(phase.get("of", ""), 4)
        else: cur = (STUDENT_PHASE if student else PRO_PHASE).get(key, cur)
    if cur is None and not ended: cur = 0
    steps = []
    for i, label in enumerate(labels):
        if ended: state = "done" if exported else ("stopped" if i == _stop_index(student, approvals, labels) else ("done" if i < _stop_index(student, approvals, labels) else "todo"))
        else: state = "done" if i < cur else "current" if i == cur else "todo"
        steps.append({"label": label, "state": state, "note": ""})
    # flags derived from real results (only on steps that have happened)
    unavailable = [k for k, v in (views.get("source_status") or {}).items() if v == "unavailable"]
    ev_i = 3 if student else 2; rv_i = 4 if student else 5
    if unavailable and steps[ev_i]["state"] in ("done", "current"): steps[ev_i].update(state="attention", note="partial evidence — unavailable: " + ", ".join(unavailable))
    if views.get("review_status") == "unverified" and steps[rv_i]["state"] in ("done", "current"): steps[rv_i].update(state="unverified", note="UNVERIFIED — the review step failed")
    if student and (completeness or {}).get("thin") and steps[0]["state"] == "done": steps[0].update(state="attention", note="short conversation — suggestions are rougher")
    if student and (views.get("deep_dive_review") or {}).get("status") == "unverified" and steps[7]["state"] in ("done", "current"): steps[7].update(state="unverified", note="UNVERIFIED — the review step failed")
    return steps


def _stop_index(student: bool, approvals: dict, labels: list[str]) -> int:
    """Where a run that ended without saving stopped."""
    if (approvals.get("understanding") or {}).get("action") == "reject": return 1
    if student:
        if (approvals.get("save") or {}).get("action") == "reject": return 8
        if (approvals.get("reactions") or {}).get("action") == "stop": return 5
        return 8
    if (approvals.get("plan") or {}).get("action") == "reject": return 6
    return 6


GLYPH = {"done": ("✓", "completed"), "current": ("●", "current step"), "todo": ("○", "not started"), "attention": ("⚠", "needs attention"), "unverified": ("⚠", "unverified"), "stopped": ("■", "stopped here")}

def step_html(step: dict) -> str:
    """Accessible row: glyph carries an aria-label, state is also in text, never colour alone."""
    g, aria = GLYPH[step["state"]]
    cls = {"done": "j-done", "current": "j-cur", "todo": "j-todo", "attention": "j-warn", "unverified": "j-warn", "stopped": "j-stop"}[step["state"]]
    note = f"<div class='j-note'>{step['note']}</div>" if step.get("note") else ""
    return f"<div class='j-step {cls}' role='listitem'><span role='img' aria-label='{aria}'>{g}</span> <span>{step['label']}</span>{'<span class=\"j-sr\"> — ' + aria + '</span>' if step['state'] in ('current', 'attention', 'unverified', 'stopped') else ''}{note}</div>"


# ───────────────────────────── refs → the person's own words ─────────────────────────────
PREF = re.compile(r"\[(p:[a-z_]+:\d+)\]"); CREF = re.compile(r"\[([cu]\d{2,3})\]"); TAG = re.compile(r"\s*\[(?:interpretation|advice)\]")

def resolve_refs(line: str, profile_refs: dict) -> dict:
    """Split a rationale/card line into its text and the student quotes it rests on. profile_refs is views['profile_refs'] ({'p:field:i': 'field: value — “quote”'})."""
    quotes = []
    for r in PREF.findall(line or ""):
        src = profile_refs.get(r, ""); m = re.search(r"“(.*)”", src)
        quotes.append(m.group(1) if m else src.split(": ", 1)[-1])
    text = TAG.sub("", CREF.sub("", PREF.sub("", line or ""))).strip()
    return {"text": text, "quotes": [q for q in quotes if q], "interpretation": "[interpretation]" in (line or "")}


# ───────────────────────────── What NextShift currently understands (interview) ─────────────────────────────
UNDERSTAND_SECTIONS = [("Interests", ["interests"]), ("Activities that energize you", ["energizing_activities"]), ("Demonstrated strengths", ["demonstrated_strengths", "claimed_strengths"]),
                       ("Skills you want to build", ["growth_areas", "not_yet_learned"]), ("Things you prefer to avoid", ["dislikes"]), ("Work preferences", ["work_preferences", "pidth"]),
                       ("Values and desired impact", ["values", "desired_impact", "lifestyle_preferences"]), ("Practical constraints", ["education_constraints", "financial_constraints", "location_constraints", "time_constraints"]),
                       ("Existing career ideas", ["existing_career_ideas"]), ("Remaining uncertainties", ["uncertainties", "contradictions"])]
PIDTH_LABEL = {"people": "people", "ideas": "ideas", "data": "data", "technology": "technology", "hands_on": "working with your hands"}

def understands_sections(profile: dict) -> list[dict]:
    """[{title, items:[{value, quote, turn, tag}]}] from the structured profile already in state. No model call; values/quotes are the student's own."""
    out = []
    for title, fields in UNDERSTAND_SECTIONS:
        items = []
        for f in fields:
            if f == "pidth":
                p = profile.get("pidth") or {}; lean = [PIDTH_LABEL[k] for k, v in sorted(p.items(), key=lambda kv: -kv[1]) if k in PIDTH_LABEL and v > 0.2]
                if lean: items.append({"value": "Leaning toward " + ", ".join(lean), "quote": "", "turn": None, "tag": "from several answers"})
                continue
            if f == "contradictions":
                for c in profile.get("contradictions") or []:
                    if c.get("status") == "open" and c.get("note"): items.append({"value": c["note"], "quote": "", "turn": c.get("turn"), "tag": "two answers pull in different directions"})
                continue
            for e in profile.get(f) or []:
                tag = {"claimed_strengths": "you said", "not_yet_learned": "not tried yet", "growth_areas": "hard now, want to improve", "demonstrated_strengths": "with an example"}.get(f, "")
                if e.get("kind") == "inferred": tag = (tag + " · " if tag else "") + "our reading"
                items.append({"value": e.get("value", ""), "quote": e.get("quote", ""), "turn": e.get("source_turn"), "tag": tag})
        out.append({"title": title, "items": items})
    return out

# ───────────────────────────── Why this appeared (career card) ─────────────────────────────
RATIONALE_LABEL = {"matches_interests": "Matches what interests you", "uses_strengths": "Uses strengths you showed", "fits_preferences": "Fits how you like to work", "constraints_ok": "Works with your constraints",
                   "why_included": "Why it made the list", "constraints_conflict": "May conflict with what you said", "poor_fit_if": "Might not fit if"}

def resolution_label(candidate: dict) -> dict:
    """Exact / closest / composite, from the resolver's own record — never inferred from the card text."""
    r = candidate.get("resolution") or ""; title = (candidate.get("persona") or {}).get("title", "")
    if r == "composite": return {"kind": "composite", "text": f"Composite — no official category for this role. Figures come from the closest official occupations" + (f": {candidate['card'].get('proxy_note')}" if (candidate.get('card') or {}).get('proxy_note') else ".")}
    if "tier 1" in r: return {"kind": "exact", "text": f"Official occupation (exact match): {title}"}
    if r.startswith("official"): return {"kind": "proxy", "text": f"Closest official occupation: {title} — figures are for this category"}
    return {"kind": "unknown", "text": "Could not be matched to an official occupation"}

def why_this_appeared(candidate: dict, views: dict) -> dict:
    """Two groups from data the graph already reviewed: the candidate's cited rationale (deterministically checked against profile refs) and the reviewed card.
    Nothing is generated here; removed content is absent because the card object IS the reviewed object."""
    prefs = views.get("profile_refs") or {}; rat = candidate.get("rationale") or {}; card = candidate.get("card") or {}
    told = []
    for k in ("why_included", "matches_interests", "uses_strengths", "fits_preferences", "constraints_ok"):
        lines = rat.get(k); lines = [lines] if isinstance(lines, str) else (lines or [])
        for l in lines:
            if l and l.strip(): told.append({"label": RATIONALE_LABEL[k], **resolve_refs(l, prefs)})
    conflicts = [{"label": RATIONALE_LABEL["constraints_conflict"], **resolve_refs(l, prefs)} for l in (rat.get("constraints_conflict") or []) if l.strip()]
    conflicts += [{"label": "Practical mismatch", **resolve_refs(l, prefs)} for l in (card.get("constraint_flags") or [])]
    if (rat.get("poor_fit_if") or "").strip(): conflicts.append({"label": RATIONALE_LABEL["poor_fit_if"], **resolve_refs(rat["poor_fit_if"], prefs)})
    soc = (candidate.get("persona") or {}).get("soc", "")
    evidence = {"outlook": [resolve_refs(f, prefs)["text"] for f in card.get("facts") or []], "education": card.get("education_entry") or "not reported",
                "tasks_ai_used": [f"{t.get('task', '')} (observed AI use {t['penetration']:.2f})" if t.get("penetration") is not None else t.get("task", "") for t in (card.get("ai_assists") or [])[:3]],
                "stays_human": [resolve_refs(f"{t.get('task', '')} — {t.get('why', '')}", prefs)["text"] for t in (card.get("more_important") or [])[:3]],
                "tradeoff": resolve_refs(card.get("tradeoff", ""), prefs)["text"], "confidence": str(card.get("evidence_confidence") or ""),
                "unknowns": [resolve_refs(u, prefs)["text"] for u in (views.get("unknowns") or []) if soc and soc in u][:3]}
    return {"told": told, "conflicts": conflicts, "evidence": evidence, "resolution": resolution_label(candidate), "removed": len((candidate.get("review") or {}).get("removed") or [])}

# ───────────────────────────── Run details (How we reached this) ─────────────────────────────
SOURCE_WORD = {"ok": "used", "partial": "partial", "unavailable": "unavailable"}

def run_details(views: dict, candidates: list[dict] | None = None, approvals: dict | None = None) -> dict:
    """User-facing facts about THIS run. Model names, cost and raw tool counts are deliberately not here (developer mode shows them)."""
    sk = views.get("skeptic") or {}; status = views.get("review_status") or sk.get("status") or "verified"
    cards = views.get("cards_by_family") or {}; n_cards = sum(len(v) for v in cards.values())
    occs = []
    if candidates:
        for c in candidates: occs.append({"label": c.get("label"), "title": (c.get("persona") or {}).get("title"), **resolution_label(c)})
    else:
        for o in (views.get("outlooks") or {}).values(): occs.append({"label": o.get("title"), "title": o.get("title"), "kind": "proxy" if o.get("proxy_note") else "exact", "text": o.get("proxy_note") or "Official occupation"})
    ap = approvals or {}
    humans = [k for k in ("understanding", "reactions", "plan", "save") if ap.get(k)]
    return {"sources": [{"name": k, "status": SOURCE_WORD.get(v, v)} for k, v in (views.get("source_status") or {}).items()], "occupations": occs, "n_cards": n_cards,
            "review_status": status, "removed": [{"text": TAG.sub("", CREF.sub("", PREF.sub("", r.get("sentence", "")))).strip(), "reason": r.get("reason", "")} for r in sk.get("stripped") or []],
            "rationale_removed": sk.get("rationale_lines_removed", 0), "unknowns": [TAG.sub("", CREF.sub("", u)).strip() for u in views.get("unknowns") or []],
            "disagreements": views.get("disagreements") or [], "approvals": humans, "verified": status != "unverified"}
