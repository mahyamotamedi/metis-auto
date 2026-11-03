# Paid benchmark pilot (P-1 to P-3): how to run it, and what the pilot machine needs

Decisions: [ADR-0053](../adr/0053-paid-benchmark-p1-p3.md). Config: `config/evaluation/benchmark.toml`. Label format: [benchmark_labels.md](../evaluation/benchmark_labels.md).

**Nothing here has run. Every paid step refuses until its gates are open and the owner has set the values below.**

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
5. **`config\local.toml`** with the machine's caps (ADR-0018). The 20 USD ceiling stays in `config/defaults.toml`.
6. **The other machines' ledger summaries** in `reports\spend\ledgers\` (step 2).

**The plan with real sizes and prices (no call):**

```powershell
.venv\Scripts\python scripts\benchmark.py plan --with-db --machine <your-label>
```

## 4. Paid steps (only after the gates; owner approval in chat per run)

Gates (final plan):
1. ADR-0018 amendment 2 committed. It is (20 USD), but it was approved for the golden answers; the benchmark's share is the owner's call (Q-62). Amendment 3 (2026-11-03) raised the ceiling and cap to 92 USD for this benchmark.
2. Metis's written answer that samples may be sent to model APIs. Set it in `[gates]` with its reference.
3. The owner's approval in chat for this run, after the printed estimate.

Owner values to set in `config/evaluation/benchmark.toml`:
- `[run]`: `hard_cap_usd`, `max_output_tokens`, `order_seed`;
- `[judges]`: two `models` from different families, `max_output_tokens`, `instruction_language`;
- `[labels]`: `acceptable_score`, `cheap_arms`;
- `[spend_share]`: `expected_machines`, `max_age_hours`.

```powershell
$env:METIS__LIVE__ENABLED = "true"
.venv\Scripts\python scripts\benchmark.py generate --run-id p1-pilot-1 --machine <label> --approved-by <owner> --cap <usd> --dataset-text-approved
.venv\Scripts\python scripts\benchmark.py judge    --run-id p1-pilot-1 --machine <label> --approved-by <owner> --cap <usd> --dataset-text-approved
Remove-Item Env:METIS__LIVE__ENABLED
.venv\Scripts\python scripts\benchmark.py spot-check --run-id p1-pilot-1
.venv\Scripts\python scripts\benchmark.py labels --run-id p1-pilot-1 --name p1-pilot-1
```

- **Generate:** each callable arm answers each pilot record with the reference's prompt.
  - Every answer is recorded in `data\recorded\`, and a rerun replays it at no cost.
  - Each live call passes the spend guard over the shared total.
  - Arms Metis no longer serves (gpt-4.1-nano, mimo-v2.5) are refused in the plan and never called.
- **Judge:** two judges, both orders, plain chat with strict JSON. Metis rejects `json_schema`, so none is sent. A malformed reply is refused, never guessed. Results go to `runs\benchmark\<run>\judging\` with no text: scores, cost and latency only.
- **Spot-check:** `sheet.csv` is ID-only and blinded. The text (`texts_LOCAL_ONLY.md`) and the key (`key_LOCAL_ONLY.csv`) stay on this machine, in git-ignored `runs\`.
- **Labels:** the label file for R-C3 and R-B3 ([format](../evaluation/benchmark_labels.md)) and a content-free summary.

The pilot is discarded from results (final plan P-1). It measures real output and reasoning lengths, and from them the cost of a main run.
