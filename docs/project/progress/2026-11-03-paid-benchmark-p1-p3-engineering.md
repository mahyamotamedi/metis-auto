## Paid benchmark P-1 to P-3: engineering for a golden-v2 pilot, real judge, labels hand-off, shared spend total (2026-11-03)

Parham (P-1 to P-3 confirmed his by Kimia, 2026-11-03), branch `paid-benchmark-p1-p3` from `main` at `650b6b6`. **Done; awaiting review. Nothing has run and no paid call was made.** Decision record: [ADR-0053](../../adr/0053-paid-benchmark-p1-p3.md). Traces: FR-EVAL-04, FR-EVAL-05, FR-ROUTE-03, FR-ROUTE-05, QA-COST, QA-PRIV, H-1; final plan "Paid branch", Review Focus 5, decision 7; evaluation overview §5 (live-client wiring, real judge).

**What exists now**
- **P-1:**
  - golden-v2 as the pilot set (A-126);
  - arm callability with reasons (gpt-4.1-nano and mimo-v2.5 refused, A-127);
  - the 35% tenant check (passes: 20% largest single account);
  - a deterministic 20-record pilot;
  - `scripts/benchmark.py plan`, which prints arms, records, calls, cost bounds, the budget and team total, the gates and the unset owner values, with no call.
- **Live-client wiring for E4:** replay-first, spend-guarded, recording live clients built from settings (`wiring/benchmark.py`, `adapters/providers/replay_first.py`). Each arm gets the gpt-5.5 reference's own prompt. A rerun replays at no cost (tested).
- **P-2:**
  - `LlmPairwiseJudge`: E5's protocol over a `ModelClient`, with strict JSON from prompt and parser and no `response_format` (A-128);
  - two families, both orders;
  - cost and latency as evaluation cost;
  - refusals become `not_evaluated`, never a crash;
  - the 60-item spot-check: ID-only blinded sheet, text in local files.
- **P-3:** the `benchmark-labels-v1` export (`cheap_ok` for R-C3, `min_adequate_tier`), tested against R-C3's own `fit_logistic`. Format: [benchmark_labels.md](../../evaluation/benchmark_labels.md). R-B3 needs a change of theirs (TODO-22).
- **Decision 7:** content-free ledger summaries, `scripts/spend_share.py export|merge`, and `SharedSpendLedger`, which bounds every paid call by the team total under the 20 USD ceiling and fails closed (A-130).

**Budget found:** the golden answers spent 12.03 USD of the 20 USD ceiling; at most about 7.97 USD is left for the team (A-129). The plan's 300-request main run does not fit.

**Still missing (each blocks a paid step):**
- gate 2, Metis's written answer on sending samples;
- Q-62, the budget share, run cap, generation limit and order seed;
- Q-63, the judges and label thresholds;
- Q-64, the machine list and summary age;
- the owner's per-run approval.

Pilot machine requirements: [benchmark_pilot.md](../../guides/benchmark_pilot.md).

**Not changed:** E4, E5, golden answers, the ledger, R-B3 and R-C3 code, the catalogue and `sprint.toml`.

Tests (Linux): new unit and mocked-HTTP integration tests; full suite and ruff in the report.
