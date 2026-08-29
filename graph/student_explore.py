"""Student journey — Phases C/D/E: candidates → evidence → fit → review → reactions → discriminators → shortlist → deep dive → exploration → save.
Reuses the professional gatherers, reconcile, outlook/work-change code and the structured reviewer. Every rationale line cites the student's own
words ([p:field:i]) and/or evidence cards ([cNN]); the reviewer checks both. Nothing is written before the save gate."""
from __future__ import annotations
import json, re, time
from langgraph.types import interrupt, Send
from . import llm, memory, nodes as N, review as rv
from .student import StudentState, FIELDS, _say, _coverage

MAX_CANDIDATES = 10; MIN_CANDIDATES = 6
GROUP_LABEL = {"strong": "Strong matches", "explore": "Worth exploring", "unexpected": "Unexpected possibilities", "reconsider": "Your ideas, reconsidered"}

# ───────────────────────────── profile refs ─────────────────────────────
def profile_refs(profile: dict) -> dict:
    """[p:field:i] → the student's evidence text, so rationales are checkable like cards."""
    out = {}
    for f in FIELDS:
        for i, e in enumerate(profile.get(f) or []): out[f"p:{f}:{i}"] = f"{f}: {e['value']}" + (f" — “{e['quote']}”" if e.get("quote") else "")
    return out

def _profile_table(profile: dict) -> str:
    return "\n".join(f"[{k}] {v}" for k, v in profile_refs(profile).items()) + f"\nleanings (people/ideas/data/technology/hands_on): {profile.get('pidth')}\nconfirmed summary: {json.dumps(profile.get('summary_sections'))}"

# ───────────────────────────── C1 generate candidates ─────────────────────────────
GEN_SYS = """You propose career directions for ONE student from their confirmed profile. Produce 8-10 varied directions in three groups: "strong" (3-4), "explore" (3-4), "unexpected" (1-2, each justified by a concrete profile item, not novelty).
Use real occupation names as they appear in the US O*NET / BLS taxonomy where possible (e.g. "Occupational Therapists", "User Experience Designers", "Electricians", "Market Research Analysts"). Modern roles without a category are fine (say so in needs_composite).
For EACH direction give a transparent rationale — every line must cite the profile refs it rests on, like [p:interests:0]:
matches_interests · uses_strengths · fits_preferences · constraints_ok · constraints_conflict · why_included · poor_fit_if (one honest line).
If the profile lists existing_career_ideas, EVERY one of them must appear as a candidate — placed honestly in strong / explore, or in a fourth group "reconsider" with the reason — so the student sees how their own ideas hold up.
Never infer from gender, race, background or school. No personality labels. Prefer directions whose education path is compatible with stated constraints; if not compatible, say so in constraints_conflict rather than dropping it.
Return {"candidates":[{"label":"...","search_title":"O*NET-style title","group":"strong|explore|unexpected","needs_composite":false,"rationale":{"matches_interests":["..."],"uses_strengths":["..."],"fits_preferences":["..."],"constraints_ok":["..."],"constraints_conflict":["..."],"why_included":"...","poor_fit_if":"..."}}]}"""

def generate_candidates(state: StudentState) -> dict:
    prof = state["profile"]; out, cost = {"candidates": []}, 0.0
    for attempt, (mt, extra) in enumerate([(7000, ""), (7000, "\nKeep every rationale line under 20 words and produce at most 8 candidates so the JSON stays short and valid.")]):
        try: out, c_ = llm.chat_json("planner", GEN_SYS + extra, _profile_table(prof), max_tokens=mt, temperature=0.4 if attempt == 0 else 0.2); cost += c_; break
        except Exception as e: _say(f"Candidate generation attempt {attempt + 1} failed ({type(e).__name__}) — retrying" if attempt == 0 else f"Candidate generation failed twice: {e}")
    if not out.get("candidates"): out = {"candidates": []}
    cands = [c for c in out.get("candidates", []) if isinstance(c, dict) and c.get("label")][:MAX_CANDIDATES]
    for i, c in enumerate(cands): c["key"] = f"k{i+1}"; c["group"] = c.get("group") if c.get("group") in GROUP_LABEL else "explore"; c.setdefault("rationale", {})
    _say(f"Thought of {len(cands)} directions: {sum(c['group']=='strong' for c in cands)} strong · {sum(c['group']=='explore' for c in cands)} worth exploring · {sum(c['group']=='unexpected' for c in cands)} unexpected")
    return {"candidates": cands, "cost_usd": cost}

