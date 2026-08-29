# NextShift AI — Graph design (proposal + AS BUILT below)

Everything below is a starting point to argue with. The tools layer (`tools/`) is built and tested; the graph is yours.

## State
```python
class State(TypedDict):
    question: str; door: Literal["professional","student"]
    persona: dict            # {soc, onet_soc, title, matched_alias, horizon}
    subquestions: list[dict] # {id, text, family, why}
    evidence: list[Card]     # from tools.schema — every gatherer returns SourceResult(cards=...)
    unknowns: list[str]; disagreements: list[dict]  # {topic, card_ids, spread}
    assumptions: list[str]   # shown at interrupt 1
    scenarios: list[dict]    # {name, prob_low, prob_high, assumptions, evidence_ids, for_you}
    task_diff: dict          # {scenario_name: {disappears:[card_id], supervised:[...], grows:[...]}}
    skeptic: dict            # {stripped:[claim], kept:int, reasons:[...]}
    brief_md: str
    tool_calls: int; cost_usd: float; errors: list[str]
    approvals: dict          # {worldview: bool|None, publish: bool|None, edits: [...]}
```

## Nodes (proposed)
| Node | Model | Does |
|---|---|---|
| `resolve_persona` | none | `tools.occupations.search_occupations(query)` → if >1 exact/near match, surface choices (this is a *third*, tiny interrupt candidate — or a UI step before the graph) |
| `decompose` | PLANNER_MODEL | question + persona → 4–6 sub-questions, each tagged `family` ∈ forecasts/exposure/statistics/research, with a one-line `why` |
| `gather_forecasts` | EXTRACTOR_MODEL for query phrasing + matching | `polymarket_search`, `manifold_search`, `metaculus_search` (token) → cards; **match the same question across platforms** and record pairs for the reconciler |
| `gather_exposure` | none | `aioe_lookup`, `anthropic_index`, `onet_task_diff` → cards (20 task cards + 3 score cards) |
| `gather_stats` | none | `bls_occupation`, `fred_series("UNRATE")`, `fred_series("OPHNFB")` → cards |
| `gather_research` | none | `epoch_recent()` → cards (later: news_search) |
| `reconcile` | EXTRACTOR_MODEL | dedupe; find same-topic cards with different values → `disagreements` (never average); collect `unknowns`; write `assumptions` (anchor forecast, SOC used, horizon, scenario set) |
| `worldview_gate` | — | `interrupt(assumptions)`; resume payload = approved/edited list |
| `build_scenarios` | PLANNER_MODEL | 4 named branches; probability ranges **derived from forecast cards** (e.g. AGI-by-horizon range = min/max across Metaculus/Polymarket/Manifold for the anchor question); `for_you` paragraph must cite card ids |
| `task_diff` | EXTRACTOR_MODEL | per branch: bucket the 20 task cards using `value` (penetration) × branch multiplier; every bucket entry keeps its card id |
| `skeptic` | SKEPTIC_MODEL | for every sentence in scenarios/for_you: find a supporting card id or strip it; output counts. Conditional edge: stripped/total > 0.30 → `build_scenarios` once (flag set) → else `escalate` |
| `render` | none | assemble view models for Streamlit (tree, board, cards, disagreement bands) |
| `publish_gate` | — | `interrupt(brief_md)`; resume = approve/edit/reject |
| `record` | none | write snapshot (cards + scenarios + persona + timestamp) to SQLite; next run diffs against it |

## Edges
`START → resolve_persona → decompose → [Send × 4 gatherers] → reconcile → worldview_gate → build_scenarios → task_diff → skeptic → (pass) render → publish_gate → record → END`; `skeptic → (fail, first time) build_scenarios`; `skeptic → (fail, second time) escalate → publish_gate` with a warning banner.

## Fan-out
Use `Send("gather_forecasts", state)` etc. from a conditional edge after `decompose`; each gatherer appends to `evidence` via an `Annotated[list, operator.add]` reducer. Isolated context = each gatherer only receives its sub-questions + persona, not the whole state.

