"""Student journey screens (career-discovery interviewer). Imported by ui/app.py; shares the shell (theme, session state, strip_refs).
Stages: s_interview_run → s_interview → s_understanding → s_working → s_results → s_discriminate → s_shortlist → s_deep → s_save → s_done."""
from __future__ import annotations
import re, uuid
import streamlit as st
from langgraph.types import Command
from ui import journey as J

C = {"amber": "#E5A24A", "student": "#7FC8E8", "green": "#8FBF9F", "red": "#E07A5F", "purple": "#B48CFF", "muted": "#8A94A6", "line": "#2A3544"}
DEMAND = {"growing": ("▲ Growing", C["green"]), "stable": ("● Stable", C["amber"]), "declining": ("▼ Declining", C["red"]), "unknown": ("? No official projection", C["muted"])}
CHANGE = {"substantial": "◆ Substantial", "moderate": "◆ Moderate", "limited": "◆ Limited", "unknown": "? Unknown"}
CORE_LABELS = {"interests_or_energizing": "what energizes you", "strengths": "strengths you've shown", "negatives": "what to avoid or build", "pidth": "people · ideas · data · tech · hands", "constraints": "practical limits", "values_or_impact": "what matters to you"}
COVERAGE_GLYPH = {"none": ("○", "not yet"), "weak": ("◔", "a little"), "moderate": ("◑", "enough"), "strong": ("●", "clear")}
BOUNDARY = "This is a guided exploration based on what you shared and available career data — not a test that determines what you should become."

def strip_refs(text) -> str: return re.sub(r"\s*\[(?:[cu]\d{2,3}|p:[a-z_]+:\d+|interpretation|advice)\]", "", str(text or "")).strip()
def pill(text, color): return f"<span class='pill' style='background:{color}22;color:{color};border:1px solid {color}66'>{text}</span>"

@st.cache_resource
def sgraph():
    from graph.student_build import build_student_graph; return build_student_graph()