# ───────────────────────────── C2 resolve to occupations ─────────────────────────────
def resolve_candidates(state: StudentState) -> dict:
    from tools import resolve as rs, composite
    cands = json.loads(json.dumps(state["candidates"])); seen_soc = {}
    for c in cands:
        title = c.get("search_title") or c["label"]; about = " ".join(c["rationale"].get("why_included", "") if isinstance(c["rationale"].get("why_included"), str) else "")
        try:
            r0 = rs.resolve(title, "", k=3)
            if r0["tier"] != 1 and c["label"] != title:   # try the plain label too — exact O*NET titles beat semantic guesses
                r1 = rs.resolve(c["label"], "", k=3)
                if r1["tier"] == 1: r0 = r1
            GENERIC = {"and", "or", "of", "the", "a", "an", "all", "other", "specialist", "manager", "worker", "coordinator", "assistant", "technician", "analyst", "director", "planner", "associate", "professional"}
            def _overlap(a, b):
                A = {x.lower().rstrip("s") for x in re.findall(r"[A-Za-z]+", a) if x.lower().rstrip("s") not in GENERIC}; B = {x.lower().rstrip("s") for x in re.findall(r"[A-Za-z]+", b) if x.lower().rstrip("s") not in GENERIC}
                return bool(A & B)
            top = r0["matches"][0] if r0.get("matches") else None; sim = (top or {}).get("similarity") or 0.0
            weak = r0["tier"] == 2 and (sim < 0.55 or (not _overlap(title, top["title"]) and sim < 0.72))   # semantic match must be strong, or share a meaningful word
            r = rs.with_composites(r0, title, about if (c.get("needs_composite") or weak) else "")
            if r.get("composites") and (c.get("needs_composite") or r["tier"] == 0 or weak):
                per = composite.persona_from(r["composites"][0], 2030); per.pop("horizon", None); c["resolution"] = "composite"
            else:
                m = r["matches"][0]; per = {"soc": m["soc"], "onet_soc": m.get("onet_soc") or f"{m['soc']}.00", "title": m["title"], "matched_via": f"tier {r['tier']}"}; c["resolution"] = f"official (tier {r['tier']})"
            c["persona"] = per; c["resolver_note"] = r.get("explanation", "")
        except Exception as e:
            c["persona"] = None; c["resolution"] = "unresolved"; c["resolver_note"] = f"could not match to an occupation: {e}"
        if c.get("persona"):   # diversity: at most two candidates per 6-digit occupation
            soc = c["persona"]["soc"]; seen_soc[soc] = seen_soc.get(soc, 0) + 1
            if seen_soc[soc] > 2: c["persona"] = None; c["resolution"] = "dropped (duplicate occupation)"
    keep = [c for c in cands if c.get("persona")]
    if not keep: _say("⚠ I couldn't produce career directions this time — you'll see an empty results screen with a retry option")
    _say(f"Matched {len(keep)} directions to official occupations" + (f" ({sum(c['resolution']=='composite' for c in keep)} assembled as composites)" if any(c['resolution']=='composite' for c in keep) else ""))
    return {"candidates": keep, "targets": [{"persona": c["persona"], "role": "candidate"} for c in keep]}

def fan_out_candidates(state: StudentState) -> list[Send]:
    sends = [Send("gather_forecasts", {"horizon": "2035"}), Send("gather_research", {})]
    for t in state["targets"]: sends += [Send("gather_outlook", {"persona": t["persona"]}), Send("gather_exposure", {"persona": t["persona"]})]
    return sends

# ───────────────────────────── C3 fit + tradeoffs (code facts, model prose) ─────────────────────────────
FIT_SYS = """You write the reader-facing text for career cards for ONE student. For each candidate you get: the student's profile refs, the candidate's rationale (already cited), official outlook facts, the three task groups and forecast context.
For each candidate return short, plain, warm text — every sentence cites [cNN] and/or [p:field:i]; interpretive sentences also end with [interpretation]:
- why_fit (2 sentences, tied to the student's own words), what_work_is_like (2 sentences from the task cards), how_ai_may_reshape (1-2 sentences — current use is NOT automation),
- human_capabilities (1-2 sentences from the 'more important' group), tradeoff (1-2 honest sentences: constraints conflict, declining demand, long education…), evidence_confidence: "low|moderate|high" with a 1-line reason.
Never guarantee anything, never call a task automated/replaced, never invent schools, courses or employers. Return {"cards": {"k1": {...}, "k2": {...}}}"""

def analyze_fit(state: StudentState) -> dict:
    prof, refs, inv = state["profile"], state["refs"], {v: k for k, v in state["refs"].items()}
    outlooks, changes = state["outlooks"], state["changes"]
    blocks = []
    for c in state["candidates"]:
        soc = c["persona"]["soc"]; o = outlooks.get(soc, {}); ch = changes.get(soc, {})
        blocks.append(f"### {c['key']} {c['label']} → {c['persona']['title']} ({c['resolution']})\nrationale: {json.dumps(c['rationale'])}\ndemand: {o.get('demand_reading')} · AI change: {o.get('ai_change_reading')}\nfacts: {' | '.join(o.get('facts', []))}\n"
                      f"AI assists: {'; '.join(r['task'][:70] + ' [' + r['ref'] + ']' for r in ch.get('ai_assists', [])[:5]) or 'none'}\nmore important: {'; '.join(r['task'][:60] + ' — ' + (r.get('why') or '') + ' [' + r['ref'] + ']' for r in ch.get('more_important', [])[:5]) or 'none'}")
    user = f"PROFILE REFS:\n{_profile_table(prof)}\n\nCANDIDATES:\n" + "\n\n".join(blocks) + f"\n\nForecast context: {state.get('forecast_context')}\nUnknowns: {state.get('unknowns')}\n\nEvidence table:\n{N._table(state['evidence'], refs)}"
    try: out, cost = llm.chat_json("planner", FIT_SYS, user, max_tokens=6000, temperature=0.3); cards = out.get("cards", {})
    except Exception as e: cards, cost = {}, 0.0; _say(f"Fit analysis failed: {e}")
    cands = json.loads(json.dumps(state["candidates"]))
    for c in cands:
        soc = c["persona"]["soc"]; o = outlooks.get(soc, {}); txt = cards.get(c["key"], {})
        c["card"] = {"why_fit": txt.get("why_fit", ""), "what_work_is_like": txt.get("what_work_is_like", ""), "how_ai_may_reshape": txt.get("how_ai_may_reshape", ""), "human_capabilities": txt.get("human_capabilities", ""),
                     "tradeoff": txt.get("tradeoff", ""), "evidence_confidence": txt.get("evidence_confidence", "low"),
                     "demand_reading": o.get("demand_reading", "unknown"), "ai_change_reading": o.get("ai_change_reading", "unknown"), "facts": o.get("facts", []), "education_entry": o.get("education_entry"), "proxy_note": o.get("proxy_note"),
                     "ai_assists": changes.get(soc, {}).get("ai_assists", [])[:6], "more_important": changes.get(soc, {}).get("more_important", [])[:6]}
    _say("Wrote the career cards — now the reviewer checks every line against the evidence and your own words")
    return {"candidates": cands, "cost_usd": cost}

