# Documentation index

Every Metis-Auto design document, decision record, and plan is linked from here. Start with **progress**, then **context**.

## Project state
- [progress.md](project/progress.md): stage status, outputs, open questions. **Read first.**
- [context.md](project/context.md): the problem, the data's shape and limits, sample signals, hypotheses (`H-n`), unknowns.
- [requirements.md](project/requirements.md): goals, `FR-`/`QA-`/`NG-` requirements, the brief→data map, traceability.
- [assumptions_and_questions.md](project/assumptions_and_questions.md): the register (`A-n`, `Q-n`, `TODO-n`).
- [live_testing_and_demo_brief.md](project/live_testing_and_demo_brief.md): **owner decisions of 2026-10-18** (amended the same day: §10, §12 teammate quickstart) on live calls, the 20 USD budget, test models, the premium baseline, sticky routing, the demo; where each part lands (Stages 6, 7, 7.5, 8, Demo milestone). The owner's brief as received, plus that dated amendment.
- [GLOSSARY.md](../GLOSSARY.md): domain terms.

## Architecture
- [repository_structure.md](architecture/repository_structure.md): where files go, what each package may import, and the promotion process (Stage 2).
- [architecture/README.md](architecture/README.md): **Stage 3 architecture index**: overview and component catalogue, request lifecycle and data flow, routing, caching, context construction, attempts (escalation and failover), evaluation, configuration, observability, providers, deployment and data. Lists every diagram and the question it answers.
- [contracts.md](architecture/contracts.md): **Stage 4 internal contracts**: conventions, catalogue (producers, consumers, privacy), versioning, sample tolerance, the reserved `traffic_source`, arrow coverage. Field tables: [contracts_reference.md](architecture/contracts_reference.md) (generated from code).
- [module_reference.md](architecture/module_reference.md): **Stage 5 module interaction reference** (updated in Stage 6): every module's callers, imports (checked by a test), data, config, kind, and status; the walking skeleton's stage-to-method map; swap points.
- [token_accounting.md](architecture/token_accounting.md): **Stage 7** token and cost accounting: supported models, methods and fidelity, what is billed and modelled, price schema, caveats, premium-baseline estimate, savings decomposition, measurements.

## Decision records (`adr/`)
| ADR | Decision | Status |
|---|---|---|
| [0001](adr/0001-python-tooling.md) | Python tooling: 3.13, venv + pip, pyproject, locked deps, ruff, pytest | decided (set up in Stage 5; locking provisional) |
| [0002](adr/0002-configurable-baselines.md) | Baselines: configurable premium placeholder plus mandatory as-logged | decided |
| [0003](adr/0003-offline-by-default-model-calls.md) | Model calls offline by default; live calls opt-in with a spending cap | decided; amended by ADR-0018 |
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
| [0015](adr/0015-keyed-content-fingerprints.md) | Keyed (HMAC) content fingerprints; amendment 1: HMAC-SHA-256 algorithm, format, test vectors | decided |
| [0016](adr/0016-curated-cache-and-traffic-source-scope.md) | Curated shared cache and traffic-source-based cache scope | **proposed — to be tested** (Q-21); scope rule S-b chosen; serving defaults unchanged; `traffic_source` reserved in Stage 4 |
| [0017](adr/0017-contract-modelling-with-pydantic.md) | Contracts are pydantic v2 models: frozen, extra fields forbidden, a privacy class on every field | decided (pydantic 2.14.1 locked, Stage 5) |
| [0018](adr/0018-live-calls-for-development-under-a-lifetime-budget.md) | Live calls for development and testing through the Metis wrapper, under a 20 USD project ceiling (amends ADR-0003); amendment 1: lifetime cap 10 USD = the Metis dashboard limit (Q-29) | decided (per-run cap and tiers provisional) |
| [0019](adr/0019-configuration-format-layers-and-secrets.md) | Configuration: TOML, six layers, `METIS__` overrides, secrets only from the environment | decided (`Settings` shape provisional) |
| [0020](adr/0020-token-and-cost-accounting.md) | Token and cost accounting: tokenizers per family as configuration (exact where published, labelled approximation otherwise), strict fidelity, tiered prices ("270K" = 270,000), labelled premium estimate, exact savings decomposition | decided (templates and Grok approximation provisional; Q-31 answered) |
| [0021](adr/0021-live-openai-compatible-adapter.md) | One live OpenAI-compatible adapter (OpenAI, DeepSeek, Grok via the Metis wrapper; openai SDK in extra `live`), SDK retries off, an uncomputable actual cost charges the estimate and stops the run, generation-limit cap | decided (usage mappings confirmed by the live check 2026-10-18; error mappings provisional) |