def run(S, inp, box=None):
    cfg = {"configurable": {"thread_id": S.thread_id}}
    for mode, ev in sgraph().stream(inp, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom":
            if "diag" in ev: S.setdefault("diag", []).append(ev); continue
            if "phase" in ev:
                S.phase = ev; S.setdefault("phase_log", []).append(ev)
                if callable(S.get("on_phase")): S.on_phase()
                continue
            S.log.append(ev["say"])
            if box is not None: box.write(f"· {ev['say']}")
        elif "__interrupt__" in ev: S.phase = None; return ev["__interrupt__"][0].value
    S.phase = None; return None

def route(S, payload):
    """Map an interrupt payload to a stage."""
    kinds = {"interview": "s_interview", "understanding": "s_understanding", "results": "s_results", "discriminate": "s_discriminate", "shortlist": "s_shortlist", "deep_dive": "s_deep", "save": "s_save"}
    S.payload = payload; S.stage = kinds.get((payload or {}).get("kind"), "s_done"); st.rerun()

def start(S):
    S.thread_id = str(uuid.uuid4()); S.log = []; S.stage = "s_interview_run"; S.first_name = ""; st.rerun()

# ───────────────────────────── interview ─────────────────────────────
def screen_interview_run(S):
    with st.status("Getting ready…", expanded=False) as box: p = run(S, {"thread_id": S.thread_id}, box)
    route(S, p)

def screen_interview(S):
    p = S.payload
    st.markdown("<span class='kicker' style='color:%s'>Exploring careers</span>" % C["student"], unsafe_allow_html=True)
    if p["turn"] == 1:
        st.markdown("## Let's figure out what kinds of work might fit you.")
        st.markdown(f"<p class='muted'>You don't need to know what career you want yet. I'll ask one question at a time — about 8 to 12 — and then show you what I understood before suggesting anything.<br><span class='small'>{BOUNDARY} Nothing is added to your saved record until you approve it at the end; while you work, your answers are kept in a resumable session file on this computer. A first name is plenty.</span></p>", unsafe_allow_html=True)
    col, side = st.columns([3, 1.3])
    with side:
        st.markdown(f"<span class='small'>Question {p['turn']} of up to {p['max_turns']}</span>", unsafe_allow_html=True); st.progress(min(p["turn"] / p["max_turns"], 1.0))
        cov = p.get("coverage") or {}
        st.markdown("<span class='kicker'>Still learning about</span>", unsafe_allow_html=True)
        for key, lab in CORE_LABELS.items():
            lvl = cov.get(key, "none"); g, aria = COVERAGE_GLYPH[lvl]
            st.markdown(f"<div class='small'><span role='img' aria-label='{aria}'>{g}</span> {lab}</div>", unsafe_allow_html=True)
        st.markdown("<div class='small' style='margin-top:6px'>A fixed rule picks the next topic from these gaps; the AI only words the question.</div>", unsafe_allow_html=True)
    with col:
        st.markdown(f"### {p['question']}")
        text = st.text_area("answer", placeholder="Type as much or as little as you like…", height=110, label_visibility="collapsed", key=f"ans{p['turn']}")
        b = st.columns([1.4, 1, 1, 1, 1])
        if b[0].button("Send →", type="primary", width="stretch"):
            if text.strip(): route(S, run(S, Command(resume={"action": "answer", "text": text.strip()})))
        if b[1].button("I'm not sure"): route(S, run(S, Command(resume={"action": "unsure"})))
        if b[2].button("Skip"): route(S, run(S, Command(resume={"action": "skip"})))
        if p.get("can_recommend") and b[3].button("Recommend careers now"): route(S, run(S, Command(resume={"action": "recommend"})))
        if p["turn"] > 8 and b[4].button("Ask me more"): route(S, run(S, Command(resume={"action": "more"})))
    if p.get("profile") is not None:
        with st.expander("What NextShift currently understands about you"):
            st.markdown("<p class='small'>Built only from your answers — each item shows the words it rests on. Nothing here is a verdict; edit an answer to change it.</p>", unsafe_allow_html=True)
            for si, sec in enumerate(J.understands_sections(p["profile"])):
                st.markdown(f"**{sec['title']}**")
                if not sec["items"]: st.markdown("<div class='small'>Not mentioned yet.</div>", unsafe_allow_html=True); continue
                for ii, it in enumerate(sec["items"][:6]):
                    tag = f" <span class='small'>· {it['tag']}</span>" if it.get("tag") else ""
                    st.markdown(f"- {it['value']}{tag}", unsafe_allow_html=True)
                    qn = f" (Q{it['turn']})" if it.get("turn") and it["turn"] < 100 else ""
                    if it.get("quote"): st.markdown(f"<div class='small' style='margin-left:18px'>Based on your answer{qn}: “{it['quote']}”</div>", unsafe_allow_html=True)
                    if it.get("turn") and it["turn"] < 100 and any(t["i"] == it["turn"] for t in p["previous"]) and st.button(f"Edit Q{it['turn']}", key=f"edq_{si}_{ii}"): S.edit_turn = it["turn"]; st.rerun()
    with col:
        if p["previous"]:
            with st.expander("Edit an earlier answer", expanded=bool(S.get("edit_turn"))):
                labels = [f"Q{t['i']}: {t['question'][:70]}" for t in p["previous"]]; idx = next((i for i, t in enumerate(p["previous"]) if t["i"] == S.get("edit_turn")), 0)
                pick = st.selectbox("Which one?", labels, index=idx, label_visibility="collapsed")
                t = p["previous"][labels.index(pick)]; new = st.text_area("Your new answer", value=t["answer"], key=f"edit{t['i']}", height=80)
                if st.button("Save this answer"): S.edit_turn = None; route(S, run(S, Command(resume={"action": "edit", "edit_turn": t["i"], "text": new})))

# ───────────────────────────── understanding gate ─────────────────────────────
def screen_understanding(S):
    p = S.payload; comp = p["completeness"]
    st.markdown("<span class='kicker'>⏸ Before I suggest anything</span>", unsafe_allow_html=True); st.markdown("## Here's what I understand about you.")
    st.markdown(f"<p class='muted'>Edit anything that's off. {'Based on a short conversation — the more you tell me, the better the suggestions get.' if comp.get('thin') else ''}</p>", unsafe_allow_html=True)
    edited = {}
    for k, title in p["titles"].items():
        edited[k] = st.text_area(title, value=p["sections"].get(k, ""), height=80, key=f"sec_{k}")
    changed = any(edited[k] != p["sections"].get(k, "") for k in edited)
    b = st.columns([2, 1.2, 1, 1])
    if b[0].button("Looks right — find careers →", type="primary", width="stretch"):
        with st.status("Thinking of directions, matching them to real occupations, checking employment outlook and where AI is already used…", expanded=True) as box:
            p2 = run(S, Command(resume={"action": "edit" if changed else "confirm", "sections": edited if changed else None}), box)
        route(S, p2)
    if b[1].button("Back to the interview"): route(S, run(S, Command(resume={"action": "back"})))
    if b[3].button("Stop here"): route(S, run(S, Command(resume={"action": "reject"})))

# ───────────────────────────── results + reactions ─────────────────────────────
def card_html(c: dict) -> str:
    cd = c["card"]; d, dc = DEMAND[cd.get("demand_reading", "unknown")]
    facts = [strip_refs(f) for f in cd.get("facts", []) if any(w in f for w in ("openings", "change", "wage"))][:3]
    edu = cd.get("education_entry") or "—"
    rows = [("Why it may fit you", cd.get("why_fit")), ("What the work is like", cd.get("what_work_is_like")), ("How AI may reshape it", cd.get("how_ai_may_reshape")), ("Human capabilities that stay important", cd.get("human_capabilities")), ("Possible mismatch", cd.get("tradeoff"))]
    body = "".join(f"<div class='task'><span class='small'>{lab}</span><br>{strip_refs(v)}</div>" for lab, v in rows if strip_refs(v))
    body += "".join(f"<div class='task' style='border-color:{C['red']}'><span class='small'>Practical mismatch</span><br>{strip_refs(fl)}</div>" for fl in cd.get("constraint_flags", []))
    proxy = f"<div class='small'>No official category for this role — figures are for the closest official occupations.</div>" if c.get("resolution") == "composite" else ""
    return (f"<div class='card'><b style='font-size:17px'>{c['label']}</b> <span class='small'>· {c['persona']['title']}</span><br>{pill('Demand ' + d, dc)} {pill('AI-related change ' + CHANGE[cd.get('ai_change_reading', 'unknown')], C['purple'])} "
            f"<span class='small'>education: {edu} · evidence: {str(cd.get('evidence_confidence', '')).split(' ')[0]}</span>{proxy}" + ("".join(f"<div class='small'>· {f}</div>" for f in facts)) + body + "</div>")

def screen_results(S):
    p = S.payload; v = p["views"]
    st.markdown("<span class='kicker'>Career directions</span>", unsafe_allow_html=True); st.markdown("## Directions that might fit you")
    if v.get("review_status") == "unverified": st.error("Our independent review step failed, so these cards were checked for citations only — not for accuracy. Treat them as a draft.")
    st.markdown(" ".join(f"<span class='badge'>{b}</span>" for b in v["badges"]), unsafe_allow_html=True)
    st.markdown(f"<p class='small'>{BOUNDARY}</p>", unsafe_allow_html=True)
    if not any(v["groups"].values()):
        st.warning("I couldn't put together career directions this time (the generation step failed). Nothing was saved.")
        if st.button("Try again from my profile"): route(S, run(S, Command(resume={"action": "back_to_understanding"})))
        if st.button("Stop"): route(S, run(S, Command(resume={"action": "stop"}))); return
    reactions = {}
    for g, cs in v["groups"].items():
        if not cs: continue
        st.markdown(f"### {v['group_label'][g]}")
        for c in cs:
            st.markdown(card_html(c), unsafe_allow_html=True)
            cols = st.columns([1, 1, 1, 3])
            verdict = None
            for col, (lab, val) in zip(cols, [("😀 Excited", "excited"), ("🤔 Curious", "curious"), ("✕ Not for me", "no")]):
                if col.checkbox(lab, key=f"rx_{c['key']}_{val}"): verdict = val
            why = cols[3].text_input("What appeals — or doesn't?", key=f"why_{c['key']}", placeholder="e.g. I like the people part, not the paperwork", label_visibility="collapsed")
            if verdict: reactions[c["key"]] = {"key": c["key"], "verdict": verdict, "why": why}
            with st.expander("Why this appeared →"): why_this_appeared(c, v)
    with st.expander("How we reached this"): render_run_details(S, v, candidates=[c for g in v["groups"].values() for c in g])
    st.markdown("---"); st.markdown("### Which of these speaks to you, and what about it appeals?")
    b = st.columns([2, 1, 1])
    if b[0].button("Continue with my reactions →", type="primary", width="stretch", disabled=not reactions):
        with st.status("Taking in your reactions…", expanded=True) as box: p2 = run(S, Command(resume={"action": "continue", "reactions": list(reactions.values())}), box)
        route(S, p2)
    if b[2].button("Stop here"): route(S, run(S, Command(resume={"action": "stop"})))

def screen_discriminate(S):
    p = S.payload; st.markdown("<span class='kicker'>One or two more questions</span>", unsafe_allow_html=True); st.markdown("## To help separate your options")
    answers = [st.text_area(q["text"], key=f"disc{i}", height=80) for i, q in enumerate(p["questions"])]
    if st.button("Continue →", type="primary"):
        with st.status("Building your shortlist…", expanded=True) as box: p2 = run(S, Command(resume={"answers": answers}), box)
        route(S, p2)

# ───────────────────────────── shortlist ─────────────────────────────
def screen_shortlist(S):
    p = S.payload; v = p["views"]; sl = v["shortlist"]; cands = {c["key"]: c for g in v["groups"].values() for c in g}
    st.markdown("<span class='kicker'>Your shortlist</span>", unsafe_allow_html=True); st.markdown("## " + " · ".join(cands[k]["label"] for k in sl["keys"] if k in cands))
    if v.get("whatif"): st.info(f"**{v['whatif']['question']}** — {strip_refs(v['whatif']['note'])}")
    dims = ["personal_fit", "daily_work", "outlook", "education_time_cost", "lifestyle", "ai_related_change", "human_edge", "uncertainty"]
    import pandas as pd
    table = pd.DataFrame({cands[k]["label"]: [strip_refs(sl["rows"].get(k, {}).get(d, "")) for d in dims] for k in sl["keys"] if k in cands}, index=[d.replace("_", " ") for d in dims])
    st.dataframe(table, width="stretch", height=min(60 + 60 * len(dims), 560))
    if strip_refs(sl.get("our_read")): st.markdown(f"<div class='card'><span class='kicker'>Our read</span> <span class='small'>a reasoned interpretation, not a verdict</span><br>{strip_refs(sl['our_read'])}</div>", unsafe_allow_html=True)
    st.markdown("### Go deeper on one")
    pick = st.radio("pick", [cands[k]["label"] for k in sl["keys"] if k in cands], horizontal=True, label_visibility="collapsed")
    key = next(k for k in sl["keys"] if cands[k]["label"] == pick)
    b = st.columns([1.6, 1.6, 1.2, 1, 1])
    if b[0].button("Deep dive →", type="primary", width="stretch"):
        with st.status("Writing the deep dive and checking it…", expanded=True) as box: p2 = run(S, Command(resume={"action": "pick", "key": key}), box)
        route(S, p2)
    wi = b[1].selectbox("what if", ["What if…", "What if I don't want graduate school?", "What if salary matters more?", "What if I want remote work?", "Show me similar careers"], label_visibility="collapsed")
    if wi != "What if…" and b[2].button("Ask"):
        with st.status("Reconsidering…", expanded=True) as box: p2 = run(S, Command(resume={"action": "whatif", "whatif": wi}), box)
        route(S, p2)
    if b[3].button("Back to all cards"): route(S, run(S, Command(resume={"action": "back_to_results"})))
    if b[4].button("Save & finish"): route(S, run(S, Command(resume={"action": "save"})))

# ───────────────────────────── deep dive + explore ─────────────────────────────
TITLES = {"why_fit": "1. Why this career may fit you", "what_people_do": "2. What people in this career actually do", "education_and_entry": "3. Education and entry paths", "outlook": "4. Employment outlook", "how_ai_may_change": "5. How AI may change the role",
          "ai_already_used_for": "6. Tasks where AI is already commonly used", "human_capabilities": "7. Human capabilities that may remain important", "risks_tradeoffs_uncertainty": "8. Risks, tradeoffs and uncertainty", "what_to_do_in_school": "9. What to do during high school or college", "test_this_career": "10. Test this career before committing"}

def screen_deep(S):
    p = S.payload; dd = p["deep_dive"]; rv_ = dd.get("review", {})
    st.markdown("<span class='kicker'>Deep dive</span>", unsafe_allow_html=True); st.markdown(f"## {dd['label']} <span class='small'>· {dd['title']}</span>", unsafe_allow_html=True)
    if rv_.get("status") == "unverified": st.error("The review step failed for this deep dive — checked for citations only.")
    for k, title in TITLES.items():
        val = dd["sections"].get(k)
        if not val: continue
        st.markdown(f"### {title}")
        if k == "test_this_career": st.markdown(f"<div class='card' style='border-color:{C['student']}66'>" + "".join(f"<div class='task' style='border-color:{C['student']}'>{strip_refs(x)}</div>" for x in val) + "</div>", unsafe_allow_html=True)
        elif isinstance(val, list): [st.markdown(f"- {strip_refs(x)}") for x in val]
        else: st.markdown(strip_refs(val))
    st.markdown(f"<p class='small'>Reviewer checked {rv_.get('total', 0)} lines, removed {len(rv_.get('stripped', []))}. {BOUNDARY}</p>", unsafe_allow_html=True)
    st.markdown("---"); st.markdown("### Keep exploring")
    b = st.columns([1.6, 1.4, 1.2, 1, 1.2])
    wi = b[0].selectbox("what if", ["What if…", "What if I don't want graduate school?", "What if salary matters more?", "What if I want remote work?", "Show me similar careers", "Help me test whether I'd enjoy this"], label_visibility="collapsed")
    if wi != "What if…" and b[1].button("Ask"):
        with st.status("Reconsidering…", expanded=True) as box: p2 = run(S, Command(resume={"action": "whatif", "whatif": wi}), box)
        route(S, p2)
    others = [k for k in p["shortlist"] if k != dd["key"]]
    if others and b[2].button("Compare with another"): route(S, run(S, Command(resume={"action": "compare", "key": others[0]})))
    if b[3].button("Back to shortlist"): route(S, run(S, Command(resume={"action": "back_to_shortlist"})))
    if b[4].button("Save & finish", type="primary"): route(S, run(S, Command(resume={"action": "save"})))

# ───────────────────────────── save gate ─────────────────────────────
def screen_save(S):
    p = S.payload; s = p["summary"]
    st.markdown("<span class='kicker'>⏸ Your approval</span>", unsafe_allow_html=True); st.markdown("## Save your exploration?")
    if s.get("review_status") == "unverified": st.warning("Parts of this exploration were not independently reviewed; the saved file will be marked UNVERIFIED.")
    st.markdown(f"<div class='card'><b>Shortlist:</b> {', '.join(s['shortlist']) or '—'}<br><b>Went deeper on:</b> {s.get('selected') or '—'}<br><b>Not for me:</b> {', '.join(s['rejected']) or '—'}</div>", unsafe_allow_html=True)
    st.markdown("**Experiments I plan to try** (edit freely)")
    exps = st.text_area("experiments", value="\n".join(strip_refs(x) for x in s["experiments"]), height=140, label_visibility="collapsed")
    b = st.columns([2, 1, 1])
    if b[0].button("Save my exploration", type="primary", width="stretch"):
        with st.status("Saving…") as box: run(S, Command(resume={"action": "approve", "experiments": [x for x in exps.split("\n") if x.strip()]}), box)
        S.stage = "s_done"; st.rerun()
    if b[2].button("Don't save"):
        with st.status("Closing without saving…") as box: run(S, Command(resume={"action": "reject"}), box)
        S.stage = "s_done"; st.rerun()

def screen_done(S, reset):
    st_ = sgraph().get_state({"configurable": {"thread_id": S.thread_id}}).values; ap = st_.get("approvals", {})
    S.final_state = {"approvals": ap, "exported_path": st_.get("exported_path"), "views": st_.get("views")}
    if callable(S.get("on_phase")): S.on_phase()   # journey indicator learns how the run ended
    if st_.get("exported_path"):
        from pathlib import Path
        st.success("Saved. Come back any time to continue exploring — your shortlist, reactions and planned experiments are kept."); st.download_button("Download (.md)", Path(st_["exported_path"]).read_text(), file_name=Path(st_["exported_path"]).name)
    elif ap.get("understanding", {}).get("action") == "reject": st.warning("Stopped before any career data was gathered — nothing was saved.")
    elif ap.get("save", {}).get("action") == "reject": st.warning("Nothing was saved.")
    else: st.info("Session ended — nothing was saved.")
    if st.button("Start again"): reset(); st.rerun()

SCREENS = {"s_interview_run": screen_interview_run, "s_interview": screen_interview, "s_understanding": screen_understanding, "s_results": screen_results, "s_discriminate": screen_discriminate,
           "s_shortlist": screen_shortlist, "s_deep": screen_deep, "s_save": screen_save}


# ───────────────────────────── explanations (reviewed data only; no generation) ─────────────────────────────
SRC_GLYPH = {"used": ("●", "used"), "partial": ("◑", "partial"), "unavailable": ("○", "unavailable")}

def why_this_appeared(c: dict, v: dict):
    """Two groups: what the student said (cited rationale, deterministically checked) and career evidence (the reviewed card). Never a score."""
    w = J.why_this_appeared(c, v)
    st.markdown(f"<div class='small'>{w['resolution']['text']}</div>", unsafe_allow_html=True)
    a, b = st.columns(2)
    with a:
        st.markdown("**Based on what you told us**")
        if not w["told"]: st.markdown("<div class='small'>No rationale line for this card survived the checks.</div>", unsafe_allow_html=True)
        for it in w["told"]:
            st.markdown(f"- {it['text']} <span class='small'>· {it['label'].lower()}</span>", unsafe_allow_html=True)
            for q in it["quotes"]: st.markdown(f"<div class='small' style='margin-left:18px'>Based on your answer: “{q}”</div>", unsafe_allow_html=True)
        if w["conflicts"]:
            st.markdown("**May conflict with what you said**")
            for it in w["conflicts"]:
                st.markdown(f"- {it['text']} <span class='small'>· {it['label'].lower()}</span>", unsafe_allow_html=True)
                for q in it["quotes"]: st.markdown(f"<div class='small' style='margin-left:18px'>Based on your answer: “{q}”</div>", unsafe_allow_html=True)
    with b:
        e = w["evidence"]; st.markdown("**Based on career evidence**")
        for f in e["outlook"]: st.markdown(f"- {f} <span class='small'>· official outlook</span>", unsafe_allow_html=True)
        st.markdown(f"- Typical entry education: {e['education']}")
        for t in e["tasks_ai_used"]: st.markdown(f"- {t} <span class='small'>· current AI use, not automation</span>", unsafe_allow_html=True)
        for t in e["stays_human"]: st.markdown(f"- {t} <span class='small'>· interpretation</span>", unsafe_allow_html=True)
        if e["tradeoff"]: st.markdown(f"- {e['tradeoff']} <span class='small'>· tradeoff</span>", unsafe_allow_html=True)
        for u in e["unknowns"]: st.markdown(f"- {u} <span class='small'>· unknown</span>", unsafe_allow_html=True)
        if e["confidence"]: st.markdown(f"<div class='small'>Evidence confidence: {e['confidence']}</div>", unsafe_allow_html=True)
    if w["removed"]: st.markdown(f"<div class='small'>The reviewer removed {w['removed']} line(s) from this card — listed under <i>How we reached this</i>.</div>", unsafe_allow_html=True)

def render_run_details(S, v: dict, candidates: list[dict] | None = None):
    """User-facing facts about this run. Model names, cost, tool counts and the raw step log live in developer mode."""
    from ui import explain
    rd = J.run_details(v, candidates)
    st.markdown("**Sources in this run** — " + " · ".join(f"<span role='img' aria-label='{SRC_GLYPH[s['status']][1]}'>{SRC_GLYPH[s['status']][0]}</span> {s['name']} ({s['status']})" for s in rd["sources"]), unsafe_allow_html=True)
    if rd["occupations"]:
        st.markdown("**Occupations looked up**")
        for o in rd["occupations"]: st.markdown(f"- {o['label']}" + (f" → {o['title']}" if o.get("title") and o["title"] != o["label"] else "") + f" <span class='small'>· {o['kind']}</span>", unsafe_allow_html=True)
    st.markdown(f"**Evidence** — {rd['n_cards']} pieces of evidence. **Review** — " + ("<b>UNVERIFIED</b>: the independent reviewer failed; only the citation check ran." if not rd["verified"] else "verified by a separate reviewer.") +
                f" {len(rd['removed'])} line(s) removed" + (f", plus {rd['rationale_removed']} rationale line(s) that did not cite your words" if rd.get("rationale_removed") else "") + ".", unsafe_allow_html=True)
    for r in rd["removed"][:10]: st.markdown(f"<div class='task'>✂ {r['text'][:140]}<br><span class='p'>{r['reason'][:120]}</span></div>", unsafe_allow_html=True)
    if rd["disagreements"]: st.markdown("**Where sources disagree**"); [st.markdown(f"- {d.get('spread', '')} across {', '.join(d.get('sources', []))}: {d.get('topic', '')}") for d in rd["disagreements"]]
    if rd["unknowns"]: st.markdown("**Known unknowns**"); [st.markdown(f"- {u}") for u in rd["unknowns"][:10]]
    if v.get("forecast_context"): st.markdown("**Forecast context (conditional)**"); [st.markdown(f"- {strip_refs(f)}") for f in v["forecast_context"]]
    done = [s["label"] for s in explain.journey(S) if s["state"] == "done" and s["label"].startswith(("Checking that we understood", "Learning from your reactions", "Waiting"))]
    human = [{"Checking that we understood": "You confirmed what we understood", "Learning from your reactions": "You reacted to the directions", "Waiting for your approval": "You approved the save"}[d] for d in done]
    st.markdown("**Your decisions so far** — " + (" · ".join(human) if human else "none yet; nothing is saved until you approve"))
    st.markdown(f"**Saved result** — {'would be marked UNVERIFIED' if not rd['verified'] else 'will be marked verified'} when you approve." if not S.get("final_state") else f"**Saved result** — {'UNVERIFIED' if not rd['verified'] else 'verified'}.")
    cards = v.get("cards_by_family") or {}
    if any(cards.values()):
        with st.expander(f"Evidence used ({rd['n_cards']})"):
            for fam, cs in cards.items():
                if cs: st.markdown(f"_{fam}_ ({len(cs)})"); [st.markdown(f"<div class='task'>{c['claim'][:160]}<br><span class='p'>{c['source']} · {c.get('as_of') or ''}" + (f" · <a href='{c.get('url')}'>source</a>" if c.get('url') else "") + "</span></div>", unsafe_allow_html=True) for c in cs[:12]]
    if explain.dev_enabled(S):
        with st.expander("Developer mode — this run"): explain.dev_block(S)