# ───────────────────────────── shared structured reviewer (cards + profile refs) ─────────────────────────────
REVIEW_SYS = N.SKEPTIC_SYS + """
Additional rules for career cards: STRIP a line if it recommends from stereotype (gender, race, background) or personality labels; if it ignores a stated constraint; if a [p:...] ref does not actually support the claim about the student; if two cards contradict each other on the same fact.
Refs starting with p: are the student's own words — check the claim against the quote."""

CITE_SYS = """You add citations to lines that lack them, for a career-guidance document. You get numbered lines and the available sources: evidence cards [cNN]/[uNN] and the student's own words [p:field:i].
For each line: append the ref(s) that genuinely support it; if it is an interpretation or advice, also append [interpretation] or [advice]; if NOTHING supports a factual claim in the line, return it unchanged (it will be removed).
Never change the words of a line. Return {"lines": {"0": "line with refs", ...}}"""

def add_citations(state: StudentState, obj: dict, refs_table: str) -> tuple[dict, float]:
    """Repair pass: lines without any ref get the refs that support them (or an [interpretation]/[advice] tag). The reviewer then verifies them like everything else."""
    ref_re = re.compile(r"\[([cu]\d{2,3}|p:[a-z_]+:\d+|interpretation|advice)\]")
    leaves = [(p, t) for p, t in rv.flatten(obj) if not ref_re.search(t) and not t.startswith(("#", "**", "_")) and not p.endswith("evidence_confidence")]
    if not leaves: return obj, 0.0
    try:
        out, cost = llm.chat_json("planner", CITE_SYS, "LINES:\n" + "\n".join(f"{i}. {t}" for i, (p, t) in enumerate(leaves)) + f"\n\nSOURCES:\n{refs_table}", max_tokens=3000, temperature=0.0)
        fixed = out.get("lines", {})
        for i, (p, t) in enumerate(leaves):
            new = fixed.get(str(i))
            if isinstance(new, str) and new.strip() and re.sub(r"\s*\[[^\]]+\]", "", new).strip()[:40] == t.strip()[:40]:   # words unchanged
                parent, key = rv._resolve(obj, p) if "#" not in p else (None, None)
                if parent is not None: parent[key] = new
                else:   # sentence inside a paragraph
                    pp, si = p.rsplit("#", 1); parent, key = rv._resolve(obj, pp); sents = rv.split_sentences(parent[key]); sents[int(si)] = new; parent[key] = " ".join(sents)
        return obj, cost
    except Exception: return obj, 0.0

