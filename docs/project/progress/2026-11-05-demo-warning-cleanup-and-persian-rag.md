## Demo warning cleanup, Persian knowledge and push-readiness review (2026-11-05)

- Removed persistent Live-ON and LLMLingua warning banners. Kept the mode chip,
  experimental label, permission gates, failed-setting errors, budget guard and
  blocked/stopped errors. Restarted the updated demo on port 8502; health is OK.
- Confirmed that the Persian dedup sample's abbreviated documents changed the
  original shop's delivery/payment policies and omitted shipping prices. Saved
  synthetic-bot replies repeated those conflicting policies. Restored the
  original instructions and full documents, retaining duplicate chunks only for
  the dedup mechanism demonstration. Source/diagnostic presets are unchanged.
- Added offline UI-to-model regressions proving the original knowledge survives
  with dedup off/on. No paid quality validation was performed; canned fake
  answers are not evidence of grounded model quality. Recommend a new
  conversation with compression Off to avoid old answers and lossy compression.
- Reproduced and fixed a second dedup pass after compression: distinct original
  chunks that compress to identical text must remain as measured. `build` now
  only lays out the already-prepared request; strategy version is 1.0.1. Four
  collision regressions cover both layouts, with/without original duplicates.
- Reproduced and fixed RAG SQL accepting tab/newline-only chunks and allowing a
  later blank turn to hide earlier usable context. Synthetic PostgreSQL tests
  cover both cases; no source dataset records were changed.
- Validation: 59 targeted UI/context tests and seven PostgreSQL tests passed.
  Final full suite (`pytest -q --run-postgres -ra`): **2,744 passed, five skipped**
  in 151.37 seconds. Skips: missing Playwright, Redis and MLflow Python extras;
  PostgreSQL event-sink test requiring a password in the process environment;
  opt-in paid/network wrapper test. Repository-wide Ruff lint and formatting
  passed; whitespace and progress-index checks passed. Browser smoke check and
  a fresh read-only directory load confirmed 179 usable-RAG cards.
- Push-readiness review against the established `main` merge base found two
  remaining spec blockers: benchmark labels glob historical score files rather
  than selecting configured judges, and framework reports require an aggregate
  recording despite per-arm recording support. Standards review also found
  unknown dedup session savings presented as zero/partial totals and non-thin
  judge orchestration in `scripts/judge_reply_check.py`. Shared test capture
  helpers were a non-blocking duplication suggestion. These pre-existing branch
  findings were not silently changed as part of the requested demo fixes.
- Not declared push-ready; changes are uncommitted and nothing was pushed.
