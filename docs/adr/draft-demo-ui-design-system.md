# ADR-XXXX (demo-ui-design-system): The demo UI's design system: one token file, a generated style sheet, a page-built header, and inlined fonts

- Status: **provisional**, the agent's reading of the approved UI spec (`docs/design/metis-auto-ui-spec.md` §2, Stage 2) and the owner's decisions of 2026-11-03 (Pipeline C, Day 3), until the owner reviews it.
- Date: 2026-11-03
- Relates to: [ADR-0024](0024-demo-ui-streamlit.md) (thin Streamlit page; its point 7 allowed only the static style sheet as unsafe HTML), [ADR-0050](0050-results-dashboard-display-rules.md) (Results display rules, unchanged), spec UI-V01..V10, UI-H01..H05, UI-C01..C04, UI-K01..K08, UI-G01..G08, UI-T01..T05.
- Code: `config/demo/theme.toml`, `src/metis_auto/wiring/ui_config.py` (`load_theme`, `ui_state`, `translator`), `src/metis_auto/wiring/ui_style.py`, `scripts/demo_ui.py` (header), `scripts/demo_pages/results.py`, `.streamlit/config.toml` `[theme]`, `assets/fonts/vazirmatn/`; tests `tests/unit/wiring/test_ui_theme.py`, `tests/integration/test_demo_ui_app.py`.

## Context
The spec makes the colours tokens in one table (UI-V03, UI-T05), asks for both themes and both languages on every screen (UI-T02, UI-V06), a slim two-row header with the theme toggle, language switch, mode chip and budget (UI-H01..H05), and a bundled Vazirmatn font (UI-V08). It does not say how, in Streamlit 1.65.0, to:

- build a header that holds widgets (Streamlit's `st.navigation(position="top")` renders its own bar with page links only);
- serve font files offline (static serving reads only `scripts/static/`, next to the main script, and refuses paths that resolve outside it, symlinks included: `build_safe_abspath` in `streamlit/web/server`);
- switch Streamlit's own theme at run time (no API; `st.context.theme` is read-only). Its widgets (react-aria in 1.65) and popovers take colours from `.streamlit/config.toml`.

## Decision
1. **One token file.** `config/demo/theme.toml` holds every colour (dark and light), the chart palettes per mode, the brand gradient stops, sizes and the font list, each value marked *sampled* (pixel read from a named screenshot) or *estimated*. `wiring.ui_config.load_theme` refuses a file with a missing token in either mode. No other file names a colour (tested on the page files and the CSS generator); `.streamlit/config.toml` repeats the dark tokens for the first paint and a test keeps them equal.
2. **A generated style sheet, injected first.** `wiring.ui_style.page_css(theme, lang)` emits the `:root` variables, the `@font-face` rules and component rules that only use `var(--…)`. Every rule is scoped with `:root` so it outranks Streamlit's emotion classes, which are inserted later at equal specificity. The light theme is therefore CSS over Streamlit's dark base: header, sidebar, cards, inputs, selects and their listboxes, toggles, radios, tabs, expanders, banners, tables, chat bubbles, Vega tooltips. Small tables use `st.table` (HTML) instead of `st.dataframe`, whose canvas grid CSS cannot recolour.
3. **The header is built in the page**, not with Streamlit's top navigation: a fixed, full-width keyed container with two rows (brand | language, mode chip, budget, theme toggle, local-demo chip; then `st.page_link` tabs with a line icon and a filled active pill). Streamlit's toolbar, main menu, deploy button and its own navigation are hidden with CSS; pages are registered with `st.navigation(position="hidden")`. The header's static fragments are `st.html` built by wiring from the strings table and numbers, HTML-escaped; no message content. This extends ADR-0024 point 7 (unsafe HTML only for static styling) to these escaped, content-free fragments.
4. **Fonts inlined as base64.** The four Vazirmatn v33.003 files (Regular, Medium, Bold, ExtraBold for the wordmark; OFL, `assets/fonts/vazirmatn/OFL.txt`) stay in `assets/fonts/vazirmatn/` and are embedded in the style sheet (~270 KB once per run, cached in the process). No CDN, no static serving.
5. **Theme and language** live in the session and in the URL (`?theme=dark|light&lang=fa|en`, defaults dark and fa); the session wins over a stale URL; tabs carry the parameters across pages.
6. **LTR isolation** of numbers, money, dates, counts and model ids by Unicode isolates (U+2066 … U+2069) in plain text (metric values, captions, progress texts, badges, table cells) and `<bdi dir="ltr">` in HTML fragments; table cells use `unicode-bidi: plaintext`.

## Alternatives considered
- **Style `st.navigation(position="top")`:** it cannot hold the toggle, budget or chips, and its layout is not the screenshots' two rows. Rejected.
- **Move the fonts to `scripts/static/` and enable static serving:** works, but splits the assets from `assets/fonts/` (owner decision 6) and adds a server option; a symlink is refused by Streamlit's path check. Rejected for now; switch if the style sheet's size matters.
- **A theme switch through Streamlit's settings menu (`[theme.light]` / `[theme.dark]`):** the user would switch in a hidden menu, not the header toggle, and the URL could not carry it. Rejected.
- **A custom component (React) for the header:** a new frontend toolchain (UI-R01). Rejected.

## Consequences
- Streamlit selectors (`data-testid`, react-aria structure) are those of 1.65.0; an upgrade must re-check them (the screenshots under `runs/demo/screens/` are the check).
- In light mode, anything Streamlit draws on a canvas or in an element the CSS does not reach keeps the dark config colours; `st.dataframe` is avoided for that reason.
- Texts built by `wiring.demo_ui` (banner details, per-message detail rows, failure texts, decomposition term names) stay English in both languages until they move to the strings table (Stage 3).
- The header's brand does not yet return to an entry screen (UI-S01 is Stage 3).
