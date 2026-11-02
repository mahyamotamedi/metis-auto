# golden-v2: the 300-request dataset without attachment records

Status: **`annotated_provisional`**. Rule labels only; human review is pending. Decision: [ADR-0029](../adr/0029-evaluation-dataset-golden-v2.md). It is golden-v1 with the 23 records that carry an attachment replaced by text-only records from the same cell. Everything in [golden_v1.md](golden_v1.md) applies, including the licence: text stays in your local database and in git-ignored folders; only IDs and labels move through git.

**Does not cover attachment-dependent requests.** The attachments are images, a text model cannot see them, and a request about an image has no fair text-only reference. For those requests use golden-v1. v2 therefore drops the golden-v1 coverage minimum `attachment_dependent` (it cannot be met), and its population and weights are over text-only requests.

## How it is built

`golden-v1` minus its attachment records, each replaced inside its own primary-intent × cohort cell: first by the next unused golden-v1 reserve (reserve order), then, if the cell has none usable, by the next candidate of the pool in seeded order. Same seed, quotas, caps and checks. It is built from the stored golden-v1 selection and refuses unless that is the pinned one (`[derive] base_fingerprint`). Result: 277 records identical to golden-v1, 23 replaced (16 from reserves, 7 from the pool), 133 reserves left.

| | golden-v1 | golden-v2 |
|---|---|---|
| Config | `config/evaluation/golden_v1.toml` | `config/evaluation/golden_v2.toml` |
| Record IDs | `gv1-<message id>` | `gv2-<message id>` |
| Fingerprint | `reports/evaluation/golden_v1/fingerprint.json` | `reports/evaluation/golden_v2/fingerprint.json` |
| Records with attachments | 23 | 0 |
| Margins | all exact | within 6 records of the quota; each documented (V-08) |

The mapping `reports/evaluation/golden_v2/golden_v1_to_golden_v2_mapping.jsonl` (IDs only) has one row per v1 record (`same` or `removed`) and per replacement.

## Media caveat

Records whose rule intent is `media_generation` (16) carry `stratum.caveats = ["text_model_cannot_fulfil_media"]`: a text model cannot produce the requested media. They are still answered; report them separately from the rest. The caveat follows the rule intent, which is a proposal, so a reviewed intent may differ.

## Build and check (after golden-v1 is built and verified)

```bash
python scripts/build_eval_dataset.py --config config/evaluation/golden_v2.toml all
```
```bash
python scripts/build_eval_dataset.py --config config/evaluation/golden_v2.toml verify
```
```bash
python scripts/validate_eval_dataset.py --config config/evaluation/golden_v2.toml --rebuild
```

`fingerprint` rewrites the team's expected result, so only the lead runs it, on purpose, after a deliberate config change. To reuse reviewed golden-v1 labels, after `git pull`: `python scripts/build_eval_dataset.py --config config/evaluation/golden_v2.toml carry-labels reports/evaluation/golden_v1/reviewed_labels.jsonl`. Labels of the 23 removed records are dropped and counted; the 23 replacements need review.

## Limits

Same as golden-v1: labels are not ground truth, this is a balanced challenge set, and no aggregate on it equals production performance. Replacements were chosen by cell only, so the complexity proxy and length margins moved (at most 6 records); [validation](../../reports/evaluation/golden_v2/validation.md) and the [quality report](../../reports/evaluation/golden_v2/quality_report.md) list every difference.
