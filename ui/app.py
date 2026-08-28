"""NextShift AI — Streamlit surface over the LangGraph supervisor.  Run: streamlit run ui/app.py
Screens: Ask (two doors) · agent thinks in public · ⏸ worldview gate · scenario tree + horizon · task-diff board · disagreement · since you last looked · ⏸ brief approve/export."""
from __future__ import annotations
import os, sys, time, uuid, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
import streamlit as st, pandas as pd, plotly.graph_objects as go
from langgraph.types import Command

st.set_page_config(page_title="NextShift AI", page_icon="⟶", layout="wide")
C = {"bg": "#0B0F14", "surface": "#121821", "line": "#2A3544", "ink": "#E6EAF0", "muted": "#8A94A6", "amber": "#E5A24A", "student": "#7FC8E8",
     "Slow diffusion": "#7FB3D5", "Fast diffusion": "#E07A5F", "AGI by horizon": "#B48CFF", "Regulatory brake": "#8FBF9F"}
st.markdown(f"""<style>
.stApp {{ background:{C['bg']}; }} h1,h2,h3 {{ font-family: Archivo, 'IBM Plex Sans', sans-serif; letter-spacing:-0.01em; }}
.card {{ background:{C['surface']}; border:1px solid {C['line']}; border-radius:10px; padding:14px 16px; margin-bottom:10px; }}
.kicker {{ color:{C['amber']}; font-size:11px; letter-spacing:.14em; text-transform:uppercase; font-weight:600; }}
.muted {{ color:{C['muted']}; font-size:13px; }} .mono {{ font-family:'IBM Plex Mono', monospace; }}
.badge {{ display:inline-block; border:1px solid {C['amber']}; color:{C['amber']}; border-radius:6px; padding:2px 8px; font-size:12px; margin:2px 4px 2px 0; }}
.task {{ border-left:3px solid {C['line']}; padding:6px 10px; margin:4px 0; font-size:13px; }} .task .p {{ color:{C['muted']}; font-family:'IBM Plex Mono'; font-size:11px; }}
</style>""", unsafe_allow_html=True)

# ───────────────────────── resources ─────────────────────────
@st.cache_resource
def graph():
    from graph.build import build_graph; return build_graph()

@st.cache_data
def landscape() -> pd.DataFrame: return pd.read_parquet(ROOT / "data/processed/landscape.parquet")

def plotly_base(fig: go.Figure, h=420) -> go.Figure:
    fig.update_layout(template="plotly_dark", paper_bgcolor=C["bg"], plot_bgcolor=C["surface"], height=h, margin=dict(l=20, r=20, t=30, b=20), font=dict(family="IBM Plex Sans", color=C["ink"]))
    return fig

S = st.session_state
S.setdefault("stage", "ask"); S.setdefault("log", []); S.setdefault("door", "professional"); S.setdefault("persona", None); S.setdefault("candidates", None)

def reset():
    for k in ("stage", "log", "payload", "final", "thread_id", "candidates"): S.pop(k, None)
    S.stage = "ask"

