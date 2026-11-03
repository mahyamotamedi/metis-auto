## Sprint Day 3, Pipeline C: D-2 results dashboard, UI spec Stages 0 and 1 (2026-11-03)

Branch `d2-results-dashboard` (from `main` at e71bbc2, #36, plus the spec commit 47fe677). **Awaiting review.** `git fetch`: `origin/main` head is e71bbc2. Build spec: `docs/design/metis-auto-ui-spec.md` (Stage 0 inspect, Stage 1 = UI-S07). Traceability: FR-FIN-02, FR-ACCT-05, FR-EVAL-02, FR-REQ-04, FR-FEAT-03, QA-COST, QA-PRIV, QA-REPRO; ADR-0024, ADR-0032, ADR-0036, ADR-0039; ADR-XXXX (results-dashboard-display-rules).

- **New:** `scripts/demo_pages/results.py` (the Results page, layout only), `src/metis_auto/wiring/ui_config.py` (strings table, direction, chart theme), `config/demo/ui_strings.toml` (Results keys, `fa` and `en`; Persian `[PLACEHOLDER: Persian review]`), `config/demo/theme.toml` (two chart colours and grid opacities; Stage 1 placeholder), `tests/unit/wiring/test_results_dashboard.py` (13 tests), `tests/unit/wiring/test_ui_config.py` (5 tests), `docs/adr/draft-results-dashboard-display-rules.md`.
- **Changed:** `wiring/lever_view.py` (additive: `dashboard`, `cache_monitor`, `version_key`, `tenant_cap`, `has_final`; `waterfall` now prices a repriced total as "token cost only, fees not priced" and shows `other` as part of token cost), `scripts/demo_ui.py` (top navigation Chat / Results via `st.navigation`; the chat is unchanged inside a function page; CSS keeps metric values and tables left-to-right inside the RTL container), `tests/integration/test_demo_ui_app.py` (+3 Results page tests with AppTest), `tests/architecture/test_ui_imports.py` (allows `scripts/demo_pages/results.py`; no colour in the page), `tests/unit/wiring/test_lever_view.py` (repriced fixture now ADR-0036-shaped), `tests/unit/experiments/test_exp_ctx_001_token_saving.py` (repriced total no longer unknown), `docs/architecture/module_reference.md` (lever_view row, new ui_config row, scripts list).
- **TDD:** the new unit tests failed at import (`RESULT_SLICE`, `ui_config` missing); the 3 page tests and the colour test failed (4 failed). Then implemented until green.

### Stage 0 findings (aggregates only)
- Streamlit 1.65.0 / Altair 6.3.0 in `.venv`: `st.navigation`, `st.Page`, `st.toggle`, `st.segmented_control` (with `required`), `st.pills`, Material icons, `AppTest` all present (checked by import and a scratch app). `AppTest.switch_page` takes **page files only**, not function pages, so Results is a file page.
- `docs/design/metis-screens/` does **not exist**; no logo or wordmark asset in the repo (UI-R08/UI-R09: text wordmark and written tokens until provided).
- 124 LeverResults, 0 skipped, four baselines; no `final.json`, no `combine`-based result, no `other` block, no guard-block reasons.
- Pipeline B's repriced results (`rb1.*`, `rb2.*`) hold **recorded-unit slices** (`baseline:fees`) inside repriced results: hidden by the view (108 of the slice/version/baseline combinations).
- Pipeline A's files reuse one `lever_id` under all four baselines (6 IDs × 4); ADR-0032 calls `lever_id` the file name. The view looks results up per baseline.
- Pipeline A's `pq-v1` is the version label of two results (first_turn and all_turns): `compare` marks them "duplicate version", never ranked.

### Open
- Owner review of ADR-XXXX (results-dashboard-display-rules), esp. the default baseline (as-logged) and "no combined number until I-1/I-2".
- Tell B: repriced slices in recorded units; tell A: one `lever_id` per baseline file.
- Persian labels unreviewed (K-2/K-3). Nav titles "Chat"/"Results" are still English (header language switch is Stage 2).
- Not checked in a real browser by the agent: the server started and served `/`, `/chat`, `/results` (HTTP 200, no log errors); the pages' scripts were run by AppTest.

### Checks
Baseline before: 2020 passed, 26 skipped, 0 failed. After: **2043 passed, 26 skipped, 0 failed**; architecture 58 passed; ruff check and format clean.
