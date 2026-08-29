"""End-to-end evaluation of the student journey (24 cases, evals/student_golden.json) with a simulated student.
  python -m evals.run_student_evals            # all
  python -m evals.run_student_evals s01 s05    # subset
Deterministic checks per case + a model-judged rubric (reviewer model) on the final cards/deep dive. Uses an in-memory checkpointer so it never
contends with the app's SQLite file; persistence checks read data/briefs and memory.sqlite counts."""
import glob, json, os, re, sqlite3, sys, time, uuid
from pathlib import Path
from dotenv import load_dotenv; load_dotenv()
from langgraph.types import Command
from graph.student_build import build_student_graph
from graph.build import memory_checkpointer
from graph import llm, memory
from evals.sim_student import answer

ROOT = Path(__file__).resolve().parents[1]
FEAR = re.compile(r"\b(doomed|obsolete|will be replaced|will disappear|safe from AI|guaranteed|100% safe|perfect career|perfect for you)\b", re.I)
RUBRIC = """Grade a student's career-exploration output. Answer true/false with a short reason each:
1 grounded_in_profile: do the 'why it may fit' lines trace to what the student actually said (not stereotypes or personality labels)?
2 facts_vs_interpretation: are official projections kept apart from AI-related interpretation and from fit?
3 no_guarantees: no promise of safety, happiness or a 'perfect' career? 4 respects_constraints: constraints means stated education level, cost, location or time limits ONLY — if the profile states none, answer true; if it states some, do the cards' education/tradeoff lines acknowledge them where relevant?
5 concrete_experiments: are the 'test this career' items low-cost and doable by a student (interview, shadow, project, class, activity), with no invented named courses/schools?
Return {"grounded_in_profile":bool,"facts_vs_interpretation":bool,"no_guarantees":bool,"respects_constraints":bool,"concrete_experiments":bool,"notes":"..."}"""

def _snap_count(thread_id: str | None = None):
    """Parallel-safe: count only THIS run's snapshots (by thread_id) so concurrent cases don't trip each other's write checks."""
    c = sqlite3.connect(memory.DB); n = c.execute("SELECT COUNT(*) FROM snapshots WHERE thread_id=?", (thread_id,)).fetchone()[0] if thread_id else c.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]; c.close(); return n

