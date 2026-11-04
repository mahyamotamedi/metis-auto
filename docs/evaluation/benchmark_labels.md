# Benchmark routing labels (`benchmark-labels-v1`): the P-3 hand-off to R-B3 and R-C3

Status: **provisional**, decided in [ADR-0053](../adr/0053-paid-benchmark-p1-p3.md) point 6. No label file exists yet: the paid pilot has not run.

Made by `python scripts/benchmark.py labels --run-id <run> --name <name>` from the two judges' score files (`runs/benchmark/<run>/judging/*.scores.jsonl`). Code: `evaluation/benchmark/labels.py`.

A pair is **swap-inconsistent** when a judge's two orders map to different verdicts (E5's own rule, `PairOutcome.swap_consistent`; a win in one order and a tie in the other counts). It is neither a tie nor a score: the judge has no verdict on it, so the arm is NA for that record, even if the other judge scored it. `benchmark.py agreement --run-id <run>` reads the filled `spot_check/sheet.csv` and the local key, computes agreement per judge and language with E5 and writes `runs/benchmark/<run>/agreement.json` (counts and statistics only); the next `labels` run reads it for `judge_gate`.

## Where it is, and why it is not committed

| File | Holds | Where |
|---|---|---|
| `<name>.labels.parquet` | one row per judged record, with the join key `user_message_id` (a dataset message ID) | `runs/benchmark/<run>/labels/` (**git-ignored**; licence: no IDs in commits) |
| `<name>.summary.json` | counts only: states, `cheap_ok`, `min_adequate_tier`, `judge_gate`, and the swap-inconsistency rate per judge and per arm | same folder; safe to commit under `reports/` |

Pass the parquet file to Pipeline B and C by the team's usual private channel, never by git.

## Columns

| Column | Type | Meaning |
|---|---|---|
| `format` | str | always `benchmark-labels-v1` |
| `record_id` | str | golden-v2 record ID |
| `user_message_id` | str | **join key**: golden-v2's `target_message_id` = the requests frame's `user_message_id` (`analysis/requests_table`) |
| `labels_source` | str | `benchmark:<name>`, one value per file |
| `state` | str | `labelled`, `not_labelled:not_judged`, `not_labelled:inconsistent` (a judge's two orders disagreed on an arm and nothing else is labelled) or `not_labelled:judges_disagree_or_incomplete` |
| `cheap_ok` | boolean (nullable) | True: some cheap arm's answer is acceptable; False: every cheap arm's answer is not; NA: unknown |
| `min_adequate_tier` | Int64 (nullable) | lowest catalogue tier among acceptable arms (routing plan L2); NA if none is known acceptable |
| `judges` | int | judges whose scores were used (2) |
| `arms_judged` | int | arms both judges scored for this record |
| `inconsistent_arms` | int | arms with a swap-inconsistent pair for at least one judge (their `acceptable:<arm>` is NA) |
| `judge_gate` | str | `validated`, `unvalidated` or `not_configured`: the E5 Persian gate of the record's language group, from the spot-check (`benchmark.py agreement`); `not_configured` while the `[gate]` values are unset. It never changes a label or drops a row |
| `acceptable:<arm>` | boolean (nullable), one column per arm | both judges' scores ≥ `acceptable_score` → True; both below → False; disagreement, a missing score or a swap-inconsistent pair → NA |

"Acceptable" compares an arm's answer with the gpt-5.5 reference answer (pairwise, both orders, E5): 1 = the arm won, 0.5 = tie, 0 = lost, averaged over the two orders. `acceptable_score` and `cheap_arms` are owner decisions (Q-63); with them unset the export refuses.

## R-C3 (small classifier, `exp-route-012`)

R-C3's `fit_logistic(train, labels, labels_source=...)` takes a boolean Series on the requests frame's index and a declared source. The export gives exactly that:

```python
from metis_auto.evaluation.benchmark.labels import labels_for_requests

labels = labels_for_requests(
    pd.read_parquet(path), requests
)  # cheap_ok, NA where unlabelled
model = fit_logistic(
    train, labels, labels_source="benchmark:<name>", l2=..., cached_separately=...
)
```

`fit_logistic` drops NA rows. R-C3 may report on these labels but must not "move" (change a routing decision) on rows whose `judge_gate` is not `validated`. Tested against R-C3's own code, unchanged (`tests/unit/evaluation/test_benchmark_judge_labels.py::test_handoff_feeds_r_c3_fit_logistic_unchanged`).

## R-B3 (kNN, `exp-route-011`)

R-B3's `KnnRouter` refuses **every** `label_source` today ("supervised use blocked"). Using these labels needs a change in Pipeline B's code (a supervised path that reads `cheap_ok` or `min_adequate_tier` by `user_message_id`), which is theirs to make (TODO-22). This format does not change for it.

## Caveats that travel with the labels

- golden-v2 is not a report-period sample (44 of 300 records are in Aug–Oct 2026) and has no attachment requests (ADR-0029). Labels from it are **training** labels; evaluate on held-out sessions.
- The judges are uncalibrated for Persian until the E5 gate passes (owner); the 60-item spot-check is the first human check.
- Labels depend on the arms judged: an arm not callable on Metis (gpt-4.1-nano, mimo-v2.5) has no column.
