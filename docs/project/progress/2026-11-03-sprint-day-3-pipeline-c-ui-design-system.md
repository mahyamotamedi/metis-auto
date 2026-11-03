## Sprint Day 3, Pipeline C: demo UI design system, UI spec Stage 2 (2026-11-03)

Branch `ui-stage2-design-system` (from `main` at 035d7b6, #38, plus d7a1d9a screenshot notes). **Awaiting review.** `git fetch`: `origin/main` head is 035d7b6. Build spec: `docs/design/metis-auto-ui-spec.md` §2 and §8 Stage 2; visual source: the six screenshots in `docs/design/metis-screens/` (local, not committed) and `docs/design/metis-screens-notes.md`; owner decisions (1)–(10) of 2026-11-03. Traceability: FR-FIN-02, FR-FEAT-03, QA-PRIV; ADR-0024, ADR-0050; ADR-XXXX (demo-ui-design-system).

- **New:** `src/metis_auto/wiring/ui_style.py` (CSS variables and component styles, Altair config per mode, base64 `@font-face`, LTR isolation, header and state fragments), `assets/fonts/vazirmatn/` (Vazirmatn v33.003 Regular, Medium, Bold, ExtraBold woff2, `OFL.txt`, `AUTHORS.txt`, `SOURCE.md` with URL and sha256), `tests/unit/wiring/test_ui_theme.py`, `docs/adr/draft-demo-ui-design-system.md`.
- **Changed:** `config/demo/theme.toml` (full token table, both modes, chart palettes per mode, brand gradient, landing, sizes, font; each value *sampled* from a named image and position, or *estimated*), `config/demo/ui_strings.toml` (+header, shell and chat strings; 220 keys), `wiring/ui_config.py` (`load_theme`, `Theme`, `ui_state`, `translator`; Stage 1 `chart_theme` removed), `wiring/lever_view.py` (additive: `StepView.blocks`, `StepView.breakdown`; the tenant-cap number LTR-isolated), `scripts/demo_ui.py` (page-built two-row header, theme and language state in session and URL, every string through the table, cost panel as cards, charts themed; callbacks and calculations unchanged), `scripts/demo_pages/results.py` (filter row, KPI cards, chart cards: waterfall, stacked before/after, donut; tables as `st.table`), `.streamlit/config.toml` (`[theme]` = dark tokens, `baseFontSize` 15), `tests/integration/test_demo_ui_app.py` (+9; existing tests ask for `?lang=en`, the language switch key is now `ui_lang`), `tests/unit/wiring/test_results_dashboard.py` (+4), `tests/unit/wiring/test_ui_config.py` (placeholder test moved to `load_theme`), `docs/architecture/module_reference.md`.
- **TDD:** `test_ui_theme.py` and the new integration tests failed at import / on missing keys; the 4 chart-row tests failed (4 failed); then implemented until green.

### Findings (Streamlit 1.65.0)
- Static serving reads only `scripts/static/` and refuses paths resolving outside it (symlinks too): fonts are inlined as base64 (~270 KB per run).
- No API switches Streamlit's own theme; widgets are react-aria (toggle, select, radio, tabs, progress), not baseweb. The light theme is CSS over the dark base; rules are scoped with `:root` to outrank Streamlit's emotion classes. `st.dataframe` (canvas) cannot be recoloured: replaced by `st.table`.
- A style-only `st.html` lands in Streamlit's event container, before the page's elements.
- `st.navigation(position="top")` cannot hold widgets: the header is built in the page; Streamlit's nav and toolbar are hidden.
- Sampled tokens differ from the notes in 14 places (header, surface, borders, text, muted, active tab, accent, all chart series); the image values are used and the notes' values are recorded next to them.

### Visual check
Headless Chrome (CDP), 1470 × 803: `runs/demo/screens/` (git-ignored): `chat|results` × `dark|light` × `fa|en`, plus `chat-*-messages.png` (two SYNTHETIC fake-mode turns) and `results-*-fa-full.png`. Remaining differences from images 3–6 are listed in the stage report.

### Open
- Persian strings unreviewed (K-2/K-3). Texts built by `wiring.demo_ui` (banner details, detail rows, failure texts, cost term names) stay English.
- UI-G01/G02 (trend line, two-series tokens): themed in the config, no chart: no real time series on Results; the chat session trend is Stage 3 (UI-D12).
- Header brand does not return to an entry screen (UI-S01 is Stage 3). Small-screen layout not checked (Stage 5).
- Owner review of ADR-XXXX (demo-ui-design-system).

### Checks
Baseline before: 2043 passed, 26 skipped, 0 failed. After: **2080 passed, 26 skipped, 0 failed**; architecture 58 passed; ruff check and format clean.
