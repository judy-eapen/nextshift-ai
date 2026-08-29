"""Student journey screens (career-discovery interviewer). Imported by ui/app.py; shares the shell (theme, session state, strip_refs).
Stages: s_interview_run → s_interview → s_understanding → s_working → s_results → s_discriminate → s_shortlist → s_deep → s_save → s_done."""
from __future__ import annotations
import re, uuid
import streamlit as st
from langgraph.types import Command

C = {"amber": "#E5A24A", "student": "#7FC8E8", "green": "#8FBF9F", "red": "#E07A5F", "purple": "#B48CFF", "muted": "#8A94A6", "line": "#2A3544"}
DEMAND = {"growing": ("▲ Growing", C["green"]), "stable": ("● Stable", C["amber"]), "declining": ("▼ Declining", C["red"]), "unknown": ("? No official projection", C["muted"])}
CHANGE = {"substantial": "◆ Substantial", "moderate": "◆ Moderate", "limited": "◆ Limited", "unknown": "? Unknown"}
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
            S.log.append(ev["say"])
            if box is not None: box.write(f"· {ev['say']}")
        elif "__interrupt__" in ev: return ev["__interrupt__"][0].value
    return None

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
        st.markdown(f"<p class='muted'>You don't need to know what career you want yet. I'll ask one question at a time — about 8 to 12 — and then show you what I understood before suggesting anything.<br><span class='small'>{BOUNDARY} Nothing you type is stored until you approve it at the end; a first name is plenty.</span></p>", unsafe_allow_html=True)
    col, side = st.columns([3, 1.3])
    with side:
        st.markdown(f"<span class='small'>Question {p['turn']} of about {p['max_turns']}</span>", unsafe_allow_html=True); st.progress(min(p["turn"] / p["max_turns"], 1.0))
        if p["learned"]:
            st.markdown("<span class='kicker'>What I've learned so far</span>", unsafe_allow_html=True)
            for l in p["learned"][:8]: st.markdown(f"<div class='small'>· {l[:90]}</div>", unsafe_allow_html=True)
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
        if p["previous"]:
            with st.expander("Edit an earlier answer"):
                labels = [f"Q{t['i']}: {t['question'][:70]}" for t in p["previous"]]; pick = st.selectbox("Which one?", labels, label_visibility="collapsed")
                t = p["previous"][labels.index(pick)]; new = st.text_area("Your new answer", value=t["answer"], key=f"edit{t['i']}", height=80)
                if st.button("Save this answer"): route(S, run(S, Command(resume={"action": "edit", "edit_turn": t["i"], "text": new})))

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
            with st.expander("Why this was suggested"):
                for k, lines in c["rationale"].items():
                    if isinstance(lines, list) and lines: st.markdown(f"**{k.replace('_', ' ')}** — " + "; ".join(strip_refs(l) for l in lines))
                    elif isinstance(lines, str) and lines.strip(): st.markdown(f"**{k.replace('_', ' ')}** — {strip_refs(lines)}")
                if c.get("review", {}).get("removed"): st.markdown(f"<span class='small'>Reviewer removed {len(c['review']['removed'])} line(s) from this card.</span>", unsafe_allow_html=True)
    with st.expander("How we reached this"):
        sk = v["skeptic"]; st.markdown(f"**Reviewer** ({sk['model'].split('/')[-1]}): {sk['total']} lines checked, {len(sk['stripped'])} removed. **Sources:** " + " · ".join(f"{'🟢' if s=='ok' else '🟡' if s=='partial' else '🔴'} {k}" for k, s in v["source_status"].items()))
        for s_ in sk["stripped"][:10]: st.markdown(f"<div class='task'>✂ {s_['sentence'][:140]}<br><span class='p'>{s_['reason'][:120]}</span></div>", unsafe_allow_html=True)
        st.markdown("**Known unknowns**"); [st.markdown(f"- {u}") for u in v["unknowns"][:10]]
        st.markdown("**Forecast context (conditional)**"); [st.markdown(f"- {strip_refs(f)}") for f in v["forecast_context"]]
        st.markdown(f"**Run** — {v['budget']['tool_calls']} tool calls · est. ${v['budget']['cost_usd']:.3f}"); [st.markdown(f"<div class='small'>· {l}</div>", unsafe_allow_html=True) for l in S.log[-25:]]
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
    if st_.get("exported_path"):
        from pathlib import Path
        st.success("Saved. Come back any time to continue exploring — your shortlist, reactions and planned experiments are kept."); st.download_button("Download (.md)", Path(st_["exported_path"]).read_text(), file_name=Path(st_["exported_path"]).name)
    elif ap.get("understanding", {}).get("action") == "reject": st.warning("Stopped before any career data was gathered — nothing was saved.")
    elif ap.get("save", {}).get("action") == "reject": st.warning("Nothing was saved.")
    else: st.info("Session ended — nothing was saved.")
    if st.button("Start again"): reset(); st.rerun()

SCREENS = {"s_interview_run": screen_interview_run, "s_interview": screen_interview, "s_understanding": screen_understanding, "s_results": screen_results, "s_discriminate": screen_discriminate,
           "s_shortlist": screen_shortlist, "s_deep": screen_deep, "s_save": screen_save}