## Checkpointer
`SqliteSaver.from_conn_string("data/processed/checkpoints.sqlite")`; `thread_id` = `f"{persona.soc}-{uuid}"` kept in `st.session_state`.

## Caps
`tool_calls ≤ 25`, `cost_usd ≤ 1.00` (estimate from token usage), wall-clock 120 s per gatherer → mark source unavailable and continue.

## Things to argue about tomorrow
1. Fixed 4 branches vs planner-decided — fixed is legible; proposed default = fixed names, planner writes the assumptions.
2. Where the persona resolution lives (graph node with interrupt vs UI step before the graph). Proposed: UI step — keeps the graph's two interrupts clean.
3. Whether `task_diff` needs an LLM at all — the penetration values may be enough with thresholds; an LLM only for the "grows" column (judgment tasks not observed in AI usage).
4. Cross-platform question matching: embedding similarity (Nebius Qwen3-Embedding-8B is available) vs LLM pairwise — embeddings are cheaper and deterministic.

## Occupation resolver (built 2026-08-28 early hours — `tools/resolve.py`)
Judy's ask: when a title isn't in the files, don't say "not found" — have an agent work out what the job is.
- **Tier 1** exact/alias match over 54K O*NET lay titles (`tools/occupations.py`). Deterministic.
- **Tier 2** (built): cheap LLM (EXTRACTOR_MODEL) writes a 2-sentence BLS-style description of the title → Nebius `Qwen3-Embedding-8B` → cosine vs 790 O*NET occupations (title + description + top aliases; "All Other" residuals excluded). Returns top-k with similarity + `confident` flag (≥0.60 and a 0.03 margin).
- **Tier 3** (Saturday, needs a search key — you.com from the course, or Tavily): when `needs_web_research`, search the title → read 2–3 job postings → extract duties → re-run tier 2 with that text → present "how I decided" + top 2 → **human confirms** (a small interrupt, or a UI step before the graph). A real ReAct loop: search → read → extract → match → ask.
- UI copy when tier ≥ 2: "No official category lists “{title}”. By meaning it's closest to {A} ({sim}) and {B} — which is you?" Never silently pick.
- Note for the write-up: the US taxonomy (SOC 2018, ~870 categories) has no Product Owner / Head of Product / Chief Product Officer — a small piece of evidence for the product's own thesis that official statistics lag how modern work is organized.

---
# AS BUILT (Fri 2026-08-28) — decisions from the design conversation

The graph is implemented in `graph/` (`state.py`, `nodes.py`, `build.py`, `llm.py`, `memory.py`) and driven by `run_cli.py` (CLI, both gates) and `evals/run_golden.py` (auto-approve, scores PLAN §3). Everything above this line is the proposal; below is what actually shipped and why it differs.

## Changes from the proposal, and why
| Proposal | Built | Why |
|---|---|---|
| `resolve_persona` node (3rd interrupt candidate) | **UI step before the graph** (`tools/resolve.py` from the Ask screen) | Keeps exactly two interrupts; one fewer resume path to test. |
| Standalone `task_diff` node (EXTRACTOR) | **Pure Python inside `build_scenarios`** (`_task_diff`) | Penetration × branch multiplier with fixed thresholds is deterministic and citable by construction — no LLM, no uncited claims. |
| `escalate` node | **Flag** `skeptic.escalated` → render shows a warning badge | Fewer nodes, same behaviour. |
| `reconcile` on EXTRACTOR | **Code** for dedupe / disagreements / unknowns; **PLANNER** only for the assumptions list | Disagreement detection must be deterministic for the golden set; only the human-editable claims need judgment. |
| `assumptions: list[str]` | **Typed `Worldview`** (soc, horizon, anchor question, scenario names, claims) — same shape as the resume payload | Interrupt 1 is a form, not a text box; "edit an assumption" is a real demo beat. |
| Brief from a template | **Model writes it, then the skeptic checks the brief itself** | Readable prose *and* the guarantee — the thing checked is the thing published. Judy's call. |
| Pairwise question matching (Nebius) | **`data/anchor_questions.json`** — 6 curated anchors with per-platform search terms + a PLANNER relevance filter that must give a one-line *why* per market | Raw market search returns puns ("Will Powell say 'Unemployment'"); forcing a reason per decision fixed the filter's accuracy. Metaculus values are gated for this account → honest `value=None` cards. |
| Residual probability for Slow diffusion | **No residual** — Slow is "none of the above", probability not computed | The anchors' questions are not mutually exclusive; 1 − Σ produced a fake 5%. |
| Sentence-level skeptic | **One claim per bullet; skeptic judges lines** | Sentence regex splitting produced uncited fragments; bullets make the unit of citation unambiguous. Evidence-count header line is generated by code, not the model (it kept miscounting). |

