"""Run the graph from the terminal. Stops at each interrupt and asks, unless --auto.
  python run_cli.py --soc 11-2021 --horizon 2030 --question "What happens to product managers if AGI arrives by 2030?"
  python run_cli.py --soc 11-2021 --auto            # approve both gates without asking (for evals)
  python run_cli.py --soc 11-2021 --edit-horizon 2035  # demo: edit an assumption at gate 1
"""
import argparse, json, os, sys, time, uuid
from dotenv import load_dotenv; load_dotenv()
from langgraph.types import Command
from graph.build import build_graph

def stream(graph, inp, cfg):
    """Print the agent thinking in public; return the interrupt payload if one fired."""
    for mode, ev in graph.stream(inp, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom": print(f"  · {ev['say']}")
        elif "__interrupt__" in ev: return ev["__interrupt__"][0].value
    return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--soc", default="11-2021"); ap.add_argument("--horizon", type=int, default=2030)
    ap.add_argument("--question", default=None); ap.add_argument("--door", default="professional"); ap.add_argument("--auto", action="store_true")
    ap.add_argument("--edit-horizon", type=int, default=None); ap.add_argument("--thread", default=None); a = ap.parse_args()
    import pandas as pd; land = pd.read_parquet("data/processed/landscape.parquet"); row = land[land.soc == a.soc]
    title = row.title.iloc[0] if len(row) else a.soc
    persona = {"soc": a.soc, "onet_soc": f"{a.soc}.00", "title": title, "matched_via": "soc", "horizon": a.horizon}
    q = a.question or f"What happens to {persona['title']} by {a.horizon}, and what should I do about it?"
    graph = build_graph(); cfg = {"configurable": {"thread_id": a.thread or str(uuid.uuid4())}}; t0 = time.time()
    print(f"NextShift AI\n▶ {persona['title']} (SOC {persona['soc']}) · {a.horizon} · thread {cfg['configurable']['thread_id'][:8]}\n  Q: {q}")
    payload = stream(graph, {"question": q, "door": a.door, "persona": persona, "thread_id": cfg["configurable"]["thread_id"]}, cfg)

    # ⏸ gate 1
    if payload and payload["kind"] == "worldview":
        wv = payload["worldview"]
        print(f"\n⏸ WORLDVIEW GATE — assumptions the agent is about to make ({time.time()-t0:.0f}s in):")
        print(f"  occupation {wv['title']} · horizon {wv['horizon']} · anchor: {wv['anchor_question'][:100]}")
        for c in wv["claims"]: print(f"  - {c}")
        if payload["disagreements"]: print("  disagreements: " + "; ".join(f"{d['anchor']} {d['spread']} across {'/'.join(d['sources'])}" for d in payload["disagreements"]))
        if payload["unknowns"]: print(f"  unknowns: {len(payload['unknowns'])} → {payload['unknowns'][:3]}")
        print(f"  sources: {payload['source_status']}")
        if payload["deltas"]: print(f"  since you last looked: {len(payload['deltas'])} changes, e.g. {payload['deltas'][0]}")
        if a.edit_horizon: resume = {"action": "edit", "worldview": {"horizon": a.edit_horizon}}
        elif a.auto: resume = {"action": "approve"}
        else:
            ans = input("\n  approve / edit <horizon> / reject > ").strip().split()
            resume = {"action": "reject"} if ans[:1] == ["reject"] else {"action": "edit", "worldview": {"horizon": int(ans[1])}} if ans[:1] == ["edit"] else {"action": "approve"}
        payload = stream(graph, Command(resume=resume), cfg)

    # ⏸ gate 2
    if payload and payload["kind"] == "publish":
        sk = payload["skeptic"]
        print(f"\n⏸ PUBLISH GATE ({time.time()-t0:.0f}s in) — skeptic {sk['model']}: kept {sk['kept']}, stripped {len(sk['stripped'])} ({sk['ratio']:.0%}), attempt {sk['attempt']}" + (" ESCALATED" if sk["escalated"] else ""))
        for s in sk["stripped"][:5]: print(f"  ✂ {s['sentence'][:110]} — {s['reason'][:80]}")
        for b in payload["badges"]: print(f"  ▲ {b}")
        print(f"  budget: {payload['budget']}")
        print("\n" + payload["brief_md"][:2500] + ("\n…" if len(payload["brief_md"]) > 2500 else ""))
        resume = {"action": "approve"} if a.auto else ({"action": "approve"} if input("\n  approve / reject > ").strip() != "reject" else {"action": "reject"})
        stream(graph, Command(resume=resume), cfg)

    final = graph.get_state(cfg).values
    print(f"\n■ done in {time.time()-t0:.0f}s · cards {len(final.get('evidence', []))} · tool calls {final.get('tool_calls')} · est. cost ${final.get('cost_usd', 0):.3f} · exported {final.get('exported_path')}")
    return final

if __name__ == "__main__": main()
