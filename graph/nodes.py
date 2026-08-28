"""Graph nodes. Rule of the house: models write prose and judgments; numbers, buckets and probabilities come from code over Cards.
Every sentence a model writes must cite a [cNN] ref; the skeptic (different model) strips what it can't verify."""
from __future__ import annotations
import json, re, time, uuid
from pathlib import Path
from langgraph.types import interrupt, Send
from langgraph.config import get_stream_writer
from tools.schema import Card, SourceResult
from tools import polymarket, manifold, metaculus, exposure, bls, fred, epoch, onet_ws
from . import llm, memory
from .state import State

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "data" / "anchor_questions.json").read_text())
ANCHORS, SCENARIOS = CFG["anchors"], CFG["scenarios"]
MAX_TOOL_CALLS, MAX_COST_USD, UNCITED_LIMIT = 25, 1.00, 0.30
FAMILIES = ["forecasts", "exposure", "statistics", "research"]

def _say(text: str):
    """'Agent thinks in public' — custom stream events the UI renders live. No-op outside a graph run."""
    try: get_stream_writer()({"say": text, "t": time.time()})
    except Exception: pass

# ───────────────────────────── memory ─────────────────────────────
def load_memory(state: State) -> dict:
    p = state["persona"]; prior = memory.load_latest(p["soc"], p["horizon"])
    _say(f"Checked memory for {p['title']} / {p['horizon']}: " + ("found a previous run to diff against." if prior else "first run for this occupation."))
    memory.save_profile(last_soc=p["soc"], last_title=p["title"], last_horizon=p["horizon"], door=state.get("door", "professional"))
    return {"prior_snapshot": prior, "thread_id": state.get("thread_id") or str(uuid.uuid4()), "evidence": [], "unknowns": [], "errors": [], "tool_calls": 0, "cost_usd": 0.0, "source_status": {}}

# ───────────────────────────── decompose (PLANNER) ─────────────────────────────
DECOMPOSE_SYS = """You are the planner for an evidence-first career-futures assistant. Break the user's question into 4-6 measurable sub-questions.
Each sub-question must be answerable by exactly one evidence family:
- forecasts: prediction-market / forecasting-platform questions about AI capability, regulation, adoption, unemployment
- exposure: how much of this occupation's tasks current AI already touches (AIOE score, Anthropic Economic Index, O*NET task list)
- statistics: employment counts, wages, growth, national unemployment/productivity (BLS, FRED)
- research: recent frontier-model releases and compute trends (Epoch AI)
Cover all four families at least once. Keep each `text` under 20 words. `why` = one line on what it tells the person about their own work."""

def decompose(state: State) -> dict:
    p = state["persona"]
    user = f"Occupation: {p['title']} (SOC {p['soc']}). Horizon: {p['horizon']}. Door: {state.get('door','professional')}.\nQuestion: {state['question']}\n" \
           'Return {"subquestions":[{"id":"q1","text":"...","family":"forecasts|exposure|statistics|research","why":"..."}]}'
    try:
        out, cost = llm.chat_json("planner", DECOMPOSE_SYS, user, max_tokens=900)
        subs = [s for s in out.get("subquestions", []) if s.get("family") in FAMILIES][:6]
    except Exception as e:
        subs, cost = [], 0.0; _say(f"Planner failed to decompose ({e}); using the default sub-questions.")
    if len({s["family"] for s in subs}) < 4:   # guarantee coverage — the gatherers key off families
        have = {s["family"] for s in subs}
        defaults = {"forecasts": f"How likely is transformative AI before {p['horizon']}?", "exposure": f"Which of a {p['title']}'s tasks does AI already perform?",
                    "statistics": f"How many {p['title']} jobs exist and what do they pay?", "research": "What frontier models shipped recently?"}
        subs += [{"id": f"q{len(subs)+i+1}", "text": defaults[f], "family": f, "why": "coverage default"} for i, f in enumerate(f for f in FAMILIES if f not in have)]
    for s in subs: _say(f"Sub-question [{s['family']}]: {s['text']}")
    return {"subquestions": subs, "cost_usd": cost}

