"""Career Explorer — the primary student entry point. Every screen here is deterministic: it reads tools.catalog (a local, cached file) and
never calls a model or a network API. Slower hand-offs (personalized guidance, the deeper AI-era analysis) leave this module and run the
existing graphs with their gates, reviewer and progress indicators.

Session state: S.stage == "explore" · S.x_view = the current view dict · S.x_stack = back-navigation history · S.x_saved = ordered saved ids ·
S.x_reactions = {id: interesting|maybe|no|understand} · S.x_return = the interview stage to return to (when the student came from the interview)."""
from __future__ import annotations
import html, time
import streamlit as st
from tools import catalog as C

C_ = {"amber": "#E5A24A", "student": "#7FC8E8", "green": "#8FBF9F", "red": "#E07A5F", "purple": "#B48CFF", "muted": "#8A94A6", "line": "#2A3544", "ink": "#E6EAF0"}
GROWTH_PILL = {"growing": ("▲ Projected to grow", C_["green"]), "stable": ("● Roughly stable", C_["amber"]), "declining": ("▼ Projected to decline", C_["red"]), "unknown": ("? No official projection", C_["muted"])}
AI_PILL = {"substantial": ("◆ AI used in many tasks today", C_["purple"]), "moderate": ("◆ AI used in some tasks today", C_["purple"]), "limited": ("◇ AI rarely used in its tasks so far", C_["muted"]), "unknown": ("? No task-level AI data", C_["muted"])}
REACTIONS = [("interesting", "😀 Interesting"), ("maybe", "🤔 Maybe"), ("understand", "🔍 Tell me more"), ("no", "✕ Not for me")]
REACTION_WORD = {"interesting": "interesting", "maybe": "maybe", "understand": "want to understand better", "no": "not for me"}
PAGE = 12; MAX_COMPARE = 4; OFFER_AT = 3
BOUNDARY = "Browsing is free and instant — nothing here is a recommendation. Figures are official statistics or observed data with their source and year; anything interpretive says so."
CSS = f"""<style>
.x-card {{ background:#121821; border:1px solid {C_['line']}; border-radius:12px; padding:14px 16px; margin:8px 0; }}
.x-card .x-desc {{ display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; min-height:2.9em; max-height:2.9em; line-height:1.45em; }}
.x-grid-card {{ min-height:215px; display:flex; flex-direction:column; }} .x-grid-card .x-grow {{ flex:1; }}
.x-card.saved {{ border-color:{C_['student']}88; }}
.x-title {{ font-size:17px; font-weight:600; color:{C_['ink']}; }} .x-sub {{ color:{C_['muted']}; font-size:13px; margin-top:2px; }}
.x-fam {{ display:inline-block; font-size:11px; border:1px solid {C_['line']}; color:{C_['muted']}; border-radius:6px; padding:0 6px; margin:4px 4px 0 0; }}
.x-pill {{ display:inline-block; border-radius:999px; padding:2px 9px; font-size:12px; font-weight:600; margin:6px 6px 0 0; }}
.x-src {{ color:{C_['muted']}; font-size:11.5px; }} .x-q {{ color:{C_['amber']}; font-size:11px; letter-spacing:.12em; text-transform:uppercase; font-weight:600; }}
.x-fact {{ background:#10161f; border:1px solid #1b2430; border-left:3px solid {C_['line']}; border-radius:9px; padding:8px 12px; margin:6px 0; font-size:14px; line-height:1.5; }}
.x-fact.h {{ border-left-color:{C_['student']}; }} .x-fact.ai {{ border-left-color:{C_['purple']}; }} .x-fact.warn {{ border-left-color:{C_['amber']}; background:{C_['amber']}0d; }}
.x-traj {{ background:#121821; border:1px solid {C_['line']}; border-radius:12px; padding:14px 16px; min-height:118px; }} .x-traj b {{ color:{C_['muted']}; font-size:11px; letter-spacing:.1em; text-transform:uppercase; font-weight:600; }}
.x-traj .x-big {{ font-family:Archivo,'IBM Plex Sans',sans-serif; font-size:26px; font-weight:700; line-height:1.15; margin:4px 0 2px; color:{C_['ink']}; }}
.x-traj .x-big.up {{ color:{C_['green']}; }} .x-traj .x-big.down {{ color:{C_['red']}; }} .x-traj .x-big.flat {{ color:{C_['amber']}; }} .x-traj .x-big.ai {{ color:{C_['purple']}; }}
.x-count {{ display:inline-block; background:{C_['student']}22; color:{C_['student']}; border:1px solid {C_['student']}66; border-radius:999px; padding:2px 10px; font-size:13px; font-weight:600; }}
.x-empty {{ color:{C_['muted']}; font-size:15px; padding:18px; text-align:center; border:1px dashed {C_['line']}; border-radius:12px; }}
table.x-cmp {{ width:100%; border-collapse:collapse; font-size:13.5px; }} table.x-cmp th, table.x-cmp td {{ border-bottom:1px solid {C_['line']}; padding:8px 8px; vertical-align:top; text-align:left; }}
table.x-cmp th {{ color:{C_['student']}; font-size:12px; letter-spacing:.06em; text-transform:uppercase; }} table.x-cmp td.r {{ color:{C_['muted']}; font-size:12px; width:150px; }}
.x-wrap {{ overflow-x:auto; }}
</style>"""

def esc(s) -> str: return html.escape(str(s or ""))
def pill(text, color): return f"<span class='x-pill' style='background:{color}22;color:{color};border:1px solid {color}66'>{esc(text)}</span>"

# ───────────────────────────── browser URL sync (real back/forward + shareable links) ─────────────────────────────
# Streamlit is a single-page app: without this, the browser's Back button leaves the app entirely. Explorer views are mirrored into
# query params (?x=career&id=…), so browser back/forward move between explorer pages and a career URL can be pasted to a friend.
_QP_KEYS = ("x", "id", "q", "name", "trait", "subject", "zone", "ids")

def _view_to_qp(view: dict) -> dict:
    k = view.get("kind", "home"); qp = {"x": k}
    if k == "career": qp["id"] = view.get("id", "")
    elif k == "search": qp["q"] = view.get("q", "")
    elif k == "collection": qp["name"] = view.get("name", "")
    elif k == "family": qp["id"] = view.get("id", "")
    elif k == "browse":
        for f in ("trait", "subject"):
            if view.get(f): qp[f] = view[f]
        if view.get("zone"): qp["zone"] = str(view["zone"])
    elif k == "compare": qp["ids"] = " ".join(view.get("ids") or [])
    return qp

def _qp_to_view(qp: dict) -> dict | None:
    k = qp.get("x")
    if k not in SCREENS: return None
    if k == "career": return {"kind": "career", "id": qp.get("id", "")} if qp.get("id") else None
    if k == "search": return {"kind": "search", "q": qp.get("q", "")} if qp.get("q") else None
    if k == "collection": return {"kind": "collection", "name": qp.get("name", "")} if qp.get("name") in C.COLLECTIONS else None
    if k == "family": return {"kind": "family", "id": qp.get("id", "")} if qp.get("id") in C.FAMILIES else None
    if k == "browse":
        v = {"kind": "browse"}
        if qp.get("trait") in C.TRAITS: v["trait"] = qp["trait"]
        if qp.get("subject") in C.SUBJECTS: v["subject"] = qp["subject"]
        if str(qp.get("zone", "")).isdigit(): v["zone"] = int(qp["zone"])
        return v if len(v) > 1 else None
    if k == "compare": return {"kind": "compare", "ids": [i for i in (qp.get("ids") or "").split() if i]}
    return {"kind": k}

