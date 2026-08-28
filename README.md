# NextShift AI
*What AI does to your work, with receipts.*

Give it your occupation, a horizon (2030 / 2035) and a question. It gathers live forecasts (Polymarket, Manifold, Metaculus), AI-exposure research (AIOE, Anthropic Economic Index, O*NET tasks), labor statistics (BLS, FRED) and frontier-model data (Epoch AI), then returns a short brief: **what changes for your tasks, which worlds we might be in, where sources disagree, what nobody knows, and what to lean into.** Every line cites a source card; a second model strips anything it can't verify; a human approves the assumptions before scenarios are built and the brief before it's exported.

Built for Maven *Mastering Agentic AI*, Week 3. LangGraph supervisor · Nebius open-weight models · Streamlit.

```
python run_cli.py --soc 11-2021 --horizon 2030      # Marketing Managers (the Product Manager persona)
python -m evals.run_golden                          # 10-occupation golden set
python -m tools.smoke_test 11-2021                  # hit every data source once
```

Docs: `PLAN.md` (scope + contract) · `graph/DESIGN.md` (architecture, as built) · `GOOD_MORNING.md` (tools layer notes).
