# Routing dev slice v1 (`router-dev-slice-v1`)

Status: **built by the owner on Windows from the commands below; awaiting review** (R2 of the decision router, [ADR-XXXX (system-one-decision-router)](../adr/draft-system-one-decision-router.md) point 10). Config: [`config/evaluation/router_dev_slice_v1.toml`](../../config/evaluation/router_dev_slice_v1.toml). Code: `data_access/full`, `evaluation/router_slice`, `wiring/router_slice.py`, `scripts/build_router_dev_slice.py`. Traces: FR-DATA-02/04/06, FR-EVAL-04/06/09, QA-PRIV, QA-REPRO; A-91.

## 1. What it is, and what it is not

150 real records of the full dataset (`poriniki/metis` at revision `30f578f2…`), seeded and stratified, for **developing** the decision router: latency and memory benchmarks on real Persian state lengths, gate and path statistics, shadow comparisons of rules, THX-01 and Mizan, cost baselines, and human tier labels (L3). It is split by session into `tune` (70%) and `check` (30%); thresholds are tuned on `tune` and frozen before `check`. **golden-v2 stays the held-out test**: no golden-v1 or golden-v2 record, session or duplicate is in the slice.

Not for: training anything; tuning on golden-v2; reading `chat_bot.provider_model` as the correct route (it is a bot setting); treating the logged answer as ground truth; measuring the answering models' latency; sending text to a hosted backend (owner decision 2026-11-02: no dataset text goes to Metis or TypeSafe).

## 2. The unit: one record

One target USER message under the **golden-v1 eligibility rules** (ADR-0028), computed by the same code that built `eval.request` (`analysis.request_features.session_requests`): a clean pair (the next conversational message is the AI answer; no consecutive USER), non-empty target and answer, answer `finish_reason = STOP`, non-null timestamps; messages ordered by timestamp (nulls last) then source order.

| Field | Source | Visible to routing |
|---|---|---|
| `message` | the target's text | yes |
| `history_json` | earlier USER and AI messages of the session, oldest first, at most 20 kept (`history_truncated`) | yes |
| `instructions` / `instructions_state` | `chat_bot.instructions`: absent if blank; unknown if null or the workflow placeholder (those bots are excluded anyway); a **configuration snapshot** that may postdate the request | yes |
| `retrieved_json` | the **answer's** retrieved chunks in file order (`derived/chat_message_rag_chunks`), `retrieval_order_unknown` | only in the `post_retrieval` profile |
| `attachment_types_json` | content types of the target's attachments; never the payload | yes (modality only) |
| `previous_ai_input_state` | whether the preceding AI message showed an input widget | as structured-input presence only |
| reference side | the logged answer, `provider_name`, `provider_model` with its mapping through `label-mapping-full-v1.toml`, recorded billing sums (input, output, cached input tokens, call count, total cost, per-call fee), finish reason | **never** |

