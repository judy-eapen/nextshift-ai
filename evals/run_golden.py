"""End-to-end evaluation of the redesigned graph — both journeys, both gates, failures, memory.
  python -m evals.run_golden            # all
  python -m evals.run_golden g01 g05    # subset
Deterministic checks per case (evals/golden.json `expect`) + an answer-quality rubric judged by the reviewer model (different family from the writer).
Writes evals/results/<timestamp>.json."""
import json, os, re, sys, time, uuid
from pathlib import Path
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from langgraph.types import Command
from graph.build import build_graph
from graph import llm, memory

ROOT = Path(__file__).resolve().parents[1]; OCC = pd.read_csv(ROOT / "data/raw/onet_occupation_data.csv")
FEAR = re.compile(r"\b(doomed|obsolete|will be replaced|will disappear|safe from AI|guaranteed|100% safe)\b", re.I)
RUBRIC = """You grade a career plan against the person's stated concerns. Answer each with true/false and a short reason:
1 answers_concerns: does the direct answer address every stated concern? 2 facts_vs_interpretation: are official projections kept apart from AI-related interpretation (labels, wording)?
3 no_guarantees: does it avoid guaranteeing safety or decline? 4 no_invented_products: does it avoid naming courses/certifications/products not in the evidence?
5 actionable: does the 30-day plan contain concrete practical experiences? Return {"answers_concerns":bool,"facts_vs_interpretation":bool,"no_guarantees":bool,"no_invented_products":bool,"actionable":bool,"notes":"..."}"""

def persona_for(code):
    onet = code if "." in code else f"{code}.00"; row = OCC[OCC["O*NET-SOC Code"] == onet]
    return {"soc": onet[:7], "onet_soc": onet, "title": row.Title.iloc[0] if len(row) else code, "matched_via": "golden"}

def build_inputs(g):
    if g["kind"] == "student":
        return {"door": "student", "interests": g["interests"].split(", "), "strengths": g["strengths"].split(", "), "constraints": {}, "concerns": ["demand", "change"], "horizon": g["horizon"], "question": "Which direction gives me good opportunities?"}, \
               [{"persona": persona_for(c), "role": "candidate"} for c in g["careers"]]
    from tools import composite, resolve as rs
    extra = {}
    if g.get("composite"): per = composite.persona_from(composite.curated(g["composite"]), 2030); per.pop("horizon", None)
    elif g.get("title"):
        r = rs.with_composites(rs.resolve(g["title"], g.get("about", ""), 3), g["title"], g.get("about", "")); extra["resolver_offers_composite"] = bool(r.get("composites"))
        per = composite.persona_from(r["composites"][0], 2030) if r.get("composites") else persona_for(r["matches"][0]["onet_soc"]); per.pop("horizon", None)
    else: per = persona_for(g["soc"])
    return {"door": "professional", "role_title": g.get("title") or g.get("composite") or per["title"], "week_description": g.get("week", ""), "industry": g.get("industry", ""), "concerns": g["concerns"], "horizon": g["horizon"], "question": "; ".join(g["concerns"]), **extra}, [{"persona": per, "role": "current"}]

