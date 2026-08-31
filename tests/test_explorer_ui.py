"""Career Explorer screens via AppTest: zero LLM calls while browsing, saving/reactions, compare ≤4, navigation to/from the interview, duplicate-action protection,
progress indicator for the slow action, honest labels, provenance in the rendered page, no developer/technical noise by default."""
import os, re, time, pytest
from streamlit.testing.v1 import AppTest
from tests import fixtures as F

APP = os.path.join(os.path.dirname(__file__), "..", "ui", "app.py")

@pytest.fixture(autouse=True)
def no_llm_no_graph(monkeypatch):
    import graph.llm, graph.build, graph.student_build
    def boom(*a, **k): raise AssertionError("model/graph called while browsing the explorer")
    monkeypatch.setattr(graph.llm, "chat", boom); monkeypatch.setattr(graph.llm, "chat_json", boom)
    monkeypatch.setattr(graph.build, "build_graph", boom); monkeypatch.setattr(graph.student_build, "build_student_graph", boom); monkeypatch.delenv("NEXTSHIFT_DEV", raising=False)

def app(view, **state):
    at = AppTest.from_file(APP, default_timeout=120)
    base = {"stage": "explore", "door": "student", "x_view": view, "x_stack": [], "x_saved": [], "x_reactions": {}, "thread_id": "t", "log": [], "step": 0, "profile": {}, "targets": []}
    base.update(state)
    for k, v in base.items(): at.session_state[k] = v
    return at.run()

def md(at): return "\n".join(m.value for m in at.markdown)
def btn(at, text): return next(b for b in at.button if text in b.label)

def test_start_screen_offers_two_student_choices_and_the_professional_door():
    at = AppTest.from_file(APP, default_timeout=120).run(); t = md(at); labels = [b.label for b in at.button]
    assert not at.exception and "Explore careers" in t and "Help me find my direction" in t and "Explore careers →" in labels and "Start the conversation →" in labels and "Start planning →" in labels

def test_home_renders_without_llm_and_shows_families_collections_search():
    at = app({"kind": "home"}); t = md(at)
    assert not at.exception and "Health and human care" in t and "Careers you may not know exist" in t and "not every job that exists" in t
    assert sum(1 for b in at.button if b.label.startswith("Explore →")) == 16 and any("What do you like doing" in m.value for m in at.markdown)
    assert "Qwen/" not in t and "tool calls" not in t and "sqlite" not in t.lower()   # no developer noise

def test_family_and_collection_pages_progressive_disclosure():
    at = app({"kind": "family", "id": "tech"}); t = md(at); assert not at.exception and "Technology and computing" in t and "Software Developers" in t and "Narrow this down" in [e.label for e in at.expander]
    at = app({"kind": "collection", "name": "ai_changes_tasks"}); t = md(at); assert "How this list is made" in t and "not whether jobs will be lost" in t

def test_search_results_explain_matches_and_empty_state():
    at = app({"kind": "search", "q": "helping animals"}); t = md(at); assert not at.exception and "Veterinarians" in t and "matched:" in t and "no AI is used in search" in t

def test_search_shows_top_five_then_more():
    at = app({"kind": "search", "q": "helping animals"})
    assert sum(1 for b in at.button if b.label.startswith("Open →")) == 5 and "Showing the top 5 of" in md(at)
    more = next(b for b in at.button if "more matches" in b.label); at = more.click().run()
    assert sum(1 for b in at.button if b.label.startswith("Open →")) > 5
    at = app({"kind": "search", "q": "zzqqxxy"}); t = md(at); assert "No career matched" in t and any("Browse families" in b.label for b in at.button)

def test_career_page_shows_layers_provenance_and_unavailable(monkeypatch):
    from tools import career_page as P
    monkeypatch.setattr(P, "cached_interpretation", lambda kind, ids: None)   # pin: no cached summary, whatever the shared cache holds
    at = app({"kind": "career", "id": "15-1252.00"}); t = md(at)
    assert "At a glance" in t and any("expander" not in "" and e.label.startswith("The work") for e in at.expander)   # summary-first; details collapsed
    assert not at.exception and "Software Developers" in t and "Official source" in t and "Derived by a fixed rule" in t and "Written by AI · reviewed" in t and "Personal to you" in t
    assert "BLS Employment Projections 2025–35 · 2025 · retrieved 20" in t and "O*NET 31.0" in t and "1,717,800" in t and "+10.2%" in t
    assert "Data not available from the current sources." in t   # industries / licensing
    assert "Jobs today" in t and "Direction to 2035" in t and "AI in the tasks today" in t and "Skills to begin building" in t and "task exposure is not an employment forecast" in t   # stat-first tiles; the explainer lives in the ⓘ popover
    assert any("Summarize this career" in b.label for b in at.button)   # nothing generated yet, and no model was called to render the page
    for bad in ("AI-proof", "safe career", "replacement risk", "will be automated"): assert bad.lower() not in t.lower()