## Final node list (14 incl. gates) and edges
`START → load_memory → decompose ⇉ Send×{gather_forecasts, gather_exposure, gather_statistics, gather_research} → reconcile → ⏸ worldview_gate → build_scenarios → write_brief → skeptic ⟲(ratio>0.30, once) → render → ⏸ publish_gate → record → END`
- `worldview_gate` reject → END. `publish_gate` reject → END (no writes). `record` is the **only** node that writes (brief file + snapshot + profile).
- Budget: 25 tool calls / $1.00 checked at the skeptic edge; a typical run is ~18 calls, ~$0.006, 80–120 s.

## Agents (write-up count)
Six model-driven agents — planner (decompose + assumptions), forecast gatherer's relevance filter, scenario builder, brief writer, skeptic (Qwen3-Next-80B *Thinking*, a different family from the Qwen3-235B planner), occupation resolver (pre-graph) — plus three deterministic gatherers running in parallel under the same `SourceResult` contract.

## Rule of the house (what makes it trustworthy)
Models write prose and judgments; **numbers, buckets and probabilities come from code over Cards.** Every bullet ends in `[cNN]` (evidence) or `[uNN]` (a known unknown); the skeptic strips anything it can't verify and the count is shown at the publish gate. Units are explained to every writer (`UNIT_GUIDE`): penetration ≠ automation.

## Known gaps (Saturday)
- Streamlit UI (`ui/`) not started — CLI proves the graph. Use `graph.stream(..., stream_mode=["custom","updates"])`; `_say()` events feed the "thinks in public" panel; `Command(resume=...)` on button click.
- Editing the horizon at gate 1 changes the persona but evidence was gathered for the original horizon's anchors — acceptable for demo; a full re-gather is a later improvement.
- Student door = landscape click → persona → same graph. No graph changes needed.
- Metaculus aggregates pending data-access approval; Polymarket + Manifold carry prices.

## Persona fix (Sat 2026-08-28, Judy's catch): "Product Manager" ≠ Marketing Managers
Marketing Managers (11-2021) is where O*NET *files the title*, but its task list (pricing, campaigns, trade shows) is not a software PM's week. Fixes: (1) resolver index now includes detailed O*NET codes (1016, not 867) so **15-1299.09 Information Technology Project Managers** — the closest task list (customer needs & priorities, deliverables, plan changes, cross-team coordination; 21 tasks, all with Anthropic penetration data) — is reachable; (2) `data/title_overrides.json` curates PM-family titles → IT Project Managers · Project Management Specialists · Marketing Managers, with an honest "no official category" note and a human pick; (3) an optional "what do you actually do?" field always triggers a semantic match and merges with title hits; (4) `onet_task_diff` filters by the detailed code so a 15-1299.09 run doesn't inherit web-admin and pen-tester tasks. Trade-off: AIOE/BLS/AEI job-level scores are 6-digit (15-1299 "Computer Occupations, All Other") — AIOE reports `partial` for it; task-level data is exact. Golden g01 now uses 15-1299.09. Write-up line: the taxonomy gap is itself evidence for the product's thesis.

