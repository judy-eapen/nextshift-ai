"""Graph nodes — redesign (Sat 2026-08-28). The person's question comes first; evidence and machinery support it.
Rule of the house: models write prose and judgments; numbers and groupings come from code over Cards.
Every line a model writes cites [cNN] (evidence) or [uNN] (a known unknown); interpretive lines are tagged [interpretation];
the skeptic (a different model family) strips what it can't verify."""
from __future__ import annotations
import json, os, re, time, uuid
from pathlib import Path
from langgraph.types import interrupt, Send
from langgraph.config import get_stream_writer
from tools.schema import Card, SourceResult
from tools import polymarket, manifold, metaculus, exposure, fred, epoch, onet_ws, composite
from tools import outlook as outlook_tool
from . import llm, memory
from .state import State

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "data" / "anchor_questions.json").read_text()); ANCHORS = CFG["anchors"]
MAX_TOOL_CALLS, MAX_COST_USD, UNCITED_LIMIT = 40, 1.00, 0.30
CONCERN_LABEL = {"demand": "whether demand for the role holds", "change": "how the work changes", "learn": "what to learn", "pivot": "whether to consider a different path"}
HORIZON_LABEL = {"1-2y": "the next 1–2 years", "2030": "by 2030", "2035": "by 2035"}
def _year(h) -> int: return {"1-2y": 2030, "2030": 2030, "2035": 2035}.get(str(h), 2030)

def _say(text: str):
    """Plain-language progress the UI shows live. No-op outside a graph run."""
    try: get_stream_writer()({"say": text, "t": time.time()})
    except Exception: pass

def _disabled(name: str) -> bool:
    return name.lower() in {x.strip().lower() for x in os.environ.get("DISABLE_SOURCES", "").split(",") if x.strip()}

def _call(name: str, fn, *args) -> SourceResult:
    if _disabled(name): return SourceResult(source=name, ok=False, error="source disabled for failure demo (DISABLE_SOURCES)")
    try: return fn(*args)
    except Exception as e: return SourceResult(source=name, ok=False, error=f"{type(e).__name__}: {e}")

def _collect(results, occ: str | None, calls: int) -> dict:
    cards, unknowns, errors, status = [], [], [], {}
    for name, r in results:
        for c in r.cards:
            if occ and not c.occ: c.occ = occ
        cards += r.cards; unknowns += r.unknowns
        if not r.ok: errors.append(f"{name}: {r.error}"); status[name] = "unavailable"
        else: status[name] = "ok" if r.cards else "partial"
    return {"evidence": cards, "unknowns": unknowns, "errors": errors, "source_status": status, "tool_calls": calls}

def _occ_key(p: dict) -> str: return p["soc"]

# ───────────────────────────── memory + understanding ─────────────────────────────
def load_memory(state: State) -> dict:
    t0 = state["targets"][0]["persona"]; prior = memory.load_latest(t0["soc"], str(state["profile"].get("horizon", "2030")))
    _say("Checked memory: " + ("found an earlier plan for this occupation to compare against." if prior else "first plan for this occupation."))
    return {"prior_snapshot": prior, "thread_id": state.get("thread_id") or str(uuid.uuid4()), "evidence": [], "unknowns": [], "errors": [], "tool_calls": 0, "cost_usd": 0.0, "source_status": {}}

UNDERSTAND_SYS = """You restate what a career-planning assistant understood about a person, so they can check it before any analysis runs.
Write 3-5 short plain sentences in the second person ("You're a…", "You want to know…"). Cover: who they are (role/industry, or interests/strengths for a student), what their week or their options look like,
which occupation(s) the analysis will use and why (say plainly if a job has no official category and was assembled from tasks), what they want to know, and the time horizon.
No jargon, no promises, no analysis yet. Return {"summary": "..."}"""

def understand(state: State) -> dict:
    p = state["profile"]; tg = state["targets"]
    occ_lines = [f"- {t['persona']['title']} ({'composite of ' + str(len(t['persona'].get('tasks', []))) + ' tasks from ' + ', '.join(t['persona'].get('source_occupations', [])[:4]) if t['persona'].get('composite') else 'official occupation ' + t['persona']['soc']}), role: {t['role']}" for t in tg]
    user = (f"Door: {p.get('door')}\nRole/title: {p.get('role_title')}\nWeek: {p.get('week_description')}\nIndustry: {p.get('industry')}\nInterests: {p.get('interests')}\nStrengths: {p.get('strengths')}\nConstraints: {p.get('constraints')}\n"
            f"Concerns: {[CONCERN_LABEL.get(c, c) for c in p.get('concerns', [])]}\nHorizon: {HORIZON_LABEL.get(str(p.get('horizon')), p.get('horizon'))}\nQuestion: {p.get('question')}\nOccupations:\n" + "\n".join(occ_lines))
    try: out, cost = llm.chat_json("planner", UNDERSTAND_SYS, user, max_tokens=400); summary = out.get("summary", "")
    except Exception as e: summary, cost = f"(could not write a summary: {e})", 0.0
    _say("Wrote back what I understood — waiting for you to confirm.")
    return {"profile": {**p, "summary": summary}, "cost_usd": cost}