def test_composite_and_detailed_labels_on_career_page():
    t = md(app({"kind": "career", "id": "composite:product-manager"})); assert "Composite role — no official category" in t and "Closest official categories" in t and "Data not available from the current sources." in t
    t = md(app({"kind": "career", "id": "15-1255.01"})); assert "specialty" in t and "broader official category" in t

def test_save_react_and_saved_count():
    at = app({"kind": "career", "id": "15-1252.00"}); assert "☆ 0 saved" in md(at)
    at = btn(at, "Save this career").click().run(); assert at.session_state["x_saved"] == ["15-1252.00"] and "☆ 1 saved" in md(at)
    at = btn(at, "Interesting").click().run(); assert at.session_state["x_reactions"] == {"15-1252.00": "interesting"} and "✓ 😀 Interesting" in [b.label for b in at.button]
    at = btn(at, "Interesting").click().run(); assert at.session_state["x_reactions"] == {}          # toggling off
    at = btn(at, "Unsave").click().run(); assert at.session_state["x_saved"] == []
    at = btn(at, "Not for me").click().run(); assert at.session_state["x_reactions"] == {"15-1252.00": "no"} and at.session_state["x_saved"] == []   # 'not for me' does not save

def test_saved_page_compare_up_to_four_and_remove():
    ids = ["15-1252.00", "29-1141.00", "17-1011.00", "27-1024.00", "23-1011.00"]
    at = app({"kind": "saved"}, x_saved=ids); assert not at.exception and sum(1 for c in at.checkbox if c.value) == 4 and any(c.disabled for c in at.checkbox)
    at = btn(at, "Compare 4 side by side").click().run(); assert at.session_state["x_view"]["kind"] == "compare" and len(at.session_state["x_view"]["ids"]) == 4
    t = md(at); assert t.count("<tr>") == 12 and "Registered Nurses" in t and "Projected growth or decline" in t and "Nothing here ranks them" in t
    at = app({"kind": "saved"}, x_saved=ids[:2]); at = btn(at, "Remove").click().run(); assert at.session_state["x_saved"] == ids[1:2]
    assert "You haven't saved any careers yet" in md(app({"kind": "saved"}))

def test_offer_appears_after_three_engagements_and_seeds_the_interview():
    at = app({"kind": "home"}, x_saved=["15-1252.00", "29-1141.00"], x_reactions={"17-1011.00": "maybe"}); t = md(at)
    assert "You saved several careers." in t and any("help me" in b.label.lower() for b in at.button)
    assert "You saved several careers." not in md(app({"kind": "home"}, x_saved=["15-1252.00"]))
    from ui import explorer
    class S(dict):
        def get(self, k, d=None): return super().get(k, d)
    s = S(x_saved=["15-1252.00", "29-1141.00"], x_reactions={"29-1141.00": "maybe", "17-1011.00": "no"}); seed = explorer.seed_from_state(s)
    assert [x["title"] for x in seed["saved"]] == ["Software Developers", "Registered Nurses", "Architects, Except Landscape and Naval"] and seed["saved"][1]["reaction"] == "maybe" and seed["saved"][2]["reaction"] == "no"

def test_navigation_back_and_return_to_interview():
    at = app({"kind": "family", "id": "tech"}, x_stack=[{"kind": "home"}], x_return="s_results", payload=F.results_payload())
    assert any("Return to my interview" in b.label for b in at.button) and "Your conversation is paused" in md(at)
    at = btn(at, "Return to my interview").click().run(); assert at.session_state["stage"] == "s_results" and not at.exception and "Directions that might fit you" in md(at)
    at = app({"kind": "career", "id": "15-1252.00"}, x_stack=[{"kind": "home"}, {"kind": "family", "id": "tech"}]); at = btn(at, "← Back").click().run(); assert at.session_state["x_view"] == {"kind": "family", "id": "tech"}

def test_results_cards_link_to_explorer_and_keep_place():
    at = AppTest.from_file(APP, default_timeout=120)
    for k, v in {"stage": "s_results", "door": "student", "payload": F.results_payload(), "thread_id": "t", "log": [], "step": 0, "profile": {}, "targets": []}.items(): at.session_state[k] = v
    at = at.run(); assert any("Open in the Career Explorer" in b.label for b in at.button)
    at = btn(at, "Open in the Career Explorer").click().run(); assert at.session_state["stage"] == "explore" and at.session_state["x_return"] == "s_results" and at.session_state["x_view"]["kind"] == "career"

def test_reset_keeps_saved_careers():
    at = app({"kind": "home"}, x_saved=["15-1252.00"]); at = next(b for b in at.sidebar.button if "Start over" in b.label).click().run()
    assert at.session_state["stage"] == "start" and at.session_state["x_saved"] == ["15-1252.00"] and "1 saved career" in md(at)

