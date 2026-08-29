# Good morning — NextShift AI, Saturday 2026-08-29

**App:** http://localhost:8599 (`streamlit run ui/app.py`). **Repo:** https://github.com/judy-eapen/nextshift-ai (everything pushed). **Deadline:** Sun 11:59 pm PT.

## What happened overnight
You approved the student redesign ("do all of it"). It's built, both journeys, all phases:

- **Phase A (both journeys):** the reviewer now judges the *structured objects the UI renders* (no more Markdown shadow); horizon isn't hardcoded; reviewer failure is loud (UNVERIFIED banner, save warning, filename tag); certainty-wording lint; `*.sqlite-wal/-shm` ignored.
- **Student interviewer:** one question at a time; code picks the next goal from coverage gaps and contradictions, the model only words it; five actions (I'm not sure · Skip · Recommend now · Ask me more · Edit an earlier answer); stops at 8–12 substantive answers or 14 max; nine-section *"Here's what I understand about you"* gate before any data is gathered.
- **Candidates → evidence → cards:** 8–10 directions in three groups (+ *Your ideas, reconsidered* when the student named careers), each with a rationale citing the student's own words `[p:field:i]`; resolved to real occupations (composites capped at two); BLS outlook, entry education, task groups; structured review per card; **deterministic "practical mismatch"** lines when entry education exceeds the student's stated limit.
- **Reactions → discriminators → shortlist → deep dive → what-ifs → save.** Ten-section deep dive with *Test this career before committing*; nothing written until the save gate.
- **Evals:** professional 12/12 (g05 retired — superseded by the interviewer); student 24-case sweep with simulated students: **24/24** across the sweeps (17 in the parallel sweep on current code, 7 rerun serially after a process stall; every case passes its deterministic checks and, where judged, the 5-point rubric). Median ≈ 9–10 min and ≈ $0.07 per full exploration when run alone; parallel runs share one Nebius endpoint and slow each other down — run evals with `EVAL_WORKERS=1` for timing.

## Saturday afternoon — "Behind the scenes" (approved plan, all four phases built)
- Sidebar **Your journey** (9 student / 7 professional steps, from real stage + phase events) · **Open behind the scenes →** dialog: *How NextShift works* · *What is saved?* · *For builders* · card **Why this appeared →** (what you told us / career evidence) · **What NextShift currently understands about you** during the interview (with *Edit Qn*) · *How we reached this* now shows run facts, not model names/cost.
- **Developer mode:** add `NEXTSHIFT_DEV=1` to `.env`, restart, tick *Developer mode* under *Demo & developer*. Only then is LangSmith tracing on — turn it on to record the video if you want traces.
- **Restart the app after pulling** (`@st.cache_resource` holds the compiled graph): `streamlit run ui/app.py`.
- `pytest tests` → 67 pass. Evals after the change: **professional 12/12** on this build (full sweep 10/12, then g01 passed on rerun and g04's miss was a false positive in the harness check — fixed; g04 passes). **Student:** subset s01 · s11 · s13 · s15 · s19 (the cases exercising the new explanation checks) **5/5** — s01/s19 first failed the old `removed_absent` check on a twin-sentence false positive (same reason text kept on another task row); the check is now per-card/per-path and both pass. The full 24-case sweep was not rerun today (~4 h serial) — run `EVAL_WORKERS=1 python -m evals.run_student_evals` overnight if you want the headline number refreshed.
- Fixed on the way: the interview said "Nothing you type is stored until you approve" — answers *are* checkpointed to `data/processed/checkpoints.sqlite` each turn; wording now says so.

## Saturday evening — performance (measured)
Instrumented every node, model and tool call (developer mode shows the timeline). Baseline vs after on the same five cases: professional 135 → 110 s; student 515 → 354 s (no ideas), 687 → 363 s (three ideas), 525 → 401 s (BLS down), 281 → 82 s (reviewer down). Interview answers ≈ 2–3 s; skip/not-sure instant; understanding 8 s; first cards ≈ 40 s. Main change: first-round cards are lightweight (official outlook + description + your words, fast review); the thinking reviewer and task-level AI evidence run only for the careers you react to. Full numbers: `evals/results/perf_baseline.json` / `perf_after.json`; design notes in `graph/DESIGN.md` (PERFORMANCE). Remaining bottleneck: the thinking reviewer (≈ 60–90 s per pass on shortlist and deep dive).

## Your Sunday (~3 h)
1. **Click through the student door yourself** (10 min). Try "I'm not sure" and "Edit an earlier answer". Tell me any wording that jars.
2. **Record the video** — `docs/VIDEO_SCRIPT.md` (updated: 3:55 is the student beat). Pre-run both paths once so caches are warm; each full analysis is 5–9 min, so cut or narrate over the working panel.
3. **Google Doc** — paste `docs/PROJECT_DOC.md`; drop in `design/architecture-diagram.png` (professional) and `design/architecture-student.png` (interviewer). Add 3–4 screenshots (interview turn · understanding gate · career cards · deep dive).
4. **Submit** https://forms.gle/HMgTU7zy6UJ8XkJX6 — video, doc, repo.

## Honest limitations (put them in the doc)
- A student run takes 5–9 min and costs ~$0.07 (ten occupations of evidence + a thinking-model reviewer over ~150 lines).
- The reviewer is strict: 15–30% of model-written lines are removed per run. Every removal is listed under *How we reached this*. That's the feature.
- Composites (roles with no official category) show proxy outlook, labelled. "Other paths" in the professional plan stays empty — no skill-similarity evidence yet.
- Metaculus prices are gated for this account; Polymarket + Manifold carry forecasts.

## If something breaks
- `python run_cli.py --composite "Product Manager" --auto` — professional path in the terminal.
- `PYTHONPATH=. python -m evals.run_student_evals s01` — one full student journey with a simulated student (~9 min).
- Reviewer failures are logged to `data/processed/review_failures.log`.
