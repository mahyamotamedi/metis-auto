## The evaluation framework applies its rules to the pipelines' lever results (2026-11-03)

Branch `benchmark-framework-report`. ADR-0053 amendment 4.

**Done**
- `evaluation/reporting/lever_verdicts.py` (pure), `wiring/lever_evaluation.py`, `scripts/evaluate_levers.py`: for each of the 132 `reports/levers/*.json` results, the saving share with its interval and provenance, units, the Persian slice, the quality side and the plan's decision rule per step; comparable groups; nothing passes by default.
- Tests first (`test_lever_verdicts.py`, `test_lever_evaluation.py`), module-reference rows, `e6_logging_and_status.md` section 5.

**Result on the 132 files**: no step has a pickable version. Context (60) and routing (36) are `cannot_pass` (tokens only, cost only). Cache: 20 retrieval results `not_evaluated` (agreement not in the file), 16 answer results `candidate` (4 with 30 reviewed of about 300). 27 of 36 cache and 52 of 60 context savings have no interval, so they make no claim. A Persian slice is reported for 4 cache, 0 context and 17 routing results.

**Not done on purpose**: replaying levers per request; ranking inside a comparable group; putting agreement, error counts or acceptable rates into `LeverResult` (the pipelines' contract).

**Open**: whether the pipelines add agreement, answer-error counts and acceptable rates to their result files; the delta, minimum n and bootstrap owner values.

**Follow-up (same day)**: the report opens with a **summary by pipeline** (A, B, C; version names mapped to pipelines, unmatched ones `unassigned`): per step, variants tried, the largest recorded-cost saving as a headline (not a pick), results with an interval, and the blocker in plain words. The per-step and per-baseline tables follow as detail.
