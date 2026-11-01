# Checklist status: full-dataset EDA

Maps every item of sections 6 to 23 of the execution prompt to **done**, **partial**, **blocked** or **n/a**. "Evidence" names the table, ledger prefix or document. Ledger = `reports/full_eda/tables/claims_ledger.csv`; tables = `reports/full_eda/tables/`. Priorities (P0/P1/P2) follow section 4 of the prompt.

## §6 Read sources and reconcile (P0)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Read brief, earlier report, sample schema | partial | `context.md`, `docs/sample_eda/` read; brief PDF known through `context.md` (not re-read); the earlier PDF report was not opened (repo equivalent used) | read the PDFs in full |
| Summarize requirements, constraints, disagreements | partial | report §2; automatic-vs-recommendation scope kept, disagreement not re-argued | C-01..C-12 not individually re-checked (C-01, C-02, C-03, C-04 touched) |
| Re-check table F, H, U, Q-04/06/09/22 | done | report §5; findings §9 | |
| Treat sample counts as hypotheses | done | no sample constant is used in code | |
| Repeated prompts, instructions, history, RAG, labels, missing billing | done | ledger `cache.*`, `instr.*`, `hist.*`, `rag.*`, `model.*`, `bill.*` | |
| Explain duplicate occurrences vs pairs vs hit rates | done | report §4.1 | |
| Hypothetical instruction contribution vs verified billable input | done | `comp.*` labelled hypothetical; `tok.*` observed | |

## §7 Scope, provenance, representativeness (P0)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Dataset card, configs, revision, access, licence | done | `data_dictionary.md`, report §2; licence limits flagged (Q5 in questions) | |
| Files, sizes, method, versions, seeds | done | `data/derived/full_eda/manifest.json`; notebook provenance cell | |
| Counts of sessions, messages, roles, calls; verify ~100k | done | ledger `scope.*` (about 80k sessions; claim not borne out) | internal calls counted only as billing items |
| Date range, strata, schema drift by date | partial | `scope.first_ym`, `monthly_profile.csv`; no category field exists | no schema-by-date review beyond monthly shares |
| Complete, truncated, filtered or sampled? | partial | `integrity.dialogue_len_match` shows internal consistency only | sampling method unknown (Metis) |
| Failed, abandoned, regenerated, branches, tool calls | partial | `finish.*`, `tool.*`, `pairing.*` | no regeneration or branch evidence available |
| Stable app, bot, user, tenant, traffic-source IDs | done | `tenant.*`; no traffic-source field (Q-22) | |
| Anonymisation placeholders | blocked | not investigated | inspect placeholder tokens vs duplicate rates |
| Compare full vs sample | partial | report §2, §5 (from sample documents, not recomputed on the sample) | recompute sample metrics with the new code |
| Generalisation statement | done | report §2 | |

## §8 Schema, integrity, structure (P0)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Data dictionary | done | `data_dictionary.md`, `field_states.csv` | |
| Nested/JSON-in-string inspection | partial | JSON columns parsed; AI content JSON share `ans.json_like` | schema variants of JSON answers not catalogued |
| Duplicate IDs, count mismatches, roles, timestamps, ordering | done | `scope.dup_message_ids`, `integrity.*`, `scope.null_timestamps` | ordering anomalies counted in notes only |
| Source vs timestamp order, ties | partial | order = timestamp then source position | tie counts not reported |
| Declared vs observed counts | done | `integrity.dialogue_len_match` | |
| Unanswered, consecutive, multiple, uncertain pairings | done | `pairing.*` | |
| Linked session/message/request/chunk tables | done | `data/derived/full_eda/*` (local) | |
| Define a request row | done | report §3, findings "How to read" | |
| Pairing quality flag with method | done | `pairing.py`, `pairing.*` | |
| Exclusions per analysis | partial | cache funnel; billing coverage | exclusions not tabulated for every metric |
| IDs linking examples without content | done | review sets (IDs only committed) | |

