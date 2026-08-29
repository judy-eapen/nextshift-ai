"""Behind-the-scenes panel: a @st.dialog with three tabs (How NextShift works · What is saved? · For builders), the sidebar journey indicator,
and the developer-mode gate. Reads only existing session state — opening it never runs the graph (tests/test_ui_panel.py).
Developer mode: available only when NEXTSHIFT_DEV=1 is set in the environment; LangSmith tracing follows developer mode."""
from __future__ import annotations
import os
from pathlib import Path
import streamlit as st
from ui import journey as J, copy as CP

ROOT = Path(__file__).resolve().parents[1]
RUN_STAGES = {"s_interview_run", "understanding_run", "working"}
SECRET_KEYS = ("NEBIUS_API_KEY", "FRED_API_KEY", "BLS_API_KEY", "LANGSMITH_API_KEY", "METACULUS_TOKEN", "ONET_API_KEY", "ANTHROPIC_API_KEY")

CSS = """<style>
.j-step { font-size:13px; padding:3px 0; display:flex; gap:6px; align-items:flex-start; }
.j-done { color:#8A94A6; } .j-cur { color:#E6EAF0; font-weight:600; } .j-todo { color:#5C6675; } .j-warn { color:#E5A24A; } .j-stop { color:#E07A5F; }
.j-note { font-size:11px; color:#8A94A6; font-weight:400; flex-basis:100%; padding-left:18px; }
.j-sr { position:absolute; left:-10000px; width:1px; height:1px; overflow:hidden; }
.bts-card { background:#121821; border:1px solid #2A3544; border-radius:12px; padding:14px 16px; margin:8px 0; }
.bts-step { border-left:3px solid #2A3544; padding:6px 12px; margin:10px 0; } .bts-here { border-left-color:#E5A24A; }
.bts-n { color:#E5A24A; font-weight:700; margin-right:8px; } .bts-tag { display:inline-block; font-size:11px; border:1px solid #2A3544; color:#8A94A6; border-radius:6px; padding:0 6px; margin-left:4px; }
.bts-callout { border-left:3px solid #E5A24A; background:#E5A24A14; padding:8px 12px; margin:8px 0; font-weight:600; }
.bts-arch { font-family: 'IBM Plex Mono', monospace; font-size:12.5px; line-height:1.7; color:#E6EAF0; } .bts-arch .g { color:#E5A24A; }
.bts-small { color:#8A94A6; font-size:12px; }
</style>"""

# ───────────────────────────── developer mode + tracing ─────────────────────────────
def dev_available() -> bool: return os.environ.get("NEXTSHIFT_DEV") == "1"

def dev_enabled(S) -> bool: return dev_available() and bool(S.get("dev_mode"))

def apply_tracing(S):
    """LangSmith tracing follows developer mode. .env may say LANGSMITH_TRACING=true; a normal session overrides it to false."""
    if "tracing_env" not in S: S.tracing_env = os.environ.get("LANGSMITH_TRACING", "false")
    on = dev_enabled(S) and S.tracing_env.lower() == "true" and bool(os.environ.get("LANGSMITH_API_KEY"))
    os.environ["LANGSMITH_TRACING"] = "true" if on else "false"; os.environ["LANGCHAIN_TRACING_V2"] = "true" if on else "false"
    return on

def tracing_on() -> bool: return os.environ.get("LANGSMITH_TRACING", "false").lower() == "true"

# ───────────────────────────── journey (sidebar) ─────────────────────────────
def _final_state(S) -> dict:
    """At an ended run, the done screen stores the checkpoint values in S.final_state and re-renders the indicator; nothing runs here."""
    return S.get("final_state") or {}

def journey(S) -> list[dict]:
    door = S.get("door") or "professional"; stage = S.get("stage", "start"); payload = S.get("payload") or {}
    views = payload.get("views") or (S.get("final_state") or {}).get("views") or {}
    completeness = payload.get("completeness") if payload.get("kind") == "understanding" else None
    fin = _final_state(S)
    return J.journey_steps(door, stage, phase=S.get("phase"), views=views, payload=payload, approvals=fin.get("approvals") or {}, exported=bool(fin.get("exported_path")), completeness=completeness)

