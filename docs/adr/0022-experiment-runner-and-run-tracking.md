# ADR-0022: Experiment runs are tracked by our own small runner, not MLflow; the event stream stays the measurement record

- Status: **decided** (custom runner, file layout, EXP-ID naming, candidate loading). An MLflow *exporter* stays an option (below). Stage 8, 2026-10-18.
- Relates to: ADR-0005 (current scope), ADR-0009 (experiments outside the package, promotion), ADR-0012 (events are the single measurement record), ADR-0014 (counterfactual source per run), ADR-0019 (configuration layers), FR-EVAL-07, QA-REPRO, A-26.
- Detail: [docs/experiments/framework.md](../experiments/framework.md).

## Context

Stage 8 needs runs that are comparable and reproducible: each run records its config, code version, data hash, seed, versions in force, counterfactual source, and results, and results from different strategies must line up in one format. The contracts for this already exist (`RunManifest`, `EvaluationResult`, `Event`, Stage 4). ADR-0012 makes the event stream the single measurement record: every metric is computed from events by `evaluation`, never kept separately. The owner asked for a comparison with MLflow's local file backend before deciding.

Facts checked on 2026-10-18 (re-verify before relying on them):
- MLflow's latest release on PyPI is **3.17.1**. The full `mlflow` package depends on `mlflow-skinny`, `mlflow-tracing`, Flask, alembic, SQLAlchemy, pandas, numpy, pyarrow, scikit-learn, scipy, matplotlib, docker, graphene, gunicorn, and more. `mlflow-skinny` still pulls in fastapi, uvicorn, starlette, the databricks SDK, the OpenTelemetry SDK, protobuf, gitpython, pyyaml, cloudpickle, and others (PyPI JSON metadata).
- MLflow's backend-store page says: "File system backend is in maintenance mode and will not receive further updates", headed "TO BE DEPRECATED SOON", "still supported for backward compatibility"; "SQLite is the default backend store" ([backend store docs](https://mlflow.org/docs/latest/self-hosting/architecture/backend-store/)). Search results say the default changed to SQLite in 3.7.0, and some third-party pages say the file store needs an explicit opt-out from 3.10. That was not confirmed on MLflow's own pages.

## Alternatives

| | A. Own runner (chosen) | B. MLflow, local file store | C. MLflow, local SQLite store |
|---|---|---|---|
| What it records | `RunManifest`, `events.jsonl`, `EvaluationResult`, `extras.json` under `runs/<EXP-ID>/<run-id>/`: typed contracts, privacy-classed and tested content-free | params, metrics, tags, artifacts under `mlruns/` | the same in `mlflow.db` + artifact folder |
| Measurement record (ADR-0012) | events; results computed from them | metrics logged as numbers, a **second** record next to the events (they could disagree), or events uploaded as an artifact with MLflow only as an index | same as B |
| Privacy (QA-PRIV) | every field has a privacy class; tests assert no content | free-form params, tags, and artifacts: nothing stops a raw string; autologging and tracing can capture prompts | same as B |
| Dependencies | none new (stdlib + pydantic) | large (above); would need its own optional extra and lock review (ADR-0001's age rule) | same as B |
| Comparison UI | a Markdown table (`compare_runs.py`) | MLflow UI: filtering, plots, run diffs | same as B |
| Future | backend-neutral files; a database later (Stage 9) | store is in maintenance mode and "to be deprecated soon" | supported default |
| Effort | about 400 lines with tests, written in this stage | wiring plus mapping our metric shapes (state, n, interval, qualifiers) to flat keys | same as B, plus a database file |

MLflow's metric model is a flat name → float series. Ours (ADR-0006) needs states (`measured` / `unmeasured` / `not_computed`) with reasons, sample sizes, intervals, and qualifiers (variant, scope, baseline, fidelity, price version). Flattening them into keys such as `candidate_hit_rate.msg_only.lit.strict.global` loses the "why not measured" information that ADR-0006 requires next to every hit rate.

## Decision

1. **A small custom runner** (`evaluation/runner`), with its files as the run record: `manifest.json` (`RunManifest`), `events.jsonl`, `results.json` (`EvaluationResult`, computed from the events), and `extras.json` (content-free counts that are not metrics). They live under `runs/<EXP-ID>/<run-id>/` (git-ignored); curated copies go to `reports/<area>/<EXP-ID>/`.
2. **The event stream stays the single measurement record** (ADR-0012). Per-case baseline costs are `evaluation_scored` events; cache-candidate lookups are `cache_lookup` events; pipeline runs keep their own events. `results.json` is a derived view and can be recomputed.
3. **No MLflow dependency now.** If a UI or cross-run search is needed later, an **exporter** may copy a run's manifest, flattened overall metrics, and the files as artifacts into MLflow (SQLite backend, since the file store is in maintenance mode). It would be a read-only view, never the record, and would come with its own decision record. The same pattern as OpenTelemetry in ADR-0012.
4. **EXP-ID naming:** `exp-<area>-<nnn>`, area ∈ `cache`, `route`, `ctx`, `cost`, `eval`, lower case (the contracts' `Name` type); folder `experiments/<area>/<id>-<slug>/`; run ID `<id>-<UTC stamp>-<6 hex>`.
5. **Candidate loading** (A-26): `[experiment.strategy]` names a `builtin` component or a `file` + `object` in the experiment's folder. Only files under `experiments/` load, through `importlib` in `wiring.experiments`. The settings loader refuses `experiment.strategy` in every layer except an experiment file, so production defaults cannot load unpromoted code.

## Consequences

- Comparing runs means reading files: `scripts/run_experiment.py` prints the table, and `evaluation.runner.compare` builds it for any set of runs. There is no interactive UI.
- The `ast` import test cannot see the dynamic import (A-26). It is covered instead by the path check and the layer rule, both tested (`tests/integration/test_experiments.py`).
- Event files are verbose (about 35 MB for one 465-case, 30-variant cache run, mostly the repeated `Versions` block). Acceptable for the sample, which is git-ignored. For the full dataset: compress, or move `Versions` to the run level (a contract change). Noted for Stage 9.
- Revisit MLflow (as an exporter) when there are more than a handful of runs to compare, or when someone other than the owner needs to browse them.