## §9 Effective input reconstruction (P0)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Meaning/timing of fields | done | report §3 | final answers need Metis |
| Sent vs stored | partial | turn-0 fits `recon.t0.*`, `recon.t0rag.*` | no payload log |
| Components accounted | partial | `comp.*` | memory, summaries, tools, attachments unknown |
| Stored instructions version | blocked | single bot snapshot | needs bot version history |
| Truncation, formatting | partial | chunk ceiling about 2,500 characters | provider-specific transformations unknown |
| Label verified/partial/hypothetical | done | data dictionary table | |
| Scenarios if unknown | partial | composition estimate with R² | no explicit scenario grid |
| Feature-availability map | partial | report §4.4 lists pre-generation features | no standalone map |
| No future/current-answer leakage | done | replay uses prior answers only | |
| Clarifications for Metis | done | `metis_questions.md` | |

## §10 Language and script (P0; label validation P1)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Label scheme and tool | done | `text_features.py` (heuristic, rule-based, no external tool) | |
| Define mixed | done | docstring; script-ratio at least 15% each | |
| Arabic script is not Persian; Latin is not English | done | `arabic_script_other` label; tests | |
| Analyse requests, instructions, history, RAG, outputs separately | partial | USER, instructions, answers; RAG/history not labelled | |
| Request, session, token-weighted | done | `lang.user.*`, `lang.sess_*`, `lang.tokw.*` | |
| Switching and requested vs observed answer language | partial | `lang.sess_switch`, `lang_request_vs_answer.csv` | requested language not extracted |
| Cross-tabs | partial | `lang_by_provider.csv` | not by task, RAG, attachments |
| Character variants, digits, ZWNJ | done | `text.user_has_*` | |
| Preserve originals; test collisions | partial | normalisation tests | collision rate not measured |
| Stratified review sample | partial | `review/language_validation.csv` exported; validation **pending** | Persian-capable reviewer |

## §11 Tasks and capability (P0 structure, P1 labels)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Multi-label taxonomy | blocked | no task classifier built | build and validate |
| Task vs length, difficulty, risk | blocked | | |
| Requested language, format, length, constraints | blocked | only JSON-answer share and `input` widgets measured | |
| History, freshness, attachment, tool dependence | partial | `review/history_dependence.csv` exported; attachment/tool shares measured | labels pending |
| Difficulty proxies | partial | simple-rule screen `route.simple_rule_*` (a screen, not a label) | |
| Task shares with token/cost intersections | blocked | | |
| ID-only review sets | done | `reports/full_eda/review/` | |
| Unsupported/OOD cases | partial | image/audio/file attachment counts, workflow bots | |

## §12 Tokens and cost concentration (P0)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Provider-reported usage; keep exact vs estimated | done | recorded usage (observed, provenance unverified); no local tokenizer used | tokenizer assets not fetched on this machine |
| Sensitivity across tokenizers | partial | `tok.chars_per_token_slope.*` | no multi-tokenizer sensitivity |
| Component tokens | partial | `comp.*` (hypothetical) | |
| Modality, reasoning categories | partial | audio fields summed in features; not reported | |
| Cached vs uncached | done | `tok.cached_*`, `cached_token_convention.csv`, `cached_by_provider.csv` | |
| Count, total, mean, median, p90, p95, p99, max | done | `dist.*`, `instr.chars.*`, `rag.*` | by key segment: model and bot only |
| Aggregate vs per-request shares | partial | aggregate shares reported | per-request ratio distributions not reported |
| Top requests, sessions, templates | partial | `cost.top*`, `instruction_groups_top.csv` | |
| Input vs output cost | done | `cost.split.*` | |
| Context growth, candidate-model budgets | partial | `history_growth.csv` | no per-model usable-budget check |
| Outliers | partial | p99 and max reported | no outlier review |
| Denominator coverage | done | ledger coverage column | |

## §13 History (P0 partial)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Depth, duration, gaps, first-turn share | partial | `session.*`, `gap.*` | no topic-change or duration table |
| Stored vs transmitted | partial | `hist.*` | policy unidentified |
| Policy identification | blocked | | needs payload evidence |
| Persistence of instructions, RAG, attachments | partial | `rag.chunk_repeat_in_session` | |
| History tokens vs turn | done | `history_growth.csv`, `history_ratio_to_turn0.csv` | |
| Dependency review | partial | review set exported | labels pending |
| Facts to survive reduction | blocked | | |
| Do not assume all turns sent | done | explicit in report | |
| Prefixes, branches, pre-request state | partial | `hist_hash` chain | |