def sync_url(S):
    """Adopt a browser back/forward (or pasted) URL; then mirror the current view into the URL."""
    try: qp = {k: st.query_params.get(k) for k in _QP_KEYS if k in st.query_params}
    except Exception: return
    if qp and qp != (S.get("_qp_last") or {}):
        v = _qp_to_view(qp)
        if v and v != S.x_view: S.x_view = v                     # navigation came from the browser, not our buttons — no stack push
    cur = _view_to_qp(S.x_view)
    if cur != (S.get("_qp_last") or {}):
        try: st.query_params.from_dict(cur)   # ONE atomic write → one browser-history entry per view, so Back/Forward land on complete URLs
        except Exception: pass
    S._qp_last = cur

# ───────────────────────────── state + navigation ─────────────────────────────
def init(S):
    S.setdefault("x_view", {"kind": "home"}); S.setdefault("x_stack", []); S.setdefault("x_saved", []); S.setdefault("x_reactions", {}); S.setdefault("x_seed", 0); S.setdefault("x_page", {})

def enter(S, view: dict | None = None, return_to: str | None = None):
    """Open the explorer (from the start screen or from an interview screen). return_to = the interview stage to come back to."""
    init(S); S.door = "student"; S.stage = "explore"
    if return_to: S.x_return = return_to
    if view: S.x_view = view; S.x_stack = [{"kind": "home"}]
    st.rerun()

def go(S, view: dict):
    S.x_stack = (S.x_stack + [S.x_view])[-20:]; S.x_view = view; st.rerun()

def back(S):
    S.x_view = S.x_stack.pop() if S.x_stack else {"kind": "home"}; st.rerun()

def saved_ids(S) -> list[str]: return list(S.get("x_saved") or [])

def toggle_save(S, rid: str):
    ids = saved_ids(S)
    if rid in ids: ids.remove(rid); S.x_flash = "Removed from your saved careers"
    else: ids.append(rid); S.x_flash = "Saved — find it under Saved & compare"
    S.x_saved = ids

def react(S, rid: str, verdict: str):
    rx = dict(S.get("x_reactions") or {})
    if rx.get(rid) == verdict: rx.pop(rid)
    else: rx[rid] = verdict
    S.x_reactions = rx
    if rid not in saved_ids(S) and verdict != "no": S.x_saved = saved_ids(S) + [rid]
    S.x_flash = f"Noted: {REACTION_WORD[verdict]}" if rid in rx else "Reaction cleared"

def seed_from_state(S) -> dict | None:
    """What the interview receives from the explorer: saved careers + reactions. Saving is never treated as a choice (see graph/student_seed.py)."""
    ids = saved_ids(S); rx = S.get("x_reactions") or {}
    items = [{"id": i, "title": (C.get(i).title if C.get(i) else i), "reaction": rx.get(i)} for i in ids] + [{"id": i, "title": (C.get(i).title if C.get(i) else i), "reaction": v} for i, v in rx.items() if i not in ids]
    return {"saved": items, "at": time.time()} if items else None

def n_engaged(S) -> int: return len(set(saved_ids(S)) | set((S.get("x_reactions") or {}).keys()))

# ───────────────────────────── catalog loading (cached per process; visible progress on first load) ─────────────────────────────
@st.cache_resource(show_spinner=False)
def _load():
    C.records(); C._index(); return C.manifest()

def ensure_loaded():
    if "x_loaded" in st.session_state: return
    from tools.catalog import DIR as _CD, VERSION as _CV
    if (_CD / f"catalog_{_CV}.parquet").exists(): _load()   # warm path: instant and silent — no status box eating the top of the page
    else:
        with st.status("Building the career catalog from local data (first run, no AI)…", expanded=False) as box:
            m = _load(); box.update(label=f"Career catalog ready — {m['records']:,} careers", state="complete")
    st.session_state["x_loaded"] = True

# ───────────────────────────── shared widgets ─────────────────────────────
def header(S, title: str, kicker: str = "Career Explorer", show_back: bool = True):
    st.markdown(CSS, unsafe_allow_html=True)
    a, b = st.columns([4, 1.6])
    with a:
        st.markdown(f"<span class='kicker' style='color:{C_['student']}'>{esc(kicker)}</span>", unsafe_allow_html=True); st.markdown(f"## {title}")
    with b:
        n = len(saved_ids(S)); st.markdown(f"<div style='text-align:right;margin-top:14px'><span class='x-count' role='status' aria-label='{n} saved careers'>☆ {n} saved</span></div>", unsafe_allow_html=True)
        if st.button("Saved & compare →", key="hdr_saved", width="stretch", disabled=S.x_view.get("kind") == "saved"): go(S, {"kind": "saved"})
    row = st.columns([1, 1, 2.2])
    if show_back and row[0].button("← Back", key="hdr_back"): back(S)
    if S.x_view.get("kind") != "home" and row[1].button("Explorer home", key="hdr_home"): go(S, {"kind": "home"})
    if S.get("x_return"):
        if row[2].button("↩ Return to my interview", key="hdr_return"): S.stage = S.x_return; S.x_return = None; st.rerun()
    elif row[2].button("How does NextShift create these results? ⚙️", key="hdr_how", help="See what comes from official data, fixed code, AI, and your decisions."):
        from ui import explain
        explain.behind_the_scenes(S)
    if S.get("x_flash"): st.toast(S.x_flash); S.x_flash = None
    offer(S)

def offer(S):
    """After several saved/reacted careers: the hand-off to the interview (which uses them as evidence, not as a decision)."""
    if n_engaged(S) >= OFFER_AT and S.x_view.get("kind") not in ("saved",):
        c1, c2 = st.columns([3, 1.4])
        c1.markdown(f"<div class='x-card' style='border-color:{C_['amber']}66;margin:4px 0'><b>You saved several careers.</b> <span class='muted'>Would you like help understanding what they have in common and which ones may fit you?</span></div>", unsafe_allow_html=True)
        if c2.button("Yes — help me →", key="offer_btn", type="primary", width="stretch"):
            from ui import student_ui; student_ui.start(S, seed=seed_from_state(S))

def career_card(S, r: C.CatalogRecord, key: str, why: list[str] | None = None, show_open: bool = True, grid: bool = False):
    saved = r.id in saved_ids(S); g, gc = GROWTH_PILL[r.growth_class]; ai, ac = AI_PILL[r.ai_change_class]
    kind = "official occupation" if r.kind == "direct" else ("specialty within an official occupation" if r.kind == "detailed" else "composite — no official category")
    desc = r.description.split(". ")[0].rstrip(".") + "."
    fams = "".join(f"<span class='x-fam'>{esc(C.FAMILIES[f]['emoji'])} {esc(C.FAMILIES[f]['label'])}</span>" for f in r.families[: 2 if grid else 3] if f in C.FAMILIES)
    edu = f" · {esc(r.education_entry)}" if r.education_entry else ""
    matched = f"<div class='x-src'>matched: {esc(', '.join(why))}</div>" if why else ""
    rx = (S.get("x_reactions") or {}).get(r.id); rxs = f" · you said: {REACTION_WORD[rx]}" if rx else ""
    ai_pill = pill(ai, ac) if not grid else (pill(ai.split(" today")[0], ac))
    st.markdown(f"<div class='x-card{' saved' if saved else ''}{' x-grid-card' if grid else ''}'><div class='x-title'>{'☆ ' if saved else ''}{esc(r.title)}</div><div class='x-sub'>{kind}{edu}{esc(rxs)}</div><div class='x-desc x-grow' style='margin-top:6px;font-size:14px'>{esc(desc)}</div><div>{pill(g, gc)}{ai_pill}</div><div>{fams}</div>{matched}</div>", unsafe_allow_html=True)
    b = st.columns(2) if grid else st.columns([1.2, 1.2, 3])
    if show_open and b[0].button("Open →", key=f"open_{key}", width="stretch"): go(S, {"kind": "career", "id": r.id})
    if b[1].button("Unsave" if saved else "☆ Save", key=f"save_{key}", width="stretch"): toggle_save(S, r.id); st.rerun()

