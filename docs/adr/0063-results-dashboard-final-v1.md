# ADR-0063: The Results page reads `final.json` in the agreed format `final-v1`, and still adds nothing across steps itself

- Status: **provisional** (sprint task I-2, 2026-11-04). Amends [ADR-0050](0050-results-dashboard-display-rules.md) point 5, which only detected `final.json`; the owner allowed the change to `wiring/lever_view.py` (Pipeline C's file) at the Stage 0 questions.
- Date: 2026-11-04
- Relates to: [ADR-0036](0036-replay-scope-split-and-baselines.md) (units), [ADR-0050](0050-results-dashboard-display-rules.md), ADR-0061; FR-ACCT-05, FR-REQ-04, QA-PRIV, QA-COST.
- Code: `src/metis_auto/analysis/final_numbers.py`, `src/metis_auto/wiring/lever_view.py` (`load_final`, `final_view`), `scripts/demo_pages/results.py`, `scripts/build_final_numbers.py`.

## Context
ADR-0050 point 5 said no combined number is shown until `final.json` has an agreed format. The combined run (I-1) now exists, with its own rules: units never mixed, a step without a figure in a baseline's units is "not computed", marginal parts that add up, and F-2's unexplained "other" block.

## Decision
1. **One format, `final-v1`**, built by `analysis.final_numbers.build_final` from the combined run's summary, the lever results, F-2's cost trace and the baseline totals. A document in any other shape is ignored and the old note stays.
2. **The page adds nothing itself.** `final_view` only formats figures already in the file: per pipeline and baseline the steps' combined figures, the combined total and its share of the baseline, the sum-rule result and a waterfall. A missing figure is the text "not computed in these units", never 0.
3. **Always shown:** the label "provisional: cost only, pending quality", the units caveat, and, in recorded units, F-2's unexplained "other" share (report period derived as all minus tune). In price-file units the "other" block is stated as not computed.
4. **No combined interval:** the steps overlap; each result's own interval stays in the per-step view and in `versions`.

## Consequences
- The per-step view and the version switch are unchanged; ADR-0050's rule that steps are not added across the page's own columns holds (the combined figures come from the file).
- Guarding tests: `tests/unit/wiring/test_final_view.py`, `tests/unit/analysis/test_final_numbers.py`, `tests/architecture/test_reports_content_free.py`, `tests/integration/test_demo_ui_app.py::test_results_page_on_the_committed_results_shows_no_ids`.
