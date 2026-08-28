# AI Futures Explorer — Week 3 Build Plan
**Locked:** Thu 2026-08-27 evening · **Due:** Sun 2026-08-30 11:59pm PT · **Course:** Maven Mastering Agentic AI, Week 3 "Build Your AI Agent"
**Spec / roadmap:** `~/Desktop/Areas/Ideas/ideas/006-ai-futures-explorer.md` (everything not in this file is post-Sunday)

---

## 0. One-liner (the primer)

My agent helps a mid-career professional (and, through a second door, a student choosing a path) understand what AI could do to their work and what to do about it, in a web app, replacing hours of podcasts and headlines that never say how confident anyone is or what to do. It decomposes their question, gathers live forecasts and real labor data, builds scenario branches and a task-level view of how their job changes on its own using 8 tools across 4 specialist sub-agents; hands off to the person before scenarios are built (to confirm its assumptions) and before anything is published; and I'll know it works when someone gets a sourced scenario brief for their occupation in under 10 minutes, with zero unsupported claims, 8 times out of 10.

**Three rules honored:** task completion (a usable brief, not a good sentence) · state is designed (evidence snapshots + profile, see §5) · writes need a human (publish/export is gated).

## 1. Scope — IN for Sunday

| In | Notes |
|---|---|
| **Domain: jobs** | Governments, prices, retirement = roadmap slide |
| **Two doors on the Ask screen** | Professional (occupation) is the demo path; Student door = landscape entry, shown but lightly built |
| **Screens** | 1 Ask · 2 Decomposition (agent thinks in public) · 3 Worldview gate · 4 Scenario tree + horizon slider (2030 / 2035) · 5 Disagreement overlay · 7 Brief export (gated) · **Task-diff board** · **Landscape bubble map** |
| **Screen 6 "Since you last looked"** | Built minimally: a second run shows evidence deltas from the stored snapshot. Recorded as the video's closing beat |
| **Sources (4 families)** | Forecasts: Metaculus + Polymarket · Exposure: AIOE + Anthropic Economic Index + O*NET tasks · Statistics: BLS (OES + projections) + FRED (unemployment, productivity) · Research: Epoch AI CSV (+ you.com news if time) |
| **Agents** | Orchestrator · 4 Evidence Gatherers (parallel) · Reconciler · Scenario Builder · Skeptic · Recorder (see §4) |
| **HITL** | 2 interrupts: worldview (edit/approve assumptions) · publish (approve brief) |
| **Memory** | Episodic evidence snapshots per run · semantic user profile (occupation, horizon, preferences) |
| **Failure handling** | Source down → partial, marked · no forecast → "unknown", never invented · conflicting sources → shown, never averaged · uncited claim → stripped, counted · retry w/ backoff on 429/5xx · step + cost caps |
| **Nebius Token Factory** | Evidence-card extraction + cross-platform question matching (cheap, high-volume) |
| **UI** | Streamlit (fastest); scenario tree + landscape via Plotly |
| **Deliverables** | Google Doc (overview, data, prompts used, iterations, learnings, **architecture diagram**) · ≤5-min video · GitHub repo |

## 2. Scope — OUT (roadmap slide only)
Adjacent-occupation pivots + skill-gap learning paths · economy/retirement panel · "will I be okay" stress test · expenses/cost-of-living lens · watch list alerts · Kalshi/Manifold/IMF/AI Index · authentication/multi-user. One example card each on the roadmap slide.

## 3. The framework (handout Part 2, every field)

