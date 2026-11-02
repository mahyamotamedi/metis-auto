# Phase 0 Foundation Implementation Plan

> **SUPERSEDED** by [`2026-11-01-final-plan.md`](2026-11-01-final-plan.md) (see its "Superseded files" section). Kept for history; do not follow.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the three versions of every later step one shared, content-free replay table over the full dataset, the five free checks answered with written results, and the evaluation admin pieces (period split, PPI correction, labelling gate) that need no paid call.

**Architecture:** Follow the existing layers ([ADR-0009](../../adr/0009-repository-structure-and-dependency-rules.md)). A full-dataset loader in `data_access` yields the existing generic `Session` plus a new optional `LoggedUsage` (billed tokens and cost split). Pure functions in `evaluation/replay_table` turn replay cases into content-free rows. Each free check is one pure module in `evaluation/free_checks` that a script runs and writes to `reports/free_checks/`. Nothing here changes serving, routing or caching, and nothing makes a live call.

**Tech Stack:** Python 3.13 in `.venv`, pydantic v2 contracts, pytest, ruff. Standard library only. No new dependency (no Parquet, DuckDB, MLflow or `ppi_py`).

**Spec:** [`Metis-Auto Master Plan.pdf`](Metis-Auto%20Master%20Plan.pdf) (Nov 1, 2026, @Mahya): Part 3 "Foundation", Part 4 "Phase 0" and "Phase S" rows A, B, C. Text extraction used while planning: scratchpad `pdf/master_plan.txt`. Repo rules: [`CLAUDE.md`](../../../CLAUDE.md), [`docs/project/progress.md`](../../project/progress.md).

## Global Constraints

- Work only in `src/metis_auto/`, `tests/`, `scripts/`, `config/`, `docs/`, `reports/`. Layer imports are enforced by `tests/architecture/test_import_rules.py`: `domain` imports only `contracts`; `data_access` imports only `ports` and `contracts`; `evaluation` never imports `wiring`.
- **Never run `git commit`, `git push`, or anything that rewrites history** (`CLAUDE.md` § Git). Every "checkpoint" step below lists changed files and a suggested message for the owner to commit.
- `data/sample_data/raw/` is read-only. Raw message content, instructions, retrieved context and answers never go into docs, commits, logs, fixtures or exported tables. Tables and reports hold IDs, keyed fingerprints and derived numbers only. Synthetic fixtures carry the `[SYNTHETIC]` marker.
- No live call, no key use, no `.env` access. Tests run offline.
- Category names stay opaque strata (A-02). Sample-EDA numbers and the PDF's EDA numbers are provisional until the full-data checks in this plan reproduce them (ADR-0008).
- After any contract change run `python tests/architecture/contracts_docgen.py` and update `docs/architecture/module_reference.md` rows (checked by `tests/architecture/test_module_reference.py`).
- Run tests with `.venv/bin/python -m pytest` (on Windows `.venv\Scripts\python.exe -m pytest`). 33 pre-existing Windows failures and 3 collection errors are known (`progress.md`, E0–E6); do not count them as regressions, compare against a baseline run taken in Task 1.
- Every threshold is an argument or comes from config. Nothing is invented: an unset value gives `not_evaluated` with a reason (same convention as E1/E2).
- Master Plan numbers used as defaults only where it states them: tune period March–July, report period August–October; Cohen's κ target 0.6; PPI. These go in `config/`, not code.

## Review Focus

Inputs the spec implies but its tasks would not otherwise exercise, most likely first:

1. A bot or session with timestamps missing or in a different timezone than assumed (A-06): rows must land in `unknown`, never silently in tune or report.
2. A request billed with `null` token counts or a cost of zero for a non-LLM workflow bot: it must never count toward a hit rate or saving; "unknown" is not zero.
3. Persian text with ZWNJ, Arabic-form letters or digit variants: query fingerprints and chunk fingerprints must be stable under the E0 `persian_fold_v1` treatment, and lengths must be counted in tokens, not characters.
4. A session where the same chunk appears twice in one message and again in later turns: dedup counts must not double count.
5. A bot with one request: `k` fitting, history-policy classification and per-bot checks must report `insufficient`, not a number.

Each line has its pinning test in the task named in brackets: 1 → Task 3, 2 → Task 5, 3 → Task 5, 4 → Task 8, 5 → Task 6.

## File Structure

