"""In-journey explanations: what NextShift understands · why this appeared · run details. Reviewed data only, no model calls, labels from the resolver."""
import json, os, pytest
from streamlit.testing.v1 import AppTest
from ui import journey as J
from tests import fixtures as F

APP = os.path.join(os.path.dirname(__file__), "..", "ui", "app.py")

@pytest.fixture(autouse=True)
def no_llm_no_graph(monkeypatch):
    import graph.llm, graph.build, graph.student_build
    def boom(*a, **k): raise AssertionError("model/graph called while rendering an explanation")
    monkeypatch.setattr(graph.llm, "chat", boom); monkeypatch.setattr(graph.llm, "chat_json", boom)
    monkeypatch.setattr(graph.build, "build_graph", boom); monkeypatch.setattr(graph.student_build, "build_student_graph", boom); monkeypatch.delenv("NEXTSHIFT_DEV", raising=False)

def app_at(stage, payload, door="student"):
    at = AppTest.from_file(APP, default_timeout=60)
    for k, val in {"stage": stage, "door": door, "payload": payload, "thread_id": "t", "log": [], "step": 0, "profile": {}, "targets": []}.items(): at.session_state[k] = val
    return at.run()

def md(at): return "\n".join(m.value for m in at.markdown)

# 5 · understands: existing state, no LLM
def test_understands_sections_from_state_only():
    secs = J.understands_sections(F.interview_payload()["profile"])
    assert [s["title"] for s in secs][:3] == ["Interests", "Activities that energize you", "Demonstrated strengths"] and len(secs) == 10
    interests = secs[0]["items"][0]; assert interests["value"] == "film" and interests["quote"] == "editing videos for friends" and interests["turn"] == 1
    assert secs[3]["items"][0]["tag"] == "hard now, want to improve"            # growth areas never framed as permanent weakness
    assert "Leaning toward people, technology" in secs[5]["items"][0]["value"]
    assert secs[4]["items"] == [] and secs[9]["items"] == []

def test_interview_screen_shows_understands_and_edit_path():
    at = app_at("s_interview", F.interview_payload()); t = md(at)
    assert not at.exception and "What NextShift currently understands about you" in [e.label for e in at.expander]
    assert "Based on your answer (Q1): “editing videos for friends”" in t and "Not mentioned yet." in t and "Still learning about" in t
    assert any(b.label == "Edit Q1" for b in at.button) and "Edit an earlier answer" in [e.label for e in at.expander]

# 6/7 · why this appeared: reviewed rationale + card only; removed content absent
def test_why_this_appeared_groups_and_quotes():
    v = F.views(); c = v["groups"]["strong"][0]; w = J.why_this_appeared(c, v)
    assert w["told"][0]["label"] == "Why it made the list" and w["told"][0]["quotes"] == ["editing videos for friends"]
    assert any(it["quotes"] == ["organizing the school's charity drive"] for it in w["told"])
    assert w["evidence"]["education"] == "Bachelor's degree" and "Projected change 2025–35: +7%" in w["evidence"]["outlook"][0] and "observed AI use 0.71" in w["evidence"]["tasks_ai_used"][0]
    assert w["resolution"]["kind"] == "exact" and w["removed"] == 1
    assert "score" not in json.dumps(w).lower()

def test_removed_content_absent_from_explanations():
    v = F.views(); removed = v["skeptic"]["stripped"][0]["sentence"].split(" [")[0]
    for c in [c for g in v["groups"].values() for c in g]: assert removed not in json.dumps(J.why_this_appeared(c, v))
    at = app_at("s_results", F.results_payload()); t = md(at)
    assert removed not in t.replace("✂ " + removed, "")            # only the crossed-out listing under "How we reached this" may show it
    assert "✂ " + removed[:60] in t

# 8 · proxy / composite labels
def test_resolution_labels():
    assert J.resolution_label(F.candidate(resolution="official (tier 1)"))["kind"] == "exact"
    assert J.resolution_label(F.candidate(resolution="official (tier 2)"))["kind"] == "proxy"
    comp = F.candidate(resolution="composite"); comp["card"]["proxy_note"] = "closest official categories: X; Y"
    lab = J.resolution_label(comp); assert lab["kind"] == "composite" and "closest official categories: X; Y" in lab["text"]
    assert J.resolution_label({"resolution": "unresolved"})["kind"] == "unknown"

def test_results_screen_labels_composite():
    t = md(app_at("s_results", F.results_payload())); assert "Composite — no official category" in t and "Official occupation (exact match): Producers and Directors" in t

# 9/10 · reviewer failure and source outage in run details
def test_run_details_unverified_and_partial():
    rd = J.run_details(F.views(review_status="unverified", sources={"BLS": "unavailable", "Manifold": "ok"}), [F.candidate()])
    assert rd["verified"] is False and {"name": "BLS", "status": "unavailable"} in rd["sources"] and rd["n_cards"] == 1 and rd["occupations"][0]["kind"] == "exact"
    t = md(app_at("s_results", F.results_payload(review_status="unverified", sources={"BLS": "unavailable", "Manifold": "ok"})))
    assert "UNVERIFIED" in t and "BLS (unavailable)" in t

# 17 · cards stay answer-first; builder facts stay out of normal copy
def test_cards_answer_first_and_no_builder_facts():
    at = app_at("s_results", F.results_payload()); t = md(at)
    assert "Why this appeared →" in [e.label for e in at.expander] and "How we reached this" in [e.label for e in at.expander]
    first_card = next(m.value for m in at.markdown if "class='card'" in m.value and "Video Producer" in m.value)
    assert first_card.index("Video Producer") < first_card.index("Why it may fit you")
    assert "Qwen/" not in t and "tool calls" not in t and "$0.07" not in t   # dev-only facts

def test_professional_run_details_shared():
    v = F.views(); pl = {"kind": "plan", "plan_md": "# plan", "views": {**v, "outlooks": {"15-1252": {"title": "Software Developers", "demand_reading": "growing", "ai_change_reading": "moderate", "facts": ["+15% [c01]"], "interpretation": [], "proxy_note": None}},
                                                                 "changes": {"15-1252": {"ai_assists": [], "more_important": [], "uncertain": [], "method_note": "n"}}, "plan": {"direct_answer": "Demand holds.", "d30": [], "m6": [], "y1": [], "confidence": {}}, "deltas": [], "refs": {}}}
    at = app_at("plan", pl, door="professional"); t = md(at)
    assert not at.exception and "Sources in this run" in t and "Software Developers" in t and "verified by a separate reviewer" in t and "Qwen/" not in t