def career_list(S, recs: list[C.CatalogRecord], key: str, why: dict[str, list[str]] | None = None, empty: str = "Nothing matched those filters.", initial: int = PAGE):
    if not recs: st.markdown(f"<div class='x-empty'>{esc(empty)}</div>", unsafe_allow_html=True); return
    n = S.x_page.get(key, initial)
    show = recs[:n]; per = 3   # horizontal cards: three per row on the full-width layout, equal height
    for row in range(0, len(show), per):
        cols = st.columns(per)
        for col, (i, r) in zip(cols, list(enumerate(show))[row: row + per]):
            with col: career_card(S, r, f"{key}_{i}", (why or {}).get(r.id), grid=True)
    if len(recs) > n:
        st.markdown(f"<div class='x-src' style='text-align:center'>Showing the top {n} of {len(recs)} matches</div>" if n == initial and initial < PAGE else f"<div class='x-src' style='text-align:center'>Showing {n} of {len(recs)}</div>", unsafe_allow_html=True)
        if st.button(f"Show {min(PAGE, len(recs) - n)} more matches", key=f"more_{key}", width="stretch"): S.x_page[key] = n + PAGE; st.rerun()

def filters(S, key: str) -> dict:
    """Plain-language filters. Returns kwargs for catalog.browse-style post-filtering."""
    with st.expander("Narrow this down", expanded=False):
        c = st.columns(3)
        g = c[0].selectbox("Jobs outlook (BLS projection to 2035)", ["Any", "Projected to grow (≥ +5%)", "Roughly stable", "Projected to decline"], key=f"f_g_{key}")
        z = c[1].selectbox("Preparation needed (O*NET Job Zone)", ["Any", "Little or some (1–2)", "Medium — training, apprenticeship or associate's (3)", "Usually a bachelor's (4)", "Graduate or professional degree (5)"], key=f"f_z_{key}")
        a = c[2].selectbox("AI use in its tasks today (observed, not a forecast)", ["Any", "Many tasks", "Some tasks", "Few or none"], key=f"f_a_{key}")
        st.markdown("<div class='x-src'>Outlook = number of jobs, from BLS. AI use = where AI is already used in the tasks, from the Anthropic Economic Index. They are different things: a career can grow and have heavy AI use at the same time.</div>", unsafe_allow_html=True)
    return {"growth": {"Any": None, "Projected to grow (≥ +5%)": "growing", "Roughly stable": "stable", "Projected to decline": "declining"}[g],
            "zones": {"Any": None, "Little or some (1–2)": (1, 2), "Medium — training, apprenticeship or associate's (3)": (3,), "Usually a bachelor's (4)": (4,), "Graduate or professional degree (5)": (5,)}[z],
            "ai": {"Any": None, "Many tasks": ("substantial",), "Some tasks": ("moderate",), "Few or none": ("limited", "unknown")}[a]}

def apply_filters(recs, f: dict):
    out = recs
    if f.get("growth"): out = [r for r in out if r.growth_class == f["growth"]]
    if f.get("zones"): out = [r for r in out if r.job_zone in f["zones"]]
    if f.get("ai"): out = [r for r in out if r.ai_change_class in f["ai"]]
    return out

