## Benchmark review fixes: swap-inconsistency, Persian gate on labels, spot-check agreement (2026-11-03)

Branch `sprint-final-i1-n1`. Files owned by Parham (ADR-0053); this is a small change for his review. [ADR-0053](../../adr/0053-paid-benchmark-p1-p3.md) Amendment 1.

**Done**
- `judge_all` marks a swap-inconsistent pair (E5's `swap_consistent` false) as state `inconsistent`, no score; labels give NA for that arm (`not_labelled:inconsistent` when nothing else is labelled); the summary has the inconsistency rate per judge and per arm.
- `judge_gate` (`validated` / `unvalidated` / `not_configured`) per label row and in the summary, from E5's `evaluate_gate`; new `[gate]` in `config/evaluation/benchmark.toml` (unset).
- `evaluation/benchmark/agreement.py` and `scripts/benchmark.py agreement --run-id <run>`: filled sheet + local key → E5 rating import → agreement per judge and language → gate → content-free `agreement.json`.
- Tests first: unit (judge, labels, agreement on [SYNTHETIC] sheets) and the mocked-HTTP integration test (its mock judge now prefers the arm's answer in either position, so no pair is inconsistent; it also runs `agreement` with the gate unset and set).

**Not done on purpose**
- The other review findings are listed as known limits in the ADR amendment; E4 and E5 code is unchanged. No live call, nothing committed.

**Open**: the gate values (owner); Parham's review; a bootstrap interval for the agreement.

**Added 2026-11-03 (pilot run `pilot-1`)**: the first generation and judging passes each stopped at one Metis connection timeout. `SpendGuardedClient` now charges the estimate and continues on `connection` / `timeout` errors, stopping only after 5 in a row (ADR-0053 amendment 2).

**Pilot `pilot-1` stopped by the owner (2026-11-03)**: 20 records, 3 arms (gpt-5-nano, gpt-4o-mini, deepseek-v4-flash), judges gpt-5.4 and deepseek-v4-flash (grok-4-1-fast never got a call; its files are in `judging_superseded/`). 54 of 60 answers; total spend 1.44 USD (cap 7). **No usable labels**: all 20 records unlabelled (6 answers missing, 10 records hit a swap-inconsistent pair, deepseek returned empty output on 29 pairs at `judges.max_output_tokens` 512). Where both judges scored (15 pairs, 12 agreeing) every cheap arm lost to the gpt-5.5 reference. gpt-5.4 was swap-inconsistent on 13 of 53 pairs (25%). The 20-record pilot works as a harness test only. Live calls were switched off again in the local config; the gate values and `expected_machines = ["saba"]` in `benchmark.toml` are pilot settings the lead should review.