def review_object(state: StudentState, obj: dict, label: str) -> tuple[dict, dict, float]:
    """Structured review over any object. Returns (reviewed_obj, skeptic_record, cost). Reviewer failure → status 'unverified' (loud), never silent keep."""
    refs = dict(state["refs"]); prefs = profile_refs(state["profile"]); cards = {c.id: c for c in state["evidence"]}
    obj, c_fix = add_citations(state, obj, _profile_table(state["profile"]) + "\n" + N._table(state["evidence"], refs))
    allrefs = {**refs, **{k: "profile:" + v for k, v in prefs.items()}}
    ref_re = re.compile(r"\[([cu]\d{2,3}|p:[a-z_]+:\d+)\]")
    leaves = rv.flatten(obj); removed, to_check, kept = [], [], 0
    for p, t in leaves:
        cited = [r for r in ref_re.findall(t) if r in allrefs]
        if rv.certainty_violation(t): removed.append({"path": p, "sentence": t, "reason": "certainty about the future (lint)"}); continue
        if t.startswith(("#", "**", "_")) or (cited and all(allrefs[r].startswith("unknown:") for r in cited)): kept += 1; continue
        if not cited and any(x in t for x in rv.TAGS) and not re.search(r"\d", t): kept += 1; continue
        if not cited and p.endswith("evidence_confidence"): kept += 1; continue
        if not cited: removed.append({"path": p, "sentence": t, "reason": "no evidence or profile ref"}); continue
        to_check.append((p, t, cited))
    verdicts, cost, status = {}, 0.0, "verified"
    if to_check:
        def src(r): return f"[{r}] " + (allrefs[r][8:] if r.startswith("p:") else (f"{cards[refs[r]].claim} (value {cards[refs[r]].value} {cards[refs[r]].unit})" if r in refs and refs[r] in cards else allrefs[r]))
        items = [(i, f"{t}\n   sources: " + " | ".join(src(r) for r in cited)) for i, (p, t, cited) in enumerate(to_check)]
        verdicts, cost, status = rv.judge_lines(items, REVIEW_SYS)
        if status == "unverified": _say(f"⚠ Reviewer model failed ({rv.judge_lines.last_error}) — {label} checked for citations only, NOT for accuracy")
    for i, (p, t, _) in enumerate(to_check):
        v = verdicts.get(i, {"verdict": "keep", "reason": "cited; reviewer did not object" if status == "verified" else "UNVERIFIED"})
        if v.get("verdict") == "strip": removed.append({"path": p, "sentence": t, "reason": v.get("reason", "")})
        else: kept += 1
    rv.apply_removals(obj, [r["path"] for r in removed])
    total = len(to_check) + sum(1 for r in removed if r["reason"].startswith("no evidence")); ratio = len(removed) / total if total else 0.0
    _say(f"Reviewed {label}: {total} lines, {len(removed)} removed" + (" — UNVERIFIED" if status == "unverified" else ""))
    return obj, {"stripped": removed, "kept": kept, "total": total, "ratio": round(ratio, 3), "status": status, "model": llm.model_name("skeptic"), "attempt": 1, "escalated": False}, cost + c_fix

def _check_rationale(rationale: dict, prefs: dict) -> tuple[dict, int]:
    """Deterministic: a rationale line survives only if every [p:...] it cites exists and it cites at least one. Returns (cleaned, removed_count)."""
    ref_re = re.compile(r"\[(p:[a-z_]+:\d+)\]"); removed = 0; out = {}
    for k, v in rationale.items():
        if isinstance(v, list):
            keep = [l for l in v if isinstance(l, str) and ref_re.findall(l) and all(rf in prefs for rf in ref_re.findall(l))]; removed += len(v) - len(keep); out[k] = keep
        elif isinstance(v, str): ok = bool(ref_re.findall(v)) and all(rf in prefs for rf in ref_re.findall(v)); out[k] = v if ok or k == "poor_fit_if" else ""; removed += 0 if ok or k == "poor_fit_if" else 1
        else: out[k] = v
    return out, removed

def review_cards(state: StudentState) -> dict:
    prefs = profile_refs(state["profile"]); rat_removed = 0
    for c in state["candidates"]: c["rationale"], n_ = _check_rationale(c["rationale"], prefs); rat_removed += n_
    obj = {"candidates": [{"key": c["key"], "label": c["label"], "group": c["group"], "card": {k: v for k, v in c["card"].items() if k in ("why_fit", "what_work_is_like", "how_ai_may_reshape", "human_capabilities", "tradeoff", "evidence_confidence")},
                           "more_important": [{"task": r["task"], "ref": r["ref"], "why": r.get("why", ""), "card_id": r["card_id"]} for r in c["card"]["more_important"]]} for c in state["candidates"]]}
    # 'why' reasons get their row ref + tag so they are judged as interpretation
    for c in obj["candidates"]:
        for r in c["more_important"]: r["why"] = (r["why"] + f" [{r['ref']}] [interpretation]") if r["why"] and "[" not in r["why"] else r["why"]
    reviewed, sk, cost = review_object(state, obj, "career cards")
    cands = json.loads(json.dumps(state["candidates"])); by = {c["key"]: c for c in reviewed["candidates"]}
    for c in cands:
        r = by.get(c["key"]);
        if not r: continue
        c["card"].update(r["card"]); c["card"]["more_important"] = r["more_important"]; c["review"] = {"removed": [x for x in sk["stripped"] if f"candidates[{reviewed['candidates'].index(r)}]" in x["path"]]}
    sk["rationale_lines_removed"] = rat_removed
    return {"candidates": cands, "skeptic": sk, "cost_usd": cost}

# ───────────────────────────── C4 results + reactions ─────────────────────────────
def render_results(state: StudentState) -> dict:
    sk = state["skeptic"]; unavailable = [k for k, v in state.get("source_status", {}).items() if v == "unavailable"]
    badges = ([f"Partial evidence — unavailable: {', '.join(unavailable)}"] if unavailable else []) + ([f"Checked — {len(sk['stripped'])} line(s) removed for lacking support"] if sk.get("stripped") else ["Checked — 0 lines removed"])
    if sk.get("status") == "unverified": badges.insert(0, "⚠ UNVERIFIED — our independent review step failed, so these cards were checked for citations only, not for accuracy. Treat them as a draft.")
    if state["completeness"].get("thin"): badges.append("Based on a short conversation — the more you tell me, the better these get")
    inv = {v: k for k, v in state["refs"].items()}
    views = {"badges": badges, "review_status": sk.get("status", "verified"), "groups": {g: [c for c in state["candidates"] if c["group"] == g] for g in GROUP_LABEL}, "group_label": GROUP_LABEL,
             "disagreements": state["disagreements"], "forecast_context": state.get("forecast_context", []), "unknowns": state.get("unknowns", []), "source_status": state.get("source_status", {}), "skeptic": sk,
             "cards_by_family": {f: [c.model_dump() for c in state["evidence"] if c.family == f] for f in ("statistics", "exposure", "forecasts", "research")}, "budget": {"tool_calls": state.get("tool_calls", 0), "cost_usd": round(state.get("cost_usd", 0), 4)},
             "profile_refs": profile_refs(state["profile"])}
    return {"views": views}