def render_journey(S, box):
    if S.get("stage", "start") == "start": box.empty(); return
    steps = journey(S); door = "student" if S.get("door") == "student" else "professional"
    now = J.phase_copy(S.get("phase"))
    html = f"<span class='kicker'>Your journey</span> <span class='bts-small'>· {door}</span><div role='list' aria-label='Your journey'>" + "".join(J.step_html(s) for s in steps) + "</div>"
    if now: html += f"<div class='bts-small' style='margin-top:6px'><span role='img' aria-label='working'>⟳</span> Right now: {now}</div>"
    box.markdown(html, unsafe_allow_html=True)

def sidebar(S):
    """Sidebar shell: journey · entry card · demo/developer expander. Called by app.py before the router."""
    st.markdown(CSS, unsafe_allow_html=True)
    box = st.empty(); S.on_phase = lambda: render_journey(S, box); render_journey(S, box)
    st.markdown("<div class='bts-card'><b>Curious how NextShift works?</b><br><span class='bts-small'>See how your answers become career recommendations.</span></div>", unsafe_allow_html=True)
    running = S.get("stage") in RUN_STAGES
    if st.button("Open behind the scenes →", width="stretch", disabled=running, help="Opens an explanation panel. Your place in the journey is kept." if not running else "Available once this step finishes"):
        behind_the_scenes(S)
    with st.expander("Demo & developer", expanded=False):
        kill = st.multiselect("Simulate a source outage", ["Polymarket", "Manifold", "BLS", "Epoch AI", "FRED"], default=[x for x in os.environ.get("DISABLE_SOURCES", "").split(",") if x])
        os.environ["DISABLE_SOURCES"] = ",".join(kill)
        if dev_available(): st.checkbox("Developer mode", key="dev_mode", help="Shows nodes, models, cost and timings; turns LangSmith tracing on.")
        else: st.markdown("<span class='bts-small'>Developer mode: set NEXTSHIFT_DEV=1 in .env to enable.</span>", unsafe_allow_html=True)
        files = sorted((ROOT / "data/briefs").glob("*.md"), reverse=True) if (ROOT / "data/briefs").exists() else []
        if files:
            st.markdown("<span class='kicker'>Saved on this computer</span>", unsafe_allow_html=True)
            for f in files[:6]: st.markdown(f"<div class='bts-small'>{f.name}</div>", unsafe_allow_html=True)
    apply_tracing(S)

# ───────────────────────────── the dialog ─────────────────────────────
@st.dialog("Behind the scenes", width="large")
def behind_the_scenes(S):
    st.markdown(CSS, unsafe_allow_html=True)
    door = "student" if S.get("door") == "student" else "professional"
    t1, t2, t3 = st.tabs(["How NextShift works", "What is saved?", "For builders"])
    with t1: tab_how(S, door)
    with t2: tab_saved(S, door)
    with t3: tab_builders(S, door)

def _here(S, door) -> int | None:
    steps = journey(S); cur = next((i for i, s in enumerate(steps) if s["state"] == "current"), None)
    if cur is None: return None
    return (CP.STUDENT_JOURNEY_TO_STEP if door == "student" else CP.PRO_JOURNEY_TO_STEP).get(cur)

def tab_how(S, door):
    st.markdown(f"<p class='bts-small'>{CP.INTRO}</p>", unsafe_allow_html=True)
    here = _here(S, door)
    for s in CP.steps(door):
        tags = "".join(f"<span class='bts-tag'>{t}</span>" for t in s["tags"])
        st.markdown(f"<div class='bts-step {'bts-here' if here == s['n'] else ''}'><span class='bts-n'>{s['n']}</span><b>{s['title']}</b>{tags}{' <span class=\"bts-small\">◀ you are here</span>' if here == s['n'] else ''}<br>{s['body']}</div>", unsafe_allow_html=True)
        if s.get("callout"): st.markdown(f"<div class='bts-callout'>{s['callout']}</div>", unsafe_allow_html=True)
        with st.expander(s["more_title"]): st.markdown(s["more"])
    st.markdown(f"<p class='bts-small'>{CP.LEGEND}</p>", unsafe_allow_html=True)

def tab_saved(S, door):
    c = CP.saved_copy(door, tracing_on())
    st.markdown(c["while"]); st.markdown(c["after"]); st.markdown(c["never"])
    if S.get("stage") not in ("start",):
        st.markdown(f"<p class='bts-small'>Right now: {'a saved record exists for this session' if (S.get('final_state') or {}).get('exported_path') else 'nothing has been added to your saved record'}.</p>", unsafe_allow_html=True)