def understanding_gate(state: State) -> dict:
    """⏸ Gate 1. Resume: {"action": "confirm"|"edit"|"reject", "profile": {...partial}, "targets": [...] (optional)}."""
    d = interrupt({"kind": "understanding", "profile": state["profile"], "targets": state["targets"]})
    action = d.get("action", "confirm"); prof = {**state["profile"], **(d.get("profile") or {})}; targets = d.get("targets") or state["targets"]
    return {"profile": prof, "targets": targets, "approvals": {**state.get("approvals", {}), "understanding": {"action": action, "at": time.time(), "edited": action == "edit"}}}

def after_understanding(state: State) -> str: return "end" if state["approvals"]["understanding"]["action"] == "reject" else "gather"

# ───────────────────────────── gathering (fan-out per occupation × family) ─────────────────────────────
def fan_out(state: State) -> list[Send]:
    sends = [Send("gather_forecasts", {"horizon": str(state["profile"].get("horizon", "2030"))}), Send("gather_research", {})]
    for t in state["targets"]: sends += [Send("gather_outlook", {"persona": t["persona"]}), Send("gather_exposure", {"persona": t["persona"]})]
    return sends

def gather_outlook(inp: dict) -> dict:
    p = inp["persona"]; res = [("BLS", _call("BLS", outlook_tool.outlook_cards, p))]
    if not p.get("composite"): res.append(("O*NET Web Services", _call("O*NET Web Services", onet_ws.onet_occupation, p.get("onet_soc") or f"{p['soc']}.00")))
    _say(f"Employment outlook for {p['title']}: " + ("found BLS 2025–35 projections" if res[0][1].cards else "no official projection — will say so"))
    return _collect(res, _occ_key(p), len(res))

def gather_exposure(inp: dict) -> dict:
    p = inp["persona"]
    if p.get("composite"):
        res = [("O*NET tasks", composite.task_cards(p)), ("Anthropic Economic Index", composite.no_official_stats("Anthropic Economic Index", p)), ("AIOE", composite.no_official_stats("AIOE", p))]
    else:
        res = [("O*NET tasks", _call("O*NET tasks", exposure.onet_task_diff, p.get("onet_soc") or p["soc"])), ("Anthropic Economic Index", _call("Anthropic Economic Index", exposure.anthropic_index, p["soc"])), ("AIOE", _call("AIOE", exposure.aioe_lookup, p["soc"]))]
    _say(f"Checked which of {p['title']}'s {len(res[0][1].cards)} tasks AI is already used for")
    return _collect(res, _occ_key(p), 3)

RELEVANCE_SYS = """You filter prediction-market search results for a research tool. Keep a market ONLY if all hold:
1. It resolves on the anchor event actually happening in the world at societal scale — not on what a company/person will *say*, *claim*, *hint*, or *announce*; not one individual's personal project; not a joke, meta, or self-referential market.
2. Its subject matches the anchor topic specifically. 3. Its time frame is compatible with the anchor's horizon (within a few years either side).
Exception — PROXY: a market that resolves on a leading lab/government *declaring* the event may be kept as a proxy; list it under "proxy".
When in doubt, drop it. Return {"decisions":[{"i":market_index,"verdict":"keep|proxy|drop","why":"<10 words"}]}"""

def gather_forecasts(inp: dict) -> dict:
    h = _year(inp.get("horizon")); calls = 0; cost_total = 0.0; cards, unknowns, errors, status = [], [], [], {}
    fn = {"polymarket": polymarket.polymarket_search, "manifold": manifold.manifold_search, "metaculus": metaculus.metaculus_search}
    for a in ANCHORS:
        topic = a["topic"].format(horizon=h); got = []
        if not a["platforms"]: unknowns.append(f"{a['id']}: no forecasting platform has a market on “{topic}”"); continue
        for plat in a["platforms"]:
            r = _call(plat.capitalize(), fn[plat], a["queries"][plat].format(horizon=h), 4); calls += 1
            status[r.source] = "unavailable" if not r.ok else ("ok" if r.cards else status.get(r.source, "partial"))
            if not r.ok: errors.append(f"{r.source}: {r.error}")
            got += r.cards
        if not got: unknowns.append(f"{a['id']}: no open market found for “{topic}”"); continue
        try:
            out, cost = llm.chat_json("planner", RELEVANCE_SYS, f"Anchor topic: {topic}\nMarkets:\n" + "\n".join(f"{i}. {c.claim}" for i, c in enumerate(got)), max_tokens=600, temperature=0.0); cost_total += cost
            dec = out.get("decisions", []); keep = {int(d["i"]) for d in dec if d.get("verdict") == "keep"}; proxy = {int(d["i"]) for d in dec if d.get("verdict") == "proxy"} - keep
        except Exception as e: keep, proxy = set(range(len(got))), set(); errors.append(f"relevance filter failed for {a['id']}: {e}")
        for i, c in enumerate(got):
            if i in keep or i in proxy:
                c.subq_id = a["id"]; c.notes = (c.notes + f" | anchor {a['id']}: {topic}").strip(" |")
                if i in proxy: c.claim = "PROXY (resolves on an announcement, not the event) — " + c.claim; c.confidence = min(c.confidence, 0.45)
                cards.append(c)
        if not (keep or proxy): unknowns.append(f"{a['id']}: markets exist but none are about “{topic}”")
    _say(f"Read what forecasters expect about AI progress: {len(cards)} relevant markets")
    return {"evidence": cards, "unknowns": unknowns, "errors": errors, "source_status": status, "tool_calls": calls, "cost_usd": cost_total}

