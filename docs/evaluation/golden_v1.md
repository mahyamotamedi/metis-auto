# golden-v1: the 300-request evaluation dataset

Status: **`annotated_provisional`**. Rule labels only; human review is pending. Decisions: [ADR-0027](../adr/0027-local-postgresql-foundation.md), [ADR-0028](../adr/0028-evaluation-dataset-golden-v1.md). Numbers: [quality report](../../reports/evaluation/golden_v1/quality_report.md), [validation](../../reports/evaluation/golden_v1/validation.md). Teammate steps: [team_setup.md](../guides/team_setup.md). Rubric: [annotation_rubric_v1.md](annotation_rubric_v1.md).

**Limits, stated plainly.** Labels are not ground truth. Historical answers and models are references, not proof of what was best. This is a balanced challenge set, and neither its balanced nor its weighted results equal production performance. PostgreSQL is our choice; we do not know what Metis uses.

**Attachments.** 23 of the 300 records carry an image attachment. [golden-v2](golden_v2.md) replaces them with text-only records; use golden-v1 for attachment-dependent requests.

**Licence.** The data is licensed to Rahnama College for non-commercial education and may not be redistributed. Text stays in your local database and in git-ignored folders. Only ID-and-label files may be committed or shared.

## What is where

| Location | Holds | Committed? |
|---|---|---|
| `config/evaluation/golden_v1.toml` | quotas, caps, rules, seed (status proposed) | yes |
| `config/evaluation/source_v1.toml` | pinned revision, expected columns, file sha256 | yes |
| `src.*`, `eval.*` in PostgreSQL | everything, including text | never |
| `reports/evaluation/golden_v1/` | quality report, validation, margins, cross-tabs, ID-only export, fingerprint, ID-only review sheet | yes, no text |
| `data/derived/eval_datasets/golden_v1/` | full export with text | never (git-ignored) |
| `runs/evaluation/golden_v1/review_local/` | review sheet with text | never (git-ignored) |

## Build and rebuild

```bash
python scripts/db_ingest.py --preflight
```
```bash
python scripts/db_ingest.py
```
```bash
python scripts/build_eval_dataset.py all
```
```bash
python scripts/validate_eval_dataset.py --rebuild
```
```bash
python scripts/build_eval_dataset.py verify
```

The steps inside `all` are `requests`, `select`, `review-sheets`, `export`, `report`. `fingerprint` rewrites the team's expected result, so only the lead runs it, on purpose, after a deliberate config change. `select` refuses to replace a dataset holding human labels without `--force`, and always refuses a frozen one.

## A record

One target USER message with its clean-paired answer. Its inputs are ordered rows in `eval.record_input_component`, holding references and hashes rather than text.

| Component kind | Availability stage | Pre-retrieval | Post-retrieval |
|---|---|---|---|
| `bot_instruction`, `bot_configuration` | `configuration_snapshot` (may postdate the request) | yes | yes |
| `earlier_message` (`transmitted_to_provider = unknown`) | `request_arrival` | yes | yes |
| `input_widget_definition`, `attachment_metadata` | `request_arrival` | yes | yes |
| `target_user_message` | `request_arrival` | yes | yes |
| `target_rag_chunk` | `retrieval_order_unknown` | no | yes |
| `earlier_rag_chunk` | `retrieval_order_unknown` | no | no |

The answer, its model label, tokens and cost are in `eval.record_reference`, outside every view.

## Annotation

1. `import-annotations` loads a completed sheet; each row is validated against the rubric, and history is kept (append-only).
2. Double-annotated records produce agreement in the quality report: linear weighted kappa for complexity, percent agreement elsewhere. Thresholds are unset, so they are report-only.
3. `plan-swaps` lists records whose reviewed intent left their cell, with a reserve for each. At most three rounds.
4. `validated` needs every check to pass, including human labels. `freeze` then makes the records, components and labels immutable. Nobody but reviewers completes review.

## Weights

`population_weight = N_cell / n_cell` over eligible requests (not distinct texts) per primary intent × cohort cell, using rule intents, so weights are provisional until review. Report balanced and weighted views apart.

## Running a routing experiment later

`exp` is empty and ready. Files in `runs/` stay the record (ADR-0022); these tables index imported summaries.

1. Read inputs from one profile, joined on the record:
   `eval.dataset_record` → `eval.routing_input_pre_retrieval_v1`.
2. For each call, write `exp.attempt` (ADR-0013), with tokens, cost, price-table version, count fidelity, and latency with its `measured` or `unmeasured` state.
3. Write outcomes to `exp.result` and quality to `exp.judgement`, keeping the three ADR-0006 signals apart.

Routers, caches and judges are not part of this work.

## Querying

See [example_queries.sql](example_queries.sql).

```bash
docker compose --profile db exec postgres psql -U metis -d metis
```