| Path | Responsibility |
|---|---|
| `docs/project/full_data_schema.md` (new) | What the full dataset is and where it lives; the schema every loader task below is written against (Task 1) |
| `config/evaluation/phase0.toml` (new) | Period boundaries, minimum n, κ target, workflow-bot rule (Task 3) |
| `src/metis_auto/evaluation/replay_table/periods.py` (new) | `assign_period` (Task 3) |
| `src/metis_auto/contracts/replay.py` (modify) | `LoggedUsage` and its fields on `LoggedMessage` and `Reference` (Task 4) |
| `src/metis_auto/data_access/full/` (new) | `FullDataSource` (Task 4) |
| `src/metis_auto/evaluation/replay_table/rows.py`, `io.py` (new) | `ReplayRow`, `build_rows`, JSON Lines read/write (Task 5) |
| `src/metis_auto/evaluation/replay_table/history_fit.py` (new) | per-bot history length `k` fitted to billed input (Task 6) |
| `src/metis_auto/evaluation/free_checks/*.py` (new) | one module per free check (Tasks 7–11) |
| `scripts/replay_table.py`, `scripts/free_checks.py` (new) | thin entry points writing content-free output under `data/derived/` and `reports/free_checks/` |
| `src/metis_auto/evaluation/comparison/ppi.py` (new) | prediction-powered mean estimate (Task 12) |
| `docs/experiments/labelling_protocol.md` (new) | rubric, annotator and κ rules (Task 13) |
| `docs/project/metis_questions.md` (new) | questions to Metis and licence check, with answers recorded (Task 14) |

## Blocking inputs (not code)

These need the owner or the data owner. The plan says where each one gates a task.

- **B-1:** the full dataset and Mahya's full-EDA work. No `full-eda` branch and no `requests.parquet` exist in this checkout or on `origin` (branches seen: `eda-mahya`, `eda-saba`, `eda_parham`, `shakib`, `sys-des`, `main`, none dated after 2026-10-19; `experiments/full_eda/README.md` says "not started"). Gates Tasks 4–11.
- **B-2:** the Metis answers (Task 14). Gate the interpretation of Tasks 7–10, not their code.
- **B-3:** the budget decision (cap raise, shared spend record). Not needed in Phase 0; recorded in Task 14 so it is not forgotten.

---

### Task 1: Locate the full dataset and fix its schema (gate B-1)

**Files:**
- Create: `docs/project/full_data_schema.md`
- Modify: `docs/project/assumptions_and_questions.md` (new rows only)

**Interfaces:**
- Produces: the schema note. Tasks 4–11 read it and nothing else for field names.

- [ ] **Step 1: Take a test baseline.** Run `.venv/bin/python -m pytest -q -x --co -q | tail -3` then the full suite once; save the failing test IDs to the scratchpad. Expected: only the known Windows failures.
- [ ] **Step 2: Ask Mahya for the exact branch, commit and data path.** Record them in `full_data_schema.md` under "Provenance" (branch, commit hash, date, who). If the work lives in another repository or only on a machine, say so; do not copy raw data into this repo (`data/full_data/` is git-ignored, Q-18).
- [ ] **Step 3: Write `full_data_schema.md`** answering, from the dataset and not from the PDF: file format and path; one line per field name with type and null rate; which field is the bot, the user, the session, the turn; whether billed input, output, cached and reasoning tokens exist per request; whether the cost split (instruction, history, chunks, message, retrieval fee) is logged or reconstructed (the PDF says the input split is "a regression-based reconstruction"); the currency; whether chunk IDs exist; whether a retrieval query is logged separately from the user message; timestamp timezone; how workflow (non-LLM) bots are identified. Mark each answer `observed` or `assumed`.
- [ ] **Step 4: Re-check four Master Plan claims on the real data** and write the counts in the note with the date: 80,179 sessions; 5 users = 97% of requests; 30% non-LLM workflow requests; 61% of chunk rows already sent earlier in the session. If any is off by more than the note's stated tolerance, say so in the note; do not edit the PDF numbers elsewhere.
- [ ] **Step 5: Add register rows** (next free `A-` and `Q-` numbers) for every `assumed` item and each question that stays open.
- [ ] **Step 6: Checkpoint.** List changed files; suggest commit message `docs: record the full-dataset schema and provenance`.

Done when: the note answers every item in Step 3 as `observed` or names who must answer. If the dataset cannot be obtained, stop the plan here and report.

---

### Task 2: Phase 0 configuration

**Files:**
- Create: `config/evaluation/phase0.toml`, `tests/unit/evaluation/test_phase0_config.py`
- Modify: `src/metis_auto/settings/` only if the settings loader must know the new file (read `docs/architecture/configuration.md` first; prefer a plain `tomllib` read in the script if the loader does not fit)