def gather_research(inp: dict) -> dict:
    res = [("Epoch AI", _call("Epoch AI", epoch.epoch_recent)), ("FRED", _call("FRED", fred.fred_series, "UNRATE"))]
    return _collect(res, None, 2)

# ───────────────────────────── reconcile (code) ─────────────────────────────
def reconcile(state: State) -> dict:
    yr = _year(state["profile"].get("horizon")); seen, cards = set(), []
    for c in state["evidence"]:
        if c.id not in seen: seen.add(c.id); cards.append(c)
    refs = {f"c{i+1:02d}": c.id for i, c in enumerate(cards)}
    refs.update({f"u{i+1:02d}": f"unknown:{u}" for i, u in enumerate(dict.fromkeys(state.get("unknowns") or []))})
    inv = {v: k for k, v in refs.items()}
    dis = []
    for a in ANCHORS:
        vals = [c for c in cards if c.subq_id == a["id"] and c.value is not None and c.unit == "probability"]
        if len({c.source for c in vals}) > 1:
            lo, hi = min(c.value for c in vals), max(c.value for c in vals)
            if hi - lo >= 0.05: dis.append({"anchor": a["id"], "topic": a["topic"].format(horizon=yr), "card_ids": [c.id for c in vals], "low": lo, "high": hi, "spread": f"{lo:.0%}–{hi:.0%}", "sources": sorted({c.source for c in vals})})
    fc = []   # conditional sentences about *pace*, cited — never per-task predictions
    for a in ANCHORS:
        vals = [c for c in cards if c.subq_id == a["id"] and c.value is not None]
        if vals:
            lo, hi = min(c.value for c in vals), max(c.value for c in vals); rng = f"{lo:.0%}" if hi - lo < 0.01 else f"{lo:.0%}–{hi:.0%}"
            fc.append(f"Forecasters currently put {rng} on “{a['topic'].format(horizon=yr)}” — if that world arrives, the shifts above would come sooner " + " ".join(f"[{inv[c.id]}]" for c in vals[:3]))
    deltas = memory.diff_snapshots(state.get("prior_snapshot"), cards)
    _say(f"Reconciled {len(cards)} pieces of evidence · {len(dis)} places where sources disagree · {len(state.get('unknowns') or [])} known unknowns")
    return {"refs": refs, "disagreements": dis, "forecast_context": fc, "deltas": deltas}

def _inv(state) -> dict: return {v: k for k, v in state["refs"].items()}

def _table(cards: list[Card], refs: dict, occ: str | None = None, max_tasks: int = 30) -> str:
    inv = {v: k for k, v in refs.items()}
    cards = [c for c in cards if c.id in inv and (occ is None or c.occ in (occ, None))]
    tasks = [c for c in cards if c.unit == "penetration"]
    if len(tasks) > max_tasks:
        top = sorted([t for t in tasks if t.value], key=lambda c: -c.value)[:max_tasks - 10]; zero = [t for t in tasks if not t.value][:10]; keep = {c.id for c in top + zero}
        cards = [c for c in cards if c.unit != "penetration" or c.id in keep]
    unk = "\n".join(f"[{k}] UNKNOWN — {v[len('unknown:'):]}" for k, v in refs.items() if k.startswith("u"))
    return (unk + "\n" if unk else "") + "\n".join(f"[{inv[c.id]}] ({c.source}, {c.as_of or 'n.d.'}) {c.claim}" + (f" — value {c.value:g} {c.unit}" if c.value is not None else "") for c in cards)

# ───────────────────────────── outlook + work change (code first, model only for interpretation) ─────────────────────────────
def _reading_demand(cards):
    g = next((c for c in cards if c.id.endswith(":growth") and c.confidence >= 0.9), None)
    if not g: return "unknown"
    return "growing" if g.value >= 5.0 else "declining" if g.value < 0 else "stable"   # any projected loss is 'declining'; national average is +3.5%

