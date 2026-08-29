# Good morning — NextShift AI is finished for submission (Sat night → Sun 2026-08-30)

**The app is running at http://localhost:8599** (`streamlit run ui/app.py` if it isn't). Repo pushed: https://github.com/judy-eapen/nextshift-ai

## What's done
- **Redesign shipped, both journeys.** Start → guided intake (4 turns) → ⏸ *Here's what I understood* → parallel evidence → **Your plan**: direct answer · 1 outlook · 2 how the work may change · 3 what this means for you · 4 30 days / 6 months / 1 year · 5 other paths · 6 confidence & uncertainty · 7 ▸ how we reached this answer → ⏸ approve / edit / don't save.
- **Student path** compares up to 3 careers in one run (parallel fan-out), with a comparison table and "our read". Example: Graphic Designers −1.7% (declining) vs UX Designers +6.0% (growing) vs Clinical Psychologists.
- **BLS Employment Projections 2025–35** wired in (your download) → real *Demand: growing / stable / declining*, openings, entry education. Composites (Product Manager) show closest official categories as *labelled proxies* plus an explicit unknown.
- **Task-diff multipliers are gone.** Three groups: *AI will probably assist* (fact, current use) · *may become more important* (low use + a stated reason — tagged interpretation) · *still uncertain*.
- **Evals: 13/13** — both journeys, edit at gate 1, reject at each gate (no writes), Polymarket outage, conflicting forecasts, broken reviewer model, second-run deltas, plus a 5-point answer-quality rubric judged by the reviewer model. `20260829-002835.json` — one clean run, all fixes in. Median ≈ 3 min, ≈ $0.01/plan.
- **UI verified end to end in Streamlit** (AppTest): professional composite through both gates and save; student 3-way through both gates with reject → nothing written.
- Architecture diagram (`design/architecture-diagram.png`), project doc draft (`docs/PROJECT_DOC.md`), 5-minute video script (`docs/VIDEO_SCRIPT.md`), sample outputs (`samples/`).

## Your Sunday, in order (~3 h)
1. **Click through once yourself** (10 min): Product Manager path with your own week description; then the student path. If any wording jars, tell me — copy is cheap to change.
2. **Record the video** (`docs/VIDEO_SCRIPT.md`, 5:00). Tip: run the PM path once before recording so caches are warm; the analysis step takes ~2–3 min — cut it or narrate over it. The student run is a good place to show the Polymarket outage badge (sidebar → *Simulate a source outage*).
3. **Google Doc**: paste `docs/PROJECT_DOC.md` (it follows the handout's required sections: overview, datasets, prompts used, iterations, learnings) and drop in `design/architecture-diagram.png`. Add 2–3 screenshots. The "prompts used with Claude Code" section is written from this week's actual conversation.
4. **Submit** the form: https://forms.gle/HMgTU7zy6UJ8XkJX6 — video, Google Doc, repo link. Deadline Sun 11:59 pm PT.

## Known limitations (say them in the doc; they're honest, not embarrassing)
- Job-level statistics don't exist for composites; we show proxies and say so. The task-level data is exact.
- "Other paths" is empty by design — no skill-similarity evidence in this run (roadmap: O*NET abilities/knowledge similarity; data is already in `data/raw/`).
- Metaculus prices are gated for this account; Polymarket + Manifold carry the forecasts. Manifold is play-money; the UI never averages them.
- A plan takes 2–4 min; the reviewer (thinking model) is most of it.
- "Since your last plan" shows real deltas only when evidence actually moved between runs.

## If something breaks
- `python run_cli.py --composite "Product Manager" --auto` reproduces the demo path in the terminal.
- `python -m evals.run_golden g01` is a 3-minute health check.
- Embedding caches (`data/processed/*.npy`) rebuild automatically on first run (~5 min).
