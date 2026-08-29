"""NextShift AI — plan your career for an AI-shaped job market.  Run: streamlit run ui/app.py
Flow: Start → guided intake (student | professional) → ⏸ understanding gate → working → your plan → ⏸ plan gate → saved.
Technical detail (evidence, forecasts, reviewer, run metrics) lives behind "How we reached this answer"."""
from __future__ import annotations
import os, re, sys, uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
import streamlit as st, pandas as pd
from langgraph.types import Command
from ui import student_ui

st.set_page_config(page_title="NextShift AI", page_icon="⟶", layout="centered")
C = {"bg": "#0B0F14", "surface": "#121821", "line": "#2A3544", "ink": "#E6EAF0", "muted": "#8A94A6", "amber": "#E5A24A", "student": "#7FC8E8", "green": "#8FBF9F", "red": "#E07A5F", "purple": "#B48CFF"}
st.markdown(f"""<style>
.stApp {{ background:{C['bg']}; }} h1,h2,h3 {{ font-family: Archivo, 'IBM Plex Sans', sans-serif; letter-spacing:-0.01em; }}
.card {{ background:{C['surface']}; border:1px solid {C['line']}; border-radius:12px; padding:18px 20px; margin:10px 0; }}
.kicker {{ color:{C['amber']}; font-size:11px; letter-spacing:.14em; text-transform:uppercase; font-weight:600; }}
.muted {{ color:{C['muted']}; font-size:14px; }} .small {{ color:{C['muted']}; font-size:12px; }}
.answer {{ font-size:18px; line-height:1.55; }}
.badge {{ display:inline-block; border:1px solid {C['amber']}; color:{C['amber']}; border-radius:6px; padding:2px 8px; font-size:12px; margin:2px 6px 2px 0; }}
.pill {{ display:inline-block; border-radius:999px; padding:3px 10px; font-size:13px; font-weight:600; margin-right:8px; }}
.task {{ border-left:3px solid {C['line']}; padding:6px 10px; margin:6px 0; font-size:14px; }} .task .p {{ color:{C['muted']}; font-size:12px; }}
.done {{ color:{C['muted']}; font-size:14px; padding:4px 0; }} .done b {{ color:{C['ink']}; }}
</style>""", unsafe_allow_html=True)

@st.cache_resource
def graph():
    from graph.build import build_graph; return build_graph()

S = st.session_state
S.setdefault("stage", "start"); S.setdefault("door", None); S.setdefault("step", 0); S.setdefault("profile", {}); S.setdefault("targets", []); S.setdefault("log", [])
HZ = {"1-2y": "Next 1–2 years", "2030": "By 2030", "2035": "By 2035"}

def reset():
    for k in list(S.keys()): del S[k]
    S.stage = "start"

def strip_refs(text) -> str:
    """Hide [cNN]/[uNN]/[interpretation]/[advice] tags from the reader; the evidence drawer still shows them."""
    return re.sub(r"\s*\[(?:[cu]\d{2,3}|interpretation|advice)\]", "", str(text or "")).strip()