## Composite occupations (Sat 2026-08-28) — `tools/composite.py`, `data/composites/*.json`
Judy's second catch: even IT Project Managers "isn't my job". Root cause: SOC 2018 has no Product Manager, so *no* single category can be. Fix: **composite occupations** — the job is assembled from O*NET task statements across all 1,016 occupations (every statement carries Anthropic penetration, so the task-diff board, scenarios and skeptic run unchanged).
- **Curated composite** (`data/composites/product_manager.json`): 23 hand-picked statements from IT project management, software development, market research, BI, marketing, UX. Covers PM-family titles (product owner, head of product, CPO…).
- **Described composite**: the person's two lines → EXTRACTOR expands to 8–10 O*NET-style task sentences → each matched (Qwen3-Embedding-8B, 18K-statement index cached in `data/processed/task_embeddings_v1.npy`) to its 2 nearest real statements within knowledge-work major groups → deduped. Raw-description matching without the expansion step was noise (Spa Managers, Real Estate agents).
- **Human picks tasks**: the Ask screen shows both composites first (★), each with a tick-list; unticked tasks leave the persona. Official categories stay listed below.
- **Honesty rule**: `persona.soc = "composite:<slug>"`; AIOE / BLS / Anthropic job-level tools return *"no official statistics exist for this occupation"* as citable unknowns — never borrowed from a neighbouring category. FRED national series still gathered.
- Write-up: "the government has no category for my job, so the agent assembled one from 18,000 task statements and showed me its work." Tuning item: the skeptic strips conditional scenario bullets more often on composites (35% on the first PM run → escalation banner); consider softening `SKEPTIC_SYS` on scenario sections or letting the writer cite the scenario's probability card.

---
# REDESIGN (Sat 2026-08-28 night) — answer first, evidence behind it

Judy's UX critique: the app was an analyst's control panel (scenario tree, forecast ranges, penetration math, skeptic metrics) and never answered the person's question. Rebuilt around **"Given an uncertain future, what is the best career decision I can make now?"** Two journeys (student · professional), guided intake, two gates.

## Graph (as built)
`START → load_memory → understand → ⏸ understanding_gate ⇉ Send×{forecasts, research, outlook×occupation, exposure×occupation} → reconcile → write_outlook → write_plan → skeptic ⟲(once) → render → ⏸ plan_gate → record → END`
- **understanding_gate** replaces the worldview gate: the user confirms/edits *what the agent understood about them* (summary, horizon, occupation, composite task list) before any evidence is gathered. Reject → END with zero tool calls.
- **plan_gate** replaces the publish gate: approve / edit / reject the plan; `record` is still the only writer.
- Fan-out is **per occupation**, so a student's 2–3 careers run in parallel through the same gatherers (`Card.occ` tags each card's occupation).
- `gather_outlook` is new: BLS Employment Projections 2025–35 (growth %, numeric change, annual openings, entry education) from `tools/outlook.py`; composites get the closest official categories as **labelled proxies** plus an explicit unknown.

## State
`Profile` (door, interests, strengths, constraints, role, week, industry, concerns, horizon, summary) · `targets: [OccupationTarget]` · `outlooks: {soc: Outlook}` (demand_reading from BLS only; ai_change_reading labelled interpretation) · `changes: {soc: WorkChange}` · `plan: Plan` (direct_answer, for_you, d30/m6/y1, adjacent, comparison, our_read, confidence) · `plan_md` (one claim per line — what the skeptic checks and what is exported). Removed as primary: scenarios, task_diff, worldview, brief.

## Task-diff replacement (the special review)
No multipliers. Three groups from *observed* penetration: **AI will probably assist** (≥0.60 — a fact about current use), **may become more important** (low use *and* a stated reason it resists delegation — a cited interpretation chosen by the planner, tagged), **still uncertain** (everything else). The method note is shown inline. Forecast markets appear only as conditional sentences about *pace* in section 6.

## Citation discipline
Facts cite `[cNN]`; unknowns cite `[uNN]`; interpretive lines add `[interpretation]`; practical advice with no factual claim carries `[advice]` and is kept unchecked; any line with a number must cite. The skeptic (Qwen3-Next-80B Thinking) reviews `plan_md` line by line; >30% stripped → one rewrite → escalation banner.