def test_slow_action_shows_progress_and_blocks_duplicates(monkeypatch):
    """Generating the explanation: an st.status box appears at once; a second click while a generation is marked in flight is ignored; a failure leaves the facts intact."""
    from tools import career_page as P
    calls = []
    def slow_fail(rid, force=False, progress=None): calls.append(rid); progress("Handing the model 33 sourced facts…"); raise RuntimeError("endpoint down")
    monkeypatch.setattr(P, "generate_interpretation", slow_fail); monkeypatch.setattr(P, "cached_interpretation", lambda kind, ids: None)
    at = app({"kind": "career", "id": "15-1252.00"}); at = btn(at, "Summarize this career").click().run()
    assert len(calls) == 1 and at.status and any("could not be reached" in s.label for s in at.status) and "1,717,800" in md(at) and at.session_state["x_gen"] is None
    at2 = app({"kind": "career", "id": "15-1252.00"}, x_gen={"id": "15-1252.00", "t": time.time()}); assert btn(at2, "Summarize this career").disabled      # in flight → no duplicate submission
    at3 = app({"kind": "career", "id": "15-1252.00"}, x_gen={"id": "15-1252.00", "t": time.time() - 600}); assert not btn(at3, "Summarize this career").disabled   # a stale flag unlocks

def test_cached_interpretation_renders_without_model(monkeypatch):
    from tools import career_page as P
    it = P.Interpretation(kind="career", ids=["15-1252.00"], model="m", reviewer="r", prompt_version=P.PROMPT_VERSION, catalog_version="cat1", generated_at="2026-08-30T00:00:00",
                          sections={"what_is_it": ["Developers build software [c01]."], "typical_day": ["Morning: plan the day [c01]"], "outlook_story": [], "who_thrives": ["You may enjoy this if you like puzzles [c01] [advice]"], "ai_story": [], "get_ready": []},
                          refs={"c01": "onet:desc:15-1252.00"}, cards=[{"id": "onet:desc:15-1252.00", "claim": "Software Developers: …", "source": "O*NET", "as_of": "2025-08-01"}], review={"status": "verified", "stripped": [], "total": 3, "kept": 3, "lint_removed": 0, "model_removed": 0}, cached=True)
    monkeypatch.setattr(P, "cached_interpretation", lambda kind, ids: it if kind == "career" else None)
    at = app({"kind": "career", "id": "15-1252.00"}); t = md(at)
    assert not at.exception and "Developers build software" in t and "Developers build software [c01]" not in t and "O*NET 2025" in t and "illustrative day" in t and "not an official BLS or O*NET conclusion" in t and "reused from cache" in t
    assert not any("Summarize this career" in b.label for b in at.button)

def test_behind_the_scenes_covers_the_explorer():
    at = app({"kind": "home"})
    assert any("How does NextShift create these results?" in b.label for b in at.button)
    at = next(b for b in at.sidebar.button if "behind the scenes" in b.label).click().run(); t = md(at)
    assert "How an answer becomes a career decision" in t and "Structured occupational data builds the catalog" in t and "Deterministic code handles browsing" in t and "The student approves before a final plan is saved" in t and "1,017" in t

def test_render_times_are_immediate():
    t0 = time.perf_counter(); app({"kind": "home"}); app({"kind": "search", "q": "nurse"}); app({"kind": "career", "id": "29-1141.00"}); dt = time.perf_counter() - t0
    assert dt < 20, dt   # three full AppTest script runs including catalog load; the in-app renders are ~150 ms each


def test_browser_url_navigation_and_shareable_links():
    """Explorer views mirror into query params: a pasted/back-forward URL opens the right page, and navigating writes the URL."""
    at = AppTest.from_file(APP, default_timeout=120)
    for k, v in {"stage": "explore", "door": "student", "x_view": {"kind": "home"}, "x_stack": [], "x_saved": [], "x_reactions": {}, "thread_id": "t", "log": [], "step": 0, "profile": {}, "targets": []}.items(): at.session_state[k] = v
    at.query_params["x"] = "career"; at.query_params["id"] = "29-1141.00"
    at = at.run()
    assert not at.exception and at.session_state["x_view"] == {"kind": "career", "id": "29-1141.00"} and "Registered Nurses" in md(at)
    at2 = app({"kind": "search", "q": "nurse"}); assert at2.query_params["x"] in ("search", ["search"]) and at2.query_params["q"] in ("nurse", ["nurse"])
    at3 = app({"kind": "home"}); at3.query_params["x"] = "collection"; at3.query_params["name"] = "not-a-collection"; at3 = at3.run()
    assert not at3.exception and at3.session_state["x_view"]["kind"] == "home"   # junk URLs are ignored