| [0022](adr/0022-experiment-runner-and-run-tracking.md) | Experiment runs tracked by our own small runner (not MLflow; an exporter stays an option); the event stream stays the record; EXP-ID naming; candidate loading from `experiments/` only | decided (Stage 8) |

## Guides
- [demo_quickstart.md](guides/demo_quickstart.md): **start here if you are new**: a step-by-step guide for teammates to run the demo: setup, fake and real-model modes, `.env` and the Metis key, `config/local.toml`, the shared budget, reading the cost panel, troubleshooting. Required deliverable of the Demo milestone (UI parts completed then).
- [local_development.md](guides/local_development.md): **Stage 6** setup from a fresh clone, smoke test natively and in Docker, configuration in practice, secrets, the live budget and spend ledger; **Stage 7.5** enabling live calls, `chat.py`, and the live wrapper check (§5.1).

## References (external sources, dated)
- [metis_wrapper_api.md](references/metis_wrapper_api.md): Metis wrapper endpoints and notes, summarised from the docs saved 2026-10-18; §4 links the Stage 7.5 live check results.
- [metis_wrapper_live_check.md](references/metis_wrapper_live_check.md): **Stage 7.5** live wrapper check of 2026-10-18 (one tiny synthetic message per test model, 0.000188 USD): reported vs counted tokens, cached and reasoning reporting, reported models; raw content-free results in `metis_wrapper_live_check_2026-10-18.json`.
- [metis_pricing_2026-10-18.csv](references/metis_pricing_2026-10-18.csv): extract of the Metis pricing page saved 2026-10-18 (public prices; structured columns defective for tiered models, see the wrapper summary §3).

## Reports
- [reports/cost/README.md](../reports/cost/README.md): **Stage 7** overhead with real tokenizers (A-38) and tokenizer-specific size estimates of the sample (estimates, not billed tokens); **Stage 8** overhead with the sample's request sizes.
- [reports/caching/](../reports/caching/README.md): **Stage 8** [EXP-CACHE-001](../reports/caching/exp-cache-001/README.md), the exact-cache baseline (candidate hits per key variant and scope; feature-only).

## Experiments
- [experiments/framework.md](experiments/framework.md): **Stage 8** experiment framework: config shape, EXP-IDs, runner kinds, adding a strategy (one interface + one config entry), run records, the comparison format, harness components.
- Plans: [caching_plan.md](experiments/caching_plan.md) (exact → semantic → persistent → curated; provider cache), [routing_plan.md](experiments/routing_plan.md) (rules to learned and LLM routers, cascades, sticky routing v1; the label problem; hidden reasoning), [context_plan.md](experiments/context_plan.md) (history windows and summaries, LLMLingua-2 and LLMLingua, retrieved-context trimming, instruction handling; Persian quality and overhead).
- Experiment conventions: [experiments/README.md](../experiments/README.md).

## Inputs
- [Project brief (PDF)](brief/project-draft.pdf).
- [Master prompt](../metis_claude_code_master_prompt.md): the engagement's stage plan. Its "Key EDA facts" are reframed by ADR-0008.

## Sample EDA (preliminary, sample-only; ADR-0008)
- [data_overview.md](sample_eda/data_overview.md) · [eda_questions.md](sample_eda/eda_questions.md) · [eda_methodology.md](sample_eda/eda_methodology.md) · [eda_results.md](sample_eda/eda_results.md)
- Notebook: `experiments/sample_eda/`. Outputs: `reports/sample_eda/`.

## Agent conventions
- [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md), and [agents/](agents/): issue tracker, triage labels, domain-doc layout.