def reaction_gate(state: StudentState) -> dict:
    """⏸ Resume: {"reactions": [{"key","verdict":"excited|curious|no","why"}], "action": "continue"|"back_to_understanding"|"stop"}."""
    d = interrupt({"kind": "results", "views": state["views"]})
    action = d.get("action", "continue"); rx = [r for r in d.get("reactions", []) if r.get("key")]
    return {"reactions": rx, "last_action": action, "approvals": {**state.get("approvals", {}), "reactions": {"action": action, "at": time.time(), "n": len(rx)}}}

def after_reactions(state: StudentState) -> str: return "end" if state["last_action"] == "stop" else "regen" if state["last_action"] == "back_to_understanding" else "update"

RX_SYS = """A student reacted to career cards. For each reaction with a 'why', extract what it reveals about the student — as profile evidence — exactly like the interview updater:
{"add": {"<field>": [{"value": "...", "quote": "their words", "kind": "stated"}]}, "pidth": {...only informed keys...}, "notes": ["one line per reaction on what it separates: e.g. 'likes psychology for the one-on-one, not the research'"]}
Fields: interests · energizing_activities · dislikes · work_preferences · values · desired_impact · lifestyle_preferences · education_constraints · financial_constraints · location_constraints · uncertainties. Do not invent."""

def update_from_reactions(state: StudentState) -> dict:
    prof = json.loads(json.dumps(state["profile"])); rx = state["reactions"]; labels = {c["key"]: c["label"] for c in state["candidates"]}
    rejected = list(state.get("rejected", [])) + [{"key": r["key"], "label": labels.get(r["key"]), "why": r.get("why", ""), "at": time.time()} for r in rx if r["verdict"] == "no"]
    described = [r for r in rx if r.get("why")]
    cost = 0.0
    if described:
        try:
            out, cost = llm.chat_json("planner", RX_SYS, "\n".join(f"{labels.get(r['key'])}: {r['verdict']} — “{r['why']}”" for r in described), max_tokens=800, temperature=0.1)
            tn = len(state["turns"]) + 100
            for f, items in (out.get("add") or {}).items():
                if f in FIELDS:
                    for e in items[:3]:
                        if isinstance(e, dict) and e.get("value"): prof[f].append({"value": str(e["value"])[:80], "quote": str(e.get("quote", ""))[:160], "source_turn": tn, "kind": "stated"})
            for k, v in (out.get("pidth") or {}).items():
                if k in ("people", "ideas", "data", "technology", "hands_on"): prof["pidth"][k] = max(-1.0, min(1.0, float(v)))
            prof["important_quotes_or_examples"] = (prof.get("important_quotes_or_examples") or []) + [n for n in (out.get("notes") or []) if isinstance(n, str)][:3]
        except Exception as e: _say(f"(reaction update skipped: {e})")
    prof["confidence_by_field"] = _coverage(prof)
    _say(f"Took in your reactions: {sum(r['verdict']=='excited' for r in rx)} excited · {sum(r['verdict']=='curious' for r in rx)} curious · {sum(r['verdict']=='no' for r in rx)} not for you")
    return {"profile": prof, "rejected": rejected, "cost_usd": cost}

# ───────────────────────────── D1 discriminating questions ─────────────────────────────
DISC_SYS = """A student is deciding among a few careers. Given the shortlisted careers (with education path and demand), the student's profile and their reactions, write 0-2 discriminating questions that would most help separate the options —
about real forks: education length/cost, people-vs-data, hands-on-vs-desk, licensing, schedule, location. Skip a question if the profile already answers it. Warm, plain, one sentence each.
Return {"questions": [{"text": "...", "separates": ["k1","k3"]}]}"""

def discriminate(state: StudentState) -> dict:
    keep = [c for c in state["candidates"] if any(r["key"] == c["key"] and r["verdict"] in ("excited", "curious") for r in state["reactions"])]
    if len(keep) <= 1: return {"pending": {"questions": []}}
    desc = "\n".join(f"{c['key']} {c['label']} — education: {c['card'].get('education_entry')} · demand: {c['card'].get('demand_reading')} · reaction: {next((r['verdict'] + ' — ' + r.get('why', '') for r in state['reactions'] if r['key'] == c['key']), '')}" for c in keep)
    try: out, cost = llm.chat_json("planner", DISC_SYS, f"Careers:\n{desc}\n\nProfile:\n{_profile_table(state['profile'])}", max_tokens=400); qs = [q for q in out.get("questions", []) if isinstance(q, dict) and q.get("text")][:2]
    except Exception: qs, cost = [], 0.0
    return {"pending": {"questions": qs}, "cost_usd": cost}

def after_discriminate(state: StudentState) -> str: return "ask" if state["pending"].get("questions") else "shortlist"

