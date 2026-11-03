# Paid benchmark pilot (P-1 to P-3): how to run it, and what the pilot machine needs

Decisions: [ADR-0053](../adr/0053-paid-benchmark-p1-p3.md), ADR-0060. Config: `config/evaluation/benchmark.toml`. Label format: [benchmark_labels.md](../evaluation/benchmark_labels.md).

**Nothing here has run. Every paid step refuses until its gates are open and the owner has set the values below.**

## 0. Owner questions (nothing runs until each is answered)

Each is an `[OWNER-PLACEHOLDER]` in `config/evaluation/benchmark.toml`, left unset on purpose; the tests expect them unset in the committed file, so set them in your local copy or in a reviewed commit. Traces: FR-EVAL-04, QA-COST, ADR-0053.

| # | Key | Question for the owner |
|---|---|---|
| Q-62 | `run.hard_cap_usd` | How many USD of the 92 USD ceiling (ADR-0018 amendment 3; an upper bound) may this benchmark spend, pilot and main together? |
| Q-63 | `run.max_output_tokens` | Generation limit per answer? (The golden answers used 8,192.) |
| Q-63 | `run.order_seed` | Seed of the call-order shuffle. |
| Q-63 | `judges.models` | Two judge models from different provider families (the code refuses same-family pairs)? |
| Q-63 | `judges.max_output_tokens`, `judges.instruction_language` | Judge reply limit; instruction language `en` or `fa`? |
| Q-63 | `labels.acceptable_score`, `labels.cheap_arms` | Score at or above which an answer is acceptable (ADR-0006 vs the PDF rule, final plan O-1); which arms define `cheap_ok`? |
| Q-64 | `spend_share.expected_machines`, `max_age_hours` | Which machine labels count, and how old may a ledger summary be? |
| O-1 | `gates.metis_allows_samples`, `metis_answer_ref` | Has Metis answered in writing that samples may go to model APIs? Where is the answer recorded? |

Once the values are set, `plan --estimate` prints the computed estimate and refuses before that (see sections 1 and 3).

## 1. Anyone, any machine: no database, no call, no key

```powershell
.venv\Scripts\python scripts\benchmark.py tenant-check
.venv\Scripts\python scripts\benchmark.py plan
```

`tenant-check` reads golden-v2's committed ID-only export and checks the 35% tenant cap for the whole set and for the pilot. `plan` prints:
- the arms (callable, or why not);
- the pilot's record count (20);
- generation and judge calls;
- the gates and the owner values still unset.

Without the database, the cost bounds say "need the golden-v2 database".

`plan --estimate --with-db` is the strict form: it refuses, listing every `set by owner: <key>` and the missing database, and otherwise adds an `estimate` block (generation plus judging, lower bound and ceiling, each compared with `run.hard_cap_usd`). `scripts/sampling_plan.py --config <file.toml> --strict` does the same for the sampling allocation (`[allocation]` and `[run]` values) and adds the call count.

## 2. Every machine before any paid run: export your ledger summary (decision 7)

```powershell
.venv\Scripts\python scripts\spend_share.py export --machine <your-label>
.venv\Scripts\python scripts\spend_share.py merge
```

`export` reads your `data\spend\ledger.jsonl` **read-only** and writes `reports\spend\ledgers\<your-label>.json`. That file holds totals per run, with no prompt and no key; commit it or send it to the person running the pilot. `merge` prints the team total. A paid run refuses if a listed machine's summary is missing or older than `max_age_hours`.

## 3. The pilot machine (whoever holds the golden-v2 database)

**What it needs:**
1. **PostgreSQL running**, with golden-v2 built and verified (`python scripts/build_eval_dataset.py ...`, see [golden_v2.md](../evaluation/golden_v2.md)), and the gpt-5.5 answers of run `ga-v2-20261101` in `eval.golden_answer`:
   - either the machine that made them;
   - or imported from the private `Metis-auto/golden-answers-v2` dataset with `scripts/golden_answers.py import` and `verify-answers` (must print PASS).
2. **The `db` lock** installed (`requirements-db.lock`), which also brings the `live` extra (`openai`).
3. **The tokenizer files** (`python scripts/fetch_tokenizer_assets.py`), so input sizes are counted, not approximated.
4. **`METIS_API_KEY`** in `.env`, and `live.enabled` switched on only for the paid step (as in the router live check).
5. **`config\local.toml`** with the machine's caps (ADR-0018). The 92 USD ceiling (amendment 3) stays in `config/defaults.toml`.
6. **The other machines' ledger summaries** in `reports\spend\ledgers\` (step 2).

**The plan with real sizes and prices (no call):**

```powershell
.venv\Scripts\python scripts\benchmark.py plan --with-db --machine <your-label>
```

