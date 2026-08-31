"""Career catalog: schema, stable ids, families, search, filters, classes, missing data, provenance, direct vs composite. Local data only — no network, no model."""
import json, os, pytest
from tools import catalog as C
from graph import nodes as N
from tools.schema import Card

RS = C.records()

def test_schema_and_required_fields():
    for r in list(RS.values())[:50] + [C.get("composite:product-manager")]:
        assert r.id and r.title and r.kind in ("direct", "detailed", "composite") and isinstance(r.families, list) and r.provenance and r.sources["onet"]["as_of"]
        assert r.growth_class in ("growing", "stable", "declining", "unknown") and r.ai_change_class in ("substantial", "moderate", "limited", "unknown")
    assert C.CatalogRecord.model_fields["id"].is_required()

def test_stable_identifiers_and_lookup():
    assert C.get("15-1252").id == "15-1252.00" and C.get("15-1252.00").soc == "15-1252" and C.get("15-1255.01").kind == "detailed" and C.get("nope") is None
    m = C.manifest(); assert m["records"] == len(RS) and m["direct"] == 867 and m["composite"] >= 1 and m["version"] == C.VERSION

def test_coverage_is_stated_honestly():
    line = C.coverage_line(); assert "not every job that exists" in line and "1,017" in line and "95%" in line

def test_every_record_has_a_family_and_mapping_is_deterministic():
    assert not [r.title for r in RS.values() if not r.families]
    assert "health" in C.get("29-1141").families and "tech" in C.get("15-1252").families and "environment" in C.get("19-2041").families and "design" in C.get("27-1024").families
    assert "hospitality" in C.get("27-2022").families and "design" not in C.get("27-2022").families    # coaches are not designers (override)
    assert set(C.get("composite:product-manager").families) >= {"emerging", "business"}
    assert {f["id"] for f in C.CONFIG["families"]} == set(C.FAMILIES) and len(C.FAMILIES) == 16

def test_search_by_exact_title_first():
    s = C.search("Registered Nurses"); assert s["title_matches"][0]["id"] == "29-1141.00" and s["title_matches"][0]["exact"]
    s = C.search("nurse"); titles = [h["title"] for h in s["title_matches"]]; assert "Registered Nurses" in titles[:5] and all("Nurse" in t for t in titles[:4])   # exact alias/prefix matches first; the official occupation before its specialties within a rank
    assert C.search("graphic designer")["title_matches"][0]["id"] == "27-1024.00"
    docs = [h["title"] for h in C.search("doctor", 30)["title_matches"]]
    assert not any("All Other" in x for x in docs[:5]) and len(docs) >= 20   # umbrella query: the catch-alls never crowd the top, and the specialists are all reachable
    assert {"Family Medicine Physicians", "Anesthesiologists", "Cardiologists"} & set(docs)

@pytest.mark.parametrize("q,expect", [("helping animals", "Veterinarians"), ("video games", "Video Game Designers"), ("working outdoors with plants", "Landscaping and Groundskeeping Workers"), ("fixing cars", "Automotive Service Technicians and Mechanics"), ("helping kids learn", "Kindergarten Teachers, Except Special Education"), ("marine biology", "Zoologists and Wildlife Biologists"), ("i am good at math", "Mathematicians"), ("I love helping people", "Healthcare Social Workers")])
def test_search_by_activity_or_subject(q, expect):
    s = C.search(q, 12); titles = [h["title"] for h in s["title_matches"] + s["meaning_matches"]]; assert expect in titles, titles
    for h in s["meaning_matches"]: assert h["why"] and 0 < h["coverage"] <= 1   # every match explains itself

def test_search_empty_and_nonsense():
    assert C.search("")["total"] == 0 and C.search("zzqqxxy")["total"] == 0

def test_filters_are_consistent_with_classes():
    for r in C.browse(family="health", growth="growing", include_residual=False): assert "health" in r.families and r.growth_class == "growing" and r.growth_pct >= 5.0
    for r in C.browse(trait="outdoors"): assert "outdoors" in r.traits and r.traits["outdoors"]["evidence"]
    for r in C.browse(subject="Biology"): assert r.knowledge.get("Biology", 0) >= C.SUBJECTS["Biology"]["min"]
    assert all(r.job_zone == 3 for r in C.browse(zone=3)) and all(r.education_entry == "Bachelor's degree" for r in C.browse(education="Bachelor's degree"))

