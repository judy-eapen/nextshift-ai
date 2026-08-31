"""Grounded hybrid career page: layers cannot mix; numbers never come from the model; missing fields are not fabricated; every explanation receives the
source evidence; labels; language lints; caching; reviewer rules; provenance. No network — the model and the reviewer are faked."""
import json, pathlib, re, tempfile, pytest
from tools import career_page as P, catalog as C, cache
from graph import llm, review as rv

@pytest.fixture
def isolated_cache(monkeypatch):
    monkeypatch.setattr(cache, "DIR", pathlib.Path(tempfile.mkdtemp())); yield

def fake_model(out):
    calls = []
    def f(role, system, user, **kw): calls.append({"role": role, "system": system, "user": user, "purpose": kw.get("purpose")}); return out, 0.0
    return f, calls

def keep_all(items, system, batch=12, max_tokens=12000, workers=4, role="skeptic"): return {i: {"verdict": "keep", "reason": "ok"} for i, _ in items}, 0.0, "verified"

GOOD = {"what_is_it": "Software developers design and build the programs people use [c01]. Demand is projected to grow [c03].",
        "typical_day": ["Morning: talk through what users need [c01]", "Afternoon: write and test code [c01]"],
        "outlook_story": "Demand looks healthy and openings are steady [c03].",
        "who_thrives": ["People who enjoy figuring out how things work tend to do well here [c01] [advice]"],
        "ai_story": "AI may speed up writing routine code while a person stays responsible [c01]. The mix may shift toward design and review; this is uncertain [c01].",
        "get_ready": ["Build a tiny app end to end [c01] [advice]"]}

# ── layers
def test_layers_are_typed_and_separate():
    pg = P.page("15-1252.00", with_cached_interpretation=False)
    assert isinstance(pg.facts, P.SourcedFacts) and isinstance(pg.derived, P.DerivedValues) and pg.interpretation is None and pg.personalized is None
    assert pg.facts.growth_pct.source == "bls_ep" and pg.facts.growth_pct.as_of == "2025-12-01" and pg.facts.growth_pct.retrieved
    assert pg.derived.growth_class.inputs == ["growth_pct"] and pg.derived.growth_class.value == "growing" and "graph" in pg.derived.growth_class.rule
    with pytest.raises(Exception): P.SourcedFacts(id="x", kind="direct", title="not a Sourced")   # a bare value cannot masquerade as a sourced fact

def test_missing_fields_not_fabricated():
    f = P.facts_for("composite:product-manager"); assert f.employment_2025 is None and f.growth_pct is None and "employment_2025" in f.unavailable and "growth_pct" in f.unavailable
    for name in ("industries", "licensing"): assert name in f.unavailable and getattr(f, name) is None
    f2 = P.facts_for("15-1252.00"); assert "industries" in f2.unavailable and "licensing" in f2.unavailable and f2.employment_2025.value == 1717800.0
    cards = P.evidence_cards(f); assert any(c.id.startswith("unknown:") and P.UNAVAILABLE in c.claim for c in cards) and not any("employed in 2025" in c.claim for c in cards)

def test_detailed_specialty_carries_the_parent_note():
    f = P.facts_for("15-1255.01"); assert f.employment_2025.note and "broader official category" in f.employment_2025.note

# ── the model is never the source of a number
def test_labor_market_numbers_never_come_from_model(isolated_cache, monkeypatch):
    out = dict(GOOD, what_is_it="There are 9 million software developers [c01]. Wages average $250,000 [c01]. Employment grows 40% [c03].")
    f, calls = fake_model(out); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    it = P.generate_interpretation("15-1252.00")
    joined = " ".join(it.sections["what_is_it"]); assert "9 million" not in joined and "250,000" not in joined and "40%" not in joined
    assert sum(1 for r in it.review["stripped"] if r["reason"] == "number not on the cited evidence card") == 3
    assert C.get("15-1252.00").emp_2025 == 1717800.0   # layer 1 untouched by anything the model said

