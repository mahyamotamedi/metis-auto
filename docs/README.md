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
| [0023](adr/0023-demo-backend-components.md) | Demo A backend: detectors, rule-based routing on effective cost (hidden reasoning counted), sticky routing v1 with `Turn.producer` (A-64, schema 0.5; coding intent, schema 0.6), labelled demo cache settings (bot-level scope, seed), EXPERIMENTAL LLMLingua-2 (extra `compress`), DeepSeek thinking templates; promoted as **placeholders**, serving defaults unchanged | decided for the demo (Demo milestone A) |
| [0024](adr/0024-demo-ui-streamlit.md) | Demo B UI: a thin Streamlit page over `ChatSession` (view model `wiring/demo_ui.py`, no logic in the page), extra `ui` with its own lock `requirements-ui.lock`, localhost only, no usage statistics, SYNTHETIC presets as configuration, right-to-left by CSS | decided for the demo (Demo milestone B) |
| [0025](adr/0025-persian-folding-treatments-and-evaluation-groups.md) | Persian folding as versioned measurement treatments (`persian_fold_v1`, `_zwnj_space_v1`, `_marks_v1`; none a default); keyed duplicate groups and leakage-safe splits for evaluation; serving path unchanged | decided (structure) for measurement only; which treatment serving may use is open |
| [0027](adr/0027-local-postgresql-foundation.md) | Local PostgreSQL for source data and evaluation datasets (not a production schema; our choice, not a claim about Metis): four schemas, Alembic, reproducible ingestion. |
| [0028](adr/0028-evaluation-dataset-golden-v1.md) | The 300-request evaluation dataset golden-v1: components with availability stages, separate reference, controlled selection, human-only complexity, team fingerprint. |
| [0029](adr/0029-evaluation-dataset-golden-v2.md) | golden-v2: golden-v1 without the 23 attachment records, each replaced inside its cell (reserves, then pool); derived from a pinned golden-v1, own fingerprint, ID mapping, media caveat. |
| [0030](adr/0030-golden-answers-gpt-5-5.md) | gpt-5.5 reference answers for golden-v2: independent calls, effort `medium`, 8192 output tokens, approval flag, table `eval.golden_answer`, failures recorded not replaced, content-free summary. |
| [0026](adr/0026-premium-baseline-gpt-5-5.md) | Premium baseline becomes `gpt-5.5` (estimate and sampling only, never routed): new price file `-g55`, catalogue entry disabled with unknown limits, tokenizer by family mapping | decided (owner, 2026-10-30) |

## Guides
- [demo_quickstart.md](guides/demo_quickstart.md): **start here if you are new**: a step-by-step guide for teammates to run the demo: setup, fake and real-model modes, **the browser UI (Demo B)** with a tour, a 5-minute demo script, and how to read the cost panel; the terminal demo (Demo A) with a walkthrough; `.env` and the Metis key, `config/local.toml`, the shared budget, troubleshooting. Followed end to end on a fresh clone (fake mode) on 2026-10-19. Required deliverable of the Demo milestone.
- [local_development.md](guides/local_development.md): **Stage 6** setup from a fresh clone, smoke test natively and in Docker, configuration in practice, secrets, the live budget and spend ledger; **Stage 7.5** enabling live calls, `chat.py`, and the live wrapper check (§5.1); **Demo A** the optional compression extra and model files (§1); **Demo B** the optional UI extra (§1).

## References (external sources, dated)
- [metis_wrapper_api.md](references/metis_wrapper_api.md): Metis wrapper endpoints and notes, summarised from the docs saved 2026-10-18; §4 links the Stage 7.5 live check results.
- [metis_wrapper_live_check.md](references/metis_wrapper_live_check.md): **Stage 7.5** live wrapper check of 2026-10-18 (one tiny synthetic message per test model, 0.000188 USD): reported vs counted tokens, cached and reasoning reporting, reported models; raw content-free results in `metis_wrapper_live_check_2026-10-18.json`.
- [metis_demo_live_check.md](references/metis_demo_live_check.md): **Demo A** live check of the whole flow, 2026-10-19 (7 SYNTHETIC calls, 0.000271 USD; reported = counted input on every call; DeepSeek thinking-off template verified with history, A-68; sticky routing and bot-level cache on live answers); raw content-free results in `metis_demo_live_check_2026-10-19.json`.
- [metis_demo_ui_live_check.md](references/metis_demo_ui_live_check.md): **Demo B** live smoke test of the UI, 2026-10-19 (the page driven in live mode, SYNTHETIC preset; 4 answers, 2 escalations, 0.001674 USD; gpt-5-nano spent its 512-token cap on reasoning, Q-44; no provider-cache hit); raw content-free results in `metis_demo_ui_live_check_2026-10-19.json`.
- [metis_pricing_2026-10-18.csv](references/metis_pricing_2026-10-18.csv): extract of the Metis pricing page saved 2026-10-18 (public prices; structured columns defective for tiered models, see the wrapper summary §3).

