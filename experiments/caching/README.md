# experiments/caching/

Exact and semantic cache experiments: normalisation, key composition, validity, embedders, thresholds, false-hit analysis (FR-XCACHE, FR-SCACHE). Offline results are **candidate hits**, not safe hits. Plan: [docs/experiments/caching_plan.md](../../docs/experiments/caching_plan.md). Exact-cache baseline: [exp-cache-001-exact-baseline](exp-cache-001-exact-baseline/README.md).

Candidates for the Stage 8 caching plan:
- curated shared cache with a simulated daily rebuild, plus traffic-source scope ([ADR-0016](../../docs/adr/0016-curated-cache-and-traffic-source-scope.md), **proposed — to be tested**, tests H-8). On the sample: mechanics only. The payoff is measured on the full dataset. Conventions: [../README.md](../README.md).