def discriminator_gate(state: StudentState) -> dict:
    """⏸ Resume: {"answers": ["...", "..."]}"""
    qs = state["pending"]["questions"]; d = interrupt({"kind": "discriminate", "questions": qs})
    answers = d.get("answers", []); turns = list(state.get("discriminators", []))
    for q, a in zip(qs, answers): turns.append({"i": len(turns) + 1, "goal": "discriminate", "question": q["text"], "answer": a, "action": "answer", "separates": q.get("separates", [])})
    return {"discriminators": turns, "last_action": "discriminated"}

def apply_discriminators(state: StudentState) -> dict:
    """Same updater as the interview, applied to the discriminator answers (kept as profile evidence)."""
    prof = json.loads(json.dumps(state["profile"])); cost = 0.0
    from .student import UPDATE_SYS
    for t in state.get("discriminators", []):
        if not t.get("answer") or t.get("applied"): continue
        try:
            out, c_ = llm.chat_json("planner", UPDATE_SYS, f"Current profile (values only): {json.dumps({f: [e['value'] for e in prof.get(f, [])] for f in FIELDS if prof.get(f)})}\nQ: {t['question']}\nA: {t['answer']}", max_tokens=600, temperature=0.1); cost += c_
            for f, items in (out.get("add") or {}).items():
                if f in FIELDS:
                    for e in items[:3]:
                        if isinstance(e, dict) and e.get("value"): prof[f].append({"value": str(e["value"])[:80], "quote": str(e.get("quote", ""))[:160], "source_turn": 200 + t["i"], "kind": "stated"})
        except Exception: pass
        t["applied"] = True
    return {"profile": prof, "discriminators": state.get("discriminators", []), "cost_usd": cost}

# ───────────────────────────── D2 shortlist ─────────────────────────────
SHORT_SYS = """Write the shortlist comparison for a student. For each shortlisted career give one short cited line per dimension: personal_fit · daily_work · outlook · education_time_cost · lifestyle · ai_related_change · human_edge · uncertainty.
Then "our_read": 2-4 sentences on how the options differ for THIS student and what would tip it — cited, ending [interpretation]; never declare a winner, never guarantee.
Return {"rows": {"k1": {...8 dims...}}, "our_read": "..."}"""

def build_shortlist(state: StudentState) -> dict:
    rx = {r["key"]: r for r in state["reactions"]}; disc = state.get("discriminators", [])
    order = sorted([c for c in state["candidates"] if rx.get(c["key"], {}).get("verdict") in ("excited", "curious")], key=lambda c: (rx[c["key"]]["verdict"] != "excited", c["group"] != "strong"))
    short = [c["key"] for c in order[:3]] or [c["key"] for c in state["candidates"] if c["group"] == "strong"][:2]
    cands = {c["key"]: c for c in state["candidates"]}
    blocks = "\n\n".join(f"### {k} {cands[k]['label']} → {cands[k]['persona']['title']}\ncard: {json.dumps({x: cands[k]['card'].get(x) for x in ('why_fit','what_work_is_like','how_ai_may_reshape','human_capabilities','tradeoff','education_entry','demand_reading')})}\nfacts: {' | '.join(cands[k]['card'].get('facts', [])[:4])}\nreaction: {rx.get(k, {}).get('verdict')} — {rx.get(k, {}).get('why', '')}" for k in short)
    user = f"PROFILE REFS:\n{_profile_table(state['profile'])}\n\nDiscriminating answers: {[(t['question'], t['answer']) for t in disc]}\n\nSHORTLIST:\n{blocks}"
    try: out, cost = llm.chat_json("planner", SHORT_SYS, user, max_tokens=2200, temperature=0.3)
    except Exception as e: out, cost = {"rows": {}, "our_read": ""}, 0.0
    obj = {"rows": {k: out.get("rows", {}).get(k, {}) for k in short}, "our_read": out.get("our_read", "")}
    reviewed, sk, c2 = review_object(state, obj, "shortlist")
    _say(f"Shortlist: {', '.join(cands[k]['label'] for k in short)}")
    return {"shortlist": short, "views": {**state["views"], "shortlist": {"keys": short, "rows": reviewed["rows"], "our_read": reviewed["our_read"], "review": sk}}, "cost_usd": cost + c2}

def shortlist_gate(state: StudentState) -> dict:
    """⏸ Resume: {"action": "pick"|"whatif"|"compare"|"back_to_results"|"save"|"stop", "key": "k1", "whatif": "no grad school", "keys": [...]}"""
    d = interrupt({"kind": "shortlist", "views": state["views"], "shortlist": state["shortlist"]})
    action = d.get("action", "pick"); log = list(state.get("exploration_log", [])) + [{"at": time.time(), "action": action, "arg": d.get("key") or d.get("whatif") or d.get("keys")}]
    upd = {"last_action": action, "exploration_log": log}
    if action == "pick": upd["selected"] = d.get("key")
    if action == "whatif": upd["pending"] = {"whatif": d.get("whatif", "")}
    return upd

def after_shortlist(state: StudentState) -> str:
    a = state["last_action"]
    return {"pick": "deep_dive", "whatif": "explore", "compare": "explore", "back_to_results": "results", "save": "save", "stop": "end"}.get(a, "deep_dive")