## Evaluation (evals/golden.json, 12 cases — g05 retired 2026-08-29, superseded by the student interviewer; student journey: evals/student_golden.json, 24 cases)
Professional clean match · PM composite · "Head of Product" needing clarification · low-exposure nurses (no fear words) · student 3-way comparison (must surface Graphic Designers −1.7%) · occupation with no projection · Polymarket disabled · conflicting forecasts · edit at gate 1 changes horizon · reject at gate 1 (0 tool calls) · reject at gate 2 (no file, no snapshot) · broken skeptic model (fallback flagged) · second run computes deltas. Plus a 5-point answer-quality rubric judged by the reviewer model.

---
# STUDENT JOURNEY REDESIGN (Sat 2026-08-29) — career-discovery interviewer

Approved design (see chat, 15-part proposal). Built in `graph/student.py` (interview loop, understanding gate), `graph/student_explore.py` (candidates → evidence → fit → review → reactions → discriminators → shortlist → deep dive → what-ifs → save), `graph/student_build.py` (one graph, one thread, seven interrupts), `ui/student_ui.py`, `evals/run_student_evals.py` + `evals/student_golden.json` (24 cases) with `evals/sim_student.py` personas.

## Decisions
- **One graph, several interrupts** (not separate graphs): the exploration loop must keep one state — profile, reactions, rejected careers, planned experiments — on one checkpoint thread. Professional journey untouched, own compiled graph.
- **Profile = Evidence, not labels.** Every field holds `{value, quote, source_turn, kind}`. Four kinds of "negative" are structural: `dislikes` · `not_yet_learned` · `growth_areas` · `*_constraints`. No permanent-weakness field exists. `[p:field:i]` refs let the reviewer check "this rests on what the student said".
- **Next question = code picks the goal, model words it.** Goal ranking = coverage gap × core bonus, contradictions first, no goal more than twice, `existing_ideas` always asked once early. The model rewrites a base question with ≤8 words of lead-in — earlier versions that "built on what they said" drifted for eight turns.
- **Completeness = code.** Ready when every core dimension (interests/energizing · strengths · negatives · people-ideas-data-tech-hands leaning · a constraint · values/impact) ≥ moderate and ≥8 substantive answers, or the student asks, or 14 turns. Thin conversations are flagged on the results.
- **Candidates**: planner proposes 8–10 in three groups with a cited seven-part rationale; code enforces ≤2 per 6-digit occupation; low-confidence semantic matches and modern roles become **composites** with proxy-labelled outlook.
- **Evidence** reuses the professional gatherers per candidate via `Send`; `Card.occ` keeps them apart. Outlook/work-change code unchanged.
- **Structured review everywhere** (`graph/review.py`): objects are flattened to leaves, paragraphs to sentences; failing leaves are deleted *in the object the UI renders*; a citation-repair pass runs first (the reviewer still verifies added refs); the reviewer runs in batches of 20 with a halving retry; any failed batch → `unverified`, red banner, filename tag. Certainty-about-the-future wording is stripped by lint regardless of citations.
- **Reactions update the profile** (the *why* becomes evidence with `kind: stated`); rejections are remembered; 0–2 discriminating questions only when the excited/curious set forks on education, people-vs-data, hands-on, licensing or schedule.
- **Shortlist** shows eight dimensions separately, never a score; "Our read" is labelled interpretation. **Deep dive** has ten sections; *Test this career* is first-class and feeds `experiments_planned`. **What-ifs** reorder within existing candidates and may add a constraint; everything goes to `exploration_log`.
- **Writes**: `record` is the only writer, after the save gate; snapshot payload generalised (profile, shortlist, reactions, rejected, experiments, log, review status).
- Boundary line shown at start, on results and in the export: *"a guided exploration based on what you shared and available career data — not a test that determines what you should become."* No age/school fields; first name optional.

## Known-issue fixes (both journeys, Phase A)
UI renders only reviewed structured objects (`state.reviewed`/`views`) · horizon comes from the profile (no hardcoded 2030) · reviewer failure is loud (UNVERIFIED status, banner, save warning, filename tag; no rewrite loop on an absent reviewer) · `*.sqlite-wal/-shm` ignored · current-use wording lint.


---
# BEHIND THE SCENES (Sat 2026-08-29 afternoon) — the system explains itself

