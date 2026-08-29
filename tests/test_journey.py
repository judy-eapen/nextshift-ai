"""Journey indicator derives from real state: stage, interrupt kind, phase events, reviewed views. Never fakes progress."""
import pytest
from ui import journey as J

def states(steps): return [s["state"] for s in steps]

# ── student: stage → current step
@pytest.mark.parametrize("stage,cur", [("s_interview", 0), ("s_understanding", 1), ("s_results", 5), ("s_discriminate", 5), ("s_shortlist", 6), ("s_deep", 7), ("s_save", 8)])
def test_student_stage_maps_to_current(stage, cur):
    st = states(J.journey_steps("student", stage))
    assert st[cur] == "current" and all(x == "done" for x in st[:cur]) and all(x == "todo" for x in st[cur + 1:])

# ── student: phase events while the graph runs move the marker (interrupt kind unchanged)
@pytest.mark.parametrize("phase,cur", [({"phase": "candidates"}, 2), ({"phase": "resolve"}, 2), ({"phase": "gather"}, 3), ({"phase": "fit"}, 3),
                                       ({"phase": "review", "of": "career cards"}, 4), ({"phase": "review", "of": "shortlist"}, 6), ({"phase": "review", "of": "deep dive"}, 7),
                                       ({"phase": "reactions"}, 5), ({"phase": "shortlist"}, 6), ({"phase": "deep"}, 7), ({"phase": "whatif"}, 6), ({"phase": "save"}, 8)])
def test_student_phase_sets_current(phase, cur):
    assert states(J.journey_steps("student", "s_understanding", phase=phase))[cur] == "current"

def test_interview_phases_stay_on_step_one():
    for p in ("question", "profile", "completeness"): assert states(J.journey_steps("student", "s_interview", phase={"phase": p}))[0] == "current"

def test_backwards_move_keeps_earlier_work_done():
    # "Back to all cards" from the shortlist: current returns to reactions; nothing beyond is marked done
    st = states(J.journey_steps("student", "s_results"))
    assert st[5] == "current" and st[6] == "todo"

# ── professional
@pytest.mark.parametrize("stage,phase,cur", [("intake", None, 0), ("understanding", None, 1), ("working", {"phase": "gather"}, 2), ("working", {"phase": "outlook"}, 3),
                                             ("working", {"phase": "plan"}, 4), ("working", {"phase": "review", "of": "plan"}, 5), ("plan", None, 6)])
def test_professional_mapping(stage, phase, cur):
    assert states(J.journey_steps("professional", stage, phase=phase))[cur] == "current"

# ── flags come from real views, never from copy
def test_partial_evidence_flags_evidence_step():
    s = J.journey_steps("student", "s_results", views={"source_status": {"BLS": "unavailable", "Manifold": "ok"}})
    assert s[3]["state"] == "attention" and "BLS" in s[3]["note"]

def test_unverified_flags_review_step_student_and_pro():
    assert J.journey_steps("student", "s_results", views={"review_status": "unverified"})[4]["state"] == "unverified"
    assert J.journey_steps("professional", "plan", views={"review_status": "unverified"})[5]["state"] == "unverified"

def test_unverified_not_shown_before_review_happened():
    assert J.journey_steps("student", "s_interview", views={"review_status": "unverified"})[4]["state"] == "todo"

def test_thin_conversation_note():
    assert J.journey_steps("student", "s_understanding", completeness={"thin": True})[0]["state"] == "attention"

# ── ended runs
def test_saved_marks_all_done():
    assert set(states(J.journey_steps("student", "s_done", exported=True))) == {"done"}

def test_reject_at_understanding_stops_there():
    st = states(J.journey_steps("student", "s_done", approvals={"understanding": {"action": "reject"}}))
    assert st[1] == "stopped" and st[0] == "done" and all(x == "todo" for x in st[2:])

def test_reject_at_save_stops_at_last():
    assert states(J.journey_steps("student", "s_done", approvals={"save": {"action": "reject"}}))[8] == "stopped"

# ── copy + accessibility
def test_phase_copy_fills_review_target():
    assert J.phase_copy({"phase": "review", "of": "shortlist"}) == "Checking the shortlist…"
    assert J.phase_copy(None) == ""

def test_every_phase_key_has_copy_and_a_step():
    for k in J.STUDENT_PHASE: assert k in J.PHASE_COPY
    for k in J.PRO_PHASE: assert k in J.PHASE_COPY

def test_step_html_has_aria_and_text_state():
    for state in J.STATES:
        h = J.step_html({"label": "X", "state": state, "note": ""})
        assert "aria-label=" in h and "role='img'" in h
        if state != "done" and state != "todo": assert J.GLYPH[state][1] in h   # state is spelled out, not colour-only

# ── refs → student's words
def test_resolve_refs_returns_quotes_and_clean_text():
    refs = {"p:interests:0": "interests: film — “editing videos for friends”", "p:values:1": "values: helping"}
    r = J.resolve_refs("You enjoy visual storytelling [p:interests:0] [c12] [interpretation]", refs)
    assert r["text"] == "You enjoy visual storytelling" and r["quotes"] == ["editing videos for friends"] and r["interpretation"]
    assert J.resolve_refs("Helping matters to you [p:values:1]", refs)["quotes"] == ["helping"]