| Field | Answer |
|---|---|
| **Agent goal** | Takes a person's occupation + horizon + question and returns a sourced scenario brief: possible futures, how their tasks change, where sources disagree. |
| **Where used** | Web app (Streamlit). |
| **Steps, in order** | 1 Parse question + persona → 2 decompose into measurable sub-questions, each mapped to a source family → 3 gather evidence in parallel (4 sub-agents) → 4 reconcile; flag disagreement; mark unknowns → 5 **pause: show assumptions; human edits/approves** → 6 build 3–4 scenario branches with forecast-derived probability ranges → 7 build task-diff per branch → 8 skeptic attacks every claim; strip uncited → 9 render tree / board / landscape → 10 **pause: human approves brief** → 11 export + record snapshot. |
| **What it can do (tools)** | READ: `metaculus_search/history` · `polymarket_search` · `aioe_lookup(soc)` · `anthropic_index_tasks(soc)` · `onet_tasks(soc)` · `bls_occupation(soc)` · `fred_series(id)` · `epoch_models()` · `news_search(q)` (optional). WRITE (gated): `export_brief` · `save_snapshot`. INTERNAL: `match_questions_across_platforms` (Nebius) · `extract_evidence_card` (Nebius). |
| **Remembers** | Across sessions: profile (occupation, horizon, door, tone pref) and one evidence snapshot per run (every card + scenario tree) so the next run can diff. Within session: the LangGraph state (§4). |
| **Never does** | Invent a probability or a number · average away disagreement · publish a claim without a source card · store personal financial data · give a verdict ("you'll be fine / you're doomed") · call any write tool without an approved interrupt. |
| **Human in the loop** | Interrupt 1 after reconcile: assumptions list (anchor forecast, occupation code, horizon, scenario set) — approve / edit / reject. Interrupt 2 before export: the brief — approve / edit / annotate. Review actions logged. |
| **When something breaks** | Tool error → retry ×2 with backoff → mark source "unavailable", continue with partial evidence, badge the brief. No matching forecast → card = "no forecast exists". Skeptic finds >30% uncited → re-run Scenario Builder once with only cited evidence, else escalate to human. Max 25 tool calls / $1 per run → stop with what exists. |
| **How I know it worked** | Golden set of 10 (occupation, horizon, question) triples: brief produced with ≥6 evidence cards, 0 uncited claims after skeptic, ≥1 disagreement surfaced, <10 min wall-clock — pass ≥8/10. Plus: the second run correctly reports deltas vs the first. |

## 4. Architecture — Supervisor (LangGraph)

**Why not single agent (write-up line):** started single; split gatherers when parallel source calls became the latency bottleneck (independent work — the one justified reason); split the skeptic because same-model self-review shares blind spots. Cost ≈3–5× single; acceptable.

```
Ask ──► Orchestrator.decompose ──► [Gatherer×4 in parallel] ──► Reconciler ──► ⏸ interrupt: worldview
                                    Forecasts | Exposure |                        │
                                    Statistics | Research                          ▼
        Recorder ◄── ⏸ interrupt: publish ◄── Skeptic ◄── TaskDiff ◄── ScenarioBuilder
           │                                     │ (>30% uncited → rebuild once → else escalate)
           ▼
   snapshot store (SQLite) ──► next run: Since-you-last-looked diff
```

**State (TypedDict):**
```python
class State(TypedDict):
    question: str; door: Literal["professional","student"]
    persona: dict            # soc_code, occupation_title, horizon (2030|2035)
    subquestions: list[dict] # {id, text, source_family, why}
    evidence: list[Card]     # {id, subq_id, claim, value, unit, source, url, as_of, spread, trend_30d, confidence, family}
    unknowns: list[str]      # subquestions with no source
    disagreements: list[dict]# {topic, cards:[ids], spread}
    assumptions: list[str]   # shown at interrupt 1
    scenarios: list[dict]    # {name, prob_low, prob_high, assumptions, evidence_ids, for_you}
    task_diff: dict          # per scenario: {disappears:[], supervised:[], grows:[]} each with evidence_ids
    skeptic: dict            # {stripped:[claims], kept:int, reason:[]}
    brief_md: str
    tool_calls: int; cost_usd: float; errors: list[str]
    approvals: dict          # {worldview: bool, publish: bool, edits: [...]}
```
**Nodes:** `decompose` · `gather_forecasts` · `gather_exposure` · `gather_stats` · `gather_research` (fan-out via `Send`) · `reconcile` · `worldview_gate` (`interrupt`) · `build_scenarios` · `task_diff` · `skeptic` (conditional edge: pass → render; fail → build_scenarios once → escalate) · `render` · `publish_gate` (`interrupt`) · `record`.
**Checkpointer:** SQLite (`langgraph.checkpoint.sqlite`) — required for interrupts + resume.
**Models:** planner/scenario/skeptic = your strongest available (Claude via API or whatever you have credits for); extraction + question matching = **Nebius Token Factory** (e.g. Qwen3 as in Week 2).
**Tracing:** LangSmith (free tier) — the trace is also your "agent thinks in public" panel source.

