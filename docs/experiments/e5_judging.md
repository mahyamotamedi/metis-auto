# E5: quality judging plumbing (judge pluggable; fake judge only)

Status: **provisional** (Stage E5, 2026-10-30). Code: `src/metis_auto/evaluation/judging/`. Spec: [evaluation framework §0.4, §0.6, §4, §6](evaluation_framework.md). **No judge model is chosen, no live call is made, no human ratings exist, and every gate value is unset: all quality scores are `unvalidated`.** The tests use a deterministic fake judge that decides by answer length; they check mechanics and hand-computed statistics, and say nothing about the quality of any judge or about Persian ability.

## 1. What exists

| Piece | Behavior |
|---|---|
| Pairwise judging | Every pair is judged twice, candidate first and reference first. Per-ordering verdicts (`first`, `second`, `tie`) map back to `candidate`, `reference`, `tie`; the pair score is their mean (win 1, tie 0.5, loss 0) and `swap_consistent` says whether both orderings agreed. A pairwise score is quality **relative to the reference** (the reference is 0.5 against itself); it is not an absolute rating. |
| Exclusions (stated) | Attachment turns are judged only if the judge sees images and the candidate is in the configured vision set (`vision_candidates`; unset = no model assumed to see images). Missing answers are `not_evaluated`. The E4 run plan has the same rule for candidate calls (`partition_image_calls`). Counts by reason are reported. |
| RAG | The judge's request view carries the logged retrieved context, so grounding is judged against what the answering model was given. |
| Judge cost | `JudgeRun.cost_usd_total` with `cost_kind = "evaluation"`: never added to request cost. |
| Calibration export | `export_calibration`: IDs, language and answer lengths only (no text), a Persian share and size from config, seeded deterministic selection. A Persian shortfall is reported (`persian_unmet`) and never filled with other languages. `to_csv` writes the rating sheet. **The sheet holds item IDs: keep it out of git.** |
| Ratings import | `read_ratings`: CSV text with `item_id, rater_id, preference`; several raters give a consensus only by strict majority. Errors name the row, never the content. |
| Agreement | Accuracy or Cohen's kappa, chosen in config (no default), judge pair preference versus human consensus, with a session-cluster bootstrap interval when a bootstrap setting is given. |
| Diagnostics | First-position pick rate (about 0.5 for an unbiased judge once orderings are swapped), swap consistency, and a verbosity-bias estimate (the judge's longer-wins share minus the humans'). |
| Persian gate | A language slice is `validated` only if `agreement_statistic`, `min_agreement` and `min_items` are all configured, the slice has at least `min_items` rated items, and agreement (the interval's lower bound if there is one, else the point) reaches `min_agreement`. Otherwise `unvalidated` with the reason. `gated_tables` sets each E1 table's `quality_validated` per language; `all` is validated only if every language present is. E1's non-inferiority and the oracle then refuse unvalidated quality (`unvalidated_quality`). |
| Instruction-language comparison | One judge per instruction language over the same pairs; per (instruction language × answer language) cell: n, agreement, swap consistency, position bias, verbosity bias. No winner is selected and there is no ranking attribute: the choice is a recorded config decision made after reading the cells. |
| Re-simulation | A design stub: user-simulator interface, a turn loop, count-only traces, `teacher_forcing_gap`. **Not a working Persian simulator.** Teacher-forced next-turn replay remains the default. |

## 2. Config fields and units (all unset by default)

```toml
[calibration]
size = <items>             persian_share = <fraction 0..1>      seed = "<string>"

[gate]
agreement_statistic = "accuracy" | "cohen_kappa"
min_agreement       = <-1..1>    # compared with the statistic; the lower CI bound if an interval exists
min_items           = <rated items per language slice>

[resimulation]
max_sessions = <n>         max_turns = <n>
```

Other arguments (supplied by the caller, no defaults): `vision_candidates` (set of model IDs), the bootstrap setting (`n_boot`, `seed`, `level`), and the minimum n for cell labels.

## 3. What is still open

- **The judge model**, its Persian ability, and how a real judge call is built (prompt, parsing, cost) are not decided; the pairwise protocol lives in `evaluation` and moving it into `ports` is a later decision. The existing pointwise `ports.Judge` is unchanged.
- **Human ratings** do not exist: no calibration set has been exported from real data, and agreement has been computed only on synthetic labels.
- **Gate values** (statistic, threshold, minimum items, calibration size and Persian share) are decisions for the owner. With them unset, every language slice, including Persian, is `unvalidated` and may not feed non-inferiority claims, oracle labels or the cheapest-acceptable decision.
- **Persian-versus-English instruction results** do not exist; the comparison has only been run on synthetic pairs and says nothing about which language is better.
- Time to first token and effort support in the live adapter (E4 notes) are untouched.