`evaluation.router_slice.records.to_request(record, profile=...)` maps a record onto the `Request` contract: `pre_retrieval` (retrieved context unknown) or `post_retrieval` (the answer's chunks present).

## 3. Exclusions and caps

Excluded: workflow bots (`provider_name = workflow` or model label `workflow`/`default`), bots with the platform-default placeholder instructions, sessions of the `workflow_unknown_config` class, every golden-v1 and golden-v2 record and its whole session, and any target in an exact, near or cross-bot duplicate group of a golden record. Hard caps: one record per session, at most 10 per bot, one per duplicate group (golden-v1's per-bot exact and near families, plus a cross-bot group of the Persian-folded text from `evaluation.grouping`). Counts by reason are in `composition.md`.

**golden-v1 reserves (Q-58, risk accepted by the owner on 2026-11-02).** The 150 golden-v1 reserves are not in the ID-only exports, so the slice cannot exclude them. If a reserve is later swapped into golden-v1, it (or its session) may already be in the slice. After any golden-v1 swap round, run this check (PostgreSQL running):

```powershell
.venv\Scripts\python scripts\build_eval_dataset.py export            # rewrites golden_v1_shareable.jsonl
.venv\Scripts\python scripts\build_router_dev_slice.py verify         # golden audit: 0 and 0, then PASS
```

The audit reports `golden_records_in_slice` and `slice_records_from_golden_sessions`; either above 0 is a FAIL. Then rebuild the slice (`build`, `verify`, `report`; it excludes the new golden record and its session) and record the rebuild in `progress.md`.

## 4. Strata (cohort targets, soft quotas, seeded fill)

Targets in the config are **soft** floors (the cohort targets also have a hard ceiling, below): each step takes the next candidate of the group that most reduces the remaining deficits, ties by a seeded hash; once targets are met the rest is a seeded random draw. Shortfalls are reported with a reason, never filled by relaxing an exclusion.

| Dimension | Target |
|---|---|
| Language group (golden-v1's groups) | Persian 62%, English 8%, mixed 6%, other Arabic-script 5% |
| Position | first turn 35%, follow-up 65% |
| Bot configuration | instructions + RAG 40%, instructions only 40%, blank 12%, RAG only 4% |
| Cohort (records; hard ceiling = target + 2) | `Remaining accounts` 30, `User A` 31, `User B` 30, `User C` 22, `User D` 21, `User E` 16 |
| Minimum counts | short follow-up (≤ 15 characters) 10, short undetermined language 8, greeting 8, coding intent 10, long message (≥ 400 characters) 8, attachments 4, high input (> 8,000 billed input tokens) 8, RAG on the answer 30 |

**Cohort targets (A-101, owner 2026-11-02).** The cohort targets are golden-v1's allocation ([session_config_report.md §8](../full_eda/session_config_report.md): 60 of 300 reserved for the 127 remaining accounts, the rest a floor plus the square root of traffic), halved to 150 (`[cohorts] targets`). They sum to the slice size. Each is a soft floor and a **hard ceiling** at target + `tolerance` (2). The `Remaining accounts` share ceiling of 30% (A-99, 45 records) stays as an upper bound; the lower ceiling wins, here 32. A cohort with at most two eligible bots has no per-bot cap (golden-v1's rule), since its target could not otherwise be met; `composition.md` says which.

Why: the first build (R2) had `Remaining accounts` at 67 of 150 (45%). With only the 30% ceiling, the second build gave the freed places to `User A` and left `User C` and `User D` at 8 each and `User E` at 2. Their traffic weights of 2.4–3.4 rested on too few records to tune on, and `User C` carries the long-context traffic the context-length criterion needs.

**Ceilings** are hard, like caps: once a stratum value reaches its ceiling, the rest of its candidates are skipped (counted as `ceiling` in `composition.md`).

**Traffic weights (A-100).** The slice is balanced on purpose, so a plain mean describes the slice, not the traffic. Every record carries `traffic_weight = cohort traffic share / cohort slice share` (in the local record file and in `ids.csv`; `cohort_traffic_share` in the record file). The traffic is the eligible targets the slice is drawn from (`[weights] traffic_basis`; `user_messages` is the alternative). A traffic-weighted metric is Σ w·m / Σ w; R8 reports it next to the balanced one. The weights average 1 over the slice when every cohort has a record, and the table in `composition.md` gives each cohort's traffic and slice shares. With 150 records, a cohort with a large weight rests on few records, so its weighted figure is noisy (A-91).

## 5. How it is read (memory-light)

Every Parquet file is a single row group, so each step reads **one file at a time** with only the columns it needs:

1. **Pass 1, structure:** `message_id, session_id, type, timestamp, finish_reason`, plus text length and attachment count computed in Arrow (`utf8_length`, `count_substring`); no text is kept. Sessions, bots (instructions only to classify them), RAG and chunk counts (IDs only), billing input tokens. → eligibility, exclusions, cohorts, and a seeded **pool of 1,500** candidates (one per session; rare flags oversampled three times). The pool is **drawn per cohort** (A-101): 1,500 split in proportion to the cohort targets (10 × target), no cohort above its eligible sessions, any spare going to the others in proportion; each cohort is its own seeded draw under the other pool targets scaled to its share. Each cohort gets at least `pool_min_multiple` (5) × its target, or every eligible session if fewer; `composition.md` lists planned, drawn and minimum per cohort and flags any cohort below its minimum. `plan` prints the same allocation without reading text.
2. **Pass 2, targeted:** full rows of the pool's sessions and the golden targets only (`is_in` on `session_id`), chunks of the pool's messages (text kept only for the pool's answers), billing of the pool's answers. → golden feature rows, duplicate groups, the final draw of 150, records.

`plan` reads no text at all. Peak memory and duration are printed and stored in the manifest (a synthetic run at the real message count peaked at about 680 MB in 8 s on Linux; real text adds a transient per-file buffer).

## 6. Outputs

| Location | Contents | Committed? |
|---|---|---|
| `data/derived/routing/dev_slice_v1/records.parquet` | full records with text (local use only) | no (git-ignored) |
| `data/derived/routing/dev_slice_v1/manifest.json` | revision, seed, config hash, counts, thresholds, duration, peak memory, platform | no |
| `reports/routing/dev_slice_v1/ids.csv` | `rs1-<message_id>`, split, strata codes, cohort pseudonym, `traffic_weight`; no text, no hashes of text | yes |
| `reports/routing/dev_slice_v1/composition.md` | achieved vs floors and ceilings, the candidate pool by cohort, availability, shortfalls, exclusions by reason (caps and ceilings), traffic weights by cohort, splits | yes |
| `reports/routing/dev_slice_v1/fingerprint.json` | config hash, source pins hash, record count, splits, hash of the ID list: verifies an identical build | yes |
| `reports/routing/dev_slice_v1/review_template.csv` | the review assignment with IDs only and empty label columns | yes |
| `runs/routing/dev_slice_v1/review_LOCAL_ONLY.csv` | the review sheet **with text** (UTF-8 with BOM for Excel) | no (git-ignored) |
| `reports/routing/dev_slice_v1/labels_l3.csv`, `labels_l3_agreement.json` | imported labels (ID, reviewer, two labels) and agreement | yes, after import |

The licence (education only, no redistribution) is why text never leaves `data/derived/` and `runs/`.

## 7. Human tier labels (L3)

Two Persian-capable reviewers (`R1`, `R2`); every record once, round-robin in seeded order, and at least 20% (30 records) by both. For each row the reviewer fills:

- `tier_needed`: `0` (a small, fast model is enough), `1` (needs the stronger tier), or `unsure`;
- `small_model_ok`: `yes`, `no` or `unsure` — "would a small model's answer be acceptable here?".

Judge from the message, the previous turns and the bot's role; the logged answer is deliberately not shown. Do not add notes with message text to the file you send back; the importer keeps only the ID, reviewer and the two labels, and reports percent agreement and Cohen's kappa on the double-annotated records. Labels are proposals for review, never ground truth.

## 8. Rebuild and verify (Windows, PowerShell)

See [router_quickstart.md §2–§3](../guides/router_quickstart.md) for the install and the dataset path. From the repository root:

```powershell
.venv\Scripts\python scripts\build_router_dev_slice.py plan
.venv\Scripts\python scripts\build_router_dev_slice.py build
.venv\Scripts\python scripts\build_router_dev_slice.py verify
.venv\Scripts\python scripts\build_router_dev_slice.py report
.venv\Scripts\python scripts\build_router_dev_slice.py import-labels <path\to\completed.csv>
```

`build` refuses a dataset whose revision or any file's sha256 differs from `config/evaluation/source_v1.toml` (an explicit `--allow-source-mismatch` builds anyway and records it). `verify` prints PASS when the config is unchanged since the committed fingerprint, the dataset is the pinned one, and the local build's IDs, strata and splits match the committed `fingerprint.json` and `ids.csv`. `report` refuses if the config changed after the build.