def run_one(graph, g):
    profile, targets = build_inputs(g); cfg = {"configurable": {"thread_id": f"golden-{g['id']}-{uuid.uuid4().hex[:6]}"}}; t0 = time.time(); err = None
    os.environ["DISABLE_SOURCES"] = g.get("disable", ""); old_sk = os.environ.get("SKEPTIC_MODEL")
    if g.get("break_skeptic"): os.environ["SKEPTIC_MODEL"] = "not/a-real-model"
    snaps_before = _snapshot_count(); log = []
    try:
        for mode, ev in graph.stream({"profile": {k: v for k, v in profile.items() if k != "resolver_offers_composite"}, "targets": targets, "thread_id": cfg["configurable"]["thread_id"]}, cfg, stream_mode=["custom", "updates"]):
            if mode == "custom": log.append(ev["say"])
        r1 = {"action": "reject"} if g.get("reject_at") == "understanding" else {"action": "edit", "profile": {"horizon": g["edit_horizon"]}} if g.get("edit_horizon") else {"action": "confirm"}
        for mode, ev in graph.stream(Command(resume=r1), cfg, stream_mode=["custom", "updates"]):
            if mode == "custom": log.append(ev["say"])
        if g.get("reject_at") != "understanding":
            for mode, ev in graph.stream(Command(resume={"action": "reject" if g.get("reject_at") == "plan" else "approve"}), cfg, stream_mode=["custom", "updates"]):
                if mode == "custom": log.append(ev["say"])
    except Exception as e: err = repr(e)
    finally:
        if old_sk: os.environ["SKEPTIC_MODEL"] = old_sk
        os.environ["DISABLE_SOURCES"] = ""
    st = graph.get_state(cfg).values; exp = g["expect"]; ol = list((st.get("outlooks") or {}).values()); plan = st.get("plan") or {}; sk = st.get("skeptic") or {}
    body = (st.get("plan_md") or "").split("\n---\n")[0]
    uncited = [l for l in body.split("\n") if l.strip() and not l.startswith(("#", "**", "_")) and not re.search(r"\[[cu]\d{2,3}\]|\[advice\]|\[interpretation\]", l)]
    checks = {"no_error": err is None, "under_10min": time.time() - t0 < 600}
    if "min_cards" in exp: checks["min_cards"] = len(st.get("evidence") or []) >= exp["min_cards"]; checks["zero_uncited"] = len(uncited) == 0; checks["direct_answer"] = len((plan.get("direct_answer") or "")) > 80
    if "demand_reading" in exp: checks["demand_reading"] = bool(ol) and ol[0]["demand_reading"] == exp["demand_reading"]
    if "ai_change_reading_in" in exp: checks["ai_change_reading"] = bool(ol) and ol[0]["ai_change_reading"] in exp["ai_change_reading_in"]
    if exp.get("must_have_projection"): checks["projection"] = any(c.id.endswith(":growth") for c in st.get("evidence", []))
    if exp.get("must_report_unknowns"): checks["unknowns"] = len(st.get("unknowns") or []) >= 1 and "Cannot be known now" in body
    if exp.get("proxy_labelled"): checks["proxy_labelled"] = "Closest official category" in body and "No official projection exists" in body
    if exp.get("resolver_offers_composite"): checks["resolver_offers_composite"] = profile.get("resolver_offers_composite", False)
    if exp.get("no_fear_words"): checks["no_fear_words"] = not FEAR.search(body)
    if "comparison_rows" in exp: checks["comparison_rows"] = len(plan.get("comparison") or []) == exp["comparison_rows"]
    if exp.get("has_our_read"): checks["our_read"] = len(plan.get("our_read") or "") > 40
    if exp.get("must_surface_declining"): checks["declining_surfaced"] = any(o["soc"] == exp["must_surface_declining"] and o["demand_reading"] == "declining" for o in ol)
    if exp.get("partial_badge"): checks["partial_badge"] = any("Partial evidence" in b for b in (st.get("views") or {}).get("badges", []))
    if exp.get("must_surface_disagreement"): checks["disagreement"] = len(st.get("disagreements") or []) >= 1
    if "final_horizon" in exp: checks["final_horizon"] = str(st.get("profile", {}).get("horizon")) == exp["final_horizon"]
    if exp.get("understanding_edited"): checks["understanding_edited"] = (st.get("approvals") or {}).get("understanding", {}).get("edited") is True
    if exp.get("no_export"): checks["no_export"] = not st.get("exported_path")
    if exp.get("no_snapshot"): checks["no_snapshot"] = _snapshot_count() == snaps_before
    if "max_tool_calls" in exp: checks["no_gathering_after_reject"] = (st.get("tool_calls") or 0) <= exp["max_tool_calls"] and not st.get("evidence")
    if exp.get("skeptic_fallback_flagged"): checks["skeptic_fallback_flagged"] = sk.get("status") == "unverified" and any("UNVERIFIED" in b for b in (st.get("views") or {}).get("badges", [])) and (st.get("views") or {}).get("review_status") == "unverified"
    if "min_cards" in exp and sk.get("stripped"):   # removed content must not reach the UI (compare against the reviewed views)
        v_ = st.get("views") or {}; ui_text = json.dumps(v_.get("plan")) + json.dumps(v_.get("outlooks")) + json.dumps(v_.get("changes"))
        checks["removed_absent_from_ui"] = not any((r["sentence"].split(" [")[0][:50] if r["path"].endswith(".why") else r["sentence"][:60]) in ui_text for r in sk["stripped"])
    if exp.get("deltas_computed"): checks["deltas_computed"] = st.get("prior_snapshot") is not None and isinstance(st.get("deltas"), list)
    rubric = {}
    if "min_cards" in exp and plan.get("direct_answer") and not g.get("break_skeptic"):
        try:
            rubric, _ = llm.chat_json("skeptic", RUBRIC, f"Concerns: {profile.get('concerns')} · Door: {profile['door']}\n\nPLAN:\n{body[:24000]}", max_tokens=8000, temperature=0.0)   # whole plan — the 30-day section sits after the outlook facts
            for k in ("answers_concerns", "facts_vs_interpretation", "no_guarantees", "no_invented_products", "actionable"): checks[f"rubric_{k}"] = bool(rubric.get(k))
        except Exception as e: rubric = {"error": repr(e)}
    return {"id": g["id"], "kind": g["kind"], "seconds": round(time.time() - t0), "cards": len(st.get("evidence") or []), "stripped": len(sk.get("stripped") or []), "uncited_final": len(uncited), "tool_calls": st.get("tool_calls"),
            "cost_usd": round(st.get("cost_usd") or 0, 4), "demand": [o["demand_reading"] for o in ol], "deltas": len(st.get("deltas") or []), "exported": st.get("exported_path"), "error": err, "checks": checks, "rubric_notes": rubric.get("notes"), "pass": all(checks.values())}

def _snapshot_count():
    import sqlite3; c = sqlite3.connect(memory.DB); n = c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]; c.close(); return n

def main():
    golden = json.loads((ROOT / "evals/golden.json").read_text()); ids = set(sys.argv[1:]); graph = build_graph(); results = []
    for g in [g for g in golden if not ids or g["id"] in ids]:
        print(f"▶ {g['id']} {g['kind']} …", end=" ", flush=True); r = run_one(graph, g); results.append(r)
        print(f"{'PASS' if r['pass'] else 'FAIL'} {r['seconds']}s cards={r['cards']} demand={r['demand']} stripped={r['stripped']} ${r['cost_usd']}" + (f" ERR {r['error']}" if r["error"] else "") + ("" if r["pass"] else f"  failed: {[k for k, v in r['checks'].items() if not v]}"), flush=True)
    out = ROOT / "evals/results"; out.mkdir(exist_ok=True); path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    summary = {"passed": sum(r["pass"] for r in results), "total": len(results), "median_seconds": sorted(r["seconds"] for r in results)[len(results) // 2] if results else None, "total_cost_usd": round(sum(r["cost_usd"] for r in results), 4)}
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=2)); print(f"\n■ {summary['passed']}/{summary['total']} · median {summary['median_seconds']}s · ${summary['total_cost_usd']} · {path}")

if __name__ == "__main__": main()
