# Documentation index

Every Metis-Auto design document, decision record, and plan is linked from here. Start with **progress**, then **context**.

## Project state
- [progress.md](project/progress.md): stage status, outputs, open questions. **Read first.**
- [context.md](project/context.md): the problem, the data's shape and limits, sample signals, hypotheses (`H-n`), unknowns.
- [requirements.md](project/requirements.md): goals, `FR-`/`QA-`/`NG-` requirements, the brief→data map, traceability.
- [assumptions_and_questions.md](project/assumptions_and_questions.md): the register (`A-n`, `Q-n`, `TODO-n`).
- [GLOSSARY.md](../GLOSSARY.md): domain terms.

## Architecture
- [repository_structure.md](architecture/repository_structure.md): where files go, what each package may import, and the promotion process (Stage 2).
- [architecture/README.md](architecture/README.md): **Stage 3 architecture index**: overview and component catalogue, request lifecycle and data flow, routing, caching, context construction, attempts (escalation and failover), evaluation, configuration, observability, providers, deployment and data. Lists every diagram and the question it answers.
- *Stage 4:* contracts. *Stage 5:* module interaction reference.

## Decision records (`adr/`)
| ADR | Decision | Status |
|---|---|---|
| [0001](adr/0001-python-tooling.md) | Python tooling: 3.13, venv + pip, pyproject, locked deps, ruff, pytest | decided (locking provisional) |
| [0002](adr/0002-configurable-baselines.md) | Baselines: configurable premium placeholder plus mandatory as-logged | decided |
| [0003](adr/0003-offline-by-default-model-calls.md) | Model calls offline by default; live calls opt-in with a spending cap | decided |
| [0004](adr/0004-repository-hygiene.md) | Repository hygiene | decided |
| [0005](adr/0005-current-phase-scope.md) | Current-phase scope: offline foundation, in-process API, Action 3 deferred | decided |
| [0006](adr/0006-evaluation-metric-definitions.md) | Evaluation metric definitions | decided (thresholds provisional) |
| [0007](adr/0007-cache-sharing-scope.md) | Cache sharing scope | decided (final policy open) |
| [0008](adr/0008-sample-eda-is-exploratory.md) | The sample EDA is exploratory | decided |
| [0009](adr/0009-repository-structure-and-dependency-rules.md) | Repository structure and dependency rules | decided (sub-packages provisional) |
| [0010](adr/0010-request-pipeline-shape.md) | Request pipeline shape: fixed stage order, routing before cache, measure in application / decide in domain, synchronous | decided (sync and stateless provisional) |
| [0011](adr/0011-cache-key-and-lookup-design.md) | Cache key and lookup: fingerprinted components, partition key plus similarity, unknown never matches | decided (rules provisional) |
| [0012](adr/0012-event-stream-as-measurement-record.md) | The event stream is the single measurement record | decided (fields provisional) |
| [0013](adr/0013-unified-attempt-model.md) | Unified attempt model: retry, failover, escalation in one policy-driven loop | decided (detectors open) |
| [0014](adr/0014-counterfactual-answers-via-model-client.md) | Counterfactual answers via the `ModelClient` port; every run declares its source | decided |
| [0015](adr/0015-keyed-content-fingerprints.md) | Keyed (HMAC) content fingerprints | provisional (Q-20) |

## Experiments
- *Stage 8:* framework doc and the routing, cache, and context plans, in `docs/experiments/`.
- Experiment conventions: [experiments/README.md](../experiments/README.md).

## Inputs
- [Project brief (PDF)](brief/project-draft.pdf).
- [Master prompt](../metis_claude_code_master_prompt.md): the engagement's stage plan. Its "Key EDA facts" are reframed by ADR-0008.

## Sample EDA (preliminary, sample-only; ADR-0008)
- [data_overview.md](sample_eda/data_overview.md) · [eda_questions.md](sample_eda/eda_questions.md) · [eda_methodology.md](sample_eda/eda_methodology.md) · [eda_results.md](sample_eda/eda_results.md)
- Notebook: `experiments/sample_eda/`. Outputs: `reports/sample_eda/`.

## Agent conventions
- [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md), and [agents/](agents/): issue tracker, triage labels, domain-doc layout.