**Interfaces:**
- Produces: `config/evaluation/phase0.toml` with tables `[periods]` (`tune_from`, `tune_until`, `report_from`, `report_until`, ISO dates, naive), `[thresholds]` (`min_n_per_bot`, `kappa_target`), `[workflow_bots]` (`rule`, `bot_refs`).

- [ ] **Step 1: Write the failing test** `test_phase0_config_has_no_unset_required_values` loading the file with `tomllib` and asserting each key above exists and that `tune_until < report_from`.
- [ ] **Step 2: Run it.** `pytest tests/unit/evaluation/test_phase0_config.py -v`. Expected: FAIL (file missing).
- [ ] **Step 3: Create the file.** Values: dates `2026-03-01`, `2026-07-31`, `2026-08-01`, `2026-10-31` (Master Plan Part 3, assumed inclusive; note the year in a comment); `kappa_target = 0.6`; `min_n_per_bot` left as a TOML comment `# unset: owner decides` and read as `None`; the test accepts `None` for `min_n_per_bot` only. `rule` is `"from_schema_note"` until Task 1 names how workflow bots are found.
- [ ] **Step 4: Run test.** Expected: PASS.
- [ ] **Step 5: Checkpoint.** Suggested message `config: add Phase 0 evaluation settings`.

---

### Task 3: Period assignment (tune / report / unknown)

**Files:**
- Create: `src/metis_auto/evaluation/replay_table/__init__.py`, `src/metis_auto/evaluation/replay_table/periods.py`
- Test: `tests/unit/evaluation/test_replay_table_periods.py`

**Interfaces:**
- Produces: `assign_period(ts: datetime | None, *, tune_from: datetime, tune_until: datetime, report_from: datetime, report_until: datetime) -> str`, returning one of `"tune"`, `"report"`, `"gap"` (between the two ranges), `"outside"` (before or after both) or `"unknown"` (`ts is None`).

- [ ] **Step 1: Write failing tests**: `test_none_is_unknown`; `test_boundaries_inclusive` (`tune_until` itself → `tune`, `report_from` itself → `report`); `test_between_is_gap`; `test_before_and_after_are_outside`; `test_timezone_aware_timestamp_is_rejected` (raise `ValueError`, because logged times are naive and the zone is unknown, A-06). Use `[SYNTHETIC]`-free pure datetimes.
- [ ] **Step 2: Run to see them fail.** Expected: `ModuleNotFoundError`.
- [ ] **Step 3: Implement `assign_period`** with the signature above; add a module docstring stating responsibility, purity and `Status: provisional (Phase 0)`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Add the module row** to `docs/architecture/module_reference.md` and run `pytest tests/architecture -q`. Expected: PASS.
- [ ] **Step 6: Checkpoint.** Suggested message `feat(eval): assign logged timestamps to tune/report periods`.

---

### Task 4: Billed usage on logged messages, and the full-dataset loader

Depends on Task 1. Field names below are placeholders for the schema note; rename to match it before writing tests.

**Files:**
- Modify: `src/metis_auto/contracts/replay.py`, `src/metis_auto/contracts/__init__.py`, `src/metis_auto/data_access/__init__.py` (docstring), `docs/architecture/contracts.md` §4, `docs/architecture/contracts_reference.md` (regenerated)
- Create: `src/metis_auto/data_access/full/__init__.py`, `src/metis_auto/data_access/full/loader.py`, `tests/fixtures/synthetic/full_dataset_example.*` (format from Task 1), `tests/unit/data_access/test_data_access_full.py`

**Interfaces:**
- Consumes: `OpaqueRef = Callable[[str, str], str]` from `data_access/sample/loader.py:55`; `Session`, `LoggedMessage` (`contracts/replay.py`).
- Produces:
  - `class LoggedUsage(ContractModel)` with optional `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_tokens` (`int | None`), `cost_by_block: dict[str, Decimal] | None` (keys from the schema note), `retrieval_fee_count: int | None`, `currency: str | None`. Every field privacy class `OPERATIONAL`.
  - `LoggedMessage.logged_usage: LoggedUsage | None = None` and `LoggedMessage.bot_ref: Identifier | None = None` and `LoggedMessage.workflow: bool | None = None` (None = unknown). `Reference` gains `logged_usage` copied by `data_access/replay_cases/builder.py:_reference`.
  - `class FullDataSource` in `data_access/full/loader.py` implementing `ports.DataSource`: `__init__(self, path: Path, opaque_ref: OpaqueRef, *, missing_key: MissingKey = "absent")`, `dataset -> "full_v1"`, `sessions() -> Iterator[Session]`.