def test_numbers_that_are_on_the_card_survive(isolated_cache, monkeypatch):
    out = dict(GOOD, what_is_it="About 1,717,800 people work as software developers [c03]. BLS projects +10.2% growth to 2035 [c04].")
    f, calls = fake_model(out); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    fx = P.facts_for("15-1252.00"); cards = P.evidence_cards(fx); refs, _ = P.refs_for(cards)
    emp = next(k for k, v in refs.items() if v.endswith(":emp2025:15-1252.00")); gr = next(k for k, v in refs.items() if v.endswith(":growth:15-1252.00"))
    out["what_is_it"] = f"About 1,717,800 people work as software developers [{emp}]. BLS projects +10.2% growth to 2035 [{gr}]."
    it = P.generate_interpretation("15-1252.00"); assert len(it.sections["what_is_it"]) == 2 and not it.review["stripped"]

# ── every explanation receives the evidence
def test_every_model_explanation_receives_source_evidence(isolated_cache, monkeypatch):
    f, calls = fake_model(GOOD); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    P.generate_interpretation("15-1252.00"); u = calls[0]["user"]
    assert "EVIDENCE TABLE" in u and "1,717,800" in u and "+10.2%" in u and "Bachelor's degree" in u and "Analyze user needs" in u and "[c01]" in u
    assert "NOT a source of facts" in calls[0]["system"] and "never estimate" in calls[0]["system"] and calls[0]["purpose"] == "career_interpretation"
    f2, calls2 = fake_model({"what_they_share": ["Both need a bachelor's [c01]"], "how_they_differ": ["Nurses care for patients; developers write code [c01] [c20]"], "questions_to_ask_yourself": ["Which day sounds better? [advice]"]})
    monkeypatch.setattr(llm, "chat_json", f2); P.generate_comparison(["15-1252.00", "29-1141.00"]); assert "Registered Nurses" in calls2[0]["user"] and "Software Developers" in calls2[0]["user"]

# ── labels + language
def test_generated_interpretations_are_labelled(isolated_cache, monkeypatch):
    f, _ = fake_model(GOOD); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    it = P.generate_interpretation("15-1252.00")
    assert it.labels["day_in_the_life"] == "An illustrative day based on common O*NET tasks. Actual work varies by employer and specialization."
    assert "not an official BLS or O*NET conclusion" in it.labels["model"] and "Written by an AI model" in it.labels["model"] and "About the work, not about you" in it.labels["fit"] and "does not mean fewer jobs" in it.labels["ai"]
    assert it.model and it.reviewer and it.model != it.reviewer and it.prompt_version == P.PROMPT_VERSION and it.catalog_version == C.VERSION

def test_good_fit_language_is_non_absolute(isolated_cache, monkeypatch):
    out = dict(GOOD, who_thrives=["You may enjoy this if you like puzzles [c01] [advice]", "This is the perfect career for you [c01] [advice]", "You must be an introvert [c01] [advice]", "Only for creative people [c01] [advice]", "You are not suited for this [c01] [advice]", "uncited: you may like it [advice]"])
    f, _ = fake_model(out); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    it = P.generate_interpretation("15-1252.00"); assert it.sections["who_thrives"] == ["You may enjoy this if you like puzzles [c01] [advice]"]
    reasons = [r["reason"] for r in it.review["stripped"]]; assert sum(1 for x in reasons if "(lint)" in x) == 4 and "fit line does not point at a task or work characteristic" in reasons   # 'perfect career' trips the shared certainty lint, the other three the absolute-fit lint

def test_ai_exposure_not_equated_with_job_loss(isolated_cache, monkeypatch):
    out = dict(GOOD, ai_story="Writing code will be automated [c01]. This job is doomed [c01]. AI may take over routine parts of code formatting [c01]. High AI exposure means fewer jobs is guaranteed [c01].")
    f, _ = fake_model(out); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    it = P.generate_interpretation("15-1252.00"); assert it.sections["ai_story"] == ["AI may take over routine parts of code formatting [c01]."]
    assert C.collection("growing_and_ai")   # the catalog itself carries careers that grow AND have heavy AI use