## §14 Instructions (P0 partial)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Presence, size, groups, shared prefixes, versions | partial | `instr.*`; no prefix or version analysis | |
| Static vs dynamic | blocked | | |
| Large, embedded, conflicting, repeated sections | blocked | max length reported only | |
| Storage vs transmission vs accidental duplication | partial | report §4.3 | |
| Shorter equivalent templates | blocked | experiment X6 | |
| Provider prefix caching separate | partial | `red.cached_share_*` | provider rules not verified |

## §15 RAG (P0 partial)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| none / empty / non-empty / absent / unknown | done | `rag.state.*` | |
| Prevalence, token and cost share | partial | `rag.requests_with_chunks`, `comp.rag_share` | cost share by RAG not separated |
| Query, results, IDs, scores, top-k, rerank, source | partial | relevancy, chunk IDs present; `rag_top_k` on bots | not analysed further |
| Chunk metrics, reuse, plateaus | done | `rag.chunk_*`, `red.rag_dup_*` | overlap not measured |
| Full context vs reference | partial | chunk text logged; final supplied context unconfirmed | |
| Workflow patterns, change over time | blocked | | |
| Relevance, redundancy, freshness | blocked | | |
| Retrieval latency/cost | partial | per-call fee finding (`fee.*`) | latency absent |
| Full vs reduced vs no RAG | done | experiment X5 | pending |
| Update and sharing scope | blocked | | needs Metis |

## §16 Attachments, input, tools (P0 partial)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Attachment inventory | done | `att.*` (no content analysis, NG-07) | |
| Modality processing cost | blocked | | |
| `input` objects | done | field names and shape in data dictionary | value distribution not analysed |
| Tool inventory | partial | `tool.*` (rare) | |
| Live-info needs | blocked | | |
| Same filename vs content | n/a | no filenames analysed | |
| Carry dependencies into eligibility | partial | cache eligibility funnel excludes attachments, tools, actions | |

## §17 Exact cache (P0)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Raw and normalised groups; occurrences vs reusable | done | `exact_cache_variants.csv`, `cache.*.reusable_ub` | |
| n−1 bound; pairs are not hits | done | report §4.1 | |
| Scopes separately | partial | session, same-user, global measured; cross-user **unmeasurable** | |
| Eligibility funnel | partial | `exact_cache_funnel.csv` | freshness and product constraints not applied |
| Candidate keys | done | four variants | generation settings and answer schema not in key |
| No universal "no history" | done | full-history variant evaluated | |
| Personalisation, time sensitivity, regeneration | blocked | only memory/RAG proxies | |
| Chronological replay without future answers | done | `cache_replay.py`, tests | completion time = logged AI timestamp (assumption) |
| TTL, capacity, invalidation | partial | TTL and LRU capacity in the table | invalidation not simulated |
| Separate isolated-key, threshold, capacity effects | partial | variant, TTL and capacity columns | |
| Curated cache | partial | `cache.firstturn_*` | traffic source unknown |
| Eligibility before reuse; candidate vs hit | done | all reported as candidate hits | validity pending (X1) |
| Hit rates, tokens, cost, intervals, storage | partial | all but storage and stale rate | |
| Insertion, lookup, validation costs | blocked | not measured | |

## §18 Semantic cache (P1)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| CPU Persian/multilingual embedding model | blocked | none installed; no content leaves the machine | choose, document and run |
| Validate on real examples | blocked | | |
| Efficient retrieval | partial | MinHash banding within bot (lexical) | ANN for embeddings |
| Exact vs incremental opportunity | partial | `sem.requests_in_near_pairs` (sampled, lexical) | |
| Paraphrase, Finglish, mixed, cross-language | blocked | | |
| Labelled review set with hard negatives | partial | `semantic_pair_validity.csv` exported (hard negatives not yet seeded) | add hard negatives |
| Label by effective-request validity | n/a | labelling guidance in review set notes columns | reviewers |
| Tune on development data | blocked | | |
| Precision, recall, latency, indexing | blocked | | |
| Threshold curves | blocked | | |
| Chronological replay | blocked | | |
| Without labels: candidate-only report | done | report §4.2 | |