def _reading_change(tasks):
    if not tasks: return "unknown", 0.0
    share = sum(1 for t in tasks if (t.value or 0) >= 0.6) / len(tasks)
    return ("substantial" if share >= 0.4 else "moderate" if share >= 0.2 else "limited"), share

OUTLOOK_SYS = """You write 2-3 one-line interpretations of one occupation's AI outlook for a non-expert. You are given the official employment projection facts (already stated — do not restate numbers) and task-level evidence of where AI is already used.
Each line must (a) end with card refs [cNN], (b) then end with the tag [interpretation], (c) avoid 'automated', 'replaced', 'safe', 'doomed', 'will'. Use 'likely', 'may', 'tends to'.
Keep what the projections say (official) apart from what AI usage suggests (interpretation). Return {"lines": ["...", "..."]}"""

MORE_IMPORTANT_SYS = """You review tasks of one occupation that show little or no AI use in observed AI conversations today. For each, decide whether there is a *specific, stateable* reason the task resists delegation to AI —
accountability for a decision, judgment under ambiguity, relationships/trust, physical presence, legal or safety responsibility. Keep ONLY those, with the reason in ≤12 words. Drop tasks where low usage may just be measurement (rare, niche, or clerical).
Return {"keep":[{"i":index,"why":"..."}]}"""

def write_outlook(state: State) -> dict:
    cards, refs, inv = state["evidence"], state["refs"], _inv(state); outlooks, changes = {}, {}; cost = 0.0
    for t in state["targets"]:
        p = t["persona"]; occ = _occ_key(p); mine = [c for c in cards if c.occ == occ and c.id in inv]
        stats = [c for c in mine if c.source == "BLS"]; tasks = [c for c in mine if c.unit == "penetration"]
        demand = _reading_demand(stats); change, share = _reading_change(tasks)
        keep_kinds = ("growth", "openings", "wage") if p.get("composite") else ("growth", "change", "openings", "emp2025", "wage")   # proxies: three lines each, the rest stays in evidence
        facts = [f"{c.claim} [{inv[c.id]}]" for c in stats if c.id.split(':')[-1] in keep_kinds]
        edu = next((c for c in stats if c.id.endswith(":education")), None)
        if edu: facts.append(f"{edu.claim} [{inv[edu.id]}]")
        proxy = next((u for u in state.get("unknowns", []) if u.startswith("BLS: no employment projection exists")), None) if p.get("composite") else None
        if proxy: facts.insert(0, f"No official projection exists for this job; the figures below are for the closest official categories [{inv.get('unknown:' + proxy, '?')}]")
        if tasks: facts.append(f"{sum(1 for x in tasks if (x.value or 0) >= 0.6)} of {len(tasks)} tasks already show heavy AI use in observed AI conversations (Anthropic Economic Index) " + " ".join(f"[{inv[x.id]}]" for x in sorted(tasks, key=lambda c: -(c.value or 0))[:3]))
        try:
            out, c_ = llm.chat_json("planner", OUTLOOK_SYS, f"Occupation: {p['title']}. Demand reading from projections: {demand}. Share of tasks with heavy AI use: {share:.0%}.\nEvidence:\n{_table(mine, refs)}", max_tokens=400); cost += c_
            interp = [l for l in out.get("lines", []) if isinstance(l, str)][:3]
        except Exception: interp = []
        outlooks[occ] = {"soc": occ, "title": p["title"], "demand_reading": demand, "ai_change_reading": change, "facts": facts, "interpretation": interp, "education_entry": edu.claim.split(": ", 1)[-1] if edu else None, "proxy_note": proxy}
        changes[occ] = _work_change(occ, tasks, inv)
        _say(f"{p['title']}: demand {demand} (BLS projection) · AI-related change {change} (interpretation)")
    for occ, ch in changes.items():
        cands = ch.pop("_candidates")
        if not cands: continue
        try:
            out, c_ = llm.chat_json("planner", MORE_IMPORTANT_SYS, "Tasks with little or no observed AI use today:\n" + "\n".join(f"{i}. {x['task']} [{x['ref']}]" for i, x in enumerate(cands)), max_tokens=700); cost += c_
            picks = {int(d["i"]): d.get("why", "") for d in out.get("keep", []) if "i" in d}
        except Exception: picks = {}
        for i, x in enumerate(cands): (ch["more_important"] if i in picks else ch["uncertain"]).append({**x, "why": picks.get(i, "")})
    return {"outlooks": outlooks, "changes": changes, "cost_usd": cost}

