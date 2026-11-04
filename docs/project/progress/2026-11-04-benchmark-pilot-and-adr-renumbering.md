## Benchmark pilot, partial main run and ADR renumbering on merge (2026-11-04)

Branch `sprint-final-pipelines`. Traces: FR-EVAL-04, QA-COST; ADR-0053, ADR-0062. Counts only; no text, IDs or hashes.

**ADR renumbering.** `origin/main` took ADR-0057 (demo local files) and ADR-0058 (demo navigation history) while this branch used the same numbers. Main's keep their numbers (`docs/adr/README.md`); this branch's two moved: `0057-results-dashboard-final-v1` is now **ADR-0063** and `0058-rules-only-decision-router-replay` is now **ADR-0064**. The entry `2026-11-03-sprint-final-stages-1-to-6.md` still names them by their old numbers (not edited: it is a dated record).

**Benchmark pilot `p1-pilot-1` (20 records, 3 callable arms, two judges).** Spent 0.209 USD. The `deepseek-v4-flash` judge first returned empty output on 59 of 60 pairs: Metis's wrapper thinks by default and the 64-token judge limit was used up by hidden reasoning. Fixes: `thinking = "disabled"` for that model in the machine's `config/local.toml`; a recorded reply that stopped at its limit with empty text is no longer replayed (`ReplayFirstClient`). After the rerun 13 of 20 records had labels (`cheap_ok` true 11, false 2, unknown 7).

**Main run `p1-main-1` (partial).** Generation was stopped by hand. Answers saved: gpt-5-nano 94, gpt-4o-mini 91, deepseek-v4-flash 99, of 900 planned. A gpt-5-nano call timed out and the spend guard stopped live calls once. Judging of the main set was started and stopped after a few minutes; no main-set scores or labels exist. `judge --judge <model>` now runs one judge, and an interrupted judge keeps the pairs it finished (only when it receives SIGINT; a background shell ignores SIGINT, so run it in the foreground).

**Not done.** Mahya, Saba and Parham were removed from `expected_machines` for the pilot (owner decision); restore them before a run that counts everyone's spend. The real reranker was not run (no GPU).
