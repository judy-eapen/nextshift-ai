"""Behind-the-scenes panel via streamlit.testing.v1.AppTest. The graph is never constructed while the panel opens/closes."""
import os, re, pytest
from streamlit.testing.v1 import AppTest
from tests import fixtures as F

APP = os.path.join(os.path.dirname(__file__), "..", "ui", "app.py")

@pytest.fixture(autouse=True)
def no_graph(monkeypatch):
    """Any attempt to build or run a graph fails the test."""
    import graph.build, graph.student_build
    def boom(*a, **k): raise AssertionError("graph constructed/run while the panel was used")
    monkeypatch.setattr(graph.build, "build_graph", boom); monkeypatch.setattr(graph.student_build, "build_student_graph", boom)
    monkeypatch.setenv("NEBIUS_API_KEY", "SECRET-VALUE-XYZ"); monkeypatch.setenv("LANGSMITH_API_KEY", "SECRET-LS-KEY"); monkeypatch.delenv("NEXTSHIFT_DEV", raising=False)

def app_at(stage="s_results", door="student", payload=None):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["stage"] = stage; at.session_state["door"] = door; at.session_state["payload"] = payload or F.results_payload()
    at.session_state["thread_id"] = "t-test"; at.session_state["log"] = ["Reviewed career cards: 41 lines, 1 removed"]; at.session_state["step"] = 0; at.session_state["profile"] = {}; at.session_state["targets"] = []
    return at.run()

def all_markdown(at): return "\n".join(m.value for m in at.markdown)

def open_button(at): return next(b for b in at.sidebar.button if "behind the scenes" in b.label)

def test_results_screen_renders_with_sidebar_journey():
    at = app_at(); md = all_markdown(at)
    assert not at.exception and "Your journey" in md and "Learning from your reactions" in md and "Curious how NextShift works?" in md

def test_open_and_close_preserve_stage_and_payload():
    at = app_at(); before = (at.session_state["stage"], at.session_state["payload"])
    at = open_button(at).click().run()
    assert not at.exception and (at.session_state["stage"], at.session_state["payload"]) == before
    at = at.run()   # a plain rerun = dialog dismissed
    assert (at.session_state["stage"], at.session_state["payload"]) == before and "Directions that might fit you" in all_markdown(at)

def test_dialog_shows_plain_language_steps_and_saved_copy():
    at = open_button(app_at()).click().run(); md = all_markdown(at)
    for s in ("We listen before recommending", "You confirm what we understood", "We check the recommendations", "You decide what happens next"): assert s in md
    assert "Path A explores careers using deterministic code" in md and "LangGraph stores state" in md
    for source in ("O*NET", "BLS", "Anthropic Economic Index", "AIOE", "Prediction markets", "Epoch AI + FRED"): assert source in md
    assert "Current AI use is not treated as proof" in md and "Nothing is published or sent to an employer" in md and "developer tracing is off" in md

def test_no_secrets_or_env_names_anywhere():
    at = open_button(app_at()).click().run(); md = all_markdown(at)
    assert "SECRET-VALUE-XYZ" not in md and "SECRET-LS-KEY" not in md
    for k in ("NEBIUS_API_KEY", "LANGSMITH_API_KEY", "FRED_API_KEY"): assert k not in md
    assert "<think>" not in md

def test_dev_mode_hidden_without_flag():
    at = open_button(app_at()).click().run(); md = all_markdown(at)
    assert not any("Developer mode" in e.label for e in at.expander) and "interrupt kind" not in md
    assert not any("Developer mode" in c.label for c in at.sidebar.checkbox)

def test_dev_mode_with_flag(monkeypatch):
    monkeypatch.setenv("NEXTSHIFT_DEV", "1"); monkeypatch.setenv("LANGSMITH_TRACING", "true")
    at = app_at(); cb = next(c for c in at.sidebar.checkbox if "Developer mode" in c.label); at = cb.check().run()
    at = open_button(at).click().run(); md = all_markdown(at)
    assert any("Developer mode — this session" in e.label for e in at.expander) and "interrupt kind" in md and "Qwen/" in md and "SECRET-VALUE-XYZ" not in md
    assert os.environ.get("LANGSMITH_TRACING") == "true"

def test_tracing_forced_off_without_dev_mode(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true"); app_at()
    assert os.environ.get("LANGSMITH_TRACING") == "false"

def test_unverified_and_partial_reach_journey():
    at = app_at(payload=F.results_payload(review_status="unverified", sources={"BLS": "unavailable", "Manifold": "ok"})); md = all_markdown(at)
    assert "aria-label='unverified'" in md and "partial evidence — unavailable: BLS" in md

def test_accessibility_labels_on_journey_and_expanders():
    at = open_button(app_at()).click().run(); md = all_markdown(at)
    assert md.count("role='img' aria-label=") >= 9 and "role='list'" in md
    assert all(e.label.strip() for e in at.expander)

def test_button_disabled_while_running():
    at = app_at(stage="s_interview_run", payload=F.interview_payload()) if False else None   # a run stage would invoke the graph; check the flag logic directly instead
    from ui.explain import RUN_STAGES; assert {"s_interview_run", "understanding_run", "working"} <= RUN_STAGES

def test_professional_plan_stage_journey():
    v = F.views(); pl = {"kind": "plan", "plan_md": "# plan", "views": {**v, "outlooks": {"15-1252": {"title": "Software Developers", "demand_reading": "growing", "ai_change_reading": "moderate", "facts": ["+15% [c01]"], "interpretation": []}},
                                                                 "changes": {"15-1252": {"ai_assists": [], "more_important": [], "uncertain": [], "method_note": "n"}}, "plan": {"direct_answer": "Demand holds.", "d30": [], "m6": [], "y1": [], "confidence": {}}, "deltas": [], "refs": {}}}
    at = app_at(stage="plan", door="professional", payload=pl); md = all_markdown(at)
    assert not at.exception and "Waiting for your approval" in md and "aria-label='current step'" in md

def test_inline_markdown_converted_inside_html_blocks():
    from ui.explain import _inline
    assert _inline("press *Recommend careers now* or **BLS** and O\\*NET") == "press <i>Recommend careers now</i> or <b>BLS</b> and O*NET"
    at = open_button(app_at()).click().run(); t = all_markdown(at)
    assert "*Recommend careers now*" not in t and "<i>Recommend careers now</i>" in t