def _work_change(occ: str, tasks: list[Card], inv: dict) -> dict:
    row = lambda c: {"card_id": c.id, "ref": inv[c.id], "task": c.claim, "penetration": c.value}
    return {"soc": occ, "ai_assists": [row(c) for c in sorted(tasks, key=lambda c: -(c.value or 0)) if (c.value or 0) >= 0.6], "more_important": [],
            "uncertain": [row(c) for c in tasks if 0.25 <= (c.value or 0) < 0.6], "_candidates": [row(c) for c in tasks if (c.value or 0) < 0.25],
            "method_note": "“AI will probably assist” = tasks that already appear in ≥60% of observed AI conversations touching this occupation's work (Anthropic Economic Index, 2025). It measures current use, not future automation. “May become more important” is our interpretation: low observed AI use *and* a stated reason the task resists delegation. Everything else is uncertain."}

# ───────────────────────────── plan (PLANNER — the only place the person enters the prose) ─────────────────────────────
PLAN_SYS = """You write a career plan for one specific person, from evidence. You get: their profile, per-occupation outlook facts and interpretations, how the work is changing (three groups), forecast context, disagreements, unknowns, and an evidence table.
HARD RULES:
- Every sentence ends with refs [cNN]/[uNN]. Interpretive or advisory sentences ALSO end with [interpretation]. No sentence without a ref.
- Keep official employment projections (facts) apart from AI-related interpretation. Never guarantee safety. Never say a job disappears or is safe. Avoid "will" about the future — use "likely", "may", "tends to".
- Never call a task automated/replaced/eliminated from a usage score. Never say low AI usage means a task "grows".
- Never invent courses, certifications, products, employers or prices. Recommend capabilities and practical experiences ("run one discovery cycle with an AI research assistant and compare it against your usual method").
- Plain English for a non-expert. Say which findings are about the occupation and which are about this person.
Return JSON:
{"direct_answer": "3-5 sentences answering EVERY stated concern in turn, by name (demand → change → learning → different path). If a concern cannot be answered from this run's evidence (e.g. 'different path' when no skill-similarity data exists), say so explicitly in one sentence rather than skipping it.",
 "outlook_takeaway": "1-2 sentences",
 "for_you": "3-5 sentences using their week/industry/interests/constraints",
 "d30": ["3-4 bullets — each ONE concrete activity this person can finish within two weeks, with a visible output: e.g. 'Run one user-research synthesis with an AI assistant and your usual method side by side; write a one-page comparison of what it missed.' Never 'explore', 'stay informed', 'consider'."],
 "m6": ["3-4 bullets — each a capability to build plus the real project or responsibility where they'd build it"], "y1": ["2-3 bullets — a position they should be in a year from now and the evidence they'd have for it"],
 "adjacent": [], "adjacent_note": "one sentence: no adjacent path is recommended because this run has no skill-similarity evidence",
 "comparison": [{"title": "...", "outlook": "...", "ai_change": "...", "education": "...", "human_edge": "...", "uncertainty": "..."}],
 "our_read": "which direction(s) this person might lean toward and the tradeoffs, cited, tagged [interpretation]",
 "confidence": {"strong": ["..."], "interpretation": ["..."], "unknown": ["..."], "disagree": ["..."]}}
comparison and our_read: students only (one comparison row per occupation, every cell cited); leave empty for professionals."""

def write_plan(state: State) -> dict:
    p = state["profile"]; refs = state["refs"]
    def occ_block(o, ch):
        g = lambda rows: "; ".join(f"{r['task'][:70]} [{r['ref']}]" for r in rows[:6]) or "none"
        return (f"### {o['title']} — demand: {o['demand_reading']} · AI change: {o['ai_change_reading']}\nFacts: " + " | ".join(o["facts"]) + "\nInterpretation: " + " | ".join(o["interpretation"]) +
                f"\nAI probably assists: {g(ch['ai_assists'])}\nMay become more important: " + ("; ".join(f"{r['task'][:60]} — {r['why']} [{r['ref']}]" for r in ch["more_important"][:6]) or "none") + f"\nUncertain: {g(ch['uncertain'])}")
    user = (f"PERSON ({p.get('door')}): role {p.get('role_title')} · industry {p.get('industry')} · week: {p.get('week_description')} · interests {p.get('interests')} · strengths {p.get('strengths')} · constraints {p.get('constraints')}\n"
            f"Concerns: {[CONCERN_LABEL.get(c, c) for c in p.get('concerns', [])]} · Horizon: {HORIZON_LABEL.get(str(p.get('horizon')), p.get('horizon'))} · Question: {p.get('question')}\n\n"
            + "\n\n".join(occ_block(state["outlooks"][k], state["changes"][k]) for k in state["outlooks"]) +
            f"\n\nForecast context (conditional, about pace of AI progress): {state.get('forecast_context')}\nDisagreements: {[d['spread'] + ' ' + d['topic'] for d in state['disagreements']]}\nUnknowns: {state.get('unknowns')}\nSources unavailable: {[k for k, v in state.get('source_status', {}).items() if v == 'unavailable']}"
            f"\n\nEvidence table:\n{_table(state['evidence'], refs)}")
    stripped = (state.get("skeptic") or {}).get("stripped", [])
    if stripped: user += "\n\nA reviewer struck these sentences last time — do not repeat them or anything like them:\n" + "\n".join(f"- {s['sentence'][:160]}" for s in stripped[:12])
    try: plan, cost = llm.chat_json("planner", PLAN_SYS, user, max_tokens=3200, temperature=0.3)
    except Exception as e: plan, cost = {"direct_answer": f"(the planner failed: {e})", "d30": [], "m6": [], "y1": [], "confidence": {}}, 0.0
    if p.get("door") != "student": plan["comparison"], plan["our_read"] = [], ""
    _say("Wrote your plan — now every line gets checked against the evidence")
    return {"plan": plan, "cost_usd": cost}