## §19 Context reduction (P0 structural)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Opportunity by component | partial | `comp.*`, `red.*` | attachments and tools not sized |
| Transparent policies | partial | duplicate chunk removal sized; windows only via excess proxy | |
| Policy specs (applicable, retained, protected, fallback) | blocked | | |
| Original vs reduced on same requests | blocked | experiments X4 to X6 | |
| Token reduction, losses, overhead | blocked | | |
| Summary amortisation, prefix-caching effect | blocked | | |
| Eligibility effect of reduction | blocked | | |
| Never remove required rules | done | stated constraint | |
| Structural only; quality **unverified** | done | report §4.3 | |
| Long context is not redundancy | done | stated | |

## §20 Model usage and routing (P1)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Label inventory; mapping file | done | `model_usage.csv`; `config/reference/label-mapping-full-v1.toml` | aliases beyond the sample not verified |
| Shares by language, task, stratum, depth, RAG | partial | provider cross-tabs, cost by turn | task, modality, RAG cuts missing |
| Model changes in sessions, errors, retries | blocked | bot snapshot only | |
| Capability/price table | partial | price file used; no new primary-source lookups | |
| Filter before cost ranking | blocked | | |
| Pre-generation features | partial | report §6 and findings | no missingness or compute-cost table |
| Why history cannot give optimal routing | done | report §4.4 | |
| Cheap baselines | partial | simple-rule screen | |
| Uncertainty fallback definition | blocked | | |
| Escalation vs failover separation | partial | experiment X8 | |
| Specification, no fabricated accuracy | done | `experiment_plan.md` | |

## §21 Quality and benchmark design (P0 design)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Quality per task | partial | `experiment_plan.md` | rubric not written |
| Three quality signals | partial | defined in plan; none measured | |
| Objective checks | partial | JSON-validity share only | |
| Evaluation set selection | partial | design in plan X7; set not built | |
| Same effective request across models | n/a | no model calls (ADR-0003) | |
| Persian quality calibration, judge spec | blocked | no paid judging run | rubric, judge, human check |
| Whole-session splits, temporal holdout | partial | stated in plan | |
| Freeze thresholds | n/a | no test run | |
| Per-segment quality | blocked | | |
| Fixed replay vs end-to-end | partial | stated in plan | |
| Review templates exported | done | `reports/full_eda/review/` | |

## §22 Financial analysis (P1)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Baselines (as-logged, premium, cheapest-capable) | partial | recorded cost (as-logged); repricing at premium `gpt-5.4` (`fin.reprice_*`); cheapest-capable not defined | Q-05 still open |
| Historical bill vs repricing | done | recorded vs price-file basis kept apart; `implied_unit_rates.csv` | |
| Provider billing rules, cached rates | partial | cached convention fixed per model | rules unverified |
| Embedding, lookup, retrieval, summary, router costs | partial | retrieval fees observed | others unmeasured |
| Formulas, assumptions, sensitivity | partial | notes in the ledger | no sensitivity grid |
| Cost per request/session/answer | partial | per request only | per acceptable answer needs quality |
| Per-lever, pairs, full pipeline | blocked | | X9 |
| Cascade cost | blocked | | |
| Quality-bound policy choice | blocked | | |
| Label observed/simulated/hypothetical | done | ledger evidence class | |

## §23 Runtime and observability (P1)

| Item | Status | Evidence | Remaining |
|---|---|---|---|
| Profile ingestion, memory, disk; overhead budget | partial | manifest (hardware, timings for ingest); lookup and embedding not benchmarked | embedding and lookup latency |
| Batching, checkpoints | done | per-shard resumable ingest | |
| Latency/TTFT | blocked | no instrumentation | |
| Warm-up, TTL, drift | partial | TTL columns, `monthly_profile.csv` | |
| Future logs specification | done | `metis_questions.md` items 3 to 10 | consolidated list not written |
| Derived fingerprints, no raw content | done | committed outputs are aggregates | |

## Outputs (§24)

| Output | Status |
|---|---|
| Short report | done (`full_eda_report.md`; about 2,200 words including tables, slightly over the target) |
| Executed notebook, smoke and full | partial: executed on the full outputs (display mode); `--smoke` pipeline run via the CLI scripts |
| Linked tables, ledger, manifests | done (local tables git-ignored; ledger committed) |
| Checklist | this file |
| Findings, dictionary, plan, questions | done |
| Figures | done (six) |
| Review sets and rubrics | partial: sets done, written rubrics not |
| README | done |
| PDF export of the report | not done |