Goal: make the architecture inspectable from the UI without turning the result screens into a dashboard. Progressive disclosure: plain language first, technical detail on request, developer facts only in developer mode.

## Built
- **`ui/journey.py`** (pure, no Streamlit): stage/phase → journey steps (student 9, professional 7) with states done · current · todo · attention · unverified · stopped; `resolve_refs` turns `[p:field:i]` into the student's quote; `understands_sections` (10 sections from the profile), `why_this_appeared` (two groups from the checked rationale + reviewed card), `run_details` (user-facing run facts), `resolution_label` (exact / proxy / composite from the resolver record).
- **Phase events**: `_phase(key, of=…)` emitted at node *start* in `graph/student.py`, `graph/student_explore.py`, `graph/nodes.py` alongside `_say`. Real current work only; the UI maps keys to copy (`PHASE_COPY`). Consumers that read `ev["say"]` skip phase events.
- **`ui/copy.py`**: all panel copy; numbers pinned to code constants (`MAX_TURNS`, `TARGET_TURNS`, `UNCITED_LIMIT`, reviewer ≠ writer) and tested in `tests/test_copy_facts.py`.
- **`ui/explain.py`**: sidebar (journey placeholder updated live from phase events via `S.on_phase`; entry card; *Demo & developer* expander) and the `@st.dialog` with three tabs. Button is disabled during run stages so a click cannot interrupt a stream.
- **Developer mode** = `NEXTSHIFT_DEV=1` env + sidebar checkbox. Shows stage, interrupt kind, phase, model roles, tool calls, cost, review record, source status, phase timeline, raw `_say` log, card ids. **LangSmith tracing follows developer mode** (`apply_tracing`): a normal session forces `LANGSMITH_TRACING=false` even if `.env` says true; the *What is saved?* tab reads the live flag.
- **Interview**: side column shows coverage of the six core areas (glyph + text, from `completeness.coverage`); *What NextShift currently understands about you* expander lists the ten sections with *Based on your answer (Qn): "…"* and an *Edit Qn* button that pre-selects the existing edit form. The interview interrupt payload now carries the profile fields (no extra model call).
- **Cards**: *Why this appeared →* — *Based on what you told us* (rationale lines, deterministically checked to `[p:…]` refs, with quotes) · *May conflict with what you said* (rationale conflicts + deterministic practical-mismatch lines) · *Based on career evidence* (BLS facts, entry education, observed-AI-use tasks, stays-human tasks, tradeoff, unknowns, evidence confidence) · exact/proxy/composite label · count of reviewer removals. No score, no generation.
- **How we reached this** (both journeys) → `render_run_details`: sources with status words, occupations with labels, evidence count, review verdict (UNVERIFIED loud), removed lines with reasons, disagreements, unknowns, forecast context, your decisions so far, verified/unverified for the saved result, evidence list. Model names, cost, tool counts and the raw log moved to developer mode.
- **Privacy copy verified**: interview state is checkpointed to `data/processed/checkpoints.sqlite` before approval (the old "nothing is stored until you approve" line was wrong and is fixed); answers go to Nebius; LangSmith only in developer mode; `record` is the only writer of `memory.sqlite` / `data/briefs`.
- Old scenario-tree diagram archived to `design/archive/`; `architecture.mmd` corrected (no retry claim; tracing optional; reviewer failure → UNVERIFIED).

## Tests (`tests/`, pytest) — 67
journey mapping for every stage/phase/flag · copy facts pinned to constants · AppTest: opening/closing the dialog keeps stage+payload and never constructs a graph · no secrets/env names/`<think>` in any rendered string · dev mode hidden without the flag, present with it, tracing forced off without it · UNVERIFIED and partial-evidence flags reach the journey · a11y roles/aria on every status glyph · understands-sections from state with `llm.chat` patched to raise · why-this-appeared uses reviewed rationale and never leaks removed sentences · exact/proxy/composite labels · cards stay answer-first · professional run details shared.
Student evals gained explanation-layer checks: `composite_labelled`, `journey_unverified`, `run_details_partial`, `removed_absent_in_why`, `why_uses_profile_refs`.