def test_no_ai_proof_or_safety_language_anywhere(isolated_cache, monkeypatch):
    out = dict(GOOD, ai_story="This career is AI-proof [c01]. A safe career from AI [c01]. Replacement risk: low [c01]. Working with a team rates high [c01].")
    f, _ = fake_model(out); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    it = P.generate_interpretation("15-1252.00"); assert it.sections["ai_story"] == ["Working with a team rates high [c01]."]
    banned = re.compile(r"ai-proof|safe career|replacement risk|job safety|guaranteed safe", re.I)
    for path in ("ui/explorer.py", "tools/career_page.py", "tools/catalog.py", "data/career_families.json"):
        text = open(path).read()
        for m in banned.finditer(text):   # the words may appear only inside the lint regex, the prompt's prohibition, or a quoted negative
            line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end())]
            assert "re.compile" in line or "never" in line.lower() or "banned" in line or "not a" in line, line[:200]

# ── cache reuse and reviewer rules
def test_cached_interpretations_are_reused(isolated_cache, monkeypatch):
    f, calls = fake_model(GOOD); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    a = P.generate_interpretation("15-1252.00"); b = P.generate_interpretation("15-1252.00"); c = P.cached_interpretation("career", ["15-1252.00"])
    assert len(calls) == 1 and not a.cached and b.cached and c.cached and b.sections == a.sections
    P.generate_interpretation("15-1252.00", force=True); assert len(calls) == 2

def test_unverified_result_is_not_cached_and_is_loud(isolated_cache, monkeypatch):
    f, calls = fake_model(GOOD); monkeypatch.setattr(llm, "chat_json", f)
    def down(items, system, batch=12, max_tokens=12000, workers=4, role="skeptic"): return {}, 0.0, "unverified"
    monkeypatch.setattr(rv, "judge_lines", down)
    it = P.generate_interpretation("15-1252.00"); assert it.review["status"] == "unverified" and P.cached_interpretation("career", ["15-1252.00"]) is None

def test_existing_reviewer_and_citation_rules_apply(isolated_cache, monkeypatch):
    seen = {}
    def judge(items, system, batch=12, max_tokens=12000, workers=4, role="skeptic"):
        seen["system"] = system; seen["items"] = items; seen["role"] = role
        return {i: {"verdict": "strip" if "grow" in t else "keep", "reason": "card says +10.2%, line says otherwise"} for i, t in items}, 0.0, "verified"
    f, _ = fake_model(dict(GOOD, what_is_it="They build programs [c01]. Demand is projected to grow forever [c03].", who_thrives=["You may enjoy this if you like puzzles [c01] [advice]"])); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", judge)
    it = P.generate_interpretation("15-1252.00")
    from graph.nodes import SKEPTIC_SYS; assert seen["system"] == SKEPTIC_SYS and seen["role"] == "skeptic" and all("cards:" in t for _, t in seen["items"])
    assert it.sections["what_is_it"] == ["They build programs [c01]."] and any(r["reason"].startswith("card says") for r in it.review["stripped"])
    assert not any("puzzles" in t for _, t in seen["items"])   # subjective fit lines are linted, not sent to the reviewer
    out_uncited = dict(GOOD, outlook_story="They write code all day.")   # a factual line without a ref is removed by the fixed rule before any model sees it
    f2, _ = fake_model(out_uncited); monkeypatch.setattr(llm, "chat_json", f2); monkeypatch.setattr(rv, "judge_lines", keep_all)
    it2 = P.generate_interpretation("15-1252.00", force=True); assert it2.sections["outlook_story"] == [] and any(r["reason"] == "no evidence ref" for r in it2.review["stripped"])

def test_provenance_survives_to_rendered_lines(isolated_cache, monkeypatch):
    f, _ = fake_model(GOOD); monkeypatch.setattr(llm, "chat_json", f); monkeypatch.setattr(rv, "judge_lines", keep_all)
    it = P.generate_interpretation("15-1252.00")
    assert P.cited_sources(it.sections["what_is_it"][0], it) == ["O*NET 2025"] and it.refs["c01"] == "onet:desc:15-1252.00" and it.cards[0]["as_of"] == "2025-08-01"

def test_personalized_layer_is_only_a_carrier():
    pg = P.PersonalizedGuidance(seed={"saved": [{"id": "15-1252.00", "title": "Software Developers", "reaction": "interesting"}]})
    assert pg.source == "interview" and "not choosing" in pg.label
