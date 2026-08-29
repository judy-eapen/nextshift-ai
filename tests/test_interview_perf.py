"""Interview turns: deterministic next question, one model call per substantive answer, zero for no-content actions."""
import pytest
from graph import student as S, llm

class Counter:
    def __init__(self, reply=None): self.calls = []; self.reply = reply or {}
    def __call__(self, role, system, user, **kw): self.calls.append((role, kw.get("purpose"))); return (self.reply, 0.0)

def fresh():
    st = S.init_interview({"thread_id": "t"}); return st

def turn(st, answer, goal="energizing", i=None):
    i = i or len(st["turns"]) + 1
    st["turns"] = st["turns"] + [{"i": i, "goal": goal, "question": "q", "answer": answer, "action": "answer" if answer not in ("(not sure)", "(skipped)") else ("unsure" if answer == "(not sure)" else "skip"), "fields_touched": []}]
    st["last_action"] = st["turns"][-1]["action"]; return st

def test_select_question_uses_curated_bank_without_model(monkeypatch):
    c = Counter(); monkeypatch.setattr(llm, "chat_json", c)
    st = fresh(); out = S.select_question(st); assert out["pending"]["question"] == S.GOALS["energizing"][2][0] and c.calls == []
    st = turn(st, "editing videos"); st["completeness"] = {**st["completeness"], "next_question_goal": "interests"}
    out = S.select_question(st); assert out["pending"]["source"] == "curated" and out["pending"]["question"] == S.GOALS["interests"][2][0] and c.calls == []

def test_select_question_calls_model_only_when_bank_exhausted(monkeypatch):
    c = Counter({"question": "A new angle on interests?"}); monkeypatch.setattr(llm, "chat_json", c)
    st = fresh(); st["completeness"] = {**st["completeness"], "next_question_goal": "interests"}
    st = turn(st, "a", goal="interests"); st = turn(st, "b", goal="interests")      # bank has 2 questions → exhausted
    out = S.select_question(st); assert out["pending"]["source"] == "model" and c.calls == [("planner", "question_new_angle")]

def test_clarify_is_templated_not_generated(monkeypatch):
    c = Counter(); monkeypatch.setattr(llm, "chat_json", c)
    st = fresh(); st = turn(st, "x"); st["profile"]["contradictions"] = [{"quote_a": "loves labs", "quote_b": "no more than 2 years", "status": "open"}]
    st["completeness"] = {**st["completeness"], "next_question_goal": "clarify"}
    out = S.select_question(st); assert "loves labs" in out["pending"]["question"] and c.calls == []

@pytest.mark.parametrize("act", ["skip", "unsure", "recommend", "more"])
def test_no_content_actions_make_no_llm_call(monkeypatch, act):
    c = Counter(); monkeypatch.setattr(llm, "chat_json", c)
    st = fresh(); st = turn(st, "(not sure)" if act == "unsure" else "(skipped)"); st["last_action"] = act
    S.update_profile(st); S.evaluate_completeness(st); assert c.calls == []

def test_substantive_turn_uses_one_model_call(monkeypatch):
    reply = {"add": {"dislikes": [{"value": "repetitive data entry", "quote": "I hate data entry", "kind": "stated"}]}, "pidth": {"people": 0.5}}
    c = Counter(reply); monkeypatch.setattr(llm, "chat_json", c)
    st = fresh(); st["profile"]["interests"] = [{"value": "film", "quote": "editing videos for friends", "source_turn": 1, "kind": "stated"}]
    st = turn(st, "I hate data entry", goal="negatives", i=2)
    out = S.update_profile(st); assert [p for _, p in c.calls] == ["profile_update"] and out["profile"]["dislikes"][0]["value"] == "repetitive data entry"

def test_contradiction_call_only_on_deterministic_trigger(monkeypatch):
    # shared substantive word between a new dislike and an interest → the extra check runs (primary reported nothing)
    reply = {"add": {"dislikes": [{"value": "writing essays", "quote": "I hate writing essays", "kind": "stated"}]}}
    c = Counter(reply); monkeypatch.setattr(llm, "chat_json", c)
    st = fresh(); st["profile"]["interests"] = [{"value": "creative writing", "quote": "I love writing stories", "source_turn": 1, "kind": "stated"}]
    st = turn(st, "I hate writing essays", goal="negatives", i=2); S.update_profile(st)
    assert [p for _, p in c.calls] == ["profile_update", "contradiction_check"]
    # primary already reported a contradiction → no second call
    reply2 = {**reply, "contradictions": [{"fields": ["interests", "dislikes"], "quote_a": "a", "quote_b": "b", "note": "n"}]}
    c2 = Counter(reply2); monkeypatch.setattr(llm, "chat_json", c2); S.update_profile(st); assert [p for _, p in c2.calls] == ["profile_update"]

def test_needs_contra_check_rules():
    prof = {"interests": [{"value": "biology", "quote": "biology labs", "source_turn": 1}], "existing_career_ideas": [{"value": "doctor", "quote": "maybe a doctor", "source_turn": 1}],
            "education_constraints": [{"value": "2-year max", "quote": "no more than two years of school", "source_turn": 3}], "dislikes": [], "growth_areas": [], "not_yet_learned": [], "financial_constraints": [], "location_constraints": [], "energizing_activities": []}
    assert S._needs_contra_check(prof, ["education_constraints"], 3, False) is True      # named careers + a hard education limit
    assert S._needs_contra_check(prof, ["education_constraints"], 3, True) is False      # primary already found one
    assert S._needs_contra_check(prof, ["work_preferences"], 3, False) is False          # no negative touched