def _plan_md(state: State, plan: dict, outlooks: dict | None = None, changes: dict | None = None) -> str:
    """Markdown export, generated FROM the reviewed structured objects (never the other way round)."""
    outlooks = outlooks if outlooks is not None else state["outlooks"]; changes = changes if changes is not None else state["changes"]
    L = []; add = L.append
    add(f"# {' vs '.join(t['persona']['title'] for t in state['targets'])} · your plan"); add(plan.get("direct_answer", ""))
    add("## 1. Your outlook")
    for k, o in outlooks.items():
        add(f"### {o['title']} — demand {o['demand_reading']} (BLS projection) · AI-related change {o['ai_change_reading']} (interpretation)")
        for f in o["facts"]: add(f"- {f}")
        for i in o["interpretation"]: add(f"- {i}")
    if plan.get("outlook_takeaway"): add(f"- {plan['outlook_takeaway']}")
    add("## 2. How the work may change")
    for k, ch in changes.items():
        add(f"### {outlooks[k]['title']}")
        add("**AI will probably assist with these tasks**"); [add(f"- {r['task']} (observed AI use {r['penetration']:.2f}) [{r['ref']}]") for r in ch["ai_assists"][:8]]
        add("**These responsibilities may become more important**"); [add(f"- {r['task']} — {r['why']} [{r['ref']}] [interpretation]") for r in ch["more_important"][:8]]
        add("**These areas remain uncertain**"); [add(f"- {r['task']} [{r['ref']}]") for r in ch["uncertain"][:6]]
        add(f"_{ch['method_note']}_")
    if plan.get("comparison"):
        add("## Comparing your options")
        for row in plan["comparison"]: add(f"- **{row.get('title')}** — outlook: {row.get('outlook')} · AI change: {row.get('ai_change')} · education: {row.get('education')} · human edge: {row.get('human_edge')} · uncertainty: {row.get('uncertainty')}")
        if plan.get("our_read"): add(f"- Our read: {plan['our_read']}")
    add("## 3. What this means for you"); add(plan.get("for_you", ""))
    add("## 4. Your preparation plan")
    for label, key in (("Next 30 days", "d30"), ("Next six months", "m6"), ("Next year", "y1")):
        add(f"**{label}**"); [add(f"- {b}" + ("" if re.search(r"\[[cu]\d{2,3}\]|\[interpretation\]", b) else " [advice]")) for b in plan.get(key, [])]
    add("## 5. Other paths to consider"); [add(f"- **{a.get('title')}** — {a.get('why_fit')} · transferable: {a.get('transferable')} · prep: {a.get('prep')} · outlook: {a.get('outlook')} · tradeoff: {a.get('tradeoff')}") for a in plan.get("adjacent", [])]
    if not plan.get("adjacent"): add(f"_{plan.get('adjacent_note') or 'Not enough evidence in this run to recommend a change of path.'}_")
    add("## 6. Confidence and uncertainty")
    for label, key in (("The evidence strongly supports", "strong"), ("Our informed interpretation", "interpretation"), ("Cannot be known now", "unknown"), ("Sources disagree or are missing", "disagree")):
        add(f"**{label}**"); [add(f"- {b}") for b in (plan.get("confidence") or {}).get(key, [])]
    for fcx in state.get("forecast_context", [])[:3]: add(f"- {fcx} [interpretation]")
    return "\n".join(x for x in L if x)

# ───────────────────────────── skeptic (SKEPTIC model — different family) ─────────────────────────────
SKEPTIC_SYS = """You are a hostile fact-checker for a career plan built from evidence cards. You get numbered lines, each with the cards it cites. Lines tagged [interpretation] are advisory/interpretive; hold them to a lower bar.
STRIP if: a number is not on a cited card or is misquoted; a card about X is used for a claim about Y; a usage/penetration score is turned into "automated / replaced / eliminated / disappears / safe"; the line guarantees an outcome ("will", "safe", "doomed"); it names a course, certification, product or employer no card mentions.
KEEP otherwise. For [interpretation] lines, KEEP if the cited cards make the reading reasonable, even if unproven. For conditional lines ("if AI progress is faster…"), judge only the consequence, not the premise.
Return {"verdicts":[{"i":0,"verdict":"keep|strip","reason":"..."}]}"""