## Reports
- [reports/cost/README.md](../reports/cost/README.md): **Stage 7** overhead with real tokenizers (A-38) and tokenizer-specific size estimates of the sample (estimates, not billed tokens); **Stage 8** overhead with the sample's request sizes; **Demo A** overhead with the detectors and with LLMLingua-2 on and off.
- [reports/caching/](../reports/caching/README.md): **Stage 8** [EXP-CACHE-001](../reports/caching/exp-cache-001/README.md), the exact-cache baseline (candidate hits per key variant and scope; feature-only).

## Experiments
- [experiments/framework.md](experiments/framework.md): **Stage 8** experiment framework: config shape, EXP-IDs, runner kinds, adding a strategy (one interface + one config entry), run records, the comparison format, harness components.
- Evaluation framework (research-backed spec and E0-E6 notes): [experiments/evaluation_framework.md](experiments/evaluation_framework.md), [e2](experiments/e2_scenario_config.md), [e4](experiments/e4_sampling_run.md), [e5](experiments/e5_judging.md), [e6](experiments/e6_logging_and_status.md); implementation prompt: [evaluation_implementation_prompt.md](experiments/evaluation_implementation_prompt.md); guide: [guides/offline_evaluation.md](guides/offline_evaluation.md). ADRs [0025](adr/0025-persian-folding-treatments-and-evaluation-groups.md), [0026](adr/0026-premium-baseline-gpt-5-5.md).
- Plans: [caching_plan.md](experiments/caching_plan.md) (exact → semantic → persistent → curated; provider cache), [routing_plan.md](experiments/routing_plan.md) (rules to learned and LLM routers, cascades, sticky routing v1; the label problem; hidden reasoning), [context_plan.md](experiments/context_plan.md) (history windows and summaries, LLMLingua-2 and LLMLingua, retrieved-context trimming, instruction handling; Persian quality and overhead).
- Experiment conventions: [experiments/README.md](../experiments/README.md).

## Inputs
- [Project brief (PDF)](brief/project-draft.pdf).
- [Master prompt](../metis_claude_code_master_prompt.md): the engagement's stage plan. Its "Key EDA facts" are reframed by ADR-0008.

## Sample EDA (preliminary, sample-only; ADR-0008)
- [data_overview.md](sample_eda/data_overview.md) · [eda_questions.md](sample_eda/eda_questions.md) · [eda_methodology.md](sample_eda/eda_methodology.md) · [eda_results.md](sample_eda/eda_results.md)
- Notebook: `experiments/sample_eda/`. Outputs: `reports/sample_eda/`.

### Full-dataset EDA (2026-10-30)
- Evaluation dataset: [golden_v1.md](evaluation/golden_v1.md) · [annotation_rubric_v1.md](evaluation/annotation_rubric_v1.md) · [example_queries.sql](evaluation/example_queries.sql) · teammate guide [team_setup.md](guides/team_setup.md). Outputs: `reports/evaluation/golden_v1/`.
- [full_eda_report.md](full_eda/full_eda_report.md) (short report) · [eda_findings.md](full_eda/eda_findings.md) · [data_dictionary.md](full_eda/data_dictionary.md) · [experiment_plan.md](full_eda/experiment_plan.md) · [metis_questions.md](full_eda/metis_questions.md) · [checklist_status.md](full_eda/checklist_status.md) · [session_config_report.md](full_eda/session_config_report.md) (sessions, shared configurations, top five, golden-set proposal)
- Notebook and README: `experiments/full_eda/`. Outputs: `reports/full_eda/`.

## Agent conventions
- [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md), and [agents/](agents/): issue tracker, triage labels, domain-doc layout.