def run_graph(inp, status_box):
    """Stream the graph; render 'thinks in public' lines; stop at the first interrupt (or END)."""
    cfg = {"configurable": {"thread_id": S.thread_id}}
    for mode, ev in graph().stream(inp, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom":
            S.log.append(ev["say"]); status_box.write(f"· {ev['say']}")
        elif "__interrupt__" in ev:
            return ev["__interrupt__"][0].value
    return None

# ───────────────────────── header / nav ─────────────────────────
top = st.columns([3, 1, 1, 1])
top[0].markdown(f"<span class='kicker'>NextShift AI</span><br><span class='muted'>What AI does to your work, with receipts.</span>", unsafe_allow_html=True)
page = top[1].radio("nav", ["Ask", "Landscape", "My briefs"], horizontal=True, label_visibility="collapsed")
with top[3]:
    kill = st.multiselect("Failure demo: disable", ["Polymarket", "Manifold", "BLS", "FRED", "Epoch AI"], default=[x for x in os.environ.get("DISABLE_SOURCES", "").split(",") if x], label_visibility="collapsed", placeholder="Failure demo: kill a source")
    os.environ["DISABLE_SOURCES"] = ",".join(kill)
    if S.stage != "ask" and st.button("↺ Start over", width="stretch"): reset(); st.rerun()

# ═══════════════════════════ ASK ═══════════════════════════
def screen_ask():
    st.markdown("## What could AI do to your work — and what should you do about it?")
    st.markdown("<span class='muted'>Live forecasts · labor statistics · AI-exposure research · every claim carries its source card. The agent pauses twice for you: before it builds scenarios, and before it publishes.</span>", unsafe_allow_html=True)
    left, right = st.columns(2)
    with left:
        st.markdown("<div class='card'><span class='kicker'>For professionals</span><h3 style='margin:4px 0'>Start from your job</h3><span class='muted'>See which of your tasks change under each scenario, where forecasters disagree, and what's in your control.</span></div>", unsafe_allow_html=True)
        title = st.text_input("Your job title", placeholder="Product manager, paralegal, registered nurse…", key="title_in")
        about = st.text_input("What do you actually do? (optional — titles are ambiguous, tasks aren't)", placeholder="e.g. own a software roadmap, write requirements, prioritize with engineers, run user research", key="about_in")
        if st.button("Find my occupation", type="secondary") and title.strip():
            from tools.resolve import resolve
            with st.spinner("Matching your work to the official occupation list…"): S.candidates = resolve(title.strip(), about.strip(), k=3)
        if S.candidates:
            r = S.candidates; st.caption(r["explanation"])
            opts = {f"{m['title']} · {m['onet_soc']}" + (" · closest by tasks" if m.get("curated") else f" · similarity {m['similarity']:.2f}" if m.get("similarity") is not None else " · O*NET lists this title here"): m for m in r["matches"]}
            pick = st.radio("Which is you?", list(opts), index=0); m = opts[pick]
            if r["tier"] == 0: st.warning("Your title has no official category — these are the closest task lists. Please pick; don't let me guess.")
            elif not r["confident"] and r["tier"] == 2: st.warning("No official category lists this title — I matched by meaning. Please confirm, don't let me guess.")
            if m.get("description"): st.caption(m["description"])
            S.persona = {"soc": m["soc"], "onet_soc": m.get("onet_soc") or f"{m['soc']}.00", "title": m["title"], "matched_via": f"tier {r['tier']}: {title.strip()}", "horizon": 2030}
    with right:
        st.markdown(f"<div class='card' style='border-color:{C['student']}55'><span class='kicker' style='color:{C['student']}'>For students</span><h3 style='margin:4px 0'>Start from the whole map</h3><span class='muted'>867 occupations, sized by how many people do them. Find fields that grow under every scenario, not just the likely one.</span></div>", unsafe_allow_html=True)
        if st.button("Open the landscape →"): S.door = "student"; S.nav_to = "Landscape"; st.rerun()
        if S.persona and S.door == "student": st.info(f"Picked from the map: **{S.persona['title']}** (SOC {S.persona['soc']})")
    if S.persona:
        st.divider(); c1, c2 = st.columns([3, 1])
        q = c1.text_input("Your question", value=f"What happens to {S.persona['title'].lower()} by 2030, and what should I do about it?")
        horizon = c2.select_slider("Horizon", [2030, 2035], value=2030)
        if st.button("▶ Ask NextShift", type="primary"):
            S.persona["horizon"] = horizon; S.question = q; S.thread_id = str(uuid.uuid4()); S.log = []; S.stage = "running"; st.rerun()

# ═══════════════════════════ RUNNING → GATE 1 ═══════════════════════════
def screen_running():
    st.markdown(f"## {S.persona['title']} · {S.persona['horizon']}"); st.caption(S.question)
    with st.status("Agent thinking in public…", expanded=True) as box:
        payload = run_graph({"question": S.question, "door": S.door, "persona": S.persona, "thread_id": S.thread_id}, box)
        box.update(label="Evidence gathered — waiting for you", state="complete", expanded=False)
    S.payload = payload; S.stage = "worldview" if payload and payload["kind"] == "worldview" else "done"; st.rerun()

def screen_worldview():
    p = S.payload; wv = p["worldview"]
    st.markdown(f"## {wv['title']} · {wv['horizon']}"); st.markdown("<span class='kicker'>⏸ Worldview gate — your call before scenarios are built</span>", unsafe_allow_html=True)
    with st.expander("How the agent got here", expanded=False):
        for l in S.log: st.write(f"· {l}")
    cols = st.columns([2, 1])
    with cols[0]:
        st.markdown("<div class='card'><b>Assumptions I'm about to make</b><br><span class='muted'>Edit any line, change the horizon, or reject. Refs like [c03] are evidence cards.</span></div>", unsafe_allow_html=True)
        horizon = st.select_slider("Horizon", [2030, 2035], value=int(wv["horizon"]))
        st.text_input("Anchor forecast", value=wv["anchor_question"], disabled=True)
        claims = [st.text_input(f"Assumption {i+1}", value=c, key=f"claim{i}") for i, c in enumerate(wv["claims"])]
    with cols[1]:
        st.markdown("<span class='kicker'>Sources</span>", unsafe_allow_html=True)
        for src, stt in p["source_status"].items(): st.markdown(f"{'🟢' if stt=='ok' else '🟡' if stt=='partial' else '🔴'} {src} <span class='muted'>{stt}</span>", unsafe_allow_html=True)
        if p["disagreements"]:
            st.markdown("<span class='kicker'>Disagreement</span>", unsafe_allow_html=True)
            for d in p["disagreements"]: st.markdown(f"<div class='card'><b>{d['spread']}</b> across {', '.join(d['sources'])}<br><span class='muted'>{d['topic']}</span></div>", unsafe_allow_html=True)
        if p["unknowns"]:
            st.markdown("<span class='kicker'>Unknown — not estimated</span>", unsafe_allow_html=True)
            for u in p["unknowns"]: st.markdown(f"<span class='muted'>· {u}</span>", unsafe_allow_html=True)
    b = st.columns(3)
    edited = horizon != int(wv["horizon"]) or claims != wv["claims"]
    if b[0].button("✓ Approve" + (" with edits" if edited else ""), type="primary"):
        S.resume = {"action": "edit" if edited else "approve", "worldview": {"horizon": horizon, "claims": claims}}; S.stage = "building"; st.rerun()
    if b[2].button("✕ Reject — stop here"):
        S.resume = {"action": "reject"}; S.stage = "building"; st.rerun()

def screen_building():
    st.markdown(f"## {S.persona['title']}")
    with st.status("Building scenarios, writing the brief, skeptic checking every line…", expanded=True) as box:
        payload = run_graph(Command(resume=S.resume), box)
        box.update(label="Draft ready — waiting for you", state="complete", expanded=False)
    S.payload = payload; S.stage = "publish" if payload and payload["kind"] == "publish" else "done"; st.rerun()

# ═══════════════════════════ RESULTS + GATE 2 ═══════════════════════════
def tree_fig(views, horizon):
    fig = go.Figure()
    for s in views["tree"]:
        lo, hi = s["prob_low"], s["prob_high"]; col = C.get(s["name"], C["muted"])
        if lo is None:
            fig.add_trace(go.Bar(y=[s["name"]], x=[1.0], orientation="h", marker=dict(color=col, opacity=0.12, line=dict(color=col, width=1)), hovertext=s["prob_note"], name=s["name"], showlegend=False, text="no forecast · not estimated", textposition="inside"))
        else:
            fig.add_trace(go.Bar(y=[s["name"]], x=[max(hi - lo, 0.01)], base=[lo], orientation="h", marker=dict(color=col), name=s["name"], showlegend=False, text=f"{lo:.0%}–{hi:.0%}" if hi - lo >= 0.01 else f"{lo:.0%}", textposition="outside", hovertext=s["prob_note"]))
    fig.update_xaxes(range=[0, 1], tickformat=".0%", title=f"Forecast range for the branch's anchor question · horizon {horizon}"); fig.update_yaxes(autorange="reversed")
    return plotly_base(fig, 300)

def screen_results():
    p = S.payload; st_ = graph().get_state({"configurable": {"thread_id": S.thread_id}}).values; views = st_["views"]; wv = st_["worldview"]
    st.markdown(f"## {wv['title']} · {wv['horizon']}")
    st.markdown(" ".join(f"<span class='badge'>{b}</span>" for b in views["badges"]) or "<span class='badge'>all sources ok · 0 sentences removed</span>", unsafe_allow_html=True)
    tabs = st.tabs(["Scenario tree", "How your work changes", "Where sources disagree", "Since you last looked", "⏸ Brief"])
    with tabs[0]:
        c1, c2 = st.columns([3, 1])
        c1.plotly_chart(tree_fig(views, wv["horizon"]), width="stretch")
        with c2:
            other = 2035 if wv["horizon"] == 2030 else 2030
            st.markdown(f"<span class='kicker'>Horizon</span><br><b>{wv['horizon']}</b>", unsafe_allow_html=True)
            if st.button(f"Re-run for {other} →"): S.persona["horizon"] = other; S.thread_id = str(uuid.uuid4()); S.log = []; S.stage = "running"; st.rerun()
            st.caption("Branch width = the min–max across platforms for that branch's anchor question. Never averaged.")
        for s in st_["scenarios"]:
            with st.expander(f"{s['name']} — {s['gist']}"):
                st.markdown("\n".join(f"- {a}" for a in s["assumptions"]) or "_no assumptions written_"); st.markdown(s["for_you"] or "_the writer had nothing citable to say here_")
    with tabs[1]:
        branch = st.radio("Branch", [s["name"] for s in views["tree"]], horizontal=True)
        board = views["board"][branch]; cols = st.columns(3)
        for col, (bucket, label, hint) in zip(cols, [("disappears", "Likely to be done by AI", "penetration × branch multiplier ≥ 0.60"), ("supervised", "AI drafts, you direct", "0.25 – 0.60"), ("grows", "Stays human — gains share", "< 0.25 or never observed")]):
            col.markdown(f"<span class='kicker'>{label}</span> <span class='muted'>{len(board[bucket])} tasks · {hint}</span>", unsafe_allow_html=True)
            for r in board[bucket][:25]:
                col.markdown(f"<div class='task' style='border-color:{C.get(branch)}'>{r['task']}<br><span class='p'>penetration {r['penetration'] if r['penetration'] is not None else '—'} · eff {r['eff']} · Anthropic Economic Index × O*NET</span></div>", unsafe_allow_html=True)
    with tabs[2]:
        if not views["bands"]: st.info("No cross-platform disagreement on this run — a disagreement needs the same anchor question priced on two platforms at least 5 points apart.")
        for d in views["bands"]:
            st.markdown(f"<div class='card'><span class='kicker'>{d['anchor']}</span><br><b>{d['topic']}</b><br>{d['spread']} across {', '.join(d['sources'])} — shown side by side, never averaged.</div>", unsafe_allow_html=True)
            cards = {c.id: c for c in st_["evidence"]}
            for cid in d["card_ids"]:
                c = cards.get(cid)
                if c: st.markdown(f"<div class='task'>{c.claim}<br><span class='p'>{c.source} · {c.spread or ''} · <a href='{c.url}'>source</a></span></div>", unsafe_allow_html=True)
        st.markdown("<span class='kicker'>Known unknowns</span>", unsafe_allow_html=True)
        for u in st_.get("unknowns", []): st.markdown(f"<span class='muted'>· {u}</span>", unsafe_allow_html=True)
    with tabs[3]:
        deltas = views["deltas"]
        if not deltas: st.info("First run for this occupation and horizon — nothing to compare against yet. Approve the brief and run again later to see what moved.")
        else:
            st.markdown(f"**{len(deltas)} signals changed since the last approved run**")
            for d in deltas:
                icon = {"moved": "↕", "new": "＋", "gone": "－"}[d["kind"]]
                extra = f" — {d['from']:.0%} → {d['to']:.0%}" if d["kind"] == "moved" and d.get("unit") == "probability" else f" — {d['from']:g} → {d['to']:g}" if d["kind"] == "moved" else ""
                st.markdown(f"<div class='task'>{icon} {d['claim']}{extra}<br><span class='p'>{d['source']}</span></div>", unsafe_allow_html=True)
    with tabs[4]:
        sk = p["skeptic"]
        st.markdown(f"<span class='kicker'>⏸ Publish gate</span> <span class='muted'>Skeptic ({sk['model'].split('/')[-1]}) kept {sk['kept']} lines, removed {len(sk['stripped'])} ({sk['ratio']:.0%}){' — escalated after 2 attempts' if sk['escalated'] else ''} · budget {p['budget']['tool_calls']} tool calls, ${p['budget']['cost_usd']:.3f}</span>", unsafe_allow_html=True)
        if sk["stripped"]:
            with st.expander(f"{len(sk['stripped'])} sentences removed for lacking a source"):
                for s_ in sk["stripped"]: st.markdown(f"<div class='task'>✂ {s_['sentence']}<br><span class='p'>{s_['reason']}</span></div>", unsafe_allow_html=True)
        brief = st.text_area("Brief (markdown — edit before approving)", value=p["brief_md"], height=420)
        b = st.columns([1, 1, 2])
        if b[0].button("✓ Approve & export", type="primary"):
            with st.status("Exporting brief and saving snapshot…") as box: run_graph(Command(resume={"action": "edit" if brief != p["brief_md"] else "approve", "brief_md": brief}), box)
            S.stage = "done"; st.rerun()
        if b[1].button("✕ Reject — don't publish"):
            with st.status("Closing without writing…") as box: run_graph(Command(resume={"action": "reject"}), box)
            S.stage = "done"; st.rerun()
        st.markdown("---"); st.markdown(brief)

def screen_done():
    st_ = graph().get_state({"configurable": {"thread_id": S.thread_id}}).values; ap = st_.get("approvals", {})
    if st_.get("exported_path"):
        st.success(f"Brief exported to `{Path(st_['exported_path']).name}` and snapshot saved — the next run for this occupation will show what moved."); st.markdown(st_["brief_md"])
        st.download_button("Download brief (.md)", st_["brief_md"], file_name=Path(st_["exported_path"]).name)
    elif ap.get("worldview", {}).get("action") == "reject": st.warning("Stopped at the worldview gate — nothing was built or written.")
    elif ap.get("publish", {}).get("action") == "reject": st.warning("Brief rejected — nothing was exported or saved.")
    else: st.info("Run ended.")
    if st.button("Ask another question"): reset(); st.rerun()

# ═══════════════════════════ LANDSCAPE (student door) ═══════════════════════════
def screen_landscape():
    st.markdown("## The landscape"); st.markdown("<span class='muted'>867 occupations. Size = people employed. Horizontal = how much of the job's task mix AI is already used for (Anthropic Economic Index). Vertical = median wage. Click a bubble to start from that job.</span>", unsafe_allow_html=True)
    d = landscape().dropna(subset=["employment", "observed_exposure", "median_wage"]).copy(); d["size"] = (d.employment ** 0.5) / 12
    fig = go.Figure(go.Scatter(x=d.observed_exposure, y=d.median_wage, mode="markers", customdata=d[["soc", "title", "employment"]].values,
                               marker=dict(size=d["size"], sizemode="diameter", color=d.observed_exposure, colorscale=[[0, C["Slow diffusion"]], [0.5, C["amber"]], [1, C["Fast diffusion"]]], opacity=0.75, line=dict(width=0.5, color=C["line"])),
                               hovertemplate="<b>%{customdata[1]}</b><br>SOC %{customdata[0]}<br>%{customdata[2]:,.0f} jobs · exposure %{x:.2f} · $%{y:,.0f}<extra></extra>"))
    fig.update_xaxes(title="Observed AI exposure (share of tasks with AI usage)"); fig.update_yaxes(title="Median wage (USD)", tickformat="$,.0f")
    ev = st.plotly_chart(plotly_base(fig, 560), width="stretch", on_select="rerun", selection_mode="points", key="land")
    pts = (ev.selection.points if ev and ev.selection else []) if ev else []
    if pts:
        soc, title, emp = pts[0]["customdata"]; S.persona = {"soc": soc, "onet_soc": f"{soc}.00", "title": title, "matched_via": "landscape", "horizon": 2030}; S.door = "student"
        st.success(f"Selected **{title}** — {emp:,.0f} people. Go to **Ask** to run it.")
    st.caption("Growth axis pending the BLS projections file (data/raw/bls_occupation_projections.xlsx).")

def screen_briefs():
    st.markdown("## My briefs"); files = sorted((ROOT / "data/briefs").glob("*.md"), reverse=True) if (ROOT / "data/briefs").exists() else []
    if not files: st.info("No approved briefs yet.")
    for f in files[:20]:
        with st.expander(f.name): st.markdown(f.read_text())

# ───────────────────────── router ─────────────────────────
if S.pop("nav_to", None) == "Landscape": page = "Landscape"
if page == "Landscape": screen_landscape()
elif page == "My briefs": screen_briefs()
else: {"ask": screen_ask, "running": screen_running, "worldview": screen_worldview, "building": screen_building, "publish": screen_results, "done": screen_done}[S.stage]()