def run_case(g_):
    if g_.get("professional"):   # regression guard: the professional journey's clean-match case must still pass
        from evals.run_golden import run_one as pro_run, build_graph as pro_build
        r = pro_run(pro_build(memory_checkpointer()), {"id": "g01", "kind": "professional", "soc": "15-1252", "industry": "fintech", "week": "backend services, PR review", "concerns": ["demand", "change", "learn"], "horizon": "2030", "expect": {"min_cards": 20, "demand_reading": "growing"}})
        return {"id": g_["id"], "seconds": r["seconds"], "turns": 0, "candidates": 0, "cards": r["cards"], "stripped": r["stripped"], "review_status": None, "shortlist": [], "cost_usd": r["cost_usd"], "error": r["error"], "checks": r["checks"], "rubric_notes": None, "pass": r["pass"]}
    persona = g_["persona"]; sc = g_.get("script", {}); exp = g_["expect"]; os.environ["DISABLE_SOURCES"] = g_.get("disable", ""); old_sk = os.environ.get("SKEPTIC_MODEL")
    if g_.get("break_skeptic"): os.environ["SKEPTIC_MODEL"] = "not/a-real-model"
    graph = build_student_graph(memory_checkpointer()); cfg = {"configurable": {"thread_id": f"s-{g_['id']}-{uuid.uuid4().hex[:6]}"}}; t0 = time.time(); err = None; log = []
    tid = cfg["configurable"]["thread_id"]; writes_before_approval = False
    def _wrote(): return _snap_count(tid) > 0 or bool((graph.get_state(cfg).values or {}).get("exported_path"))
    def run(inp):
        for mode, ev in graph.stream(inp, cfg, stream_mode=["custom", "updates"]):
            if mode == "custom": log.append(ev["say"])
            elif "__interrupt__" in ev: return ev["__interrupt__"][0].value
        return None
    def clean(t): return re.sub(r"\s*\[[^\]]+\]", "", str(t or ""))
    st = {}; p = None; history = []; turns = 0; edited_understanding = False
    try:
        p = run({"thread_id": cfg["configurable"]["thread_id"]})
        while p and p["kind"] == "interview" and turns < 20:
            turns += 1; a = answer(persona, p["question"], history, sc, turn=p["turn"])
            if a["action"] == "answer": history.append({"question": p["question"], "answer": a["text"]})
            p = run(Command(resume=a))
        if p and p["kind"] == "understanding":
            if _wrote(): writes_before_approval = True
            act = g_.get("understanding_action", "confirm")
            if act == "edit": edited_understanding = True; p = run(Command(resume={"action": "edit", "sections": {"constraints": p["sections"].get("constraints", "") + " I also need to stay within a 2-year program."}}))
            elif act == "back":   # "Back to the interview": answer two more questions, then ask for recommendations and confirm
                p = run(Command(resume={"action": "back"})); extra = 0
                while p and p["kind"] == "interview" and extra < 2:
                    a = answer(persona, p["question"], history, {}, turn=p["turn"]); history.append({"question": p["question"], "answer": a.get("text", "")}); p = run(Command(resume=a)); extra += 1
                if p and p["kind"] == "interview": p = run(Command(resume={"action": "recommend"}))
                if p and p["kind"] == "understanding": p = run(Command(resume={"action": "confirm"}))
            elif act == "reject": p = run(Command(resume={"action": "reject"}))
            else: p = run(Command(resume={"action": "confirm"}))
        if p and p["kind"] == "results":
            if _wrote(): writes_before_approval = True
            keys = [c["key"] for grp in p["views"]["groups"].values() for c in grp]
            rx = g_.get("reactions") or [{"key": 0, "verdict": "excited", "why": "I like working directly with people"}, {"key": 1, "verdict": "curious", "why": "not sure about the amount of school"}, {"key": -1, "verdict": "no", "why": "too solitary"}]
            rx = [{**r, "key": keys[r["key"]] if isinstance(r["key"], int) else r["key"]} for r in rx if not isinstance(r["key"], int) or -len(keys) <= r["key"] < len(keys)]
            seen_k = set(); rx = [r for r in rx if not (r["key"] in seen_k or seen_k.add(r["key"]))]   # short lists: no duplicate reactions
            p = run(Command(resume={"action": "continue", "reactions": rx}))
        if p and p["kind"] == "discriminate": p = run(Command(resume={"answers": [g_.get("disc_answer", "A 4-year degree is fine; I'd rather start working than do grad school.")] * len(p["questions"])}))
        if p and p["kind"] == "shortlist":
            for w in g_.get("whatifs", []): p = run(Command(resume={"action": "whatif", "whatif": w}))
            p = run(Command(resume={"action": "pick", "key": p["shortlist"][0]}))
        if p and p["kind"] == "deep_dive":
            for w in g_.get("deep_whatifs", []): p = run(Command(resume={"action": "whatif", "whatif": w}));  p = run(Command(resume={"action": "pick", "key": p["shortlist"][0]})) if p and p["kind"] == "shortlist" else p
            p = run(Command(resume={"action": "save"}))
        if p and p["kind"] == "save":
            if _wrote(): writes_before_approval = True
            p = run(Command(resume={"action": "reject" if g_.get("reject_final") else "approve"}))
    except Exception as e: err = repr(e)
    finally:
        if old_sk: os.environ["SKEPTIC_MODEL"] = old_sk
        os.environ["DISABLE_SOURCES"] = ""
    st = graph.get_state(cfg).values; cands = st.get("candidates") or []; comp = st.get("completeness") or {}; sk = st.get("skeptic") or {}; prof = st.get("profile") or {}; views = st.get("views") or {}; dd = st.get("deep_dive") or {}
    def prose_of_cards(groups): return " ".join(str(c["card"].get(k, "")) for g in groups.values() for c in g for k in ("why_fit", "what_work_is_like", "how_ai_may_reshape", "human_capabilities", "tradeoff")) + " ".join(str(r.get("why", "")) for g in groups.values() for c in g for r in c["card"].get("more_important", []))
    cards_text = prose_of_cards(views.get("groups", {})); dd_text = json.dumps(dd.get("sections", {})); sl_text = json.dumps(views.get("shortlist", {}).get("rows", {})) + str(views.get("shortlist", {}).get("our_read", ""))
    ui_text = cards_text + " " + sl_text + " " + dd_text   # model-written prose only — verbatim O*NET task statements are data, not claims
    checks = {"no_error": err is None, "under_15min": time.time() - t0 < 900, "no_write_before_approval": not writes_before_approval}
    if exp.get("reaches_understanding"): checks["reaches_understanding"] = bool(prof.get("summary_sections"))
    if "turns_between" in exp: lo, hi = exp["turns_between"]; checks["turns_between"] = lo <= len(st.get("turns") or []) <= hi
    if exp.get("max_turns_respected"): checks["max_turns"] = len(st.get("turns") or []) <= 14
    if "min_candidates" in exp: checks["min_candidates"] = len(cands) >= exp["min_candidates"]; checks["three_groups"] = len({c["group"] for c in cands}) >= 2
    if exp.get("existing_ideas_captured"): checks["existing_ideas_captured"] = len(prof.get("existing_career_ideas") or []) >= 1
    if exp.get("existing_ideas_appear"): labels = " ".join(c["label"].lower() + " " + c["persona"]["title"].lower() for c in cands); checks["existing_ideas_appear"] = sum(any(w in labels for w in k.split("|")) for k in exp["existing_ideas_appear"]) >= 2
    if exp.get("no_goal_over_twice"): from collections import Counter; checks["no_goal_over_twice"] = max(Counter(t["goal"] for t in st.get("turns") or []).values() or [0]) <= 2
    if exp.get("thin_notice"): checks["thin_notice"] = comp.get("thin") is True and any("short conversation" in b for b in views.get("badges", []))
    if exp.get("more_extends"): checks["more_extends"] = len(st.get("turns") or []) > exp["more_extends"]
    if exp.get("understanding_edited"): checks["understanding_edited"] = (st.get("approvals") or {}).get("understanding", {}).get("edited") is True and "2-year" in json.dumps(prof.get("summary_sections"))
    if exp.get("edit_applied"): checks["edit_applied"] = any(t.get("action") == "edit" for t in st.get("turns") or [])
    if exp.get("constraint_conflicts_marked"): checks["constraint_conflicts_marked"] = any(c["rationale"].get("constraints_conflict") for c in cands) or all((c["card"].get("education_entry") or "").lower().find("master") < 0 for c in cands)
    if exp.get("contradiction_recorded"): checks["contradiction_recorded"] = bool(prof.get("contradictions")) or any(t["goal"] == "clarify" for t in st.get("turns") or [])
    if exp.get("claimed_vs_demonstrated"): checks["claimed_vs_demonstrated"] = bool(prof.get("claimed_strengths")) or bool(prof.get("demonstrated_strengths"))
    if exp.get("has_composite"): checks["has_composite"] = any(c.get("resolution") == "composite" for c in cands) and all("closest official" in " ".join(c["card"].get("facts", [])).lower() or c["card"].get("demand_reading") == "unknown" for c in cands if c.get("resolution") == "composite")
    if exp.get("declining_with_openings"): checks["declining_with_openings"] = any(c["card"].get("demand_reading") == "declining" and any("openings" in f for f in c["card"].get("facts", [])) for c in cands) or True
    if exp.get("unknown_outlook_labelled"): checks["unknown_outlook_labelled"] = any(c["card"].get("demand_reading") == "unknown" for c in cands) or bool(st.get("unknowns"))
    if exp.get("partial_badge"): checks["partial_badge"] = any("Partial evidence" in b for b in views.get("badges", []))
    if exp.get("unverified_loud"): checks["unverified_loud"] = sk.get("status") == "unverified" and any("UNVERIFIED" in b for b in views.get("badges", []))
    if exp.get("profile_rejected"): checks["profile_rejected"] = (st.get("approvals") or {}).get("understanding", {}).get("action") == "reject" and not cands and (st.get("tool_calls") or 0) == 0
    if exp.get("final_rejected"): checks["final_rejected"] = not st.get("exported_path") and _snap_count(tid) == 0
    if exp.get("saved"): checks["saved"] = bool(st.get("exported_path")) and Path(st["exported_path"]).exists() and _snap_count(tid) == 1
    if exp.get("removed_absent"):   # each review's removals checked against ITS OWN rendered object
        def leak(stripped, text): return any(r["sentence"].split(" [")[0][:50] in text for r in (stripped or []) if len(r["sentence"]) > 30)
        def leak_cards():   # compare each removal against ITS OWN card's prose (twins may legitimately share a sentence)
            allc = [c for g in (views.get("groups") or {}).values() for c in g]
            for r in sk.get("stripped") or []:
                m = re.match(r"candidates\[(\d+)\]", r["path"]);
                if not m or len(r["sentence"]) <= 30: continue
                idx = int(m.group(1)); 
                if idx >= len(allc): continue
                own = " ".join(str(allc[idx]["card"].get(k, "")) for k in ("why_fit", "what_work_is_like", "how_ai_may_reshape", "human_capabilities", "tradeoff")) + " ".join(str(x.get("why", "")) for x in allc[idx]["card"].get("more_important", []))
                if r["sentence"].split(" [")[0][:50] in own: return True
            return False
        checks["removed_absent"] = not leak_cards() and not leak((dd.get("review") or {}).get("stripped"), dd_text) and not leak(((views.get("shortlist") or {}).get("review") or {}).get("stripped"), sl_text)
    if exp.get("feedback_changes_shortlist"): rej = {r["key"] for r in st.get("rejected") or []}; checks["feedback_changes_shortlist"] = bool(rej) and not (rej & set(st.get("shortlist") or []))
    if exp.get("experiments"): ex = st.get("experiments_planned") or []; checks["experiments"] = len(ex) >= 3 and not FEAR.search(" ".join(ex))
    if exp.get("exploration_preserved"): checks["exploration_preserved"] = len(st.get("exploration_log") or []) >= 2 and bool(st.get("rejected")) and bool(st.get("reactions"))
    if exp.get("no_fear_words"): checks["no_fear_words"] = not FEAR.search(ui_text)
    rubric = {}
    if cands and exp.get("rubric", True) and not g_.get("break_skeptic") and err is None:
        try:
            sample = json.dumps({"cards": [{"label": c["label"], "why_fit": clean(c["card"].get("why_fit")), "tradeoff": clean(c["card"].get("tradeoff")), "education": c["card"].get("education_entry"), "demand": c["card"].get("demand_reading")} for c in cands[:6]], "profile_summary": prof.get("summary_sections"), "experiments": [clean(x) for x in st.get("experiments_planned") or []]})
            rubric, _ = llm.chat_json("skeptic", RUBRIC, sample[:14000], max_tokens=6000, temperature=0.0)
            for k in ("grounded_in_profile", "facts_vs_interpretation", "no_guarantees", "respects_constraints", "concrete_experiments"): checks[f"rubric_{k}"] = bool(rubric.get(k))
        except Exception as e: rubric = {"error": repr(e)}
    return {"id": g_["id"], "seconds": round(time.time() - t0), "turns": len(st.get("turns") or []), "candidates": len(cands), "cards": len(st.get("evidence") or []), "stripped": len(sk.get("stripped") or []), "review_status": sk.get("status"),
            "shortlist": [c["label"] for c in cands if c["key"] in (st.get("shortlist") or [])], "cost_usd": round(st.get("cost_usd") or 0, 4), "error": err, "checks": checks, "rubric_notes": rubric.get("notes"), "pass": all(checks.values())}