def _reviewable(state: State) -> dict:
    """The exact objects the UI renders. Task statements themselves are verbatim cards (skipped); the model-written 'why' lines are reviewed."""
    import copy
    return {"plan": copy.deepcopy(state["plan"]),
            "outlooks": {k: {"facts": list(o["facts"]), "interpretation": list(o["interpretation"])} for k, o in state["outlooks"].items()},
            "changes": {k: {"more_important": [{"task": r["task"], "ref": r["ref"], "why": r.get("why", ""), "card_id": r["card_id"], "penetration": r.get("penetration")} for r in ch["more_important"]]} for k, ch in state["changes"].items()}}

def skeptic(state: State) -> dict:
    """Reviews the structured objects line by line; removes failing leaves; records status. Failure of the reviewer model is loud, never silent."""
    from . import review as rv
    refs, cards = state["refs"], {c.id: c for c in state["evidence"]}; attempt = (state.get("skeptic") or {}).get("attempt", 0) + 1
    obj = _reviewable(state); leaves = rv.flatten(obj)
    # 'why' reasons in more_important have their card on the row, not inline — give them the row's ref for the check
    leaves = [(p, (t + f" [{_leaf_ref(obj, p)}] [interpretation]" if p.endswith(".why") else t)) for p, t in leaves]
    removed, to_check, kept_paths = [], [], []
    for p, t in leaves:
        kind = rv.classify(t, refs)
        if rv.certainty_violation(t): removed.append({"path": p, "sentence": t, "reason": "certainty about the future (lint)"}); continue
        if kind in ("heading", "unknown_only", "advice"): kept_paths.append(p); continue
        if kind == "uncited": removed.append({"path": p, "sentence": t, "reason": "no evidence ref" + (" (contains a number)" if re.search(r"\d", t) else "")}); continue
        to_check.append((p, t, [r for r in rv.REF.findall(t) if r in refs]))
    verdicts, cost, status = {}, 0.0, "verified"
    if to_check:
        listing = "\n\n".join(f"{i}. {t}\n   cards: " + " | ".join(f"[{r}] {cards[refs[r]].claim} (value {cards[refs[r]].value} {cards[refs[r]].unit})" for r in cited if refs[r] in cards) for i, (p, t, cited) in enumerate(to_check))
        try:
            text, cost = llm.chat("skeptic", SKEPTIC_SYS + "\nRespond with valid JSON only.", listing, max_tokens=14000, temperature=0.0)
            try: verdicts = {int(v["i"]): v for v in json.loads(re.search(r"\{.*\}", text, flags=re.S).group(0)).get("verdicts", []) if "i" in v}
            except Exception:
                verdicts = {int(i): {"verdict": v, "reason": (r or "")[:200]} for i, v, r in re.findall(r'"i"\s*:\s*(\d+)\s*,\s*"verdict"\s*:\s*"(keep|strip)"(?:\s*,\s*"reason"\s*:\s*"([^"]*))?', text)}
                if not verdicts: raise ValueError("no verdicts parseable")
        except Exception as e:
            status = "unverified"; _say(f"⚠ Reviewer model failed ({type(e).__name__}) — cards were checked for citations only, NOT for accuracy")
    for i, (p, t, _) in enumerate(to_check):
        v = verdicts.get(i, {"verdict": "keep", "reason": "cited; reviewer did not object" if status == "verified" else "UNVERIFIED — reviewer unavailable"})
        if v.get("verdict") == "strip": removed.append({"path": p, "sentence": t, "reason": v.get("reason", "")})
        else: kept_paths.append(p)
    rv.apply_removals(obj, [r["path"] for r in removed])
    total = len(to_check) + sum(1 for r in removed if r["reason"].startswith("no evidence ref")); ratio = len(removed) / total if total else 0.0
    escalated = ratio > UNCITED_LIMIT and attempt >= 2
    _say(f"Reviewed {total} lines: {len(removed)} removed" + (" — rewriting once" if ratio > UNCITED_LIMIT and not escalated and status == "verified" else ""))
    return {"skeptic": {"stripped": removed, "kept": len(kept_paths), "total": total, "ratio": round(ratio, 3), "attempt": attempt, "escalated": escalated, "status": status, "model": llm.model_name("skeptic")},
            "reviewed": obj if (ratio <= UNCITED_LIMIT or escalated or status == "unverified") else None, "cost_usd": cost}

