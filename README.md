# NextShift AI
*What AI does to your work, with receipts.*

**Plan your career for an AI-shaped job market.** Students don't need to know what they want: a career-discovery interviewer asks one question at a time, shows what it understood, proposes 8–10 directions in three groups with cited reasons, takes reactions, narrows to a shortlist, and goes deep on one — including low-cost ways to test it. Professionals ask about their own role. A guided intake, then the agent restates what it understood (you confirm or fix it), gathers evidence in parallel — BLS Employment Projections 2025–35, O*NET tasks × Anthropic Economic Index, AIOE, prediction markets, Epoch AI, FRED — and writes a plan that leads with the answer: **your outlook · how the work may change · what this means for you · a 30-day / 6-month / 1-year preparation plan · other paths · confidence and uncertainty**. Every factual line cites evidence; a second model (different family) strips what it can't verify; you approve the plan before it is saved. Jobs the SOC taxonomy doesn't have (Product Manager…) are assembled as composites from 18,000 O*NET task statements — and labelled as such.

Built for Maven *Mastering Agentic AI*, Week 3. LangGraph supervisor · Nebius open-weight models · Streamlit.

```
python run_cli.py --soc 15-1252 --industry fintech --week "backend services, PR review, on-call" --auto
python run_cli.py --composite "Product Manager" --industry "real-estate software" --week "user research, requirements, prioritization" --auto
python run_cli.py --student --careers 27-1024 15-1255 19-3039 --interests "psychology, design, technology" --auto
python -m evals.run_golden                          # 13-case professional golden set
EVAL_WORKERS=3 python -m evals.run_student_evals    # 24-case student sweep with simulated students
python -m tools.smoke_test 11-2021                  # hit every data source once
```

Stable evidence (occupation resolution, O*NET web service, forecast searches, Epoch/FRED) is cached under `data/processed/cache/` (versioned, gitignored; `NEXTSHIFT_NO_CACHE=1` disables). First run builds two embedding caches with Nebius (occupations, and all 18K O*NET task statements — ~5 min, a few cents); they are gitignored under `data/processed/*.npy`.

**Behind the scenes:** every screen carries a sidebar *Your journey* indicator (derived from graph stage and node phase events — never faked) and an *Open behind the scenes →* dialog: *How NextShift works* (seven plain-language steps, tagged [you]/[code]/[AI]), *What is saved?* (verified against the checkpoint and memory code), and *For builders* (architecture, model-vs-deterministic boundaries, state, failure handling, diagrams). Career cards explain *Why this appeared →* in two groups — what you told us (quotes) and career evidence — from the reviewed objects only. Developer mode (`NEXTSHIFT_DEV=1` in `.env`, then the sidebar checkbox) adds nodes, model roles, cost and a phase timeline, and is the only mode in which LangSmith tracing is on. Tests: `pytest tests` (journey mapping, copy pinned to code constants, AppTest panel checks).

**Evals:** professional 12/12 (median 122 s) · student 24/24 (median 371 s ≈ 6 min, ≈ $0.03 per exploration; simulated students; both gates, injected failures, memory, exploration loop) — `evals/results/`. Samples: `samples/`. Architecture: `design/architecture-diagram.png` (professional) · `design/architecture-student.png` (student interviewer).

Docs: `PLAN.md` (scope + contract) · `graph/DESIGN.md` (architecture, as built) · `GOOD_MORNING.md` (tools layer notes).
