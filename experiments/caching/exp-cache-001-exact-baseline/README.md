# EXP-CACHE-001: exact-cache baseline

- **Hypothesis:** H-3 (exact repeats exist, but most are unsafe under a conservative key); mechanics for H-8.
- **Plan:** [caching_plan.md, stage C1](../../../docs/experiments/caching_plan.md#c1-exact-cache-baseline-exp-cache-001-done-2026-10-18). Framework: [framework.md](../../../docs/experiments/framework.md).
- **Strategy:** the built-in `exact` candidate index (`evaluation.cache_candidates`), no candidate code here.
- **Data slice:** the sample (`sample_v1`), every pairing flag except the excluded `no_preceding_user`; naive logged-time order.
- **Metrics:** candidate hit rate per key variant and scope, hit correctness (unmeasured), as-logged cost of the hits, coverage, both baselines.
- **Success/kill:** in the plan.
- **Results:** [reports/caching/exp-cache-001/](../../../reports/caching/exp-cache-001/README.md).

```sh
.venv/bin/python scripts/run_experiment.py experiments/caching/exp-cache-001-exact-baseline/config.toml \
    --report-dir reports/caching/exp-cache-001
.venv/bin/python scripts/run_experiment.py experiments/caching/exp-cache-001-exact-baseline/config.toml \
    --set experiment.data.missing_key=unknown --report-dir reports/caching/exp-cache-001
```