## 4. Paid steps (only after the gates; owner approval in chat per run)

Gates (final plan):
1. ADR-0018 amendment 3 committed (2026-11-03: ceiling and lifetime cap 92 USD, an upper bound; amendment 2 had 20 USD for the golden answers). It is committed; the benchmark's share of it is the owner's call (Q-62, `run.hard_cap_usd`).
2. Metis's written answer that samples may be sent to model APIs. Set it in `[gates]` with its reference.
3. The owner's approval in chat for this run, after the printed estimate.

Owner values to set in `config/evaluation/benchmark.toml` are listed in section 0.

### Command sequence (not run; each step waits for the previous one's gate)

Replace `<label>`, `<owner>` and `<usd>`. On macOS or Linux, use `export METIS__LIVE__ENABLED=true` and `unset METIS__LIVE__ENABLED` instead of the PowerShell lines, and `.venv/bin/python scripts/...` for the paths.

**Gate A, before anything:** section 0 answered; `gates.metis_allows_samples = true` with `metis_answer_ref`; every machine's ledger summary exported (section 2); `pytest -q` green.

```powershell
# 1. Strict estimate for the pilot. Must print an estimate, not a refusal.
.venv\Scripts\python scripts\benchmark.py plan --estimate --with-db --machine <label> --scope pilot
```

**Gate B:** the owner reads the estimate and approves in chat, naming the cap.

```powershell
# 2. Pilot of 20 (discarded from results). Paid.
$env:METIS__LIVE__ENABLED = "true"
.venv\Scripts\python scripts\benchmark.py generate --scope pilot --run-id p1-pilot-1 --machine <label> --approved-by <owner> --cap <usd> --dataset-text-approved
.venv\Scripts\python scripts\benchmark.py judge    --scope pilot --run-id p1-pilot-1 --machine <label> --approved-by <owner> --cap <usd> --dataset-text-approved
Remove-Item Env:METIS__LIVE__ENABLED
.venv\Scripts\python scripts\benchmark.py spot-check --run-id p1-pilot-1
.venv\Scripts\python scripts\benchmark.py labels --run-id p1-pilot-1 --name p1-pilot-1
```

**Gate C, after the pilot:** the pilot's measured output and reasoning lengths replace the limit-based ceiling. Re-run the strict estimate for the main set (`--scope main`), check that it fits what is left under the cap (`scripts\spend_share.py merge` shows the team total), and get the owner's approval in chat again. Stop if the pilot showed truncation, malformed judge replies, or a cost per record far above the estimate.

```powershell
# 3. Strict estimate for the main 300. Pilot answers replay at no cost.
.venv\Scripts\python scripts\benchmark.py plan --estimate --with-db --machine <label> --scope main

# 4. Main 300 (paid).
$env:METIS__LIVE__ENABLED = "true"
.venv\Scripts\python scripts\benchmark.py generate --scope main --run-id p1-main-1 --machine <label> --approved-by <owner> --cap <usd> --dataset-text-approved
.venv\Scripts\python scripts\benchmark.py judge    --scope main --run-id p1-main-1 --machine <label> --approved-by <owner> --cap <usd> --dataset-text-approved
Remove-Item Env:METIS__LIVE__ENABLED
.venv\Scripts\python scripts\benchmark.py spot-check --run-id p1-main-1
.venv\Scripts\python scripts\benchmark.py labels --run-id p1-main-1 --name p1-main-1
```

The main set is every golden-v2 record (300, largest tenant 20%); it is not a report-period sample (ADR-0053 point 1), so its labels train R-B3 and R-C3 and do not stand as a held-out report. `--scope main` was added in the sprint close; it is covered by a synthetic test only and has not run against the database.

- **Generate:** each callable arm answers each pilot record with the reference's prompt.
  - Every answer is recorded in `data\recorded\`, and a rerun replays it at no cost.
  - Each live call passes the spend guard over the shared total.
  - Arms Metis no longer serves (gpt-4.1-nano, mimo-v2.5) are refused in the plan and never called.
- **Judge:** two judges, both orders, plain chat with strict JSON. Metis rejects `json_schema`, so none is sent. A malformed reply is refused, never guessed. Results go to `runs\benchmark\<run>\judging\` with no text: scores, cost and latency only.
- **Spot-check:** `sheet.csv` is ID-only and blinded. The text (`texts_LOCAL_ONLY.md`) and the key (`key_LOCAL_ONLY.csv`) stay on this machine, in git-ignored `runs\`.
- **Labels:** the label file for R-C3 and R-B3 ([format](../evaluation/benchmark_labels.md)) and a content-free summary.

The pilot is discarded from results (final plan P-1). It measures real output and reasoning lengths, and from them the cost of a main run.