def run_graph(inp, box):
    cfg = {"configurable": {"thread_id": S.thread_id}}
    for mode, ev in graph().stream(inp, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom":
            if "phase" in ev:
                S.phase = ev
                if callable(S.get("on_phase")): S.on_phase()
                continue
            S.log.append(ev["say"]); box.write(f"· {ev['say']}")
        elif "__interrupt__" in ev: S.phase = None; return ev["__interrupt__"][0].value
    S.phase = None; return None

# ═══════════════════════════ START ═══════════════════════════
def screen_start():
    st.markdown("<span class='kicker'>NextShift AI</span>", unsafe_allow_html=True)
    st.markdown("## Plan your career for an AI-shaped job market.")
    st.markdown("<p class='muted'>Understand how demand for a career may change, how AI may reshape the work, and what you can do to prepare.</p>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='card' style='border-color:{C['student']}66'><span class='kicker' style='color:{C['student']}'>Students</span><h3 style='margin:6px 0'>I'm exploring careers</h3><p class='muted'>You don't need to know what you want yet — a short conversation, then directions worth exploring.</p></div>", unsafe_allow_html=True)
        if st.button("Start exploring →", width="stretch"): S.door = "student"; student_ui.start(S)
    with c2:
        st.markdown("<div class='card'><span class='kicker'>Professionals</span><h3 style='margin:6px 0'>I'm preparing for changes in my career</h3><p class='muted'>See what's coming for your role and what to do now.</p></div>", unsafe_allow_html=True)
        if st.button("Start planning →", type="primary", width="stretch"): S.door = "professional"; S.profile = {"door": "professional"}; S.stage = "intake"; S.step = 0; st.rerun()
    st.markdown("<p class='small' style='margin-top:24px'>Evidence: BLS employment projections · O*NET tasks · Anthropic Economic Index · AIOE · Polymarket, Manifold, Metaculus · Epoch AI · FRED. Every plan is checked line by line and approved by you before it's saved.</p>", unsafe_allow_html=True)

# ═══════════════════════════ INTAKE (guided turns) ═══════════════════════════
def done_line(label, value): st.markdown(f"<div class='done'>✓ {label}: <b>{value}</b></div>", unsafe_allow_html=True)

def resolve_targets_professional():
    from tools.resolve import resolve, with_composites
    from tools.composite import persona_from
    p = S.profile; r = with_composites(resolve(p["role_title"], p.get("week_description", ""), k=3), p["role_title"], p.get("week_description", ""))
    S.candidates = r
    if r.get("composites"):   # prefer a curated composite, then a described one
        per = persona_from(r["composites"][0], 2030); per.pop("horizon", None); return [{"persona": per, "role": "current"}]
    m = r["matches"][0]; return [{"persona": {"soc": m["soc"], "onet_soc": m.get("onet_soc") or f"{m['soc']}.00", "title": m["title"], "matched_via": f"tier {r['tier']}"}, "role": "current"}]

def resolve_targets_student(careers: list[str]) -> list[dict]:
    from tools.resolve import resolve
    out = []
    for c in careers[:3]:
        r = resolve(c, "", k=1); m = r["matches"][0] if r.get("matches") else None
        if m: out.append({"persona": {"soc": m["soc"], "onet_soc": m.get("onet_soc") or f"{m['soc']}.00", "title": m["title"], "matched_via": f"tier {r['tier']}: {c}"}, "role": "candidate"})
    return out

def suggest_careers(interests: str, strengths: str) -> list[str]:
    from tools.resolve import semantic_match
    try: return [m["title"] for m in semantic_match(f"A career for someone interested in {interests}, good at {strengths}.", 5)]
    except Exception: return []

def screen_intake():
    p = S.profile; step = S.step
    st.markdown(f"<span class='kicker'>{'Exploring careers' if S.door == 'student' else 'Preparing for change'}</span>", unsafe_allow_html=True)
    if S.door == "professional":
        if step > 0: done_line("Role", p["role_title"])
        if step > 1: done_line("Your week", p["week_description"][:90] + ("…" if len(p["week_description"]) > 90 else ""))
        if step > 2: done_line("Industry", p["industry"] or "—")
        if step == 0:
            st.markdown("### What's your current role?"); v = st.text_input("role", placeholder="e.g. Product Manager, Paralegal, Registered Nurse", label_visibility="collapsed")
            if st.button("Continue →", type="primary") and v.strip(): p["role_title"] = v.strip(); S.step = 1; st.rerun()
        elif step == 1:
            st.markdown("### What does a normal week actually look like?"); st.markdown("<p class='muted'>Titles are ambiguous; tasks aren't. Two or three lines is plenty.</p>", unsafe_allow_html=True)
            v = st.text_area("week", placeholder="e.g. user research, writing requirements, prioritizing with engineering, stakeholder alignment, launch coordination", label_visibility="collapsed", height=100)
            if st.button("Continue →", type="primary") and v.strip(): p["week_description"] = v.strip(); S.step = 2; st.rerun()
        elif step == 2:
            st.markdown("### What industry are you in?"); v = st.text_input("industry", placeholder="e.g. real-estate software, hospital system, public accounting", label_visibility="collapsed")
            if st.button("Continue →", type="primary"): p["industry"] = v.strip(); S.step = 3; st.rerun()
        elif step == 3:
            st.markdown("### What's on your mind most?")
            opts = {"demand": "Will demand for my role hold?", "change": "How will my responsibilities change?", "learn": "What should I learn?", "pivot": "Should I consider a different path?"}
            picked = [k for k, lbl in opts.items() if st.checkbox(lbl, value=k in ("demand", "change", "learn"))]
            h = st.radio("Time horizon", list(HZ), format_func=HZ.get, horizontal=True)
            if st.button("Continue →", type="primary") and picked:
                p["concerns"], p["horizon"] = picked, h; p["question"] = "; ".join(opts[k] for k in picked)
                with st.spinner("Matching your work to the official occupation list…"): S.targets = resolve_targets_professional()
                S.thread_id = str(uuid.uuid4()); S.log = []; S.stage = "understanding_run"; st.rerun()
    else:
        if step > 0: done_line("Interests", ", ".join(p["interests"]))
        if step > 1: done_line("Strengths", ", ".join(p["strengths"]) or "—")
        if step > 2: done_line("Considering", ", ".join(p["careers"]))
        if step == 0:
            st.markdown("### What subjects or activities pull you in?"); v = st.text_input("interests", placeholder="e.g. psychology, design, technology", label_visibility="collapsed")
            if st.button("Continue →", type="primary") and v.strip(): p["interests"] = [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]; S.step = 1; st.rerun()
        elif step == 1:
            st.markdown("### What are you naturally good at, or enjoy doing?"); v = st.text_input("strengths", placeholder="e.g. visual thinking, listening to people, writing, math", label_visibility="collapsed")
            if st.button("Continue →", type="primary"): p["strengths"] = [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]; S.step = 2; st.rerun()
        elif step == 2:
            st.markdown("### Which careers are you considering?"); st.markdown("<p class='muted'>Up to three. Not sure? Start from the suggestions.</p>", unsafe_allow_html=True)
            if "suggestions" not in S:
                with st.spinner("Looking at careers that match your interests…"): S.suggestions = suggest_careers(", ".join(p["interests"]), ", ".join(p.get("strengths", [])))
            typed = st.text_input("Type careers, separated by commas", placeholder="e.g. Graphic Designer, UX Designer, Psychologist")
            chosen = st.multiselect("Or pick from suggestions", options=S.suggestions, label_visibility="visible", max_selections=3)
            if st.button("Continue →", type="primary") and (typed.strip() or chosen):
                p["careers"] = ([x.strip() for x in typed.split(",") if x.strip()] + chosen)[:3]; S.step = 3; st.rerun()
        elif step == 3:
            st.markdown("### Anything that shapes the decision?"); st.markdown("<p class='muted'>All optional.</p>", unsafe_allow_html=True)
            edu = st.select_slider("Education you're open to", ["Certificate / short program", "Associate (2-yr)", "Bachelor's (4-yr)", "Graduate degree"], value="Bachelor's (4-yr)")
            cost = st.radio("Cost sensitivity", ["Very", "Somewhat", "Not a constraint"], horizontal=True, index=1); loc = st.text_input("Location or remote preference", placeholder="e.g. stay near Richmond, VA; open to remote")
            h = st.radio("Time horizon", ["2030", "2035"], format_func=lambda x: f"By {x}", horizontal=True, index=1)
            if st.button("Continue →", type="primary"):
                p["constraints"] = {"education_max": edu, "cost": cost, "location": loc}; p["horizon"] = h; p["concerns"] = ["demand", "change"]; p["question"] = f"Which of {', '.join(p['careers'])} gives me good opportunities in an AI-shaped job market?"
                with st.spinner("Matching your options to official occupations…"): S.targets = resolve_targets_student(p["careers"])
                S.thread_id = str(uuid.uuid4()); S.log = []; S.stage = "understanding_run"; st.rerun()
    if st.button("← Start over"): reset(); st.rerun()

# ═══════════════════════════ UNDERSTANDING GATE ═══════════════════════════
def screen_understanding_run():
    with st.status("Reading what you told me…", expanded=False) as box:
        payload = run_graph({"profile": S.profile, "targets": S.targets, "thread_id": S.thread_id}, box)
    S.payload = payload; S.stage = "understanding" if payload and payload["kind"] == "understanding" else "done"; st.rerun()

def screen_understanding():
    pl = S.payload; prof = pl["profile"]; targets = pl["targets"]
    st.markdown("<span class='kicker'>⏸ Before I analyze anything</span>", unsafe_allow_html=True); st.markdown("## Here's what I understood — fix anything that's off.")
    summary = st.text_area("summary", value=prof.get("summary", ""), height=150, label_visibility="collapsed")
    st.markdown("<p class='small'>Occupation(s) I'll analyze:</p>", unsafe_allow_html=True)
    for ti, t in enumerate(targets):
        per = t["persona"]
        if per.get("composite"):
            st.markdown(f"<div class='card'><b>{per['title']}</b><br><span class='muted'>{per.get('note', '')}</span></div>", unsafe_allow_html=True)
            with st.expander(f"Review the {len(per['tasks'])} tasks — untick anything that isn't your week"):
                keep = [x for i, x in enumerate(per["tasks"]) if st.checkbox(f"{x['task']}  ·  _{x['title']}_", value=True, key=f"t{ti}_{i}")]
            per["tasks"] = keep; per["source_occupations"] = sorted({x["title"] for x in keep})
        else: st.markdown(f"<div class='card'><b>{per['title']}</b> <span class='small'>official occupation {per['onet_soc']}</span></div>", unsafe_allow_html=True)
    if S.get("candidates") and len(S.candidates.get("matches", [])) > 1 and S.door == "professional":
        with st.expander("Not the right occupation? Pick another"):
            alts = S.candidates["matches"]; labels = [f"{m['title']} · {m['onet_soc']}" for m in alts]; pick = st.radio("alt", labels, label_visibility="collapsed")
            if st.button("Use this one instead"):
                m = alts[labels.index(pick)]; S.targets = [{"persona": {"soc": m["soc"], "onet_soc": m.get("onet_soc") or f"{m['soc']}.00", "title": m["title"], "matched_via": "user-picked"}, "role": "current"}]
                S.payload["targets"] = S.targets; st.rerun()
    h = st.radio("Horizon", list(HZ), index=list(HZ).index(str(prof.get("horizon", "2030"))), format_func=HZ.get, horizontal=True)
    edited = summary != prof.get("summary") or h != str(prof.get("horizon")) or any(t["persona"].get("composite") for t in targets)
    b = st.columns([2, 1, 1])
    if b[0].button("That's right — analyze →", type="primary", width="stretch"):
        S.resume = {"action": "edit" if edited else "confirm", "profile": {"summary": summary, "horizon": h}, "targets": targets}; S.stage = "working"; st.rerun()
    if b[2].button("Stop here"): S.resume = {"action": "reject"}; S.stage = "working"; st.rerun()

def screen_working():
    st.markdown("## Working on your plan")
    with st.status("Gathering evidence…", expanded=True) as box:
        payload = run_graph(Command(resume=S.resume), box); box.update(label="Done", state="complete", expanded=False)
    S.payload = payload; S.stage = "plan" if payload and payload["kind"] == "plan" else "done"; st.rerun()

# ═══════════════════════════ YOUR PLAN + GATE 2 ═══════════════════════════
def pill(text, color): return f"<span class='pill' style='background:{color}22;color:{color};border:1px solid {color}66'>{text}</span>"
DEMAND = {"growing": ("▲ Growing", C["green"]), "stable": ("● Stable", C["amber"]), "declining": ("▼ Declining", C["red"]), "unknown": ("? No official projection", C["muted"])}
CHANGE = {"substantial": ("◆ Substantial", C["purple"]), "moderate": ("◆ Moderate", C["amber"]), "limited": ("◆ Limited", C["green"]), "unknown": ("? Unknown", C["muted"])}

def screen_plan():
    pl = S.payload; v = pl["views"]; plan = v["plan"]; outlooks = v["outlooks"]; changes = v["changes"]
    st.markdown("<span class='kicker'>Your plan</span>", unsafe_allow_html=True); st.markdown(f"## {' vs '.join(o['title'] for o in outlooks.values())}")
    if v.get("review_status") == "unverified": st.error("Our independent review step failed, so this plan has only been checked for citations — not for accuracy. Treat it as a draft; re-run later for a reviewed version.")
    if v["badges"]: st.markdown(" ".join(f"<span class='badge'>{b}</span>" for b in v["badges"]), unsafe_allow_html=True)
    st.markdown(f"<div class='card answer'>{strip_refs(plan.get('direct_answer', ''))}</div>", unsafe_allow_html=True)

    st.markdown("### 1. Your outlook")
    for o in outlooks.values():
        d, dc = DEMAND[o["demand_reading"]]; c, cc = CHANGE[o["ai_change_reading"]]
        st.markdown(f"<div class='card'><b>{o['title']}</b><br>{pill('Demand ' + d, dc)} <span class='small'>BLS projection 2025–35</span><br>{pill('AI-related change ' + c, cc)} <span class='small'>our interpretation of current AI use</span>" +
                    "".join(f"<div class='task'>{strip_refs(f)}</div>" for f in o["facts"][:6]) + "".join(f"<div class='task' style='border-color:{C['amber']}'>{strip_refs(i)} <span class='small'>(interpretation)</span></div>" for i in o["interpretation"]) + "</div>", unsafe_allow_html=True)
    if plan.get("outlook_takeaway"): st.markdown(f"**Takeaway.** {strip_refs(plan['outlook_takeaway'])}")

    st.markdown("### 2. How the work may change")
    for k, ch in changes.items():
        if len(changes) > 1: st.markdown(f"**{outlooks[k]['title']}**")
        cols = st.columns(3)
        for col, (bucket, label, color) in zip(cols, [("ai_assists", "AI will probably assist with…", C["purple"]), ("more_important", "May become more important", C["green"]), ("uncertain", "Still uncertain", C["muted"])]):
            col.markdown(f"<span class='kicker' style='color:{color}'>{label}</span>", unsafe_allow_html=True)
            for r in ch[bucket][:7]:
                sub = f"observed AI use {r['penetration']:.2f}" if bucket == "ai_assists" else (r.get("why") or ("observed AI use " + (f"{r['penetration']:.2f}" if r.get("penetration") is not None else "not observed")))
                col.markdown(f"<div class='task' style='border-color:{color}'>{r['task']}<br><span class='p'>{sub}</span></div>", unsafe_allow_html=True)
        st.markdown(f"<p class='small'>{ch['method_note']}</p>", unsafe_allow_html=True)

    if plan.get("comparison"):
        st.markdown("### Comparing your options")
        st.dataframe(pd.DataFrame([{k.replace("_", " ").title(): strip_refs(val) for k, val in row.items()} for row in plan["comparison"]]), hide_index=True, width="stretch")
        if plan.get("our_read"): st.markdown(f"<div class='card'><span class='kicker'>Our read</span><br>{strip_refs(plan['our_read'])}</div>", unsafe_allow_html=True)

    st.markdown("### 3. What this means for you"); st.markdown(strip_refs(plan.get("for_you", "")))
    st.markdown("### 4. Your preparation plan")
    cols = st.columns(3)
    for col, (label, key) in zip(cols, [("Next 30 days", "d30"), ("Next six months", "m6"), ("Next year", "y1")]):
        col.markdown(f"<span class='kicker'>{label}</span>", unsafe_allow_html=True); [col.markdown(f"- {strip_refs(b)}") for b in plan.get(key, [])]
    st.markdown("### 5. Other paths to consider")
    if plan.get("adjacent"):
        for a in plan["adjacent"]: st.markdown(f"<div class='card'><b>{a.get('title')}</b><br>{strip_refs(a.get('why_fit'))}<br><span class='small'>Transferable: {strip_refs(a.get('transferable'))} · Prep: {strip_refs(a.get('prep'))} · Outlook: {strip_refs(a.get('outlook'))} · Tradeoff: {strip_refs(a.get('tradeoff'))}</span></div>", unsafe_allow_html=True)
    else: st.markdown(f"<p class='muted'>{strip_refs(plan.get('adjacent_note') or 'Not enough evidence in this run to recommend a change of path.')}</p>", unsafe_allow_html=True)
    st.markdown("### 6. Confidence and uncertainty")
    conf = plan.get("confidence") or {}
    for label, key in (("The evidence strongly supports", "strong"), ("Our informed interpretation", "interpretation"), ("Cannot be known now", "unknown"), ("Sources disagree or are missing", "disagree")):
        if conf.get(key): st.markdown(f"**{label}**"); [st.markdown(f"- {strip_refs(b)}") for b in conf[key]]
    for fcx in v["forecast_context"][:2]: st.markdown(f"<p class='small'>{strip_refs(fcx)}</p>", unsafe_allow_html=True)
    if v["deltas"]:
        st.markdown("### Since your last plan"); [st.markdown(f"- {d['kind']}: {d['claim'][:120]}" + (f" ({d['from']:g} → {d['to']:g})" if d["kind"] == "moved" else "")) for d in v["deltas"][:8]]

    with st.expander("7. How we reached this answer"):
        sk = v["skeptic"]
        st.markdown("**Sources** — " + " · ".join(f"{'🟢' if s=='ok' else '🟡' if s=='partial' else '🔴'} {k}" for k, s in v["source_status"].items()))
        st.markdown(f"**Reviewer** ({sk['model'].split('/')[-1]}, a different model family than the writer): kept {sk['kept']} lines, removed {len(sk['stripped'])} ({sk['ratio']:.0%}) after {sk['attempt']} pass(es).")
        for s_ in sk["stripped"][:8]: st.markdown(f"<div class='task'>✂ {s_['sentence'][:140]}<br><span class='p'>{s_['reason'][:120]}</span></div>", unsafe_allow_html=True)
        st.markdown("**Where sources disagree**"); [st.markdown(f"- {d['spread']} across {', '.join(d['sources'])}: {d['topic']}") for d in v["disagreements"]] or st.markdown("- none this run")
        st.markdown("**Known unknowns**"); [st.markdown(f"- {u}") for u in v["unknowns"]]
        st.markdown("**Forecast context (conditional)**"); [st.markdown(f"- {strip_refs(f)}") for f in v["forecast_context"]]
        st.markdown(f"**Run** — {v['budget']['tool_calls']} tool calls · est. ${v['budget']['cost_usd']:.3f}")
        st.markdown("**Agent steps**"); [st.markdown(f"<div class='small'>· {l}</div>", unsafe_allow_html=True) for l in S.log]
        st.markdown("**Evidence cards**")
        for fam, cards in v["cards_by_family"].items():
            if cards:
                st.markdown(f"_{fam}_ ({len(cards)})"); [st.markdown(f"<div class='task'>{c['claim'][:160]}<br><span class='p'>{c['source']} · {c.get('as_of') or ''} · <a href='{c.get('url')}'>source</a></span></div>", unsafe_allow_html=True) for c in cards[:12]]

    st.markdown("---"); st.markdown("<span class='kicker'>⏸ Your approval</span>", unsafe_allow_html=True)
    if v.get("review_status") == "unverified": st.warning("This plan is unverified (review step failed). If you save it, the file will be marked UNVERIFIED.")
    with st.expander("Edit the plan text before saving"):
        md = st.text_area("plan", value=pl["plan_md"], height=300, label_visibility="collapsed")
    b = st.columns([2, 1, 1])
    if b[0].button("Approve & save my plan", type="primary", width="stretch"):
        with st.status("Saving…") as box: run_graph(Command(resume={"action": "edit" if md != pl["plan_md"] else "approve", "plan_md": md}), box)
        S.stage = "done"; st.rerun()
    if b[2].button("Don't save"):
        with st.status("Closing without saving…") as box: run_graph(Command(resume={"action": "reject"}), box)
        S.stage = "done"; st.rerun()

def screen_done():
    st_ = graph().get_state({"configurable": {"thread_id": S.thread_id}}).values; ap = st_.get("approvals", {})
    if st_.get("exported_path"):
        st.success("Your plan is saved. Come back later and we'll show you what changed."); st.download_button("Download plan (.md)", st_["plan_md"], file_name=Path(st_["exported_path"]).name)
        st.markdown(strip_refs(st_["plan_md"].split("\n---\n")[0]))
    elif ap.get("understanding", {}).get("action") == "reject": st.warning("Stopped before analysis — nothing was gathered or saved.")
    elif ap.get("plan", {}).get("action") == "reject": st.warning("Plan not saved.")
    else: st.info("Run ended.")
    if st.button("Start again"): reset(); st.rerun()

# ───────────────────────── sidebar (demo controls) + router ─────────────────────────
with st.sidebar:
    st.markdown("<span class='kicker'>Demo controls</span>", unsafe_allow_html=True)
    kill = st.multiselect("Simulate a source outage", ["Polymarket", "Manifold", "BLS", "Epoch AI", "FRED"], default=[x for x in os.environ.get("DISABLE_SOURCES", "").split(",") if x])
    os.environ["DISABLE_SOURCES"] = ",".join(kill)
    files = sorted((ROOT / "data/briefs").glob("*.md"), reverse=True) if (ROOT / "data/briefs").exists() else []
    if files:
        st.markdown("<span class='kicker'>Saved plans</span>", unsafe_allow_html=True)
        for f in files[:6]: st.markdown(f"<div class='small'>{f.name}</div>", unsafe_allow_html=True)
    if S.stage != "start" and st.button("↺ Start over"): reset(); st.rerun()

if S.stage in student_ui.SCREENS: student_ui.SCREENS[S.stage](S)
elif S.stage == "s_done": student_ui.screen_done(S, reset)
else: {"start": screen_start, "intake": screen_intake, "understanding_run": screen_understanding_run, "understanding": screen_understanding, "working": screen_working, "plan": screen_plan, "done": screen_done}[S.stage]()