def tab_builders(S, door):
    which = st.radio("Journey", ["Student", "Professional"], index=0 if door == "student" else 1, horizontal=True, label_visibility="collapsed")
    arch = CP.STUDENT_ARCH if which == "Student" else CP.PRO_ARCH
    st.markdown("<div class='bts-arch'>" + "<br>".join(("<span class='g'>→</span> " if i else "") + a for i, a in enumerate(arch)) + "</div>", unsafe_allow_html=True)
    st.markdown("<p class='bts-small'>⏸ = a gate where the person decides (LangGraph interrupt). Every gate can end the run with nothing written.</p>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: st.markdown("**Model-assisted work** [AI]"); [st.markdown(f"- {x}") for x in CP.MODEL_WORK]
    with c2: st.markdown("**Deterministic controls** [code]"); [st.markdown(f"- {x}") for x in CP.DETERMINISTIC]
    with st.expander("State and memory"): [st.markdown(f"- {x}") for x in CP.STATE_MEMORY]
    with st.expander("Failure handling"): [st.markdown(f"- {x}") for x in CP.FAILURE]
    with st.expander("Architecture diagram"):
        img = ROOT / "design" / ("architecture-student.png" if which == "Student" else "architecture-diagram.png")
        if img.exists(): st.image(str(img), caption=f"{which} journey — source: design/{img.stem.replace('-diagram', '')}.mmd", width="stretch")
    if dev_enabled(S):
        with st.expander("Developer mode — this session", expanded=True): dev_block(S)
    elif dev_available(): st.markdown("<p class='bts-small'>Developer mode is available — tick it under *Demo & developer* in the sidebar.</p>", unsafe_allow_html=True)

def dev_block(S):
    """Only what actually exists in state. No env values, no prompts, no reasoning traces (llm.chat strips <think> before anything is stored)."""
    payload = S.get("payload") or {}; views = payload.get("views") or {}; sk = views.get("skeptic") or {}
    st.markdown(f"**Stage** `{S.get('stage')}` · **interrupt kind** `{payload.get('kind', '—')}` · **thread** `{str(S.get('thread_id', ''))[:8]}…` · **phase** `{(S.get('phase') or {}).get('phase', '—')}`")
    st.markdown("**Model roles** — " + " · ".join(f"{k}: `{v}`" for k, v in CP.model_roles().items()))
    if views.get("budget"): st.markdown(f"**Run** — {views['budget'].get('tool_calls', 0)} tool calls · est. ${views['budget'].get('cost_usd', 0):.4f}")
    if sk: st.markdown(f"**Review** — status `{sk.get('status')}` · {sk.get('total', 0)} lines · {len(sk.get('stripped', []))} removed · ratio {sk.get('ratio', 0):.2f} · rationale lines removed {sk.get('rationale_lines_removed', 0)}")
    if views.get("source_status"): st.markdown("**Sources** — " + " · ".join(f"{k}: `{v}`" for k, v in views["source_status"].items()))
    st.markdown(f"**Tracing** — LangSmith {'on' if tracing_on() else 'off'}")
    phases = S.get("phase_log") or []
    if phases:
        st.markdown("**Phase timeline (this run)**")
        for i, p in enumerate(phases): st.markdown(f"<div class='bts-small'>{p['t'] - phases[0]['t']:6.1f}s  {p['phase']}{' · ' + p['of'] if p.get('of') else ''}</div>", unsafe_allow_html=True)
    if S.get("log"):
        with st.expander(f"Agent steps ({len(S.log)})"): [st.markdown(f"<div class='bts-small'>· {l}</div>", unsafe_allow_html=True) for l in S.log[-40:]]
    cards = views.get("cards_by_family") or {}
    if cards:
        with st.expander("Evidence card ids"):
            for fam, cs in cards.items():
                if cs: st.markdown(f"_{fam}_ — " + ", ".join(f"`{c.get('id', '')[:14]}`" for c in cs[:20]))
    st.markdown("<p class='bts-small'>Not instrumented: cache hits/misses, per-node timings beyond phase events, retry counts. Shown only what the graph records.</p>", unsafe_allow_html=True)
