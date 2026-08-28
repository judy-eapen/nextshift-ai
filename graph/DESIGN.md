# Graph design — proposal for Judy's design conversation (NOT implemented; do that with Claude Code)

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
