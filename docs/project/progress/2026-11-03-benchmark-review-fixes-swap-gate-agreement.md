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
