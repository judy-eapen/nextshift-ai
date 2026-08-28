# NextShift AI — Good morning: what got built overnight (Aug 27→28)

**Built and tested (all committed):**
- `tools/schema.py` — `Card` + `SourceResult`: the message contract every gatherer returns. Tools never raise; errors are data.
- `tools/` — one module per source, each live-tested: `fred.py`, `bls.py` (OES employment + wage per SOC), `polymarket.py`, `manifold.py` (new: free, no key, dense AI questions), `metaculus.py` (token-ready), `exposure.py` (AIOE + Anthropic Economic Index + O*NET task-diff join), `epoch.py`, `occupations.py` (job-title → SOC search from O*NET reported titles).
- `tools/smoke_test.py` — `python -m tools.smoke_test 11-2021` hits every source. 8 of 9 OK; Metaculus needs your token.
- `data/processed/landscape.parquet` — **867 occupations** × title, AIOE (79% coverage), LM-AIOE, Anthropic observed exposure (87%), BLS employment + median wage (94%). Growth column empty until you drop `bls_occupation_projections.xlsx` in `data/raw/` (browser download).
- `evals/golden.json` — 10 (occupation, horizon, question) triples for the success measure.
- `graph/DESIGN.md` — proposed State/nodes/edges/caps + 4 things to argue about. **Not implemented on purpose** — that's your design conversation.

- `tools/resolve.py` — **occupation resolver** (your idea): exact/alias → LLM-described title → embedding match over O*NET descriptions+aliases, with a confidence gate that flags weak matches for the tier-3 web-research fallback (Saturday; needs a you.com/Tavily key). `resolve('product owner')` → Project Management Specialists / Marketing Managers, asks you to confirm. See graph/DESIGN.md.

**Done this morning:** O*NET Web Services key saved and tested (`tools/onet_ws.py` — live description, Bright Outlook tag, technology skills). Smoke test now covers 10 sources.

**Your two 2-minute tasks before the design conversation:**
1. ~~Metaculus token~~ done — but Metaculus gates **aggregate community predictions** behind a separate data-access approval (values come back null even with a valid token; the download endpoint says "restricted… see metaculus.com/api for requesting access"). Request access via the form/contact on https://www.metaculus.com/api (mention: student project, non-commercial, Maven agentic-AI course). Until approved, the Metaculus tool returns honest metadata cards (question + forecaster count, value unknown) and Polymarket + Manifold carry the forecast values.
2. Download https://www.bls.gov/emp/ind-occ-matrix/occupation.xlsx in a browser → save as `data/raw/bls_occupation_projections.xlsx` → re-run `python data/build_landscape.py`.

**Opening prompt for Claude Code (in this folder):**
> Read PLAN.md, GOOD_MORNING.md, graph/DESIGN.md and skim tools/schema.py and tools/smoke_test.py. Do not write code yet. Critique the proposed graph in DESIGN.md against PLAN.md's Sunday scope: what would you change, and why? Then propose the final State, nodes, edges, and the two interrupts. Stop and wait for me.

**Facts worth knowing from the data:** Customer Service Reps: 2.6M jobs, observed AI exposure 0.70 (highest big bubble). Registered Nurses: 3.4M jobs, exposure 0.06. Marketing Managers (your PM persona): 395K jobs, $166.8K, exposure 0.32, AIOE percentile 89%. Epoch logged 4 models ≥1e25 FLOP in the last 180 days — the "why forecasts moved" card.