# ───────────────────────────── D3 deep dive ─────────────────────────────
DEEP_SYS = """Write a deep dive on ONE career for ONE student. Sections (each 2-4 short sentences or 3-5 bullets; every sentence cites [cNN] and/or [p:field:i]; interpretive lines end [interpretation]; practical suggestions with no factual claim end [advice]):
why_fit · what_people_do · education_and_entry · outlook · how_ai_may_change · ai_already_used_for (bullets from task cards) · human_capabilities · risks_tradeoffs_uncertainty · what_to_do_in_school (bullets) ·
test_this_career (3-5 bullets — concrete, low-cost experiments: interview a professional, shadow, a representative project, a student activity, an intro class, compare pathways, reflect on whether it was energizing).
Never invent named courses, certifications, schools or employers. Never guarantee. Return {"sections": {"why_fit": "...", "what_people_do": "...", "education_and_entry": "...", "outlook": "...", "how_ai_may_change": "...", "ai_already_used_for": ["..."], "human_capabilities": "...", "risks_tradeoffs_uncertainty": "...", "what_to_do_in_school": ["..."], "test_this_career": ["..."]}}"""

def deep_dive(state: StudentState) -> dict:
    c = next(c for c in state["candidates"] if c["key"] == state["selected"]); soc = c["persona"]["soc"]; o = state["outlooks"].get(soc, {}); ch = state["changes"].get(soc, {})
    user = (f"PROFILE REFS:\n{_profile_table(state['profile'])}\n\nCAREER: {c['label']} → {c['persona']['title']} ({c['resolution']})\nrationale: {json.dumps(c['rationale'])}\ncard: {json.dumps({k: c['card'].get(k) for k in ('why_fit','what_work_is_like','how_ai_may_reshape','human_capabilities','tradeoff')})}\n"
            f"facts: {' | '.join(o.get('facts', []))}\nAI assists: {'; '.join(r['task'][:80] + ' [' + r['ref'] + ']' for r in ch.get('ai_assists', [])[:8])}\nmore important: {'; '.join(r['task'][:70] + ' — ' + (r.get('why') or '') + ' [' + r['ref'] + ']' for r in ch.get('more_important', [])[:6])}\n"
            f"uncertain: {'; '.join(r['task'][:70] + ' [' + r['ref'] + ']' for r in ch.get('uncertain', [])[:5])}\nForecast context: {state.get('forecast_context')}\nUnknowns: {state.get('unknowns')}\n\nEvidence table (this career + economy-wide):\n{N._table(state['evidence'], state['refs'], occ=soc)}")
    try: out, cost = llm.chat_json("planner", DEEP_SYS, user, max_tokens=3500, temperature=0.3); sections = out.get("sections", {})
    except Exception as e: sections, cost = {"why_fit": f"(writer failed: {e})"}, 0.0
    reviewed, sk, c2 = review_object(state, {"sections": sections}, "deep dive")
    experiments = [x for x in reviewed["sections"].get("test_this_career", []) if isinstance(x, str)]
    _say(f"Deep dive on {c['label']} ready — {len(experiments)} ways to test it before committing")
    return {"deep_dive": {"key": c["key"], "label": c["label"], "title": c["persona"]["title"], "sections": reviewed["sections"], "review": sk}, "experiments_planned": experiments, "views": {**state["views"], "deep_dive_review": sk}, "cost_usd": cost + c2}

def explore_gate(state: StudentState) -> dict:
    """⏸ After the deep dive. Resume: {"action": "similar"|"compare"|"whatif"|"changed_mind"|"back_to_shortlist"|"save"|"stop", "whatif": "...", "key": "..."}"""
    d = interrupt({"kind": "deep_dive", "deep_dive": state["deep_dive"], "views": state["views"], "shortlist": state["shortlist"]})
    action = d.get("action", "save"); log = list(state.get("exploration_log", [])) + [{"at": time.time(), "action": action, "arg": d.get("whatif") or d.get("key")}]
    upd = {"last_action": action, "exploration_log": log}
    if action in ("whatif", "similar", "compare", "changed_mind"): upd["pending"] = {"whatif": d.get("whatif", ""), "mode": action, "key": d.get("key")}
    if action == "compare" and d.get("key"): upd["selected"] = d.get("key")
    return upd

def after_explore(state: StudentState) -> str:
    return {"save": "save", "stop": "end", "back_to_shortlist": "shortlist", "compare": "deep_dive", "changed_mind": "results"}.get(state["last_action"], "explore")

# ───────────────────────────── E exploration (what-if / similar) ─────────────────────────────
WHATIF_SYS = """A student asked a what-if about their shortlist (e.g. 'what if I don't want graduate school', 'what if salary matters more', 'what if I want remote work', 'show me similar careers').
Given their profile, all candidate cards and the question, return {"note": "2-4 cited sentences on how the shortlist changes under this what-if, ending [interpretation]", "reorder": ["k3","k1"], "add_constraint": {"field": "education_constraints|financial_constraints|location_constraints|lifestyle_preferences|null", "value": "...", "quote": "..."}}
Only reorder among existing candidates; never invent careers or numbers."""

