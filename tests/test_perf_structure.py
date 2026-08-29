"""Level A/B evidence split, caches, review roles, reuse and invalidation — unit-level, no network, no model."""
import json, os, subprocess, pytest
from langgraph.types import Send
from graph import student_explore as X, review as rv, llm, nodes as N
from tools import cache

def cand(key, soc, group="strong"):
    return {"key": key, "label": key, "group": group, "resolution": "official (tier 1)", "persona": {"soc": soc, "onet_soc": soc + ".00", "title": key}, "rationale": {"why_included": f"you said so [p:interests:0]", "poor_fit_if": "long hours"},
            "card": {"education_entry": "Bachelor's degree", "constraint_flags": []}}

def base_state(**kw):
    st = {"candidates": [cand("k1", "11-1111"), cand("k2", "22-2222", "explore"), cand("k3", "33-3333")], "targets": [], "deep_socs": [], "deep_done_socs": [], "refs": {}, "evidence": [], "profile": {"interests": [{"value": "x", "quote": "q", "source_turn": 1, "kind": "stated"}]},
          "outlooks": {}, "changes": {}, "views": {}, "reactions": [], "deep_dives": {}}
    st["targets"] = [{"persona": c["persona"], "role": "candidate"} for c in st["candidates"]]; st.update(kw); return st

# 6 · initial cards never fan out to task-level exposure
def test_light_fanout_has_no_exposure():
    sends = X.fan_out_light(base_state()); names = [s.node for s in sends]
    assert "gather_exposure" not in names and names.count("gather_outlook") == 3 and all(s.arg.get("light") for s in sends if s.node == "gather_outlook")

# 7 · deep evidence only for the deep set, and only once
def test_deep_fanout_only_for_deep_socs_not_done():
    st = base_state(deep_socs=["11-1111", "33-3333"], deep_done_socs=["11-1111"], pending_after_deep="discriminate")
    sends = X.fan_out_deep(st); assert [s.arg["persona"]["soc"] for s in sends] == ["33-3333"]
    st["deep_done_socs"] = ["11-1111", "33-3333"]; assert X.fan_out_deep(st) == "discriminate"