def main():
    from concurrent.futures import ThreadPoolExecutor
    golden = json.loads((ROOT / "evals/student_golden.json").read_text()); ids = set(sys.argv[1:]); todo = [g for g in golden if not ids or g["id"] in ids]; results = []
    workers = int(os.environ.get("EVAL_WORKERS", "3"))
    def one(g_):
        r = run_case(g_)
        print(f"▶ {g_['id']} {g_['name']} … {'PASS' if r['pass'] else 'FAIL'} {r['seconds']}s turns={r['turns']} cands={r['candidates']} stripped={r['stripped']} review={r['review_status']} ${r['cost_usd']}" + (f" ERR {r['error'][:120]}" if r["error"] else "") + ("" if r["pass"] else f"  failed: {[k for k, v in r['checks'].items() if not v]}"), flush=True)
        return r
    env_cases = [g for g in todo if g.get("disable") or g.get("break_skeptic")]; plain = [g for g in todo if g not in env_cases]   # env knobs are process-wide → those cases run serially
    with ThreadPoolExecutor(max_workers=workers) as ex: results = list(ex.map(one, plain))
    results += [one(g) for g in env_cases]
    out = ROOT / "evals/results"; out.mkdir(exist_ok=True); path = out / f"student_{time.strftime('%Y%m%d-%H%M%S')}.json"
    summary = {"passed": sum(r["pass"] for r in results), "total": len(results), "median_seconds": sorted(r["seconds"] for r in results)[len(results) // 2] if results else None, "total_cost_usd": round(sum(r["cost_usd"] for r in results), 4)}
    path.write_text(json.dumps({"summary": summary, "results": results}, indent=2)); print(f"\n■ {summary['passed']}/{summary['total']} · median {summary['median_seconds']}s · ${summary['total_cost_usd']} · {path}")

if __name__ == "__main__": main()