- [ ] **Step 1: Write failing contract tests** in `tests/unit/contracts/`: `test_logged_usage_defaults_are_none`; `test_logged_usage_rejects_negative_tokens`; and extend the existing privacy tests (`tests/unit/contracts`) so the content-free check lists `LoggedUsage` as having no `content` field.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Add the contract fields.** Bump the contract schema minor version as the Stage 5–Demo changes did (`Versions`); regenerate `contracts_reference.md`; update contracts.md §4 with one line that billing fields exist only on replay contracts.
- [ ] **Step 4: Write failing loader tests** against a **synthetic** fixture in the Task 1 format: `test_sessions_in_stable_order`; `test_bot_ref_and_session_ref_are_opaque_and_raw_ids_never_appear` (assert no raw ID substring in `model_dump_json()`); `test_missing_billing_is_none_not_zero`; `test_workflow_flag_follows_schema_rule`; `test_empty_strings_are_absent`; `test_unknown_role_raises`.
- [ ] **Step 5: Implement `FullDataSource`** reusing the sample loader's helpers where they apply (empty → absent, null → unknown `not_in_log`, `_ceilings` truncation flags). Read-only; never writes beside the source file.
- [ ] **Step 6: Run** `pytest tests/unit/contracts tests/unit/data_access tests/architecture -q`. Expected: PASS.
- [ ] **Step 7: Add module rows**, run `ruff check` and `ruff format`.
- [ ] **Step 8: Checkpoint.** Suggested message `feat(data): add LoggedUsage and the full-dataset loader`.

---

### Task 5: The replay table (content-free rows)

**Files:**
- Create: `src/metis_auto/evaluation/replay_table/rows.py`, `src/metis_auto/evaluation/replay_table/io.py`, `scripts/replay_table.py`
- Test: `tests/unit/evaluation/test_replay_table_rows.py`

**Interfaces:**
- Consumes: `ReplayCase` (`contracts/replay.py:153`); `build_all` (`data_access/replay_cases/builder.py:131`); `Fingerprinter` (`application/measurement`); `normalise` and the `persian_fold_v1` treatment (`domain/caching`, ADR-0025); `detect_language`, `length_bucket` (`domain/features`); `assign_period` (Task 3).
- Produces:
  - `@dataclass(frozen=True) class ReplayRow` with: `case_id`, `session_ref`, `bot_ref | None`, `turn_index`, `period`, `llm_request: bool | None` (None = unknown), `language`, `length_bucket`, `input_tokens | None`, `output_tokens | None`, `cached_input_tokens | None`, `cost_by_block | None`, `retrieval_fee_count | None`, `message_fp`, `query_fp | None`, `chunk_fps: tuple[str, ...]`, `answer_fp | None`, `pairing_flag`, `quality_flags`. No text field.
  - `build_rows(cases: Iterable[ReplayCase], *, fingerprinter: Fingerprinter, periods: PeriodBounds, language_config: LanguageConfig) -> list[ReplayRow]` (`PeriodBounds` is a frozen dataclass of the four boundaries from Task 3).
  - `write_rows(rows, path: Path) -> None` and `read_rows(path: Path) -> list[ReplayRow]` in `io.py`, JSON Lines, one row per line, `Decimal` as string.

- [ ] **Step 1: Write failing tests**, all on synthetic cases built with `tests/fixtures/synthetic`:
  - `test_row_has_no_content_field` (iterate `dataclasses.fields`; none named or typed as text) and `test_row_json_contains_no_message_text` (assert a distinctive `[SYNTHETIC]` string from the case is not in the serialised row).
  - `test_workflow_request_is_not_llm_request`: a case with `workflow=True` → `llm_request is False`; one with `workflow=None` → `None`. (Review Focus 2)
  - `test_missing_tokens_are_none_not_zero`.
  - `test_query_fp_stable_under_persian_folding`: two messages differing only by ZWNJ / Arabic-form «ي» vs «ی» / Arabic-Indic vs Persian digits give the same `query_fp`. (Review Focus 3)
  - `test_chunk_fps_same_text_same_fp_and_order_kept`.
  - `test_round_trip_write_read_rows`.
  - `test_period_unknown_when_no_timestamp`.