def test_growth_classification_matches_the_graph():
    assert C.growth_class(5.0) == "growing" and C.growth_class(4.9) == "stable" and C.growth_class(-0.1) == "declining" and C.growth_class(None) == "unknown"
    for r in list(RS.values())[:200]:   # same thresholds as graph/nodes._reading_demand on a BLS growth card
        if r.growth_pct is None: continue
        card = Card(id="bls:proj:x:growth", family="statistics", claim="x", value=r.growth_pct, source="BLS", confidence=0.95)
        assert N._reading_demand([card]) == r.growth_class
    assert C.ai_change_class(0.4, 10) == "substantial" and C.ai_change_class(0.2, 10) == "moderate" and C.ai_change_class(0.1, 10) == "limited" and C.ai_change_class(None, 0) == "unknown"

def test_missing_data_stays_missing():
    comp = C.get("composite:product-manager")
    assert comp.emp_2025 is None and comp.growth_pct is None and comp.growth_class == "unknown" and comp.aioe is None and comp.proxies and comp.note
    det = C.get("15-1255.01"); assert det.bls_note and "broader official category" in det.bls_note and det.emp_2025 == C.get("15-1255.00").emp_2025
    no_proj = [r for r in RS.values() if r.kind == "direct" and r.growth_pct is None]; assert no_proj and all(r.growth_class == "unknown" for r in no_proj)
    assert C.trajectory(comp)["direction"] == "No official projection for this occupation"

def test_source_dates_and_provenance():
    for k, s in C.SOURCES.items(): assert s["name"] and s["kind"] and ("as_of" in s)
    r = C.get("15-1252"); assert r.provenance["employment_projection_education"] == "bls_ep" and r.sources["bls_ep"]["as_of"] == "2025-12-01" and r.sources["aei"]["as_of"] == "2025-03-27"
    assert "not automation" in r.sources["aei"]["note"]

def test_direct_vs_detailed_vs_composite_labels():
    assert C.get("15-1252").kind == "direct" and C.get("15-1299.09").kind == "detailed" and C.get("composite:product-manager").kind == "composite"
    d = C.detail("composite:product-manager"); assert "no official" in d["record"].note.lower() and d["related"]   # composites relate to the occupations their tasks come from

def test_collections_make_the_growth_vs_exposure_distinction():
    both = C.collection("growing_and_ai"); assert both and all(r.growth_class == "growing" and r.ai_change_class == "substantial" for r in both)
    assert all(r.growth_class == "declining" for r in C.collection("declining")) and all((r.growth_pct or 0) >= 10 for r in C.collection("fast_growing"))
    assert all(r.human_intensive and (r.ai_task_share or 0) <= 0.05 for r in C.collection("human_intensive"))
    u1, u2 = C.collection("unknown", seed=0, limit=10), C.collection("unknown", seed=1, limit=10); assert u1 != u2 and not any(r.familiar or r.residual for r in u1 + u2)
    assert C.collection("unknown", seed=0, limit=10) == u1   # deterministic for a seed

def test_compare_up_to_four_no_score():
    cmp = C.compare(["15-1252.00", "29-1141.00", "17-1011.00", "27-1024.00", "23-1011.00"])
    assert len(cmp["ids"]) == 4 and [r["label"] for r in cmp["rows"]] == [l for l, _ in C.COMPARE_ROWS] and all(len(r["cells"]) == 4 for r in cmp["rows"])
    blob = json.dumps(cmp).lower(); assert "score" not in blob and "winner" not in blob and "best choice" not in blob

def test_detail_view_model_and_related():
    d = C.detail("15-1252.00"); assert d["record"].title == "Software Developers" and d["related"] and d["test"] and d["trajectory"]["labels"]["ai_shaped"].startswith("observed use, not a forecast")
    assert all("of 5" in w["evidence"] for w in d["workday"]) and all(e["evidence"] for e in d["enjoy"])

def test_catalog_dir_gitignored_and_atomic_build(tmp_path, monkeypatch):
    root = os.path.dirname(os.path.dirname(__file__)); assert "data/processed/catalog/" in open(os.path.join(root, ".gitignore")).read()
    monkeypatch.setattr(C, "DIR", tmp_path); p = C.build(force=True); assert p.exists() and (tmp_path / "manifest.json").exists() and not list(tmp_path.glob("*.tmp"))