def _leaf_ref(obj: dict, path: str) -> str:
    from .review import _resolve
    parent, _ = _resolve(obj, path); return parent.get("ref", "?")

def after_skeptic(state: State) -> str:
    sk = state["skeptic"]
    if sk.get("status") == "unverified": return "render"          # loud failure path: show it, don't loop on a reviewer that isn't there
    return "render" if (sk["ratio"] <= UNCITED_LIMIT or sk["escalated"] or state.get("cost_usd", 0) > MAX_COST_USD) else "rewrite"

# ───────────────────────────── render → ⏸ plan gate → record ─────────────────────────────
def render(state: State) -> dict:
    cards, inv, sk = state["evidence"], _inv(state), state["skeptic"]; rv = state["reviewed"]
    # reviewed objects → the only things the UI shows
    outlooks = {k: {**o, "facts": rv["outlooks"][k]["facts"], "interpretation": rv["outlooks"][k]["interpretation"]} for k, o in state["outlooks"].items()}
    changes = {k: {**ch, "more_important": rv["changes"][k]["more_important"]} for k, ch in state["changes"].items()}
    plan = rv["plan"]
    unavailable = [k for k, v in state.get("source_status", {}).items() if v == "unavailable"]
    badges = ([f"Partial evidence — unavailable: {', '.join(unavailable)}"] if unavailable else []) + ([f"{'Citation check' if sk.get('status') == 'unverified' else 'Checked'} — {len(sk['stripped'])} line(s) removed for lacking support"] if sk.get("stripped") else ([] if sk.get("status") == "unverified" else ["Checked — 0 lines removed"])) + (["⚠ The reviewer could not verify much of the draft after two attempts — read with care"] if sk.get("escalated") else [])
    if sk.get("status") == "unverified": badges.insert(0, "⚠ UNVERIFIED — our independent review step failed, so this plan was checked for citations only, not for accuracy. Treat it as a draft.")
    md = _plan_md(state, plan, outlooks, changes)
    footer = "\n\n---\n### Evidence\n" + "\n".join(f"- [{inv[c.id]}] {c.claim} — {c.source}{', ' + c.as_of if c.as_of else ''}{' · ' + c.url if c.url else ''}" for c in cards if c.id in inv)
    views = {"badges": badges, "review_status": sk.get("status", "verified"), "outlooks": outlooks, "changes": changes, "plan": plan, "disagreements": state["disagreements"], "forecast_context": state.get("forecast_context", []),
             "unknowns": state.get("unknowns", []), "deltas": state.get("deltas", []), "source_status": state.get("source_status", {}), "skeptic": sk, "refs": state["refs"],
             "cards_by_family": {f: [c.model_dump() for c in cards if c.family == f] for f in ("statistics", "exposure", "forecasts", "research")}, "budget": {"tool_calls": state.get("tool_calls", 0), "cost_usd": round(state.get("cost_usd", 0), 4)}}
    return {"views": views, "plan": plan, "outlooks": outlooks, "changes": changes, "plan_md": md + footer}

def plan_gate(state: State) -> dict:
    """⏸ Gate 2. Resume: {"action": "approve"|"edit"|"reject", "plan_md": str (if edit)}."""
    d = interrupt({"kind": "plan", "plan_md": state["plan_md"], "views": state["views"]})
    action = d.get("action", "approve"); md = d.get("plan_md") if action == "edit" and d.get("plan_md") else state["plan_md"]
    return {"plan_md": md, "approvals": {**state.get("approvals", {}), "plan": {"action": action, "at": time.time(), "edited": action == "edit"}}}

def after_plan(state: State) -> str: return "record" if state["approvals"]["plan"]["action"] in ("approve", "edit") else "end"

def record(state: State) -> dict:
    """The ONLY node that writes: plan file + snapshot + profile."""
    p = state["targets"][0]["persona"]; out_dir = ROOT / "data" / "briefs"; out_dir.mkdir(parents=True, exist_ok=True)
    tag = "_UNVERIFIED" if (state.get("skeptic") or {}).get("status") == "unverified" else ""
    path = out_dir / f"{re.sub(r'[^A-Za-z0-9.-]+', '_', p['soc'])}_{state['profile'].get('horizon', 'h')}_{time.strftime('%Y%m%d-%H%M%S')}{tag}.md"; path.write_text(state["plan_md"])
    sid = memory.save_snapshot(state["thread_id"], p["soc"], str(state["profile"].get("horizon", "2030")), state["evidence"], {"plan": state["plan"], "profile": {k: v for k, v in state["profile"].items() if k != "summary"}, "review_status": (state.get("skeptic") or {}).get("status")}, p)
    memory.save_profile(last_profile={k: v for k, v in state["profile"].items() if k != "summary"}, last_soc=p["soc"])
    _say(f"Saved your plan ({path.name}) and a snapshot so next time we can show what changed")
    return {"exported_path": str(path)}
