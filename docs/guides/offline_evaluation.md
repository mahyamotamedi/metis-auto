# Offline evaluation: running the pieces, and the owner-run live steps

Status: **provisional** (Stage E6, 2026-10-30). Background: [evaluation_framework.md](../experiments/evaluation_framework.md), [e6_logging_and_status.md](../experiments/e6_logging_and_status.md). Nothing here calls a model unless the live section is followed by the owner.

## 1. Setup and tests (Windows or macOS)

```bash
.venv/Scripts/python.exe -m pytest tests -q        # Windows; use .venv/bin/python on macOS
```

The suite is offline and needs no key. (The old Windows failures are fixed; on a fresh clone run the usual install from [local_development.md](local_development.md).)

## 2. Offline pieces you can run today (no calls, no key)

| What | Command | Output |
|---|---|---|
| Full-prompt input token counts and input-only cost lower bounds on the sample | `python scripts/input_cost_report.py --as-of YYYY-MM-DD [--min-n N] [--max-age-days D]` | a **new** file in `reports/cost/` (never overwrites); aggregates only |
| The sampling plan's per-slice sizes before any run | `python scripts/sampling_plan.py [--config plan.toml] [--min-n N]` | printed JSON; with no config it only prints the population |
| Tokenizer-specific size estimates | `python scripts/estimate_sample_tokens.py` | `reports/cost/sample_token_estimates.json` |

Every threshold, size, quota, cap, δ and judge-gate value is **unset by default**; an unset value gives `not_evaluated` or `insufficient` with the reason. Put your own values in an experiment file (see [e2](../experiments/e2_scenario_config.md), [e4](../experiments/e4_sampling_run.md) and [e5](../experiments/e5_judging.md) for fields and units).

The rest is a Python API under `metis_auto.evaluation` (`comparison`, `costing`, `inputs`, `sampling`, `judging`, `reporting`). The end-to-end shape, as the tests do it: plan a sample (`plan_sample`), plan calls (`plan_calls`), run them through injected clients (`execute`), judge pairs (`judge_items`), gate the judge (`evaluate_gate`, `gated_tables`), and build the report (`build_comparison_report`, then `to_markdown` and `to_plain`; write the two files under `reports/<area>/<id>/` yourself). Tests use fake clients and a fake judge only.

## 3. Live steps (owner-run only)

**Not ready to run.** The sampling harness refuses to start a live run without an approval, but there is no wiring yet that builds live clients and invocations for it, and the live adapter does not yet apply the effort setting or measure time to first token. Do not attempt a live sampling run until that step exists and you have decided the following:

1. **Approve the run** in writing: who, which run ID, and a USD cap (`LiveApproval`). Sample conversations additionally need `sample_conversations_approved`; otherwise use only your own or synthetic messages (ADR-0018).
2. **Set the cap and the limits:** `hard_cap_usd`, `max_output_tokens`, `order_seed`, the model list and effort labels. The harness checks every call's worst case against the lower of the run cap and the approval cap, and stops when it would not fit. Your project cap is 10 USD lifetime under a 20 USD ceiling (ADR-0018, Q-29); check what you have spent first (`python scripts/show_budget.py`). A pilot of the size discussed does not fit a small cap; decide the budget before approving anything.
3. **Re-verify prices** on the Metis pricing page (the table in the repo is a historical snapshot) and decide whether a maximum price age applies.
4. **What gets recorded:** the recording decorator writes each call's input parts and answer to a JSON Lines file under `data/recorded/` (git-ignored, inside the privacy boundary). The harness's own records are content-free (tokens, cost, latency, finish reason). Never commit `data/recorded/`, calibration sheets (they hold item IDs) or `.env`.
5. **Judging** needs a judge model, a calibration set rated by Persian-speaking humans, and the gate values; until then every quality score stays `unvalidated`.
