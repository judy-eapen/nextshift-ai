"""Run the golden set with both gates auto-approved and score PLAN §3: ≥N cards, 0 uncited after skeptic, ≥1 disagreement where expected, <10 min.
  python -m evals.run_golden            # all 10
  python -m evals.run_golden g01 g04    # subset
Writes evals/results/<timestamp>.json and prints a table."""
import json, sys, time, uuid
from pathlib import Path
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from langgraph.types import Command
from graph.build import build_graph

ROOT = Path(__file__).resolve().parents[1]

def run_one(graph, g: dict) -> dict:
    land = pd.read_parquet(ROOT / "data/processed/landscape.parquet"); row = land[land.soc == g["soc"]]
    persona = {"soc": g["soc"], "onet_soc": f"{g['soc']}.00", "title": row.title.iloc[0] if len(row) else g["occupation"], "matched_via": "golden", "horizon": g["horizon"]}
    cfg = {"configurable": {"thread_id": f"golden-{g['id']}-{uuid.uuid4().hex[:6]}"}}; t0 = time.time(); err = None
    try:
        for _ in graph.stream({"question": g["question"], "door": "professional", "persona": persona, "thread_id": cfg["configurable"]["thread_id"]}, cfg, stream_mode="updates"): pass
        for _ in graph.stream(Command(resume={"action": "approve"}), cfg, stream_mode="updates"): pass
        for _ in graph.stream(Command(resume={"action": "approve"}), cfg, stream_mode="updates"): pass
    except Exception as e: err = repr(e)
    st = graph.get_state(cfg).values; sk = st.get("skeptic") or {}; exp = g.get("expect", {})
    # "uncited after skeptic": any body sentence in the final brief without a [cNN]/[uNN] ref (headings, blockquote badge, evidence footer excluded)
    import re
    body = (st.get("brief_md") or "").split("\n---\n")[0]
    uncited = [l for l in body.split("\n") if l.strip() and not l.startswith(("#", ">", "_")) and not re.search(r"\[[cu]\d{2}\]", l)]   # headings, badge line, code-generated evidence line are exempt
    r = {"id": g["id"], "occupation": persona["title"], "seconds": round(time.time() - t0), "cards": len(st.get("evidence") or []), "disagreements": len(st.get("disagreements") or []),
         "unknowns": len(st.get("unknowns") or []), "stripped": len(sk.get("stripped") or []), "skeptic_ratio": sk.get("ratio"), "escalated": sk.get("escalated"), "uncited_final": len(uncited),
         "tool_calls": st.get("tool_calls"), "cost_usd": round(st.get("cost_usd") or 0, 4), "exported": st.get("exported_path"), "error": err}
    checks = {"min_cards": r["cards"] >= exp.get("min_cards", 6), "zero_uncited": r["uncited_final"] == 0, "under_10min": r["seconds"] < 600, "brief_exists": bool(st.get("brief_md")) and err is None}
    if exp.get("must_surface_disagreement"): checks["disagreement"] = r["disagreements"] >= 1
    if exp.get("must_report_unknowns"): checks["unknowns"] = r["unknowns"] >= 1
    if exp.get("low_exposure_expected"):
        ae = next((c for c in st.get("evidence", []) if c.source == "Anthropic Economic Index" and c.unit == "share"), None); checks["low_exposure"] = ae is not None and ae.value < 0.25
    r["checks"] = checks; r["pass"] = all(checks.values()); return r

def main():
    golden = json.loads((ROOT / "evals/golden.json").read_text()); ids = set(sys.argv[1:])
    todo = [g for g in golden if not ids or g["id"] in ids]; graph = build_graph(); results = []
    for g in todo:
        print(f"▶ {g['id']} {g['occupation']} / {g['horizon']} …", end=" ", flush=True); r = run_one(graph, g); results.append(r)
        print(f"{'PASS' if r['pass'] else 'FAIL'} {r['seconds']}s cards={r['cards']} disagree={r['disagreements']} unknown={r['unknowns']} stripped={r['stripped']} uncited={r['uncited_final']} ${r['cost_usd']}" + (f" ERROR {r['error']}" if r["error"] else "") + ("" if r["pass"] else f"  failed: {[k for k, v in r['checks'].items() if not v]}"))
    out = ROOT / "evals/results"; out.mkdir(exist_ok=True); path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    summary = {"passed": sum(r["pass"] for r in results), "total": len(results), "median_seconds": sorted(r["seconds"] for r in results)[len(results) // 2] if results else None, "total_cost_usd": round(sum(r["cost_usd"] for r in results), 4)}
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=2)); print(f"\n■ {summary['passed']}/{summary['total']} passed · median {summary['median_seconds']}s · ${summary['total_cost_usd']} · {path}")

if __name__ == "__main__": main()