## 5. Data notes (verified 2026-08-27)
- **Metaculus** `https://www.metaculus.com/api2/questions/?search=...` — no key; use `community_prediction.history` for trend. Cache to disk.
- **Polymarket Gamma** `https://gamma-api.polymarket.com/markets?...` — no key; price ≈ probability.
- **AIOE** — CSV from github.com/AIOE-Data/AIOE; join on SOC code.
- **Anthropic Economic Index** — HF `Anthropic/EconomicIndex`, latest release folder; use the occupation/task-level automation-vs-augmentation tables; pre-aggregate offline into a small parquet (the raw usage files are 200MB+ — do not load at runtime).
- **O*NET** — Web Services (free key) `occupations/{soc}/summary/tasks`; or download the Task Statements CSV once.
- **BLS** — OES + Employment Projections; API key free. Pre-download the projections table (one CSV) to avoid rate limits.
- **FRED** — free key, 120/min: `UNRATE`, `OPHNFB` (productivity), `CIVPART`.
- **Epoch** — `epoch.ai/data` Notable Models CSV, daily; use for "why forecasts moved" cards.
- Landscape needs ~900 rows of {soc, title, employment, aioe, growth} — build this join offline Friday morning; it's a CSV, not a runtime call.

## 6. Build order

**Thu night (tonight, ~2h) — plumbing**
1. Repo `ai-futures-explorer/`: `uv`/venv, `langgraph`, `langchain`, `streamlit`, `plotly`, `httpx`, `pandas`, `langsmith`. `.env.example` with FRED/BLS/O*NET/Nebius/LangSmith keys.
2. Register keys: FRED, BLS, O*NET, Nebius, LangSmith. Download AIOE CSV, BLS projections CSV, O*NET tasks CSV, Epoch CSV, Anthropic Index occupation tables → `data/raw/`.
3. Smoke-test each API with one call; write `tools/` with one file per source returning **Card** objects. Make every tool return `{"error": ...}` on failure instead of raising.
4. **System-design conversation with Claude Code first** (instructor advice): paste this PLAN, ask it to propose the graph, challenge it, then implement.

**Fri (~6h) — the loop**
5. Offline join → `data/landscape.parquet` (soc, title, employment, wage, growth, aioe, ai_index_share).
6. LangGraph: state, `decompose`, 4 gatherers with `Send` fan-out, `reconcile`, SQLite checkpointer. Run end-to-end for one occupation (Product Manager, SOC 11-2021) → print evidence cards.
7. `worldview_gate` interrupt + `build_scenarios` (4 fixed branches: Slow diffusion · Fast diffusion · AGI by horizon · Regulatory brake; probability ranges derived from Metaculus/Polymarket cards). `task_diff` from O*NET × Anthropic Index × AIOE.
8. `skeptic` with strip-and-count + conditional edge. `publish_gate` + `record` (snapshot to SQLite).
9. Golden set: 10 triples in `evals/golden.json`; a script that runs them and reports the §3 metrics.

**Sat (~6h) — the surface + the failures**
10. Streamlit: Ask (two doors) → live decomposition panel (stream state) → worldview gate UI → scenario tree (Plotly sankey/branch) + horizon slider → task-diff board → disagreement toggle → brief preview + approve → export `.md`/PDF.
11. Landscape bubble map (Plotly scatter, size=employment, x=aioe, y=growth, color=scenario direction); click → set persona and jump to the professional path.
12. **Failure demos, deliberately:** kill Polymarket (env flag) → partial badge; ask about an occupation with no forecasts → "unknown" cards; inject an uncited claim → skeptic strips it (show the badge count). Step/cost caps tested.
13. "Since you last looked": second run for the same persona diffs cards vs stored snapshot; render delta list. (If short on time: hardcode the diff render over two real snapshots.)
14. Architecture diagram (Figma via MCP, or draw.io) — supervisor graph with interrupts and the snapshot store.

