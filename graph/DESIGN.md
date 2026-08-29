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

## Evaluation (evals/golden.json, 13 cases)
Professional clean match · PM composite · "Head of Product" needing clarification · low-exposure nurses (no fear words) · student 3-way comparison (must surface Graphic Designers −1.7%) · occupation with no projection · Polymarket disabled · conflicting forecasts · edit at gate 1 changes horizon · reject at gate 1 (0 tool calls) · reject at gate 2 (no file, no snapshot) · broken skeptic model (fallback flagged) · second run computes deltas. Plus a 5-point answer-quality rubric judged by the reviewer model.
