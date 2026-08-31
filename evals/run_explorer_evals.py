"""Deterministic Career Explorer evaluation (evals/explorer_golden.json): title searches, plain-language activity searches, school-subject browse, discovery
collections, growth/decline/high-exposure-but-growing cases, missing-data and composite cases, compare rows, family coverage. No model, no network.
  python -m evals.run_explorer_evals            # all → evals/results/explorer_<timestamp>.json"""
import json, sys, time
from pathlib import Path
from tools import catalog as C, career_page as P

ROOT = Path(__file__).resolve().parents[1]

def run_case(g: dict) -> dict:
    t0 = time.perf_counter(); checks = {}; k = g["kind"]
    if k in ("title", "activity"):
        s = C.search(g["q"], 12); top = [h["id"] for h in s["title_matches"] + s["meaning_matches"]][:10]
        if "expect_first" in g: checks["first"] = bool(top) and top[0] == g["expect_first"]
        if "expect_in_top" in g: checks["in_top"] = any(i in top for i in g["expect_in_top"])
        checks["explained"] = all(h["why"] for h in s["meaning_matches"]); detail = top[:5]
    elif k == "subject":
        rs = C.browse(subject=g["subject"]); ids = {r.id for r in rs}; checks["expect_in"] = all(i in ids for i in g["expect_in"]); checks["min_count"] = len(rs) >= g["min_count"]; detail = len(rs)
    elif k == "collection":
        rs = C.collection(g["name"]); ids = {r.id for r in rs}; detail = len(rs)
        if "not_in" in g: checks["not_in"] = not any(i in ids for i in g["not_in"])
        if "min_count" in g: checks["min_count"] = len(rs) >= g["min_count"]
        if g.get("no_residual"): checks["no_residual"] = not any(r.residual for r in rs)
        if "all_growth_at_least" in g: checks["growth"] = all((r.growth_pct or -99) >= g["all_growth_at_least"] for r in rs)
        if "all_class" in g: checks["class"] = all(r.growth_class == g["all_class"] for r in rs)
        if "all_ai" in g: checks["ai"] = all(r.ai_change_class == g["all_ai"] for r in rs)
        if "max_ai_share" in g: checks["ai_share"] = all((r.ai_task_share or 0) <= g["max_ai_share"] for r in rs)
        if "expect_in" in g: checks["expect_in"] = all(i in ids for i in g["expect_in"])
    elif k == "record":
        r = C.get(g["id_"]); detail = r.title
        checks["kind"] = r.kind == g["kind_"]
        for f in g.get("none_fields", []): checks[f"none:{f}"] = getattr(r, f) is None
        if "growth_class" in g: checks["growth_class"] = r.growth_class == g["growth_class"]
        if "ai_class_in" in g: checks["ai_class"] = r.ai_change_class in g["ai_class_in"]
        if g.get("has_proxies"): checks["proxies"] = bool(r.proxies)
        if g.get("has_bls_note"): checks["bls_note"] = bool(r.bls_note)
        if "min_related" in g: checks["related"] = len(r.related) >= g["min_related"]
        if "min_tasks" in g: checks["tasks"] = r.n_tasks >= g["min_tasks"]
        if g.get("openings_positive"): checks["openings"] = (r.openings_annual or 0) > 0
    elif k == "facts":
        f = P.facts_for(g["id_"]); detail = f.unavailable
        checks["unavailable"] = all(x in f.unavailable for x in g["unavailable_includes"]); checks["sourced"] = all(getattr(f, x) is not None and getattr(f, x).source_name and getattr(f, x).retrieved for x in g["sourced"])
        checks["no_fabrication"] = all(getattr(f, x, None) is None for x in g["unavailable_includes"])
    elif k == "compare":
        c = C.compare(g["ids"]); blob = json.dumps(c).lower(); detail = c["titles"]
        checks["rows"] = len(c["rows"]) == g["rows"] and all(len(r["cells"]) == len(g["ids"]) for r in c["rows"]); checks["no_words"] = not any(w in blob for w in g["no_words"])
    elif k == "family_coverage":
        rs = C.records().values(); detail = {f: sum(f in r.families for r in rs) for f in C.FAMILIES}
        checks["all_have_family"] = all(r.families for r in rs); checks["min_per_family"] = all(v >= g["min_per_family"] for v in detail.values())
    else: checks["known_kind"] = False; detail = None
    return {"id": g["id"], "kind": k, "ms": round((time.perf_counter() - t0) * 1000, 1), "checks": checks, "detail": detail, "pass": all(checks.values())}

def main():
    ids = set(sys.argv[1:]); cases = json.loads((ROOT / "evals/explorer_golden.json").read_text())["cases"]; results = []
    C.records(); C._index()   # warm (this is the one-time per-process cost)
    for g in cases:
        if ids and g["id"] not in ids: continue
        r = run_case(g); results.append(r); print(f"{'PASS' if r['pass'] else 'FAIL'} {r['id']} {r['kind']:16} {r['ms']:6.1f} ms" + ("" if r["pass"] else f"  failed: {[k for k, v in r['checks'].items() if not v]}  {str(r['detail'])[:120]}"))
    out = ROOT / "evals/results"; out.mkdir(exist_ok=True); path = out / f"explorer_{time.strftime('%Y%m%d-%H%M%S')}.json"
    summary = {"passed": sum(r["pass"] for r in results), "total": len(results), "median_ms": sorted(r["ms"] for r in results)[len(results) // 2] if results else None, "llm_calls": 0, "network_calls": 0, "catalog": {k: v for k, v in C.manifest().items() if k in ("version", "records", "direct", "detailed", "composite", "coverage")}}
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=1)); print(f"\n■ {summary['passed']}/{summary['total']} · median {summary['median_ms']} ms · 0 model calls · {path}")
    return 0 if summary["passed"] == summary["total"] else 1

if __name__ == "__main__": sys.exit(main())