**Sun (~5h) — ship**
15. Run the golden set; fix the top 2 failures; record metrics for the doc.
16. Record video (≤5 min): 0:00 the question and why podcasts can't answer it · 0:40 ask as a PM → agent thinks in public · 1:30 worldview gate (edit an assumption) · 2:00 scenario tree, drag horizon, disagreement overlay · 3:00 task-diff board · 3:30 **failure**: source down → partial badge; skeptic strips 3 claims · 4:15 second run → "since you last looked" · 4:45 architecture + roadmap slide (pivots, stress test, expenses, student door).
17. Google Doc: overview, one-liner + framework, architecture diagram, data sources table, prompts used with Claude Code, iterations (single→supervisor decision), golden-set results, learnings, roadmap. Differentiation line vs Career Compass. Push repo; submit the form (**confirm which link** — handout vs deck differ).

## 7. Cut list (if Saturday runs long, cut in this order)
1. Landscape click-through (keep the static map) → 2. Disagreement overlay as toggle (keep spread text on cards) → 3. Research gatherer (Epoch) → 4. Student door beyond the Ask screen → 5. "Since you last looked" live diff (use two recorded snapshots). **Never cut:** the two interrupts, the skeptic, the failure demos, the golden set.

## 8. Risks & mitigations
- Metaculus/Polymarket question matching is fuzzy → Nebius matcher + a hand-curated `data/anchor_questions.json` of 10 known AI/econ questions as fallback.
- Anthropic Index files are huge → pre-aggregate offline; never load raw at runtime.
- Interrupts in Streamlit are awkward → run the graph with `thread_id` in session state; resume on button click. Test this Friday, not Saturday.
- Scope creep (you have 5 roadmap features) → they live on one slide. This file is the contract.

---
## Design assets (2026-08-27)
- **Architecture diagram — shareable PNG on Google Drive:** https://drive.google.com/open?id=12IR2hhy5Oq-Z6OOuCHO6ar7QL1VzixbQ (anyone-with-link) · folder **AI Futures Explorer**: https://drive.google.com/drive/folders/12zGSKE5kmVqjKf6ma4XafeIsC_LAvOb0 (also holds the Mermaid source `.mmd`). Local: `design/architecture-diagram.png` (3968×2776), source `design/architecture.mmd`; re-render with `npx -y -p @mermaid-js/mermaid-cli mmdc -i architecture.mmd -o architecture-diagram.png -c mmdc.json -b white -s 2 -w 2000`. FigJam version (needs Figma share settings): https://www.figma.com/board/mjfPRt4jVertJlpz9P4gtc
- **Mockups (design canvas, "Instrument panel" direction):** https://claude.ai/code/artifact/cc0c6a71-55a8-4e80-b2fa-b3be5ca5240e — 4 screens: Ask (two doors) · Scenario tree + horizon slider · Task-diff board · Since you last looked. Working files in `design/*.dc.html`. Numbers are illustrative samples.
- **Palette:** bg #0B0F14 · surface #121821 · line #1F2833/#2A3544 · ink #E6EAF0 · muted #8A94A6 · amber (human/attention) #E5A24A · student door #7FC8E8 · branches: Slow #7FB3D5 · Fast #E07A5F · AGI #B48CFF · Brake #8FBF9F. Type: Archivo (display) · IBM Plex Sans (body) · IBM Plex Mono (numbers).

