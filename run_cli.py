"""Run the redesigned graph from the terminal. Stops at each gate and asks, unless --auto.
  python run_cli.py --soc 15-1252 --auto                                   # Software Developers, professional
  python run_cli.py --composite "Product Manager" --industry "real-estate software" --week "discovery, requirements, prioritization with eng" --auto
  python run_cli.py --student --careers 27-1024 15-1255 19-3039 --interests "psychology, design, technology" --auto
"""
import argparse, time, uuid
from dotenv import load_dotenv; load_dotenv()
import pandas as pd
from langgraph.types import Command
from graph.build import build_graph

OCC = pd.read_csv("data/raw/onet_occupation_data.csv")

def persona_for(code: str) -> dict:
    onet = code if "." in code else f"{code}.00"; row = OCC[OCC["O*NET-SOC Code"] == onet]
    return {"soc": onet[:7], "onet_soc": onet, "title": row.Title.iloc[0] if len(row) else code, "matched_via": "soc"}

def stream(graph, inp, cfg):
    for mode, ev in graph.stream(inp, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom": print(f"  · {ev['say']}")
        elif "__interrupt__" in ev: return ev["__interrupt__"][0].value
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--soc", default=None); ap.add_argument("--composite", default=None); ap.add_argument("--about", default="")
    ap.add_argument("--student", action="store_true"); ap.add_argument("--careers", nargs="*", default=[]); ap.add_argument("--interests", default=""); ap.add_argument("--strengths", default="")
    ap.add_argument("--industry", default=""); ap.add_argument("--week", default=""); ap.add_argument("--concerns", default="demand,change,learn"); ap.add_argument("--horizon", default="2030")
    ap.add_argument("--question", default=None); ap.add_argument("--auto", action="store_true"); ap.add_argument("--edit-horizon", default=None); ap.add_argument("--reject-at", choices=["understanding", "plan"], default=None)
    a = ap.parse_args()
    if a.student:
        targets = [{"persona": persona_for(c), "role": "candidate"} for c in a.careers]
        profile = {"door": "student", "interests": [x.strip() for x in a.interests.split(",") if x.strip()], "strengths": [x.strip() for x in a.strengths.split(",") if x.strip()], "constraints": {},
                   "concerns": ["demand", "change"], "horizon": a.horizon, "question": a.question or "Which of these directions gives me good opportunities in an AI-shaped job market?"}
    else:
        if a.composite:
            from tools import composite
            comp = composite.curated(a.composite) if not a.about else composite.from_description(a.composite, a.about); assert comp, "no curated composite; pass --about"
            persona = composite.persona_from(comp, 2030); persona.pop("horizon", None)
        else: persona = persona_for(a.soc or "15-1252")
        targets = [{"persona": persona, "role": "current"}]
        profile = {"door": "professional", "role_title": a.composite or persona["title"], "week_description": a.week, "industry": a.industry, "concerns": a.concerns.split(","), "horizon": a.horizon,
                   "question": a.question or f"Will demand for my role decline, how will my responsibilities change, and what should I learn in the next year?"}
    graph = build_graph(); cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}; t0 = time.time()
    print(f"NextShift AI ▶ {' vs '.join(t['persona']['title'] for t in targets)} · {profile['door']} · {a.horizon}")
    payload = stream(graph, {"profile": profile, "targets": targets, "thread_id": cfg["configurable"]["thread_id"]}, cfg)
    if payload and payload["kind"] == "understanding":
        print(f"\n⏸ UNDERSTANDING GATE ({time.time()-t0:.0f}s)\n  {payload['profile'].get('summary')}")
        if a.reject_at == "understanding": resume = {"action": "reject"}
        elif a.edit_horizon: resume = {"action": "edit", "profile": {"horizon": a.edit_horizon}}
        elif a.auto: resume = {"action": "confirm"}
        else: ans = input("\n  confirm / edit <horizon> / reject > ").split(); resume = {"action": "reject"} if ans[:1] == ["reject"] else {"action": "edit", "profile": {"horizon": ans[1]}} if ans[:1] == ["edit"] else {"action": "confirm"}
        payload = stream(graph, Command(resume=resume), cfg)
    if payload and payload["kind"] == "plan":
        v = payload["views"]; sk = v["skeptic"]
        print(f"\n⏸ PLAN GATE ({time.time()-t0:.0f}s) — reviewer kept {sk['kept']}, removed {len(sk['stripped'])} ({sk['ratio']:.0%}), attempt {sk['attempt']}" + (" ESCALATED" if sk["escalated"] else ""))
        for s in sk["stripped"][:4]: print(f"  ✂ {s['sentence'][:100]} — {s['reason'][:70]}")
        for b in v["badges"]: print(f"  ▲ {b}")
        print(f"  budget {v['budget']}\n"); print(payload["plan_md"].split("\n---\n")[0][:3500])
        resume = {"action": "reject"} if a.reject_at == "plan" else {"action": "approve"} if a.auto else ({"action": "approve"} if input("\n  approve / reject > ").strip() != "reject" else {"action": "reject"})
        stream(graph, Command(resume=resume), cfg)
    final = graph.get_state(cfg).values
    print(f"\n■ {time.time()-t0:.0f}s · cards {len(final.get('evidence', []))} · tool calls {final.get('tool_calls')} · est. ${final.get('cost_usd', 0):.3f} · exported {final.get('exported_path')}")

if __name__ == "__main__": main()
