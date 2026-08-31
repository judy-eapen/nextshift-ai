"""Explorer → interview bridge: saved careers become visible evidence (not a choice), targeted comparison questions are templated deterministically,
the interview asks them early, no extra model call is introduced, and the snapshot carries the seed."""
import pytest
from graph import student as S, student_seed as SS, llm

SEED = {"saved": [{"id": "17-1011.00", "title": "Architects, Except Landscape and Naval", "reaction": "interesting"}, {"id": "15-1255.00", "title": "Web and Digital Interface Designers", "reaction": "maybe"},
                  {"id": "19-3033.00", "title": "Clinical and Counseling Psychologists", "reaction": "understand"}, {"id": "43-9021.00", "title": "Data Entry Keyers", "reaction": "no"}]}

def test_seed_evidence_is_quoted_and_never_a_choice():
    ev = SS.seed_evidence(SEED)
    assert len(ev["existing_career_ideas"]) == 3 and all("Saving is not choosing" in e["quote"] and e["source_turn"] == 0 and e["kind"] == "stated" for e in ev["existing_career_ideas"])
    assert ev["dislikes"][0]["value"].startswith("Data Entry Keyers") and "not for me" in ev["dislikes"][0]["quote"]
    assert SS.seed_evidence(None) == {} and SS.seed_evidence({"saved": []}) == {}

def test_targeted_questions_are_deterministic_and_grounded():
    qs = SS.seed_questions(SEED); assert 1 <= len(qs) <= 3 and qs == SS.seed_questions(SEED)
    assert any("Clinical and Counseling Psychologists" in q and ("doctoral" in q.lower() or "years of preparation" in q.lower()) for q in qs)   # long preparation on a 'maybe/understand' career
    assert any("understand better" in q for q in qs)
    assert all("?" in q and "perfect" not in q.lower() for q in qs) and "Data Entry Keyers" not in " ".join(qs)   # 'not for me' careers are not compared

def test_pairwise_trait_fork_question():
    seed = {"saved": [{"id": "27-1024.00", "title": "Graphic Designers", "reaction": "interesting"}, {"id": "13-2011.00", "title": "Accountants and Auditors", "reaction": "interesting"}]}
    qs = SS.seed_questions(seed); assert qs and "Graphic Designers" in qs[0] and "Accountants and Auditors" in qs[0] and "creative" in qs[0].lower()

def test_interview_uses_seed_without_extra_model_calls(monkeypatch):
    calls = []; monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (calls.append(k.get("purpose")), {})[1])
    st = S.init_interview({"thread_id": "t", "explorer_seed": SEED}); assert calls == [] and st["seed_questions"] and len(st["profile"]["existing_career_ideas"]) == 3 and st["profile"]["dislikes"]
    st["completeness"]["next_question_goal"] = "energizing"; out = S.select_question(st); assert out["pending"]["source"] == "curated" and calls == []
    st["turns"] = [{"i": 1, "goal": "energizing", "question": out["pending"]["question"], "answer": "editing videos", "action": "answer", "fields_touched": []}]; st["last_action"] = "answer"
    comp = S.evaluate_completeness(st)["completeness"]; assert comp["next_question_goal"] == "saved_careers"   # right after the opener
    st["completeness"] = comp; q = S.select_question(st); assert q["pending"]["question"] == st["seed_questions"][0] and q["pending"]["source"] == "curated" and calls == []
    st["turns"].append({"i": 2, "goal": "saved_careers", "question": q["pending"]["question"], "answer": "the visual side", "action": "answer", "fields_touched": []})
    for _ in range(3):   # at most two targeted questions, then the normal goals resume
        comp = S.evaluate_completeness(st)["completeness"]; st["completeness"] = comp
        if comp["next_question_goal"] != "saved_careers": break
        st["turns"].append({"i": len(st["turns"]) + 1, "goal": "saved_careers", "question": "x", "answer": "y", "action": "answer", "fields_touched": []})
    assert sum(t["goal"] == "saved_careers" for t in st["turns"]) <= 2 and calls == []

def test_without_seed_behaviour_is_unchanged(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model")))
    st = S.init_interview({"thread_id": "t"}); assert st["explorer_seed"] is None and st["seed_questions"] == [] and st["profile"]["existing_career_ideas"] == []
    st["turns"] = [{"i": 1, "goal": "energizing", "question": "q", "answer": "a", "action": "answer", "fields_touched": []}]; st["last_action"] = "answer"
    assert S.evaluate_completeness(st)["completeness"]["next_question_goal"] != "saved_careers"

def test_snapshot_payload_carries_seed():
    import inspect; from graph import student_explore as X
    assert '"explorer_seed": state.get("explorer_seed")' in inspect.getsource(X.record)
