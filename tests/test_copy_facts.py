"""Panel copy must not overstate the code. Every number/claim in ui/copy.py is pinned to the constant or behaviour it describes."""
import os, re
from ui import copy as CP
from graph.student import MAX_TURNS, TARGET_TURNS
from graph import llm

def all_text(door="student"):
    parts = [CP.INTRO, CP.LEGEND] + [f"{s['title']} {s['body']} {s.get('callout', '')} {s['more']}" for s in CP.steps(door)]
    parts += list(CP.saved_copy(door, True).values()) + list(CP.saved_copy(door, False).values()) + CP.MODEL_WORK + CP.DETERMINISTIC + CP.STATE_MEMORY + CP.FAILURE + CP.STUDENT_ARCH + CP.PRO_ARCH
    return "\n".join(parts)

def test_turn_limits_come_from_code():
    t = all_text(); assert f"at {MAX_TURNS} questions" in t and f"{TARGET_TURNS[0]}–{TARGET_TURNS[1]} answers" in t
    assert not re.search(r"\b(1[0-3]|1[5-9]|20) questions", t)   # no stray hard-coded limit

def test_reviewer_is_a_different_model_or_copy_must_change():
    assert llm.model_name("skeptic") != llm.model_name("planner"), "copy says the reviewer is a different model from the writer"

def test_saved_copy_tracks_tracing_flag():
    on, off = CP.saved_copy("student", True)["while"], CP.saved_copy("student", False)["while"]
    assert "LangSmith" in on and "developer tracing is off" in off and "LangSmith" not in off.replace("developer tracing is off", "")

def test_no_secret_values_or_prompts_in_copy(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "SECRET-VALUE-XYZ"); t = all_text() + all_text("professional")
    assert "SECRET-VALUE-XYZ" not in t and "<think>" not in t
    for banned in ("You are a warm, plain-spoken", "hostile fact-checker", "Respond with valid JSON"): assert banned not in t   # no hidden prompts

def test_callout_present_and_exact():
    s5 = CP.steps("student")[4]; assert s5["callout"].startswith("Current AI use is not treated as proof that a career will disappear.")

def test_boundary_line_matches_ui():
    from ui.student_ui import BOUNDARY; assert CP.BOUNDARY == BOUNDARY

def test_seven_steps_two_human():
    for door in ("student", "professional"):
        s = CP.steps(door); assert [x["n"] for x in s] == list(range(1, 8)) and sum("you" in x["tags"] for x in s) == 2