# ───────────────────────────── screens ─────────────────────────────
def screen_home(S):
    header(S, "Explore the world of work", show_back=False)
    st.markdown(f"<p class='muted'>Most students know a few dozen careers. The U.S. government tracks about a thousand. Browse by what you like doing, by school subject, or by family — and save the ones worth a second look.</p><p class='small'>{esc(C.coverage_line())}</p>", unsafe_allow_html=True)
    with st.form("x_search", border=False):
        q = st.text_input("Search", placeholder="A career title, or plain words — “helping animals”, “video games”, “working outdoors with plants”", label_visibility="collapsed")
        if st.form_submit_button("Search →", type="primary") and q.strip(): go(S, {"kind": "search", "q": q.strip()})
    st.markdown("<span class='x-q'>What do you like doing?</span>", unsafe_allow_html=True)
    cols = st.columns(4)
    for i, (tid, t) in enumerate(C.TRAITS.items()):
        if cols[i % 4].button(f"{t['emoji']} {t['label']}", key=f"trait_{tid}", width="stretch"): go(S, {"kind": "browse", "trait": tid})
    st.markdown("<span class='x-q' style='display:block;margin-top:14px'>Discover</span>", unsafe_allow_html=True)
    cols = st.columns(2)
    for i, (cid, c) in enumerate(C.COLLECTIONS.items()):
        with cols[i % 2]:
            st.markdown(f"<div class='x-card'><div class='x-title'>{esc(c['emoji'])} {esc(c['label'])}</div><div class='x-sub'>{esc(c['blurb'])}</div></div>", unsafe_allow_html=True)
            if st.button("Browse →", key=f"col_{cid}", width="stretch"): go(S, {"kind": "collection", "name": cid})
    st.markdown("<span class='x-q' style='display:block;margin-top:14px'>Career families</span>", unsafe_allow_html=True)
    fams = C.family_summary(); cols = st.columns(2)
    for i, f in enumerate(fams):
        with cols[i % 2]:
            st.markdown(f"<div class='x-card'><div class='x-title'>{esc(f['emoji'])} {esc(f['label'])}</div><div class='x-sub'>{esc(f['blurb'])}</div><div class='x-src' style='margin-top:6px'>{f['count']} careers · {f['growing']} projected to grow · e.g. {esc(', '.join(f['examples'][:2]))}</div></div>", unsafe_allow_html=True)
            if st.button("Explore →", key=f"fam_{f['id']}", width="stretch"): go(S, {"kind": "family", "id": f["id"]})
    st.markdown("<span class='x-q' style='display:block;margin-top:14px'>By school subject or preparation level</span>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        subj = st.selectbox("A subject you like", ["Choose a subject…"] + list(C.SUBJECTS), label_visibility="visible", key="home_subject")
        if subj != "Choose a subject…" and st.button("Careers that use it →", key="go_subject", width="stretch"): go(S, {"kind": "browse", "subject": subj})
    with c2:
        zone = st.selectbox("How much preparation are you open to?", ["Choose a level…"] + [f"Job Zone {z}: {C.ZONE_SHORT[z]}" for z in (1, 2, 3, 4, 5)], key="home_zone")
        if zone != "Choose a level…" and st.button("Careers at this level →", key="go_zone", width="stretch"): go(S, {"kind": "browse", "zone": int(zone.split()[2][0])})
    st.markdown(f"<p class='small' style='margin-top:18px'>{esc(BOUNDARY)}</p>", unsafe_allow_html=True)

def screen_family(S):
    fid = S.x_view["id"]; f = C.FAMILIES.get(fid)
    if not f: header(S, "Unknown family"); return
    header(S, f"{f['emoji']} {f['label']}")
    st.markdown(f"<p class='muted'>{esc(f['blurb'])}</p><p class='small'>Families are a NextShift grouping over the official occupation codes (a career can sit in more than one). The list is sorted by how many people do the job.</p>", unsafe_allow_html=True)
    fl = filters(S, f"fam_{fid}"); recs = apply_filters(C.browse(family=fid, include_residual=False), fl)
    career_list(S, recs, f"fam_{fid}", empty="No careers in this family match those filters — loosen one of them.")

def screen_collection(S):
    name = S.x_view["name"]; c = C.COLLECTIONS.get(name)
    if not c: header(S, "Unknown collection"); return
    header(S, f"{c['emoji']} {c['label']}")
    st.markdown(f"<p class='muted'>{esc(c['blurb'])}</p><p class='small'><b>How this list is made:</b> {esc(c['explain'])}</p>", unsafe_allow_html=True)
    if name == "unknown" and st.button("🔀 Show me different ones", key="reshuffle"): S.x_seed = int(S.x_seed) + 1; S.x_page.pop(f"col_{name}", None); st.rerun()
    fl = filters(S, f"col_{name}"); recs = apply_filters(C.collection(name, seed=int(S.get("x_seed", 0))), fl)
    career_list(S, recs, f"col_{name}", empty="Nothing in this collection matches those filters.")

def screen_browse(S):
    v = S.x_view; kw = {}
    if v.get("trait"): t = C.TRAITS[v["trait"]]; header(S, f"{t['emoji']} {t['label']}"); st.markdown(f"<p class='muted'>{esc(t['blurb'])}</p><p class='small'>A career is listed when O*NET rates the matching work activity, interest or knowledge area high for it; each card's page shows the exact rating.</p>", unsafe_allow_html=True); kw["trait"] = v["trait"]
    elif v.get("subject"): header(S, f"Careers that use {v['subject']}"); st.markdown("<p class='small'>Listed when O*NET rates knowledge of this subject as important for the occupation (on a 1–5 scale). It says what the job draws on, not what you must major in.</p>", unsafe_allow_html=True); kw["subject"] = v["subject"]
    elif v.get("zone"): header(S, f"Job Zone {v['zone']}: {C.ZONE_SHORT[v['zone']]}"); st.markdown("<p class='small'>O*NET Job Zones group occupations by how much education, experience and training they usually need. Individual paths vary.</p>", unsafe_allow_html=True); kw["zone"] = v["zone"]
    else: header(S, "Browse")
    fl = filters(S, "browse"); recs = apply_filters(C.browse(include_residual=False, **kw), fl)
    career_list(S, recs, "browse")

def screen_search(S):
    q = S.x_view["q"]; header(S, f"Results for “{q}”")
    with st.form("x_search2", border=False):
        q2 = st.text_input("Search again", value=q, label_visibility="collapsed")
        if st.form_submit_button("Search →") and q2.strip() and q2.strip() != q: go(S, {"kind": "search", "q": q2.strip()})
    t0 = time.perf_counter(); res = C.search(q, 24); ms = (time.perf_counter() - t0) * 1000
    rs = C.records(); why = {h["id"]: h["why"] for h in res["meaning_matches"]}
    if res["total"] == 0:
        st.markdown(f"<div class='x-empty'>No career matched “{esc(q)}”. Try plainer words for the activity (“fixing cars”, “helping kids learn”), a school subject, or browse a family below.</div>", unsafe_allow_html=True)
        if st.button("Browse families instead", key="srch_home"): go(S, {"kind": "home"})
        return
    st.markdown(f"<div class='x-src'>{res['total']} matches in {ms:.0f} ms — {len(res['title_matches'])} by title, {len(res['meaning_matches'])} by what the work involves. The top five are shown first; no AI is used in search.</div>", unsafe_allow_html=True)
    all_ids = [h["id"] for h in res["title_matches"] + res["meaning_matches"]]
    if res["total"] >= 10:   # umbrella queries ("doctor", "engineer"): say where the crowd is and offer the whole family
        fam_count = {}
        for i_ in all_ids:
            for fm in rs[i_].families: fam_count[fm] = fam_count.get(fm, 0) + 1
        top_f, n_f = max(fam_count.items(), key=lambda kv: kv[1]) if fam_count else (None, 0)
        if top_f and n_f >= res["total"] * 0.5:
            f_ = C.FAMILIES[top_f]; c1, c2 = st.columns([3, 1.4])
            c1.markdown(f"<div class='x-card' style='margin:4px 0'><b>“{esc(q)}” is a broad one</b> <span class='muted'>— {n_f} of the {res['total']} matches are {esc(f_['emoji'])} {esc(f_['label'])} careers. The five below are just the biggest.</span></div>", unsafe_allow_html=True)
            if c2.button(f"Browse all {esc(f_['label'])} →", key="srch_family", width="stretch"): go(S, {"kind": "family", "id": top_f})
    for h in res["title_matches"]: why[h["id"]] = [f"title: {h['matched']}"] if h["matched"] != rs[h["id"]].title else ["title"]
    ordered = [rs[h["id"]] for h in res["title_matches"]] + [rs[h["id"]] for h in res["meaning_matches"]]
    career_list(S, ordered, f"s_{q}", why, initial=5)

def _src(text: str) -> str: return f"<div class='x-src'>{esc(text)}</div>"

LAYER = {"fact": ("Official source", C_["green"]), "rule": ("Derived by a fixed rule", C_["amber"]), "model": ("Written by AI · reviewed", C_["purple"]), "you": ("Personal to you", C_["student"])}
def layer_tag(kind: str) -> str:
    lab, col = LAYER[kind]; return f"<span class='x-pill' style='background:{col}22;color:{col};border:1px solid {col}66;font-size:11px;margin:0 0 4px 0'>{esc(lab)}</span>"

def sourced_line(s, fmt=lambda v: v) -> str:
    """Render a layer-1 Sourced value with its provenance, or the honest gap sentence."""
    from tools.career_page import UNAVAILABLE
    if s is None: return f"<div class='x-fact warn'>{esc(UNAVAILABLE)}</div>"
    prov = f"{s.source_name}" + (f" · {s.as_of[:4]}" if s.as_of else "") + (f" · retrieved {s.retrieved}" if s.retrieved else "")
    return f"<div class='x-fact'>{fmt(s.value)}<div class='x-src'>{esc(prov)}{(' · ' + esc(s.note)) if s.note else ''}</div></div>"

def _cited(text: str, it) -> str:
    from tools.career_page import strip_refs, cited_sources
    srcs = cited_sources(text, it); tail = f" <span class='x-src'>· {esc(', '.join(srcs))}</span>" if srcs else (" <span class='x-src'>· suggestion</span>" if "[advice]" in (text or "") else "")
    return f"{esc(strip_refs(text))}{tail}"

def _para(lines, it) -> str:
    """One paragraph from reviewed sentences; sources aggregated into a single footnote instead of after every sentence."""
    from tools.career_page import strip_refs, cited_sources
    lines = lines if isinstance(lines, list) else ([lines] if lines else [])
    text = " ".join(strip_refs(l) for l in lines if strip_refs(l)); srcs = []
    for l in lines: srcs += cited_sources(l, it)
    srcs = list(dict.fromkeys(srcs))
    return (f"<div style='font-size:15px;line-height:1.65;margin:2px 0 4px'>{esc(text)}</div>" + (f"<div class='x-src'>{esc(' · '.join(srcs))}</div>" if srcs else "")) if text else ""

def render_interpretation(S, it, rid: str):
    """The narrative brief — the model retells the page's sourced facts in plain language; labels fixed in code, never model-written."""
    from tools.career_page import NARRATIVE_TITLES
    sec = it.sections; rec = it.review
    st.markdown(f"<div class='x-src'>{layer_tag('model')} From the sourced facts on this page, checked line by line ({rec.get('total', 0)} lines, {len(rec.get('stripped', []))} removed) — not an official BLS or O*NET conclusion · {esc(it.generated_at[:10])}{' · reused from cache' if it.cached else ''}</div>", unsafe_allow_html=True)
    if rec.get("status") == "unverified": st.error("Unverified: the reviewer step failed for this explanation, so it was checked for citations and language only — not for accuracy.")
    left, right = st.columns([1.6, 1])
    with left:
        for key in ("what_is_it", "outlook_story", "ai_story"):
            html_ = _para(sec.get(key), it)
            if html_: st.markdown(f"<span class='x-q'>{esc(NARRATIVE_TITLES[key])}</span>", unsafe_allow_html=True); st.markdown(html_, unsafe_allow_html=True)
        if sec.get("typical_day"):
            st.markdown(f"<span class='x-q'>{esc(NARRATIVE_TITLES['typical_day'])}</span><div class='x-src'>{esc(it.labels['day_in_the_life'])}</div>", unsafe_allow_html=True)
            st.markdown(_para(sec["typical_day"], it), unsafe_allow_html=True)
    with right:
        for key in ("who_thrives", "get_ready"):
            if sec.get(key):
                st.markdown(f"<span class='x-q'>{esc(NARRATIVE_TITLES[key])}</span>", unsafe_allow_html=True)
                for l in sec[key]: st.markdown(f"<div class='x-fact ai'>{_cited(l, it)}</div>", unsafe_allow_html=True)
    if rec.get("stripped"):
        with st.expander(f"Review details — what the checks removed ({len(rec['stripped'])})"):
            st.markdown(f"<div class='x-src'>{esc(it.labels['model'])} {rec.get('lint_removed', 0)} line(s) removed by fixed rules, {rec.get('model_removed', 0)} by the independent reviewer ({esc(it.reviewer)}).</div>", unsafe_allow_html=True)
            for r in rec["stripped"]: st.markdown(f"<div class='x-fact'>✂ {esc(strip_refs_(r['sentence']))}<br><span class='x-src'>{esc(r['reason'])}</span></div>", unsafe_allow_html=True)
    with st.expander(f"Evidence the model was given ({len(it.cards)} facts)"):
        for k, cid in it.refs.items():
            c = next((c for c in it.cards if c["id"] == cid), None)
            if c: st.markdown(f"<div class='x-fact'>[{k}] {esc(c['claim'][:180])}<br><span class='x-src'>{esc(c['source'])} · {esc(c.get('as_of') or 'n.d.')}</span></div>", unsafe_allow_html=True)

def strip_refs_(t): 
    from tools.career_page import strip_refs; return strip_refs(t)

def generate_block(S, rid: str, r: C.CatalogRecord):
    """Layer 3 controls: show a cached explanation instantly (no model call); otherwise offer to generate with a live progress box; duplicate clicks are ignored."""
    from tools import career_page as P
    it = P.cached_interpretation("career", [rid])
    gen = S.get("x_gen") or {}; inflight = gen.get("id") == rid and time.time() - gen.get("t", 0) < 180   # a stale flag (crashed run) unlocks after 3 minutes
    if it is None:
        st.markdown(f"<div class='x-card'><div class='x-title'>Get the short version</div><div class='x-sub'>An AI model can summarize everything on this page — what the job is, an illustrative day, “you may enjoy this if…” lines tied to real tasks, and how AI may touch the work. It sees only the sourced facts below, every line cites them, fixed checks remove unsupported numbers or absolute claims, and a separate reviewer checks the rest. First time takes 1–2 minutes; after that it's instant for everyone.</div></div>", unsafe_allow_html=True)
        if st.button("Summarize this career (AI, reviewed) →", key="c_gen", type="primary", disabled=inflight, help="Disabled while a summary for this career is being written" if inflight else None):
            S.x_gen = {"id": rid, "t": time.time()}
            with st.status("Writing the summary from the sourced facts…", expanded=True) as box:
                try: it = P.generate_interpretation(rid, progress=lambda t: box.write(f"· {t}")); box.update(label="Summary ready", state="complete", expanded=False)
                except Exception as e: box.update(label="The model could not be reached — the sourced facts above are unaffected. Try again in a moment.", state="error"); st.write(f"{type(e).__name__}"); S.x_gen = None; return
            S.x_gen = None; st.rerun()
    else: render_interpretation(S, it, rid)

def screen_career(S):
    from tools import career_page as P
    rid = S.x_view["id"]; pg = P.page(rid)
    if not pg: header(S, "Career not found"); st.markdown("<div class='x-empty'>This career is not in the catalog.</div>", unsafe_allow_html=True); return
    f, d, r = pg.facts, pg.derived, C.get(rid); header(S, r.title, kicker="Career page")
    kind = {"direct": f"Official U.S. occupation {r.soc}", "detailed": f"O*NET specialty {r.onet_soc} within “{r.bls_title}”", "composite": "Composite role — no official category"}[r.kind]
    fams = " ".join(f"{C.FAMILIES[fid]['emoji']} {C.FAMILIES[fid]['label']}" for fid in r.families[:3] if fid in C.FAMILIES)
    top = st.columns([4.2, 1.3])
    top[0].markdown(f"<div class='x-sub'>{esc(kind)} · {esc(fams)}</div>", unsafe_allow_html=True)
    with top[1].popover("ⓘ How to read this page", width="stretch"):
        st.markdown("Every line is labelled by where it comes from:", unsafe_allow_html=False)
        st.markdown(" ".join(layer_tag(k) for k in ("fact", "rule", "model", "you")), unsafe_allow_html=True)
        st.markdown("- Facts and figures come **only** from the official sources named next to them; a missing figure says so — nothing is estimated.\n"
                    "- The four tiles are separate readings: jobs today, projected direction, where AI is already used in the tasks, and what to learn. A career can have heavy AI use and still grow — task exposure is not an employment forecast.\n"
                    "- Reactions stay in this session and, if you ask for guidance, go to the interview as things you noticed — not as a decision.\n"
                    "- Use ← Back here (not the browser's); the page URL always points at what you're viewing, so refresh, bookmark and share all work.")
    if r.bls_note: st.markdown(f"<div class='x-fact warn'>{esc(r.bls_note)}</div>", unsafe_allow_html=True)
    if r.kind == "composite": st.markdown(f"<div class='x-fact warn'>{esc(r.note)} Closest official categories: {esc(', '.join(p['title'] for p in r.proxies))}.</div>", unsafe_allow_html=True)
    saved = rid in saved_ids(S); rx = (S.get("x_reactions") or {}).get(rid)
    b = st.columns([1.3, 1.1, 0.9, 1.1, 1.1])
    if b[0].button("Unsave" if saved else "☆ Save this career", key="c_save", type="primary" if not saved else "secondary", width="stretch"): toggle_save(S, rid); st.rerun()
    for col, (val, lab) in zip(b[1:], REACTIONS):
        if col.button(("✓ " if rx == val else "") + lab, key=f"c_rx_{val}", width="stretch"): react(S, rid, val); st.rerun()
    # trajectory (layer 2 over layer 1)
    tj = d.trajectory.value; cols = st.columns(4)
    def tile(col, label, big, big_cls, sub, src):
        col.markdown(f"<div class='x-traj'><b>{esc(label)}</b><div class='x-big {big_cls}'>{esc(big)}</div><div style='font-size:12.5px;color:{C_['muted']}'>{esc(sub)}</div><div class='x-src' style='margin-top:7px'>{esc(src)}</div></div>", unsafe_allow_html=True)
    tile(cols[0], "Jobs today", C._fmt_int(r.emp_2025) if r.emp_2025 is not None else "—", "", (f"typical entry: {r.education_entry.lower()}" if r.education_entry else "no official count") if r.emp_2025 is not None else ("composite — see proxies" if r.kind == "composite" else "no official count"), "BLS 2025")
    g_cls = {"growing": "up", "declining": "down", "stable": "flat"}.get(r.growth_class, "")
    tile(cols[1], "Direction to 2035", (f"{r.growth_pct:+.1f}%" if r.growth_pct is not None else "—"), g_cls, (f"{GROWTH_PILL[r.growth_class][0]} · ~{C._fmt_int(r.openings_annual)} openings/yr" if r.growth_pct is not None else "no official projection"), "BLS projection 2025–35")
    tile(cols[2], "AI in the tasks today", (f"{int(round(r.ai_task_share * r.n_tasks))} of {r.n_tasks}" if r.ai_task_share is not None else "—"), "ai", ("tasks show heavy observed AI use" if r.ai_task_share is not None else "no task-level AI data"), "observed use, not a forecast · AEI")
    tile(cols[3], "Skills to begin building", (tj["skills"][0] if tj["skills"] else "—"), "", ", ".join(tj["skills"][1:4]), "O*NET · not personalized")

    # ── the short version first (layer 3: cached AI summary, or the offer to write one)
    st.markdown("### At a glance")
    generate_block(S, rid, r)
    # ── everything else: same sourced sections, grouped and collapsed so the page reads short
    st.markdown("<p class='muted' style='margin-top:10px'>Every figure behind the summary, with its source — open what you want to check.</p>", unsafe_allow_html=True)
    with st.expander("The work — what it is, what people do, what a day feels like, who may enjoy it (1–5)", expanded=False):
        # ── layer 1 + 2 sections
        st.markdown(f"### 1 · What is this career? {layer_tag('fact')}", unsafe_allow_html=True); st.markdown(sourced_line(f.description, lambda v: esc(v)), unsafe_allow_html=True)
        st.markdown(f"### 2 · What do people in it actually do? {layer_tag('fact')}", unsafe_allow_html=True)
        if f.tasks:
            for t in f.tasks.value[:8]: st.markdown(f"<div class='x-fact'>{esc(t['task'])}</div>", unsafe_allow_html=True)
            st.markdown(_src(f"{r.n_tasks} task statements ({f.tasks.source_name}, retrieved {f.tasks.retrieved}); the first {min(8, r.n_tasks)} shown, core tasks first."), unsafe_allow_html=True)
        else: st.markdown(sourced_line(None), unsafe_allow_html=True)
        st.markdown(f"### 3 · What might a typical workday feel like? {layer_tag('rule')}", unsafe_allow_html=True)
        if d.workday_hints.value:
            for w in d.workday_hints.value: st.markdown(f"<div class='x-fact'>{esc(w['text'])} <span class='x-src'>· {esc(w['evidence'])}</span></div>", unsafe_allow_html=True)
            st.markdown(_src(f"Rule: {d.workday_hints.rule} — typical conditions reported by workers ({f.work_context.source_name if f.work_context else 'O*NET'}), not any one job. The AI explanation below can turn these into an illustrative day."), unsafe_allow_html=True)
        else: st.markdown(sourced_line(None), unsafe_allow_html=True)
        st.markdown(f"### 4 · Who may enjoy this kind of work? {layer_tag('rule')}", unsafe_allow_html=True)
        if d.enjoy_hints.value:
            for e in d.enjoy_hints.value: st.markdown(f"<div class='x-fact'>{esc(e['text'])} <span class='x-src'>· {esc(e['evidence'])}</span></div>", unsafe_allow_html=True)
            st.markdown(_src("About the work, not about you: O*NET's interest profile and activity ratings for the occupation. Whether it fits you is what the guided conversation is for."), unsafe_allow_html=True)
        else: st.markdown(sourced_line(None), unsafe_allow_html=True)
        st.markdown(f"### 5 · What strengths or working preferences may help? {layer_tag('fact')}", unsafe_allow_html=True)
        sa, sk = st.columns(2); sv = d.strengths_hints.value
        with sa:
            st.markdown("<span class='x-q'>Activities rated most important</span>", unsafe_allow_html=True)
            for x in sv["activities"]: st.markdown(f"<div class='x-fact'>{esc(x['text'])} <span class='x-src'>· {esc(x['evidence'])}</span></div>", unsafe_allow_html=True)
        with sk:
            st.markdown("<span class='x-q'>Knowledge areas rated most important</span>", unsafe_allow_html=True)
            for x in sv["knowledge"]: st.markdown(f"<div class='x-fact'>{esc(x['text'])} <span class='x-src'>· {esc(x['evidence'])}</span></div>", unsafe_allow_html=True)
        if not sv["activities"] and not sv["knowledge"]: st.markdown(sourced_line(None), unsafe_allow_html=True)
    with st.expander("Preparation and outlook — education, jobs, growth, openings, pay (6–9)", expanded=False):
        st.markdown(f"### 6 · What education, training or preparation is commonly needed? {layer_tag('fact')}", unsafe_allow_html=True)
        st.markdown(sourced_line(f.education_entry, lambda v: f"Typical education for entry: <b>{esc(v)}</b>"), unsafe_allow_html=True)
        if f.experience_entry: st.markdown(sourced_line(f.experience_entry, lambda v: f"Work experience usually needed: {esc(v)}"), unsafe_allow_html=True)
        if f.training_entry: st.markdown(sourced_line(f.training_entry, lambda v: f"On-the-job training: {esc(v)}"), unsafe_allow_html=True)
        if f.job_zone: st.markdown(sourced_line(f.job_zone, lambda v: f"O*NET Job Zone {v['zone']} — {esc(v['name'])}"), unsafe_allow_html=True)
        st.markdown(f"<div class='x-fact'>Licensing requirements: <span class='x-src'>{esc(P.UNAVAILABLE)}</span></div>", unsafe_allow_html=True)
        st.markdown(f"### 7 · About how many jobs exist? · 8 · Growing or declining? · 9 · Annual openings? {layer_tag('fact')}", unsafe_allow_html=True)
        c7, c8, c9 = st.columns(3); g, gc = GROWTH_PILL[r.growth_class]
        def prov(s): return esc(f"{s.source_name} · {s.as_of[:4]} · retrieved {s.retrieved}") if s else esc(P.UNAVAILABLE)
        c7.markdown(f"<div class='x-traj'><b>Jobs in 2025</b><div style='font-size:22px;margin-top:6px'>{esc(C._fmt_int(r.emp_2025)) if f.employment_2025 else '—'}</div><div class='x-src'>{prov(f.employment_2025)}</div></div>", unsafe_allow_html=True)
        c8.markdown(f"<div class='x-traj'><b>2025 → 2035</b><div style='margin-top:6px'>{pill(g, gc)}</div><div style='font-size:15px;margin-top:4px'>{(f'{r.growth_pct:+.1f}% ({esc(C._fmt_int(r.emp_change))} jobs) · all occupations {C.NATIONAL_GROWTH:+.1f}%' if f.growth_pct else esc(P.UNAVAILABLE))}</div><div class='x-src'>{prov(f.growth_pct)}{' · a projection with uncertainty, not a promise' if f.growth_pct else ''}</div></div>", unsafe_allow_html=True)
        c9.markdown(f"<div class='x-traj'><b>Openings per year</b><div style='font-size:22px;margin-top:6px'>{esc(C._fmt_int(r.openings_annual)) if f.openings_annual else '—'}</div><div class='x-src'>{prov(f.openings_annual)}{' · growth plus people leaving or retiring' if f.openings_annual else ''}</div></div>", unsafe_allow_html=True)
        if r.growth_class == "declining" and r.openings_annual: st.markdown(f"<div class='x-fact warn'>Fewer jobs overall does not mean no way in: about {esc(C._fmt_int(r.openings_annual))} openings a year are still projected as people retire or move.</div>", unsafe_allow_html=True)
        st.markdown(sourced_line(f.median_wage, lambda v: f"Median annual wage: ${v:,.0f}"), unsafe_allow_html=True)
        st.markdown(f"<div class='x-fact'>Industries employing this occupation: <span class='x-src'>{esc(P.UNAVAILABLE)}</span></div>", unsafe_allow_html=True)
        if f.bls_factors:
            st.markdown(f"<span class='x-q'>Why BLS expects the change it projects</span>", unsafe_allow_html=True)
            for x in f.bls_factors.value[:3]: st.markdown(f"<div class='x-fact'>{esc(x['text'])}<div class='x-src'>{esc(x['industry'])} · {esc(f.bls_factors.source_name)} Table 1.12 · retrieved {esc(f.bls_factors.retrieved)}</div></div>", unsafe_allow_html=True)
    with st.expander("AI and the human side — task-level AI use, what stays human, skills (10–13)", expanded=False):
        st.markdown(f"### 10 · Which tasks may AI reshape, and 11 · which parts stay strongly human? {layer_tag('rule')}", unsafe_allow_html=True)
        ai = C.ai_task_groups(r); ca, ch = st.columns(2)
        with ca:
            st.markdown(f"<span class='x-q' style='color:{C_['purple']}'>Tasks where AI is already commonly used</span>", unsafe_allow_html=True)
            if ai["heavy"]:
                for t in ai["heavy"][:6]: st.markdown(f"<div class='x-fact ai'>{esc(t['task'])}<br><span class='x-src'>observed AI use {t['penetration']:.2f}</span></div>", unsafe_allow_html=True)
            elif r.n_tasks_observed: st.markdown("<div class='x-empty'>None of this occupation's tasks show heavy AI use in the observed data so far.</div>", unsafe_allow_html=True)
            else: st.markdown(sourced_line(None), unsafe_allow_html=True)
            if ai["mid"]:
                st.markdown("<span class='x-q'>Some observed use — direction unclear</span>", unsafe_allow_html=True)
                for t in ai["mid"][:4]: st.markdown(f"<div class='x-fact'>{esc(t['task'])}<br><span class='x-src'>observed AI use {t['penetration']:.2f}</span></div>", unsafe_allow_html=True)
        with ch:
            st.markdown(f"<span class='x-q' style='color:{C_['student']}'>Parts of the work that rate high as in-person, physical or judgment-based</span>", unsafe_allow_html=True)
            hs = C.human_side(r)
            if hs:
                for h in hs: st.markdown(f"<div class='x-fact h'>{esc(h['text'])} <span class='x-src'>· {esc(h['evidence'])}</span></div>", unsafe_allow_html=True)
                st.markdown(_src(f"Rule: {d.human_intensive.rule}. It describes today's work, not a guarantee about the future."), unsafe_allow_html=True)
            else: st.markdown("<div class='x-empty'>No activity in this occupation rates high on the in-person / hands-on / judgment scales we check.</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='x-fact warn'>{esc(ai['method'])} Current use is not automation, and heavy use is not a job-loss forecast: {esc(r.title)} is {esc(C.GROWTH_LABEL[r.growth_class].lower())} while {esc(C.AI_LABEL[r.ai_change_class].lower())}.</div>", unsafe_allow_html=True)
        # ── layer 3
        st.markdown(f"### 12 · What new responsibilities could AI create? · 13 · What skills would help someone stay relevant? {layer_tag('model')}", unsafe_allow_html=True)
        st.markdown(f"<div class='x-src'>These two need interpretation, so they are not read off a table. Starting points from the data: the knowledge and activities rated most important above — {esc(', '.join(tj['skills'][:4]))}. The AI explanation below reasons about them task by task, citing the evidence, and a separate reviewer checks it.</div>", unsafe_allow_html=True)
    with st.expander("Related careers and ways to test your interest (14–15)", expanded=False):
        # ── 14–15 (layer 1 + 2)
        st.markdown(f"### 14 · Related or adjacent careers {layer_tag('fact')}", unsafe_allow_html=True)
        rel = C.related(rid)
        if rel:
            cols = st.columns(2)
            for i, x in enumerate(rel[:8]):
                gl, _ = GROWTH_PILL[x.growth_class]
                with cols[i % 2]:
                    if st.button(f"{x.title}  ·  {gl.split(' ', 1)[1] if ' ' in gl else gl}", key=f"rel_{i}", width="stretch"): go(S, {"kind": "career", "id": x.id})
            st.markdown(_src(f"{C.SOURCES['onet']['name']} related occupations (official list){' — for a composite, the occupations its tasks come from' if r.kind == 'composite' else ''}."), unsafe_allow_html=True)
        else: st.markdown(sourced_line(None), unsafe_allow_html=True)
        st.markdown(f"### 15 · What could you do now to test whether this interests you? {layer_tag('rule')}", unsafe_allow_html=True)
        for x in d.test_ideas.value: st.markdown(f"<div class='x-fact h'>{esc(x)}</div>", unsafe_allow_html=True)
        st.markdown(_src(f"Rule: {d.test_ideas.rule} — general, not personalized. The guided conversation turns these into a plan built around what you say."), unsafe_allow_html=True)
    # ── hand-offs (layer 4)
    st.markdown("---"); st.markdown(f"### Go further {layer_tag('you')}", unsafe_allow_html=True)
    st.markdown("<p class='muted'>Everything above came from local data in milliseconds (plus the optional reviewed explanation). The two options below use the AI agent with your own input — they take minutes, cite their evidence, pass a separate reviewer, and pause for your approval.</p>", unsafe_allow_html=True)
    h1, h2 = st.columns(2)
    with h1:
        st.markdown("<div class='x-card'><div class='x-title'>Help me find my direction</div><div class='x-sub'>A short conversation about what energizes you. The careers you saved and your reactions come along as things you noticed while browsing — not as a choice.</div></div>", unsafe_allow_html=True)
        if st.button("Start the guided conversation →", key="c_interview", width="stretch"):
            if rid not in saved_ids(S): S.x_saved = saved_ids(S) + [rid]
            from ui import student_ui; student_ui.start(S, seed=seed_from_state(S))
    with h2:
        st.markdown(f"<div class='x-card'><div class='x-title'>Deeper AI-era analysis of {esc(r.title)}</div><div class='x-sub'>Gathers task-level AI-use evidence, forecasts and the official outlook; a model writes an outlook and a preparation plan; a different model checks every line; you approve before it is saved. Usually 2–4 minutes.</div></div>", unsafe_allow_html=True)
        if st.button("Request the analysis and plan →", key="c_analysis", type="primary", width="stretch"): start_analysis(S, r)
    st.markdown(f"<p class='small'>{esc(BOUNDARY)}</p>", unsafe_allow_html=True)

def start_analysis(S, r: C.CatalogRecord):
    """Hand-off to the existing evidence → reviewer → gates graph (graph/build.py) for ONE career, framed for a student. Duplicate clicks are absorbed by the stage change."""
    import uuid
    if S.get("stage") == "understanding_run": return
    if r.kind == "composite":
        from tools import composite
        comp = composite.curated(r.title.replace(" (composite)", "")); per = composite.persona_from(comp, 2035) if comp else None
        if per: per.pop("horizon", None)
    else: per = {"soc": r.soc, "onet_soc": r.onet_soc, "title": r.title, "matched_via": "career explorer"}
    if not per: st.error("This composite has no curated task list, so the analysis cannot run."); return
    rx = (S.get("x_reactions") or {})
    S.profile = {"door": "student", "interests": [C.TRAITS[t]["label"].lower() for t in r.traits][:3], "strengths": [], "careers": [r.title], "constraints": {}, "concerns": ["demand", "change", "learn"], "horizon": "2035",
                 "question": f"Is demand for {r.title} expected to grow, how may AI reshape the work, and what could a student do now to prepare?", "explorer_context": {"saved": saved_ids(S), "reaction": rx.get(r.id)}}
    S.targets = [{"persona": per, "role": "candidate"}]; S.door = "professional"; S.x_from_explorer = r.id; S.x_return = "explore"
    S.thread_id = str(uuid.uuid4()); S.log = []; S.step = 0; S.stage = "understanding_run"; st.rerun()

def screen_saved(S):
    header(S, "Saved & compare", show_back=True)
    ids = [i for i in saved_ids(S) if C.get(i)]; rx = S.get("x_reactions") or {}
    if not ids:
        st.markdown("<div class='x-empty'>You haven't saved any careers yet. Open a career page and press ☆ Save — then come back here to compare up to four side by side.</div>", unsafe_allow_html=True); return
    st.markdown("<p class='muted'>Tick up to four to compare them row by row. There is no score and no winner — just the same questions asked of each.</p>", unsafe_allow_html=True)
    picked = S.setdefault("x_compare_pick", ids[:MAX_COMPARE])
    picked = [p for p in picked if p in ids]
    for i, rid in enumerate(ids):
        r = C.get(rid); c = st.columns([0.5, 3, 2, 1, 1])
        on = c[0].checkbox("compare", value=rid in picked, key=f"cmp_{rid}", label_visibility="collapsed", disabled=(rid not in picked and len(picked) >= MAX_COMPARE))
        if on and rid not in picked: picked.append(rid)
        if not on and rid in picked: picked.remove(rid)
        g, gc = GROWTH_PILL[r.growth_class]
        c[1].markdown(f"<div class='x-title' style='font-size:15px'>{esc(r.title)}</div><div class='x-sub'>{esc(r.education_entry or 'education not reported')}</div>", unsafe_allow_html=True)
        c[2].markdown(pill(g, gc) + (f"<div class='x-src'>you said: {esc(REACTION_WORD[rx[rid]])}</div>" if rid in rx else "<div class='x-src'>no reaction yet</div>"), unsafe_allow_html=True)
        if c[3].button("Open", key=f"sv_open_{i}", width="stretch"): go(S, {"kind": "career", "id": rid})
        if c[4].button("Remove", key=f"sv_rm_{i}", width="stretch"): toggle_save(S, rid); st.rerun()
    S.x_compare_pick = picked
    if len(picked) > MAX_COMPARE: st.warning(f"Compare works with up to {MAX_COMPARE} careers at a time — untick one.")
    b = st.columns([2, 2, 2])
    if b[0].button(f"Compare {len(picked)} side by side →", key="cmp_go", type="primary", width="stretch", disabled=not (2 <= len(picked) <= MAX_COMPARE)): go(S, {"kind": "compare", "ids": picked[:MAX_COMPARE]})
    if len(ids) >= 2 and b[1].button("Help me understand what these have in common →", key="cmp_interview", width="stretch"):
        from ui import student_ui; student_ui.start(S, seed=seed_from_state(S))
    if b[2].button("Clear all saved", key="cmp_clear", width="stretch"): S.x_saved = []; S.x_reactions = {}; S.x_compare_pick = []; S.x_flash = "Cleared"; st.rerun()
    st.markdown("<div class='x-src'>Saved careers and reactions stay in this browser session while you move between browsing, comparing and the guided conversation. They are added to your saved record only if you approve a save at the end of a conversation.</div>", unsafe_allow_html=True)

def screen_compare(S):
    ids = S.x_view.get("ids") or []; cmp = C.compare(ids)
    header(S, "Side by side", show_back=True)
    if len(cmp["ids"]) < 2: st.markdown("<div class='x-empty'>Pick at least two saved careers to compare.</div>", unsafe_allow_html=True); return
    st.markdown("<p class='muted'>Same rows for every career. Official figures carry their source; text rows are templated from O*NET ratings. Nothing here ranks them.</p>", unsafe_allow_html=True)
    head = "".join(f"<th>{esc(t)}</th>" for t in cmp["titles"])
    body = "".join(f"<tr><td class='r'>{esc(row['label'])}</td>" + "".join(f"<td>{esc(c)}</td>" for c in row["cells"]) + "</tr>" for row in cmp["rows"])
    st.markdown(f"<div class='x-wrap'><table class='x-cmp'><tr><td class='r'></td>{head}</tr>{body}</table></div>", unsafe_allow_html=True)
    st.markdown("<div class='x-src'>Sources — " + " · ".join(f"{esc(k)}: {esc(v)}" for k, v in cmp["sources"].items()) + "</div>", unsafe_allow_html=True)
    rx = S.get("x_reactions") or {}
    st.markdown("<span class='x-q' style='display:block;margin-top:12px'>Your reactions</span>", unsafe_allow_html=True)
    cols = st.columns(len(cmp["ids"]))
    for col, rid, title in zip(cols, cmp["ids"], cmp["titles"]):
        with col:
            st.markdown(f"<div class='x-sub'><b>{esc(title)}</b></div>", unsafe_allow_html=True)
            for val, lab in REACTIONS:
                if st.button(("✓ " if rx.get(rid) == val else "") + lab, key=f"cmp_rx_{rid}_{val}", width="stretch"): react(S, rid, val); st.rerun()
    st.markdown(f"### Explain the differences {layer_tag('model')}", unsafe_allow_html=True)
    from tools import career_page as P
    it = P.cached_interpretation("comparison", cmp["ids"])
    if it is None:
        st.markdown("<div class='x-src'>An AI model can explain, from the facts in this table only, what these careers share and how they differ — every line cites its source, fixed checks and a separate reviewer apply, and nothing is ranked. Reused once generated.</div>", unsafe_allow_html=True)
        if st.button("Explain (AI, reviewed) →", key="cmp_gen", disabled=S.get("x_gen") == "cmp"):
            S.x_gen = "cmp"
            with st.status("Reading the facts for each career…", expanded=True) as box:
                try: P.generate_comparison(cmp["ids"], progress=lambda t: box.write(f"· {t}")); box.update(label="Ready", state="complete", expanded=False)
                except Exception as e: box.update(label="The model could not be reached — the table above is unaffected.", state="error"); st.write(type(e).__name__); S.x_gen = None; return
            S.x_gen = None; st.rerun()
    else:
        rec = it.review
        st.markdown(f"<div class='x-src'>{esc(it.labels['model'])} Checked: {rec.get('total', 0)} lines, {len(rec.get('stripped', []))} removed. Generated {esc(it.generated_at[:10])}{' · reused' if it.cached else ''}.</div>", unsafe_allow_html=True)
        for key, lab in (("what_they_share", "What they share"), ("how_they_differ", "How they differ"), ("questions_to_ask_yourself", "Questions to ask yourself")):
            if it.sections.get(key):
                st.markdown(f"<span class='x-q'>{lab}</span>", unsafe_allow_html=True)
                for l in it.sections[key]: st.markdown(f"<div class='x-fact ai'>{_cited(l, it)}</div>", unsafe_allow_html=True)
    st.markdown(f"### Make it personal {layer_tag('you')}", unsafe_allow_html=True)
    if st.button("Ask the agent to help me interpret these →", key="cmp_ask", type="primary"):
        from ui import student_ui; student_ui.start(S, seed=seed_from_state(S))

SCREENS = {"home": screen_home, "family": screen_family, "collection": screen_collection, "browse": screen_browse, "search": screen_search, "career": screen_career, "saved": screen_saved, "compare": screen_compare}

def render(S):
    init(S); ensure_loaded(); sync_url(S)
    # Known limitation: the browser's own Back button updates the URL but Streamlit ignores outside URL changes (its frontend keeps an internal
    # copy of the query string), so live back/forward re-rendering is impossible without a custom component. What the URL sync DOES give:
    # every explorer page has a real address — refresh keeps your place, career pages can be bookmarked and shared, and ← Back in the header
    # walks the in-app history. A framework limit, not a product choice; the roadmap's Next.js front end removes it.
    SCREENS.get(S.x_view.get("kind"), screen_home)(S)