- [ ] **Step 2: Run to see failure.** Expected: `ImportError`.
- [ ] **Step 3: Implement** `PeriodBounds`, `ReplayRow`, `build_rows`, `write_rows`, `read_rows`. Fingerprint purposes: `"replay_message"`, `"replay_query"`, `"replay_chunk"`, `"replay_answer"` (add them to the Fingerprinter's allowed purposes the same way `dup_group` was added in E0; read `application/measurement` for the mechanism). `query_fp` uses the logged retrieval query if the schema note says one exists, else `None`.
- [ ] **Step 4: Write `scripts/replay_table.py`** (`--source`, `--out`, `--config config/evaluation/phase0.toml`): reads a `FullDataSource`, writes JSONL under `data/derived/replay/`, prints only counts: rows, by period, `llm_request` true/false/unknown, exclusions from `build_all`. Refuses an `--out` inside `data/sample_data/raw/`.
- [ ] **Step 5: Run** `pytest tests/unit/evaluation/test_replay_table_rows.py tests/architecture -q`. Expected: PASS.
- [ ] **Step 6: Checkpoint.** Suggested message `feat(eval): add the content-free replay table`.

Done when: running the script on the real data prints counts and the table covers every LLM request (Master Plan Phase S row A); the number of requests without billed tokens is printed, not hidden.

---

### Task 6: Fit the history length `k` per bot to billed input

**Files:**
- Create: `src/metis_auto/evaluation/replay_table/history_fit.py`
- Test: `tests/unit/evaluation/test_replay_table_history_fit.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class FitInput` with `case_id: str`, `bot_ref: str`, `fixed_tokens: int` (instructions + chunks + message counted with the model's own tokenizer), `history_turn_tokens: tuple[int, ...]` (most recent first), `billed_input_tokens: int`.
  - `fit_case_k(item: FitInput) -> tuple[int, int]` returning `(best_k, absolute_token_error)`; smallest `k` wins ties.
  - `@dataclass(frozen=True) class BotFit` with `bot_ref`, `n`, `k: int | None`, `median_abs_error`, `p95_abs_error`, `share_within_5_percent`, `status` (`"fitted"` or `"insufficient"`).
  - `fit_bots(items: Sequence[FitInput], *, min_n: int | None) -> list[BotFit]`: per bot, `k` is the value minimising the sum of absolute errors over its cases.

- [ ] **Step 1: Write failing tests**: `test_fit_case_k_exact_match` (fixed 100, history [50, 40, 30], billed 190 → `(2, 0)`); `test_fit_case_k_zero_history`; `test_fit_case_k_tie_picks_smaller_k`; `test_fit_bots_picks_constant_k_per_bot`; `test_bot_with_one_request_is_insufficient` and `test_min_n_none_gives_insufficient_with_reason` (Review Focus 5); `test_error_report_is_per_bot`.
- [ ] **Step 2: Run to see failure.** Expected: `ImportError`.
- [ ] **Step 3: Implement** with prefix sums over `history_turn_tokens`; choose `k` minimising `abs(fixed + prefix[k] − billed)`.
- [ ] **Step 4: Run tests.** Expected: PASS.
- [ ] **Step 5: Add a `--fit-history` option to `scripts/replay_table.py`** that builds `FitInput` from the full prompt component counts (reuse the E3 composition in `evaluation/inputs/composition.py`; read it first for the call to count components per model) and prints per-bot error rows. Test the option with a mocked counter in `test_replay_table_history_fit.py::test_script_wiring_prints_counts_only`.
- [ ] **Step 6: Checkpoint.** Suggested message `feat(eval): fit history length per bot to billed input tokens`.

Done when: token error per bot is reported for every bot with enough requests (Master Plan Phase S row A). Counts are local estimates, labelled by tokenizer fidelity, never billed tokens (CLAUDE.md token rule).

---

### Task 7: Free check 1 — is one 0.002 fee one retrieval lookup?

**Files:**
- Create: `src/metis_auto/evaluation/free_checks/__init__.py`, `.../fee_vs_lookup.py`
- Test: `tests/unit/evaluation/test_free_check_fee_vs_lookup.py`

**Interfaces:**
- Produces: `fee_vs_lookup(rows: Sequence[ReplayRow], *, fee_amount: Decimal) -> FeeLookupResult` with `n`, `n_with_fee_data`, `share_fee_count_equals_one`, `share_fee_count_equals_chunk_groups`, `distribution: dict[int, int]` (fee count → rows), `state` (`"measured"`, `"insufficient"`), `reason`. `fee_amount` is an argument (0.002 appears in the PDF; unverified).

- [ ] **Step 1: Write failing tests**: all rows have `retrieval_fee_count == 1` → share 1.0; mixed counts give the right distribution; rows with `None` fee data are excluded and counted separately, not treated as 0; workflow rows excluded.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Checkpoint.** Suggested message `feat(eval): free check, retrieval fee versus lookup`.

### Task 8: Free check 2 — does the logged retrieval query differ from the message?

**Files:** `.../free_checks/query_vs_message.py`, `tests/unit/evaluation/test_free_check_query_vs_message.py`

**Interfaces:** Produces `query_vs_message(rows) -> QueryResult` with `n_with_query`, `share_identical` (`query_fp == message_fp`), `share_different`, `by_bot: dict[str, float]`, `state`, `reason`. Rows with `query_fp is None` count as `no_logged_query`, never as identical.

- [ ] **Step 1: Write failing tests**: identical fp → identical; different → different; `None` excluded and counted; a bot where every query differs is listed in `by_bot` with share 1.0 (a hidden rewriter signal). Add **`test_same_chunk_twice_in_message_counts_once`** for Review Focus 4 on the shared `chunk_fps` helper `distinct_chunk_fps(row) -> tuple[str, ...]` (put it in `rows.py` and import here).
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Checkpoint.** Suggested message `feat(eval): free check, retrieval query versus message`.

### Task 9: Free check 3 — are a turn's chunks still in the next turn's prompt?

**Files:** `.../free_checks/chunks_carried.py`, `tests/unit/evaluation/test_free_check_chunks_carried.py`

**Interfaces:** Produces `chunks_carried(rows, tokens_per_chunk: Mapping[str, int]) -> CarriedResult`. For each pair of consecutive turns in one session, `explained_delta = billed_input[t+1] − billed_input[t]` is compared with two models: the new turn *with* turn t's chunks kept in history and *without* them. Result: `n_pairs`, `share_consistent_with_kept`, `share_consistent_with_dropped`, `share_ambiguous`, `state`, `reason`. A tolerance argument `token_tolerance: int` has no default.

- [ ] **Step 1: Write failing tests** with hand-built rows: a pair whose billed delta equals new message + answer tokens only → `dropped`; delta also includes the earlier chunk tokens → `kept`; delta fits neither → `ambiguous`; missing billed tokens → excluded; non-consecutive turns are not paired.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Checkpoint.** Suggested message `feat(eval): free check, chunks carried across turns`.

Note for the writer: this is the check that decides whether dropping repeated chunks is safe, so the report must state the tolerance used and that the result is an inference from token counts.

### Task 10: Free check 4 — which history policy does each bot use?

**Files:** `.../free_checks/history_policy.py`, `tests/unit/evaluation/test_free_check_history_policy.py`

**Interfaces:** Consumes `BotFit` and per-case best `k` (Task 6). Produces `classify_history_policy(per_case_k_by_bot: Mapping[str, Sequence[tuple[int, int]]], *, min_n: int | None) -> list[BotPolicy]`, where each tuple is `(turn_index, best_k)`. `BotPolicy.policy` is `"fixed_window"` (best `k` is constant once the turn index exceeds it), `"token_budget"` (best `k` shrinks as turns get longer; the fitted token total per prompt plateaus), `"mixed"`, or `"insufficient"`, plus `evidence` numbers. It never says `"summary"`: summaries cannot be told from token counts alone, so such bots are `"mixed"` with the residual error shown.

- [ ] **Step 1: Write failing tests**: constant `k=4` after turn 4 → `fixed_window`; plateauing token total → `token_budget`; a one-request bot → `insufficient`; `min_n=None` → `insufficient` with reason.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Checkpoint.** Suggested message `feat(eval): free check, history policy per bot`.

### Task 11: Free check 5 — Gemini thinking and cached tokens

**Files:** `.../free_checks/gemini_thinking.py`, `tests/unit/evaluation/test_free_check_gemini_thinking.py`

**Interfaces:** Produces `gemini_thinking(rows, answer_tokens: Mapping[str, int], *, model_label: str) -> ThinkingResult` where `answer_tokens` maps `case_id` to the answer's local token count. Result: `n`, `median_ratio` (billed output ÷ answer tokens), `p90_ratio`, `share_ratio_above(threshold)` with `threshold` an argument, `rows_with_cached_tokens_logged`, `rows_with_reasoning_tokens_logged`, `state`, `reason`. Only rows whose `model_label` matches are used.

- [ ] **Step 1: Write failing tests**: ratio 1.0 everywhere → median 1.0; ratio 5 → flagged above threshold 3; no cached token field anywhere → `rows_with_cached_tokens_logged == 0` and the reason says "possible logging gap" (not "no caching"); other models are ignored.
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Write `scripts/free_checks.py`** (`--table`, `--out reports/free_checks/`) that runs Tasks 7–11 and writes one content-free JSON per check plus `README.md` stating date, data version (Task 1 note), thresholds used and which results are `insufficient`. Test with `test_script_writes_one_json_per_check_and_no_text` on a synthetic table.
- [ ] **Step 6: Checkpoint.** Suggested message `feat(eval): run the five free checks and write their reports`.

Done when: each check has a written answer in `reports/free_checks/` (Master Plan Phase S row C), and Task 1's four re-checked claims plus these five results are summarised in `docs/project/progress.md` under a "Phase 0" heading.

---

### Task 12: Prediction-powered inference for the corrected judge mean

**Files:**
- Create: `src/metis_auto/evaluation/comparison/ppi.py`
- Test: `tests/unit/evaluation/test_evaluation_ppi.py`

**Interfaces:**
- Consumes: `cluster_bootstrap` pattern from `comparison/stats.py:41` (seeded, session-clustered) and `Estimate` from `comparison/types.py:83`.
- Produces: `ppi_mean(labelled_human: Sequence[float], labelled_judge: Sequence[float], unlabelled_judge: Sequence[float], *, level: float, bootstrap: int | None, seed: int | None) -> Estimate`. The point estimate is `mean(unlabelled_judge) + mean(human − judge on labelled)`. Interval by the normal approximation of the PPI variance (`var(unlabelled_judge)/N + var(human − judge)/n`) with a clearly named alternative if `bootstrap` is set. Unset `level` → `not_evaluated`.

- [ ] **Step 1: Write failing tests**: judge equals human on the labelled set → estimate equals `mean(unlabelled_judge)` with the narrow interval; judge biased by +0.1 on every labelled item → the estimate shifts down by 0.1; fewer than 2 labelled items → `not_evaluated` with a reason; hand-computed example with exact expected point and half-width (compute with plain arithmetic in the test, not with the code under test); `test_matches_reference_values_if_ppi_py_is_installed` (skipped if the package is absent, never added to the locks).
- [ ] **Step 2–4: Fail, implement, pass.**
- [ ] **Step 5: Checkpoint.** Suggested message `feat(eval): add the prediction-powered mean estimator`.

Decision recorded, not made here: the Master Plan names the `ppi_py` package; this plan implements the mean estimator in the standard library to avoid a lock change. If a regression or quantile PPI is later needed, reconsider in an ADR.

### Task 13: Labelling protocol and the κ gate

**Files:**
- Create: `docs/experiments/labelling_protocol.md`, `tests/unit/evaluation/test_labelling_gate_kappa.py`

**Interfaces:**
- Consumes: `agreement`, `evaluate_gate`, `read_ratings`, `export_calibration`, `CalibrationConfig`, `GateConfig` in `evaluation/judging/calibration.py` (read its signatures at lines 54–96 and 262–420 first).

- [ ] **Step 1: Write the failing test** `test_two_raters_below_target_kappa_fail_the_gate` and `test_two_raters_at_target_pass`, using the existing `agreement` / gate code with `kappa_target = 0.6` read from `config/evaluation/phase0.toml` and synthetic labels (a 20-item table where the two raters agree on 12 vs 15 items; compute the expected κ by hand in the test).
- [ ] **Step 2: Run.** If these pass without code changes, the existing E5 code already satisfies the gate; keep the tests as the pin. If they fail, fix `calibration.py` minimally and name the fix in the checkpoint.
- [ ] **Step 3: Write the protocol** (no content from the dataset): two native Persian speakers; the rubric (what "better" means, ties, refusing, language, formatting) as questions, left for Mahya and the annotators to fill in with the pilot; 8 Persian anchor examples are collected in the benchmark pilot (Phase 1 background task), not invented here; sheet columns exactly those `to_csv` emits; double-labelling share (60 of 250, from the PDF); what happens if κ < target (rubric revision, not discarding labels); licence precondition from Task 14.
- [ ] **Step 4: Checkpoint.** Suggested message `docs(eval): labelling protocol and kappa gate tests`.

### Task 14: Questions to Metis, licence check and the budget decision

**Files:**
- Create: `docs/project/metis_questions.md`
- Modify: `docs/project/assumptions_and_questions.md` (new rows)

- [ ] **Step 1: Copy the seven questions** from the Master Plan's "Questions for Metis" verbatim into the file, each with `status: open`, who asks, date asked, answer, date answered, and which task's interpretation it changes (Q1 → Tasks 7–8; Q2 → whether Phase 1 versions B and C are measured potential only; Q3 → Tasks 9–10; Q4 → Task 11; Q5 → the routing candidate pool and `config/reference/` price rows; Q6 → Task 13; Q7 → the paid-run budget).
- [ ] **Step 2: Add the licence check** as its own row: who confirms that samples may be sent to model APIs and shown to annotators. Until answered, `scripts/sampling_plan.py` keeps refusing sample-conversation runs (E4 guard); do not change that.
- [ ] **Step 3: Record the budget conflict** as a question for the owner: Master Plan about 100 USD over five 20 USD keys with caps raised to 18 USD; repo lifetime cap 10 USD under a 20 USD ceiling ([ADR-0018](../../adr/0018-live-calls-for-development-under-a-lifetime-budget.md), Q-29), ledger per machine (`adapters/system/ledger.py`). 5 × 18 = 90, below the plan's own 100 USD table. Any change needs an ADR-0018 amendment and a reviewed commit to `config/defaults.toml`; no code is changed in Phase 0.
- [ ] **Step 4: Record the Hugging Face token rotation** as an owner action (the PDF says a token appears in the EDA prompt); do not look for or copy it.
- [ ] **Step 5: Checkpoint.** Suggested message `docs: record Metis questions, the licence check and the budget question`.

---

### Task 15: Phase 0 exit check and status update

**Files:**
- Modify: `docs/project/progress.md` (new "Phase 0" section), `docs/README.md` (index), `CLAUDE.md` (one pointer line to the replay table and free checks)

- [ ] **Step 1: Run the whole suite** and compare with the Task 1 baseline. Expected: no new failures; new tests all pass; `ruff check` and `ruff format --check` clean on changed files.
- [ ] **Step 2: Run the two scripts end to end on a synthetic source.** Expected: the replay table and five JSON reports are written; grep the outputs for a `[SYNTHETIC]` message string. Expected: no matches.
- [ ] **Step 3: Write the 6-part stage report** in `progress.md` (changes, decisions, assumptions, questions, next stage, exit criteria) with this exit criterion, taken from the Master Plan: *the replay table works, the free checks are answered, and one evaluation command produces a result* — and state honestly what is not done: the "MLflow-ready result" waits on the tooling decision; the judge model, the human labels, the price rows for candidate models and the cap changes wait on B-2 and B-3.
- [ ] **Step 4: Stop for review.** List changed files and a suggested commit message; do not commit.

---

## Self-review

**Spec coverage** (Master Plan Part 3 Foundation and Part 4 Phase 0/S rows A–C):
- Merge `full-eda`: no such branch exists → Task 1 (gate B-1). Not silently skipped.
- Replay table with bot, session, turn, language, billed tokens, cost split, retrieval query, chunk IDs, logged answer → Tasks 4–5 (as fingerprints; answer text stays in the source, per `CLAUDE.md`).
- Leave workflow bots out of every saving and hit rate → Task 5 (`llm_request`), Review Focus 2.
- Time split Mar–Jul / Aug–Oct → Tasks 2–3.
- Rebuild prompts with `k` per bot fitted to billed tokens → Task 6.
- Five free checks → Tasks 7–11. The cache-related checks (repeat windows, follow-up overlap, phatic share, churn) belong to the Cache and Context plans' "Check" stages in the Master Plan and are not included here.
- Gateway price list in `config/reference/` → **not in this plan.** Prices for the six catalogue models already exist (`prices-metis-2026-10-18-g55.toml`); the candidate models (e.g. `gpt-6-luna`) depend on Metis answer Q5 and belong to the Routing plan.
- Judge set-up (two families, both orders, strict JSON, anchors) → **not in this plan.** E5 provides the pluggable plumbing; choosing and paying for judges needs B-3 and the pilot. Named in Task 15's "not done".
- Human-label tool and protocol → Task 13. PPI → Task 12.
- Per-key spend caps and shared spend record → **not in this plan**; recorded as a decision in Task 14.
- "metis eval runs on 50 items" and MLflow → **not in this plan**; MLflow is a Phase S tool decision.
- Questions to Metis and licence check → Task 14.

**Step scan:** Tasks 4 and 6 depend on Task 1's schema and E3's composition API; their steps tell the implementer to read those first rather than guessing names. No step says "handle edge cases" without a named test.

**Type consistency:** `ReplayRow` fields (Task 5) are the only inputs to Tasks 7–11; `BotFit` / `FitInput` (Task 6) feed Task 10; `PeriodBounds` (Task 5) wraps the four boundaries `assign_period` (Task 3) takes. `distinct_chunk_fps` is defined in `rows.py` (Task 5) and used in Tasks 8–9.

**Proportion:** about 15 tasks for a Master Plan phase of 11 deliverables; code blocks are signatures and test names, not bodies.