def fan_out(state: State) -> list[Send]:
    """Conditional edge after decompose: one Send per family present. Each gatherer sees only its slice (isolated context)."""
    p = state["persona"]; subs = state["subquestions"]
    return [Send(f"gather_{fam}", {"persona": p, "subquestions": [s for s in subs if s["family"] == fam], "budget": MAX_TOOL_CALLS // 4 + 2})
            for fam in FAMILIES if any(s["family"] == fam for s in subs)]

# ───────────────────────────── gatherers ─────────────────────────────
def _disabled(name: str) -> bool:
    """Failure demo: DISABLE_SOURCES="Polymarket,BLS" in the environment (or the UI toggle) makes a source report itself down."""
    import os; return name.lower() in {x.strip().lower() for x in os.environ.get("DISABLE_SOURCES", "").split(",") if x.strip()}

def _call(name: str, fn, *args) -> SourceResult:
    if _disabled(name): return SourceResult(source=name, ok=False, error="source disabled for failure demo (DISABLE_SOURCES)", unknowns=[])
    return fn(*args)

def _collect(results: list[tuple[str, SourceResult]], subq_id: str | None, calls: int) -> dict:
    """Turn SourceResults into a state update. Errors are data; a down source becomes a badge, never an exception."""
    cards, unknowns, errors, status = [], [], [], {}
    for name, r in results:
        for c in r.cards:
            if subq_id and not c.subq_id: c.subq_id = subq_id
        cards += r.cards; unknowns += r.unknowns
        if not r.ok: errors.append(f"{name}: {r.error}"); status[name] = "unavailable"
        else: status[name] = "ok" if r.cards else "partial"
    return {"evidence": cards, "unknowns": unknowns, "errors": errors, "source_status": status, "tool_calls": calls}

RELEVANCE_SYS = """You filter prediction-market search results for a research tool. Keep a market ONLY if all hold:
1. It resolves on the anchor event actually happening in the world at societal scale — not on what a company/person will *say*, *claim*, *hint*, or *announce*; not on one individual's personal project; not a joke, meta, or self-referential market.
2. Its subject matches the anchor topic specifically (AGI ≠ an AI song charting; unemployment ≠ what a Fed chair says).
3. Its time frame is compatible with the anchor's horizon (within a few years either side).
Exception — PROXY: a market that resolves on a leading lab/government *declaring or announcing* the anchor event (not the event itself) may be kept as a proxy; list it under "proxy", not "keep".
When in doubt, drop it — a missing forecast is reported honestly as 'unknown'; a wrong one is not.
Return {"decisions":[{"i":market_index,"verdict":"keep|proxy|drop","why":"<10 words"}]}"""

def gather_forecasts(inp: dict) -> dict:
    """Search 3 platforms per anchor, then a cheap model drops the word-match junk. Anchor id becomes subq_id so the reconciler can compare platforms."""
    p = inp["persona"]; h = p["horizon"]; calls = 0; total_cost = 0.0; cards, unknowns, errors, status = [], [], [], {}
    fn = {"polymarket": polymarket.polymarket_search, "manifold": manifold.manifold_search, "metaculus": metaculus.metaculus_search}
    for a in ANCHORS:
        topic = a["topic"].format(horizon=h); got = []
        for plat in a["platforms"]:
            if calls >= inp.get("budget", 8) + 6: break   # forecasts get a bigger slice: 3 platforms × 6 anchors is the main spend
            r = _call(plat.capitalize(), fn[plat], a["queries"][plat].format(horizon=h), 4); calls += 1
            src = r.source; status[src] = "unavailable" if not r.ok else ("ok" if r.cards else status.get(src, "partial"))
            if not r.ok: errors.append(f"{src}: {r.error}")
            got += r.cards
        if not a["platforms"]: unknowns.append(f"{a['id']}: no forecasting platform has a market on “{topic}”"); continue
        if not got: unknowns.append(f"{a['id']}: no open market found for “{topic}”"); continue
        try:   # relevance filter (EXTRACTOR) — one call per anchor
            listing = "\n".join(f"{i}. {c.claim}" for i, c in enumerate(got))
            out, cost = llm.chat_json("planner", RELEVANCE_SYS, f"Anchor topic: {topic}\nMarkets:\n{listing}", max_tokens=600, temperature=0.0)
            dec = out.get("decisions", []); keep = {int(d["i"]) for d in dec if d.get("verdict") == "keep"}; proxy = {int(d["i"]) for d in dec if d.get("verdict") == "proxy"} - keep; total_cost += cost
        except Exception as e:
            keep, proxy, cost = set(range(len(got))), set(), 0.0; errors.append(f"relevance filter failed for {a['id']}: {e}")
        kept = [c for i, c in enumerate(got) if i in keep or i in proxy]
        for i, c in enumerate(got):
            if i in keep or i in proxy: c.subq_id = a["id"]; c.notes = (c.notes + f" | anchor {a['id']}: {topic}").strip(" |")
            if i in proxy: c.claim = "PROXY (resolves on an announcement, not the event) — " + c.claim; c.confidence = min(c.confidence, 0.45)
        _say(f"Forecasts {a['id']}: {len(got)} markets found, {len(kept)} actually about “{topic[:60]}”")
        if not kept: unknowns.append(f"{a['id']}: markets exist but none are about “{topic}”")
        cards += kept
    # if no platform gave a *value* for A1, say so explicitly — the AGI branch will show 'no forecast'
    if not any(c.subq_id == "A1" and c.value is not None for c in cards): unknowns.append(f"A1: no platform gives a usable probability for AGI by {h}")
    return {"evidence": cards, "unknowns": unknowns, "errors": errors, "source_status": status, "tool_calls": calls, "cost_usd": total_cost}

def gather_exposure(inp: dict) -> dict:
    p = inp["persona"]; soc = p["soc"]; onet = p.get("onet_soc") or f"{soc}.00"
    res = [("AIOE", _call("AIOE", exposure.aioe_lookup, soc)), ("Anthropic Economic Index", _call("Anthropic Economic Index", exposure.anthropic_index, soc)), ("O*NET tasks", _call("O*NET tasks", exposure.onet_task_diff, soc)), ("O*NET Web Services", _call("O*NET Web Services", onet_ws.onet_occupation, onet))]
    _say(f"Exposure: {sum(len(r.cards) for _, r in res)} cards (scores + {len(res[2][1].cards)} tasks) for {p['title']}")
    return _collect(res, inp["subquestions"][0]["id"] if inp["subquestions"] else None, 4)

def gather_stats(inp: dict) -> dict:
    p = inp["persona"]
    res = [("BLS", _call("BLS", bls.bls_occupation, p["soc"])), ("FRED", _call("FRED", fred.fred_series, "UNRATE")), ("FRED", _call("FRED", fred.fred_series, "OPHNFB"))]
    _say(f"Statistics: BLS {'ok' if res[0][1].ok else 'unavailable'}, FRED {'ok' if res[1][1].ok else 'unavailable'}")
    return _collect(res, inp["subquestions"][0]["id"] if inp["subquestions"] else None, 3)

def gather_research(inp: dict) -> dict:
    res = [("Epoch AI", _call("Epoch AI", epoch.epoch_recent))]
    _say(f"Research: {len(res[0][1].cards)} Epoch cards")
    return _collect(res, inp["subquestions"][0]["id"] if inp["subquestions"] else None, 1)

# ───────────────────────────── reconcile (code + one PLANNER call for the assumptions) ─────────────────────────────
ASSUMPTIONS_SYS = """You write the assumptions a career-futures agent is about to make, so a person can check and edit them before scenarios are built.
Write 4-6 one-line claims. Each must cite a card ref like [c03] from the evidence table. Only state what the cards say; if a number is missing say so.
Return {"claims":["...", ...]}"""

def reconcile(state: State) -> dict:
    cards: list[Card] = state["evidence"]
    seen, deduped = set(), []
    for c in cards:
        if c.id in seen: continue
        seen.add(c.id); deduped.append(c)
    refs = {f"c{i+1:02d}": c.id for i, c in enumerate(deduped)}
    refs.update({f"u{i+1:02d}": f"unknown:{u}" for i, u in enumerate(dict.fromkeys(state.get("unknowns") or []))})   # unknowns are citable too: "[u01] no market exists for …"
    by_id = {c.id: c for c in deduped}
    # disagreements: same anchor, probability values, spread > 10 points — shown, never averaged
    disagreements = []
    for a in ANCHORS:
        vals = [(c.id, c.value, c.source) for c in deduped if c.subq_id == a["id"] and c.value is not None and c.unit == "probability"]
        if len(vals) >= 2:
            lo, hi = min(v for _, v, _ in vals), max(v for _, v, _ in vals)
            if len({s for *_, s in vals}) > 1 and hi - lo >= 0.05:   # needs ≥2 platforms; one platform's different thresholds is not a disagreement
                disagreements.append({"topic": a["topic"].format(horizon=state["persona"]["horizon"]), "anchor": a["id"], "card_ids": [i for i, *_ in vals],
                                      "low": lo, "high": hi, "spread": f"{lo:.0%}–{hi:.0%}", "sources": sorted({s for *_, s in vals})})
    # exposure disagreement: AIOE percentile vs Anthropic observed exposure pointing different ways is worth surfacing as text, handled in render
    a1 = [c for c in deduped if c.subq_id == "A1" and c.value is not None]
    anchor_q = a1[0].claim if a1 else f"No open market gives a probability for AGI by {state['persona']['horizon']}"
    user = f"Person: {state['persona']['title']} (SOC {state['persona']['soc']}), horizon {state['persona']['horizon']}. Question: {state['question']}\n\nEvidence table:\n{_table(deduped, refs)}\n\nUnknowns: {state.get('unknowns')}"
    try:
        out, cost = llm.chat_json("planner", ASSUMPTIONS_SYS, user, max_tokens=700); claims = [c for c in out.get("claims", []) if isinstance(c, str)][:6]
    except Exception as e:
        claims, cost = [f"(planner unavailable: {e})"], 0.0
    wv = {"soc": state["persona"]["soc"], "title": state["persona"]["title"], "horizon": state["persona"]["horizon"], "anchor_question": anchor_q,
          "anchor_card_ids": [c.id for c in a1], "scenario_names": [s["name"] for s in SCENARIOS], "claims": claims, "edited": False}
    deltas = memory.diff_snapshots(state.get("prior_snapshot"), deduped)
    _say(f"Reconciled {len(deduped)} cards · {len(disagreements)} disagreements · {len(state.get('unknowns') or [])} unknowns · {len(deltas)} changes since last run")
    # replace evidence with the deduped list: return the *difference*? No — reducer is add-only, so we keep evidence as-is and rely on refs (ids are unique per card).
    return {"refs": refs, "disagreements": disagreements, "worldview": wv, "deltas": deltas, "cost_usd": cost}

def _table(cards: list[Card], refs: dict, max_tasks: int = 30) -> str:
    """Evidence table for the models. Occupations with 100+ O*NET tasks would swamp the prompt: keep every non-task card, the top-20 tasks by penetration
    and 10 unobserved tasks (the 'stays human' evidence). All cards remain citable and appear in the brief's evidence footer."""
    inv = {v: k for k, v in refs.items()}
    tasks = [c for c in cards if c.unit == "penetration"]
    if len(tasks) > max_tasks:
        top = sorted([t for t in tasks if t.value], key=lambda c: -c.value)[:max_tasks - 10]; zero = [t for t in tasks if not t.value][:10]
        keep = {c.id for c in top + zero}; cards = [c for c in cards if c.unit != "penetration" or c.id in keep]
    unk = "\n".join(f"[{k}] UNKNOWN — {v[len('unknown:'):]}" for k, v in refs.items() if k.startswith("u"))
    return (unk + "\n" if unk else "") + "\n".join(f"[{inv[c.id]}] ({c.source}, {c.as_of or 'n.d.'}) {c.claim}" + (f" — value {c.value:g} {c.unit}" if c.value is not None else " — value unknown") + (f"; {c.spread}" if c.spread else "")
                     for c in cards if c.id in inv)

# ───────────────────────────── interrupt 1 ─────────────────────────────
def worldview_gate(state: State) -> dict:
    """Stops the run and shows the assumptions. Resume payload: {"action": "approve"|"edit"|"reject", "worldview": {...}}."""
    decision = interrupt({"kind": "worldview", "worldview": state["worldview"], "disagreements": state["disagreements"], "unknowns": state.get("unknowns", []),
                          "source_status": state.get("source_status", {}), "deltas": state.get("deltas", [])})
    action = decision.get("action", "approve"); wv = {**state["worldview"], **(decision.get("worldview") or {})}
    wv["edited"] = action == "edit"
    persona = {**state["persona"], "horizon": int(wv.get("horizon", state["persona"]["horizon"]))}
    return {"worldview": wv, "persona": persona, "approvals": {**state.get("approvals", {}), "worldview": {"action": action, "at": time.time(), "edits": decision.get("worldview") if action == "edit" else None}}}

def after_worldview(state: State) -> str: return "end" if state["approvals"]["worldview"]["action"] == "reject" else "build"

# ───────────────────────────── build scenarios (code for numbers, PLANNER for prose) ─────────────────────────────
def _range_for(anchor_id: str | None, cards: list[Card]):
    vals = [c for c in cards if anchor_id and c.subq_id == anchor_id and c.value is not None and c.unit == "probability"]
    if not vals: return None, None, [], "no forecast exists on any platform — probability not estimated"
    lo, hi = min(c.value for c in vals), max(c.value for c in vals)
    return lo, hi, [c.id for c in vals], f"min–max across {len(vals)} market(s) on {', '.join(sorted({c.source for c in vals}))}; never averaged"

UNIT_GUIDE = """Meaning of card units — use these words, not stronger ones:
- penetration (0-1): the share of observed AI conversations (Anthropic Economic Index) that touch this task TODAY. 0.9 means 'AI is already heavily used for this task', NOT 'this task is automated' or 'this job disappears'. Never write 'fully automated', 'replaced', 'eliminated' from a penetration value.
- score (AIOE): relative exposure of the occupation's abilities to AI language models; higher = more exposed. It is not a probability of job loss.
- share (observed exposure): fraction of the occupation's tasks with observed AI usage.
- probability: a market price or forecast for the stated question only — do not transfer it to a different question.
- jobs / usd: BLS employment count and median wage for the year stated."""

SCENARIO_SYS = UNIT_GUIDE + """\nYou write scenario narratives for one person's occupation. You are given four FIXED scenario names, their probability ranges (already computed from forecast cards — do not change or invent numbers),
and an evidence table. For each scenario write:
- assumptions: 2-3 short lines on what must be true in this world (cite refs like [c04] where a card supports it)
- for_you: 3-5 sentences on what this world means for this specific occupation — which kinds of tasks change, what stays human. EVERY sentence must end with at least one [cNN] ref that supports it. If no card supports a sentence, do not write it.
Never give a verdict ("you'll be fine"/"you're doomed"). Never state a number that isn't on a card.
Return {"scenarios":[{"name":"...","assumptions":["..."],"for_you":"..."}]}"""

def build_scenarios(state: State) -> dict:
    cards = state["evidence"]; refs = state["refs"]; wv = state["worldview"]; attempt = (state.get("skeptic") or {}).get("attempt", 0)
    scen = []
    for s in SCENARIOS:
        lo, hi, ids, note = _range_for(s.get("anchor"), cards)
        scen.append({"name": s["name"], "color": s["color"], "gist": s["gist"], "prob_low": lo, "prob_high": hi, "prob_card_ids": ids, "prob_note": note, "multiplier": s["task_multiplier"]})
    slow = next(x for x in scen if x["name"] == "Slow diffusion")
    slow["prob_note"] = "the 'none of the above' world — no market prices it directly, and the other branches' questions are not mutually exclusive, so no residual is computed"
    stripped = (state.get("skeptic") or {}).get("stripped", []) if attempt else []
    user = (f"Person: {wv['title']} (SOC {wv['soc']}), horizon {wv['horizon']}. Question: {state['question']}\n"
            f"Human-approved assumptions: {wv.get('claims')}\n\nScenarios and fixed probability ranges:\n" +
            "\n".join(f"- {x['name']}: {_fmt_range(x)} — {x['gist']}" for x in scen) + f"\n\nEvidence table:\n{_table(cards, refs)}" +
            (f"\n\nA reviewer struck these sentences last time for lacking support — do not repeat them or anything like them:\n" + "\n".join(f"- {s['sentence']}" for s in stripped[:12]) if stripped else ""))
    try:
        out, cost = llm.chat_json("planner", SCENARIO_SYS, user, max_tokens=2200, temperature=0.3)
        prose = {x.get("name"): x for x in out.get("scenarios", [])}
    except Exception as e:
        prose, cost = {}, 0.0; _say(f"Scenario builder failed: {e}")
    for x in scen:
        pr = prose.get(x["name"], {}); x["assumptions"] = pr.get("assumptions", []); x["for_you"] = pr.get("for_you", "")
        x["evidence_refs"] = sorted(set(re.findall(r"\[([cu]\d{2})\]", x["for_you"] + " ".join(x["assumptions"]))))
    task_diff = _task_diff(cards, scen)
    _say(f"Built {len(scen)} scenarios" + (" (rebuild after skeptic)" if attempt else "") + f"; task-diff over {len(task_diff.get('_tasks', []))} tasks")
    return {"scenarios": scen, "task_diff": task_diff, "cost_usd": cost}

def _fmt_range(x: dict) -> str: return "no forecast" if x["prob_low"] is None else f"{x['prob_low']:.0%}–{x['prob_high']:.0%}"

def _task_diff(cards: list[Card], scen: list[dict]) -> dict:
    """Pure code. penetration (share of observed AI use touching the task, 0-1) × branch multiplier → bucket. Every entry keeps its card id."""
    tasks = [c for c in cards if c.unit == "penetration"]
    out = {"_tasks": [c.id for c in tasks], "_rule": "eff = penetration × branch multiplier; ≥0.60 disappears (AI does it), 0.25–0.60 supervised (AI drafts, human directs), <0.25 or unobserved grows (stays human, gains share)"}
    for x in scen:
        b = {"disappears": [], "supervised": [], "grows": []}
        for c in tasks:
            eff = (c.value or 0.0) * x["multiplier"]; row = {"card_id": c.id, "task": c.claim, "penetration": c.value, "eff": round(eff, 3)}
            (b["disappears"] if eff >= 0.60 else b["supervised"] if eff >= 0.25 else b["grows"]).append(row)
        out[x["name"]] = b
    return out

# ───────────────────────────── brief writer (PLANNER, cite-or-omit) ─────────────────────────────
BRIEF_SYS = UNIT_GUIDE + """
You write a short markdown brief for one person about their occupation's AI future.
FORMAT: `## ` headings, then bullets. ONE claim per bullet, one sentence, ending with the refs that support it, e.g. `- Market research is already the task AI touches most in this job (penetration 0.92) [c10].` No paragraphs, no multi-sentence bullets.
Sections in this order: (1) What changes for you — the task view first; (2) Which worlds we might be in — one bullet per scenario, stating its probability range only if given, then what that world means for these tasks; (3) Where sources disagree; (4) What we don't know — cite [uNN] refs; (5) What to lean into — tasks that stay human in every scenario and the technology skills listed for the occupation.
CITATION RULES: a claim about a task cites that task's card; a probability cites the market card; a claim about exposure cites the score card. Never cite a forecast card to support a claim about tasks. A scenario bullet may reason conditionally ("In an AGI world, the tasks AI already touches most — market research [c10] — would likely be run by AI with you directing") but every task it names carries its card.
NEVER: state a number not on a card · average forecasts · give a verdict on the person's future · invent courses or products · write "automated/replaced/eliminated" from a penetration value. 300–450 words."""

def write_brief(state: State) -> dict:
    cards, refs, scen, td = state["evidence"], state["refs"], state["scenarios"], state["task_diff"]
    inv = {v: k for k, v in refs.items()}
    def names(bucket, s): return "; ".join(f"{r['task'][:70]} [{inv.get(r['card_id'],'?')}]" for r in td[s["name"]][bucket][:6])
    grows_all = set.intersection(*[{r["card_id"] for r in td[s["name"]]["grows"]} for s in scen]) if scen else set()
    user = (f"Person: {state['worldview']['title']}, horizon {state['worldview']['horizon']}. Question: {state['question']}\n\n"
            "Scenarios (fixed ranges):\n" + "\n".join(f"- {s['name']} ({_fmt_range(s)}; {s['prob_note']}): {s['for_you']}" for s in scen) +
            "\n\nTask view per scenario:\n" + "\n".join(f"- {s['name']}: disappears → {names('disappears', s) or 'none'} | supervised → {names('supervised', s) or 'none'}" for s in scen) +
            f"\n\nTasks that stay human in every scenario: " + "; ".join(f"{next(c.claim for c in cards if c.id==i)[:70]} [{inv[i]}]" for i in list(grows_all)[:8]) +
            f"\n\nDisagreements: {state['disagreements']}\nUnknowns: {state.get('unknowns')}\nSources unavailable: {[k for k,v in state.get('source_status',{}).items() if v=='unavailable']}"
            f"\n\nEvidence table:\n{_table(cards, refs)}")
    try: text, cost = llm.chat("planner", BRIEF_SYS, user, max_tokens=1600, temperature=0.3)
    except Exception as e: text, cost = f"## Brief unavailable\nThe writer failed: {e}", 0.0
    _say(f"Drafted brief ({len(text.split())} words)")
    return {"brief_draft": text, "cost_usd": cost}

# ───────────────────────────── skeptic (SKEPTIC model — different family) ─────────────────────────────
SKEPTIC_SYS = UNIT_GUIDE + '''
You are a hostile fact-checker for a brief about one occupation's AI future. You get numbered sentences, each with the evidence cards it cites. For each decide:
- STRIP if: a number is not on a cited card or is misquoted; a card about question X is used to support claim Y; the sentence turns a penetration/exposure score into "automated/replaced/eliminated"; it gives a verdict on the person ("you'll be fine", "your job is safe/doomed"); or it recommends a specific product/course.
- KEEP otherwise — including scenario sentences. Scenario sentences are CONDITIONAL ("In a fast-diffusion world, …", "Under AGI, …"): judge only whether the *consequence* is a reasonable reading of the cited cards. Do NOT strip a scenario sentence because its premise is unlikely — the probability of the premise is reported separately.
- KEEP sentences that describe a task as "AI-assisted", "AI already used heavily for", "human-led", "stays with you" when the cited task card's penetration supports that direction.
Return {"verdicts":[{"i":0,"verdict":"keep|strip","reason":"..."}]}'''

_SENT = re.compile(r"\n+")   # brief is one claim per line (bullets); headings are their own lines

def skeptic(state: State) -> dict:
    draft, refs, cards = state["brief_draft"], state["refs"], {c.id: c for c in state["evidence"]}
    attempt = (state.get("skeptic") or {}).get("attempt", 0) + 1
    sents = [s.strip() for s in _SENT.split(draft) if s.strip()]
    keep_idx, stripped, to_check = {}, [], []
    for i, s in enumerate(sents):
        if s.startswith("#") or s.startswith("---"): keep_idx[i] = s; continue
        cited = re.findall(r"\[([cu]\d{2})\]", s)
        valid = [refs[r] for r in cited if r in refs]
        if not valid: stripped.append({"sentence": s, "reason": "no valid evidence ref"}); continue
        if all(v.startswith("unknown:") for v in valid): keep_idx[i] = s; continue   # 'no data exists for X' cites an unknown — nothing to fact-check
        to_check.append((i, s, valid))
    verdicts = {}
    if to_check:
        listing = "\n\n".join(f"{i}. {s}\n   cards: " + " | ".join(f"[{r}] {cards[cid].claim} (value {cards[cid].value} {cards[cid].unit})" for r, cid in zip([r for r in re.findall(r'\[([cu]\d{2})\]', s) if r in refs], valid) if cid in cards) for i, s, valid in to_check)
        try:
            text, cost = llm.chat("skeptic", SKEPTIC_SYS + "\nRespond with valid JSON only.", listing, max_tokens=12000, temperature=0.0)   # thinking model: reasoning tokens count
            try:
                m = re.search(r"\{.*\}", text, flags=re.S); verdicts = {int(v["i"]): v for v in json.loads(m.group(0)).get("verdicts", []) if "i" in v}
            except Exception:   # malformed JSON (unescaped quotes in reasons) — salvage verdicts by pattern
                verdicts = {int(i): {"verdict": v, "reason": (r or "").strip()[:200]} for i, v, r in re.findall(r'"i"\s*:\s*(\d+)\s*,\s*"verdict"\s*:\s*"(keep|strip)"(?:\s*,\s*"reason"\s*:\s*"([^"]*))?', text)}
                if not verdicts: raise ValueError("no verdicts parseable")
        except Exception as e:
            cost = 0.0; _say(f"Skeptic model failed ({e}); falling back to citation-only check")
    else: cost = 0.0
    for i, s, _ in to_check:
        v = verdicts.get(i, {"verdict": "keep", "reason": "cited; model did not object"})
        if v.get("verdict") == "strip": stripped.append({"sentence": s, "reason": v.get("reason", "")})
        else: keep_idx[i] = s
    kept = [keep_idx[i] for i in sorted(keep_idx)]   # original order — headings stay above their paragraphs
    total = len(to_check) + len([s for s in stripped if s["reason"] == "no valid evidence ref"])
    ratio = (len(stripped) / total) if total else 0.0
    escalated = ratio > UNCITED_LIMIT and attempt >= 2
    _say(f"Skeptic (attempt {attempt}): {len(stripped)}/{total} sentences stripped ({ratio:.0%})" + (" — escalating to human with a warning" if escalated else " — rebuilding once" if ratio > UNCITED_LIMIT else ""))
    kept = [k for j, k in enumerate(kept) if not (k.startswith("#") and (j + 1 == len(kept) or kept[j + 1].startswith("#")))]   # drop headings left empty
    brief_md = "\n\n".join(kept) if ratio <= UNCITED_LIMIT or escalated else state.get("brief_md", "")
    return {"skeptic": {"stripped": stripped, "kept": len(kept), "total": total, "ratio": round(ratio, 3), "attempt": attempt, "escalated": escalated, "model": llm.model_name("skeptic")},
            "brief_md": brief_md, "cost_usd": cost}

def after_skeptic(state: State) -> str:
    sk = state["skeptic"]
    if sk["ratio"] <= UNCITED_LIMIT or sk["escalated"]: return "render"
    if state.get("cost_usd", 0) > MAX_COST_USD or state.get("tool_calls", 0) > MAX_TOOL_CALLS: return "render"   # budget cap: stop with what exists
    return "rebuild"

# ───────────────────────────── render (code) ─────────────────────────────
def render(state: State) -> dict:
    cards = state["evidence"]; sk = state["skeptic"]; refs = state["refs"]; inv = {v: k for k, v in refs.items()}
    badges = []
    if sk.get("escalated"): badges.append(f"⚠ Skeptic could not verify {sk['ratio']:.0%} of sentences after two attempts — unsupported sentences removed; read with care")
    unavailable = [k for k, v in state.get("source_status", {}).items() if v == "unavailable"]
    if unavailable: badges.append(f"Partial evidence — unavailable: {', '.join(unavailable)}")
    if sk.get("stripped"): badges.append(f"{len(sk['stripped'])} sentence(s) removed for lacking a source")
    if state.get("unknowns"): badges.append(f"{len(state['unknowns'])} sub-question(s) with no data — shown as unknown, not estimated")
    footer = "\n\n---\n### Evidence\n" + "\n".join(f"- [{inv[c.id]}] {c.claim} — {c.source}{', ' + c.as_of if c.as_of else ''}{' · ' + c.url if c.url else ''}" for c in cards if c.id in inv)
    fc = [c for c in cards if c.family == "forecasts" and c.value is not None]; years = sorted({c.as_of[:4] for c in cards if c.as_of})
    evidence_line = f"_Evidence: {len(cards)} cards from {len({c.source for c in cards})} sources · {len(fc)} forecast market(s) with prices on {', '.join(sorted({c.source for c in fc})) or 'none'} · data {years[0]}–{years[-1]}_" if years else ""
    header = f"# {state['worldview']['title']} · horizon {state['worldview']['horizon']}\n_NextShift AI brief — what AI does to your work, with receipts_  \n{evidence_line}\n" + (("> " + " · ".join(badges) + "\n\n") if badges else "\n")
    views = {"tree": [{k: s[k] for k in ("name", "color", "prob_low", "prob_high", "prob_note", "gist")} for s in state["scenarios"]],
             "board": {k: v for k, v in state["task_diff"].items() if not k.startswith("_")}, "bands": state["disagreements"], "deltas": state.get("deltas", []),
             "badges": badges, "cards_by_family": {f: [c.model_dump() for c in cards if c.family == f] for f in FAMILIES}, "source_status": state.get("source_status", {}),
             "budget": {"tool_calls": state.get("tool_calls", 0), "cost_usd": round(state.get("cost_usd", 0), 4)}}
    return {"views": views, "brief_md": header + state["brief_md"] + footer}

# ───────────────────────────── interrupt 2 ─────────────────────────────
def publish_gate(state: State) -> dict:
    """Resume payload: {"action": "approve"|"edit"|"reject", "brief_md": str (if edit), "annotations": [str]}."""
    decision = interrupt({"kind": "publish", "brief_md": state["brief_md"], "skeptic": state["skeptic"], "badges": state["views"]["badges"], "deltas": state.get("deltas", []), "budget": state["views"]["budget"]})
    action = decision.get("action", "approve"); brief = decision.get("brief_md") if action == "edit" and decision.get("brief_md") else state["brief_md"]
    if decision.get("annotations"): brief += "\n\n### Reader notes\n" + "\n".join(f"- {a}" for a in decision["annotations"])
    return {"brief_md": brief, "approvals": {**state.get("approvals", {}), "publish": {"action": action, "at": time.time(), "edited": action == "edit"}}}

def after_publish(state: State) -> str: return "record" if state["approvals"]["publish"]["action"] in ("approve", "edit") else "end"

# ───────────────────────────── record (the ONLY node with write tools) ─────────────────────────────
def record(state: State) -> dict:
    p = state["persona"]; out_dir = ROOT / "data" / "briefs"; out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{p['soc']}_{p['horizon']}_{time.strftime('%Y%m%d-%H%M%S')}.md"; path.write_text(state["brief_md"])
    sid = memory.save_snapshot(state["thread_id"], p["soc"], p["horizon"], state["evidence"], state["scenarios"], p)
    _say(f"Exported {path.name}; snapshot #{sid} saved for next time")
    return {"exported_path": str(path)}