def explore(state: StudentState) -> dict:
    q = (state.get("pending") or {}).get("whatif", ""); mode = (state.get("pending") or {}).get("mode", "whatif"); prof = json.loads(json.dumps(state["profile"]))
    cands = {c["key"]: c for c in state["candidates"]}
    user = f"WHAT-IF ({mode}): {q}\n\nPROFILE REFS:\n{_profile_table(prof)}\n\nCANDIDATES:\n" + "\n".join(f"{k} {c['label']} — demand {c['card'].get('demand_reading')} · education {c['card'].get('education_entry')} · tradeoff: {c['card'].get('tradeoff')}" for k, c in cands.items()) + f"\nCurrent shortlist: {state['shortlist']}"
    try: out, cost = llm.chat_json("planner", WHATIF_SYS, user, max_tokens=700, temperature=0.3)
    except Exception as e: out, cost = {"note": f"(could not evaluate: {e})", "reorder": []}, 0.0
    ac = out.get("add_constraint") or {}
    if ac.get("field") in FIELDS and ac.get("value"): prof[ac["field"]].append({"value": ac["value"][:80], "quote": (ac.get("quote") or q)[:160], "source_turn": 300 + len(state.get("exploration_log", [])), "kind": "stated"})
    reviewed, sk, c2 = review_object(state, {"note": out.get("note", "")}, "what-if")
    order = [k for k in out.get("reorder", []) if k in cands] or state["shortlist"]
    log = list(state.get("exploration_log", [])); log[-1] = {**log[-1], "note": reviewed["note"], "shortlist_after": order[:3]}
    _say(f"Considered: {q or mode} → shortlist now {', '.join(cands[k]['label'] for k in order[:3])}")
    return {"profile": prof, "shortlist": order[:3], "exploration_log": log, "views": {**state["views"], "whatif": {"question": q, "note": reviewed["note"], "review": sk}}, "cost_usd": cost + c2}

# ───────────────────────────── save ─────────────────────────────
def save_gate(state: StudentState) -> dict:
    """⏸ Resume: {"action": "approve"|"reject", "experiments": [...edited]}"""
    summary = {"shortlist": [c["label"] for c in state["candidates"] if c["key"] in state["shortlist"]], "rejected": [r["label"] for r in state.get("rejected", [])], "experiments": state.get("experiments_planned", []), "selected": (state.get("deep_dive") or {}).get("label"),
               "review_status": (state.get("skeptic") or {}).get("status", "verified")}
    d = interrupt({"kind": "save", "summary": summary})
    action = d.get("action", "approve"); upd = {"approvals": {**state.get("approvals", {}), "save": {"action": action, "at": time.time()}}}
    if d.get("experiments") is not None: upd["experiments_planned"] = d["experiments"]
    return upd

def after_save(state: StudentState) -> str: return "record" if state["approvals"]["save"]["action"] == "approve" else "end"

def record(state: StudentState) -> dict:
    """The ONLY writer in the student graph."""
    from pathlib import Path
    out_dir = N.ROOT / "data" / "briefs"; out_dir.mkdir(parents=True, exist_ok=True); tag = "_UNVERIFIED" if (state.get("skeptic") or {}).get("status") == "unverified" else ""
    dd = state.get("deep_dive") or {}; cands = {c["key"]: c for c in state["candidates"]}
    md = [f"# Career exploration · {time.strftime('%Y-%m-%d')}", "_A guided exploration based on what you shared and available career data — not a test that determines what you should become._", "", "## What I understood about you"]
    md += [f"**{t}** — {state['profile']['summary_sections'].get(k, '')}" for k, t in __import__('graph.student', fromlist=['SECTION_TITLES']).SECTION_TITLES.items()]
    md += ["", "## Shortlist"] + [f"- **{cands[k]['label']}** ({cands[k]['persona']['title']}) — {cands[k]['card'].get('why_fit', '')}" for k in state["shortlist"] if k in cands]
    if dd: md += ["", f"## Deep dive: {dd['label']}"] + [f"**{k.replace('_', ' ').title()}**\n" + (v if isinstance(v, str) else "\n".join(f"- {x}" for x in v)) for k, v in dd["sections"].items()]
    md += ["", "## Not for me"] + [f"- {r['label']} — {r['why']}" for r in state.get("rejected", [])]
    md += ["", "## Experiments I plan to try"] + [f"- {x}" for x in state.get("experiments_planned", [])]
    path = out_dir / f"student_{re.sub(r'[^A-Za-z0-9]+', '-', (dd.get('label') or 'exploration').lower())}_{time.strftime('%Y%m%d-%H%M%S')}{tag}.md"; path.write_text("\n".join(md))
    first = cands[state["shortlist"][0]]["persona"]["soc"] if state["shortlist"] else "student"
    memory.save_snapshot(state["thread_id"], first, "2035", state["evidence"], {"profile": {k: v for k, v in state["profile"].items() if k != "summary_sections"}, "summary_sections": state["profile"].get("summary_sections"), "shortlist": state["shortlist"], "reactions": state["reactions"], "rejected": state.get("rejected", []),
                                                                                 "experiments": state.get("experiments_planned", []), "exploration_log": state.get("exploration_log", []), "review_status": (state.get("skeptic") or {}).get("status")}, cands[state["shortlist"][0]]["persona"] if state["shortlist"] else {})
    _say(f"Saved your exploration ({path.name}) — profile, shortlist, reactions and planned experiments")
    return {"exported_path": str(path)}