def test_reactions_select_top_three_and_invalidate(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model for reactions without a why")))
    st = base_state(turns=[], reactions=[{"key": "k2", "verdict": "excited"}, {"key": "k1", "verdict": "curious"}, {"key": "k3", "verdict": "no"}], views={"shortlist": {"x": 1}, "groups": {}}, deep_dives={"k1": {"old": True}})
    out = X.update_from_reactions(st)
    assert out["deep_socs"] == ["11-1111", "22-2222"] and out["evidence_stage"] == "deep" and out["deep_dives"] == {} and "shortlist" not in out["views"] and "deep_dives" in out["evidence_meta"]["invalidates"]

# 11 · reopening a deep dive reuses it; a new pick outside the deep set routes to deepen
def test_deep_dive_memo_hit_makes_no_model_call(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    dd = {"key": "k1", "label": "k1", "title": "k1", "sections": {"test_this_career": ["shadow someone [advice]"]}, "review": {"status": "verified", "stripped": []}}
    st = base_state(selected="k1", deep_dives={"k1": dd}, views={"groups": {}})
    out = X.deep_dive(st); assert out["deep_dive"] is dd and out["experiments_planned"] == ["shadow someone [advice]"]

def test_pick_outside_deep_set_routes_to_deepen():
    st = base_state(selected="k2", deep_socs=["11-1111"], last_action="pick"); assert X.after_shortlist(st) == "deepen"
    st["deep_socs"] = ["11-1111", "22-2222"]; assert X.after_shortlist(st) == "deep_dive"
    assert X.deepen_one(base_state(selected="k3", deep_socs=["11-1111"]))["deep_socs"] == ["11-1111", "33-3333"]

# 10 · returning to results is a render, not a regeneration
def test_back_to_results_renders_only(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("model called")))
    assert X.after_shortlist(base_state(last_action="back_to_results")) == "results"
    st = base_state(skeptic={"stripped": [], "status": "verified"}, source_status={}, completeness={}, disagreements=[], forecast_context=[], unknowns=[], evidence=[])
    v = X.render_results(st)["views"]; assert set(v["groups"]) == {"strong", "explore", "unexpected", "reconsider"}

# light cards: deterministic, cited, facts kept apart from interpretation
def test_light_card_is_deterministic_and_marks_interpretation():
    c = cand("k1", "11-1111"); o = {"facts": ["Typical education needed for entry: Bachelor's degree [c03]", "BLS projects +7% [c01]"], "education_entry": "Bachelor's degree", "growth_pct": 7.0, "demand_reading": "growing", "ai_change_reading": "pending"}
    prof = {"interests": [{"value": "x", "quote": "q", "source_turn": 1}], "education_constraints": [{"value": "2-year max", "quote": "no more than two years", "source_turn": 2}], "financial_constraints": []}
    card = X._light_card(c, o, prof)
    assert card["why_fit"].endswith("[p:interests:0]") and card["tradeoff"].endswith("[interpretation]") and card["ai_change_reading"] == "pending" and card["how_ai_may_reshape"] == ""
    assert card["constraint_flags"] and "[p:education_constraints:0]" in card["constraint_flags"][0] and "[c03]" in card["constraint_flags"][0]

# reviewer roles: light → fast model, deep → thinking model; failure stays UNVERIFIED (12)
def test_review_roles_and_unverified(monkeypatch):
    seen = []
    def fake_judge(items, system, batch=16, max_tokens=12000, workers=4, role="skeptic"):
        seen.append((role, batch)); fake_judge.last_error = "boom"; return {}, 0.0, ("unverified" if role == "skeptic" else "verified")
    monkeypatch.setattr(rv, "judge_lines", fake_judge); monkeypatch.setattr(X, "add_citations", lambda st, obj, refs: (obj, 0.0)); rv.REVIEW_MEMO.clear()
    st = base_state(evidence_stage="light"); [c["card"].update({"why_fit": "you said so [p:interests:0]", "tradeoff": "long hours [interpretation]"}) for c in st["candidates"]]
    out = X.review_cards(st); assert seen[0][0] == "extractor" and seen[0][1] == 30 and out["skeptic"]["status"] == "verified" and out["skeptic"]["stage"] == "light"
    st2 = base_state(evidence_stage="deep", deep_socs=["11-1111"], skeptic=out["skeptic"]); [c["card"].update({"why_fit": "fits [p:interests:0]", "more_important": []}) for c in st2["candidates"]]
    out2 = X.review_cards(st2); assert seen[1][0] == "skeptic" and out2["skeptic"]["status"] == "unverified" and out2["skeptic"]["passes"] == 2 and out2["deep_done_socs"] == ["11-1111"]

def test_review_memo_skips_identical_object(monkeypatch):
    calls = []
    def fake_judge(items, system, batch=16, max_tokens=12000, workers=4, role="skeptic"): calls.append(1); return {0: {"verdict": "strip", "reason": "r"}}, 0.0, "verified"
    monkeypatch.setattr(rv, "judge_lines", fake_judge); monkeypatch.setattr(X, "add_citations", lambda st, obj, refs: (obj, 0.0)); rv.REVIEW_MEMO.clear()
    st = base_state(refs={}); obj = {"note": "the future is bright for you [p:interests:0]"}
    r1, sk1, _ = X.review_object(st, json.loads(json.dumps(obj)), "what-if"); r2, sk2, _ = X.review_object(st, json.loads(json.dumps(obj)), "what-if")
    assert len(calls) == 1 and sk1["stripped"] and sk2["stripped"] and r2["note"] == ""

# 8/9 · cache keys carry dataset versions; personalized memo keys carry model/role; no student text in the disk cache namespace list
def test_stable_cache_keys_include_versions(monkeypatch):
    k1 = cache.key_for("resolver", title="Product  Manager", about="", k=3); k2 = cache.key_for("resolver", title="product manager", about="", k=3); assert k1 == k2
    monkeypatch.setitem(cache.VERSIONS, "resolver", "r999"); assert cache.key_for("resolver", title="product manager", about="", k=3) != k1
    assert cache.key_for("forecasts", platform="polymarket", query="AGI", horizon=2030) != cache.key_for("forecasts", platform="polymarket", query="AGI", horizon=2035)
    assert set(cache.TTL) >= {"forecasts", "research", "onet_ws", "resolver"} and cache.TTL["forecasts"] <= 24 * 3600

def test_cache_roundtrip_atomic_and_corrupt_tolerant(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DIR", tmp_path); k = cache.key_for("research", source="x", args=[])
    assert cache.get("research", k) is None; cache.put("research", k, {"a": 1}); assert cache.get("research", k) == {"a": 1}
    (tmp_path / "research" / f"{k}.json").write_text("{not json"); assert cache.get("research", k) is None and not (tmp_path / "research" / f"{k}.json").exists()
    assert not list(tmp_path.glob("**/*.tmp"))

# 20 · caches and diagnostics never touch tracked files
def test_cache_dir_is_gitignored_and_no_tracked_writes():
    root = os.path.dirname(os.path.dirname(__file__)); assert "data/processed/cache/" in open(os.path.join(root, ".gitignore")).read()
    tracked = subprocess.run(["git", "ls-files", "data/processed/cache"], cwd=root, capture_output=True, text=True).stdout.strip(); assert tracked == ""

# incremental refs: existing [cNN] survive when deep evidence is added
def test_reconcile_keeps_existing_refs():
    from tools.schema import Card
    c1 = Card(id="a", family="statistics", claim="x", source="BLS"); c2 = Card(id="b", family="exposure", claim="y", source="O*NET")
    st = {"profile": {"horizon": "2035"}, "evidence": [c1], "unknowns": [], "refs": {}, "prior_snapshot": None}
    r1 = N.reconcile(st)["refs"]; assert r1 == {"c01": "a"}
    st2 = {**st, "evidence": [c1, c2], "refs": r1}; r2 = N.reconcile(st2)["refs"]; assert r2 == {"c01": "a", "c02": "b"}