## UI decision (2026-08-27): Streamlit, confirmed
Next.js (Cruise Crew Planner's stack) considered and rejected for Sunday — two codebases + API layer is the wrong risk when the grade is on the agent. Rebuild in Next.js later if this becomes a product; the LangGraph backend carries over unchanged.

`.streamlit/config.toml` to match the mockups:
```toml
[theme]
base = "dark"
primaryColor = "#E5A24A"
backgroundColor = "#0B0F14"
secondaryBackgroundColor = "#121821"
textColor = "#E6EAF0"
font = "sans serif"
```
Plotly: `template="plotly_dark"`, paper/plot bg `#0B0F14`/`#121821`, branch colors Slow `#7FB3D5` · Fast `#E07A5F` · AGI `#B48CFF` · Brake `#8FBF9F`. Use `st.status`/`st.empty` containers for the "agent thinks in public" panel (stream graph events); `st.session_state["thread_id"]` for interrupt resume.

## Model decision (2026-08-27): Nebius-only
No Anthropic key; all LLM calls go through Nebius Token Factory (OpenAI-compatible, `langchain-openai` with `base_url`). Routing in `.env`:
- `PLANNER_MODEL=Qwen/Qwen3-235B-A22B-Instruct-2507` — orchestrator, scenario builder (strongest instruct)
- `SKEPTIC_MODEL=Qwen/Qwen3-Next-80B-A3B-Thinking` — a *different* model family/mode for the skeptic, so reflection doesn't share the planner's blind spots (Lesson 29)
- `EXTRACTOR_MODEL=Qwen/Qwen3-30B-A3B-Instruct-2507` — evidence-card extraction, question matching (cheap, high volume)
Write-up line: "runs entirely on open-weight models; planner and skeptic deliberately differ."
Setup status 2026-08-27 night: repo scaffolded + committed; FRED, BLS, LangSmith, Nebius keys saved and smoke-tested; O*NET Web Services pending email (public Task Statements download is the fallback); datasets still to download into data/raw/.

## Data notes from the downloads (2026-08-27 night)
- **AIOE:** `aioe_AIOE_DataAppendix.xlsx` → sheet **Appendix A** = `SOC Code, Occupation Title, AIOE` (the per-occupation score); Appendix E = ability-level exposure (for task-diff weighting). `aioe_Language_Modeling_AIOE_and_AIIE.xlsx` sheet `LM AIOE` = the language-model-specific variant — arguably the better one for this product; load both, show LM by default.
- **Anthropic Economic Index:** `aei/job_exposure.csv` = 756 occupations × `observed_exposure` (0–1); `aei/task_penetration.csv` = 17,998 O*NET task statements × `penetration` (1,354 nonzero). **Join task_penetration to onet_task_statements on the task text** — that is the task-diff board's data. Marketing Managers (11-2021) observed exposure = 0.32.
- **O*NET 31.0:** task_statements (20 tasks for 11-2021), occupation_data (SOC→title for the landscape), abilities + knowledge (for pivot math later).
- **Epoch:** 1,052 notable models, latest Aug 14 2026 — use for "why forecasts moved" cards.
- **Persona: verified against O*NET's Sample of Reported Job Titles (data/raw/onet_reported_titles.csv).** "Product Manager" and "Product Marketing Manager" are officially listed under **11-2021 Marketing Managers** — so that's the default match, not an approximation. Closest technical alternative: **15-1299.09 Information Technology Project Managers** ("Cloud Product Director", "Data Center Product Director"). Every other "product" title in O*NET is manufacturing/engineering/design. UI: on "product manager" offer 11-2021 (official) + 15-1299.09, with a one-line note that no PM-specific code exists. Use the reported-titles file as the occupation search index (title → SOC) — it's how real people name their jobs.
- **BLS projections:** blocked scripted download (403) — Judy downloads `occupation.xlsx` manually from bls.gov/emp/ind-occ-matrix/ into data/raw/, or the Statistics gatherer uses the BLS API (OES series per SOC) which is already working.

## Overnight build (Aug 27→28) — see GOOD_MORNING.md
Tools layer complete and live-tested (9 sources incl. new Manifold; Metaculus token-ready), occupation search index, landscape.parquet (867 SOCs, 94% employment coverage), golden set, graph/DESIGN.md proposal. Graph deliberately not implemented — Judy's design conversation. Pending: METACULUS_TOKEN, BLS projections xlsx (manual).
