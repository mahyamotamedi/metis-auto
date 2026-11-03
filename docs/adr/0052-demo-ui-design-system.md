# ADR-0052: The demo UI's design system: one token file, a generated style sheet, a page-built header, and inlined fonts

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

## Amendment 1 (2026-11-03): polish rules

Owner review of Stage 2 (2026-11-03), eight points, applied in UI Stage 2b (Pipeline C). Status: **decided by the owner** for the rules; the Persian wording stays `[PLACEHOLDER: Persian review]` (K-2/K-3).

1. **Wordmark.** The brand text is "متیس‌اتو" (fa) / "Metis-Auto" (en), heavy weight, with the small "نمونه‌ی آزمایشی" / "prototype" pill. "متیس" alone is never shown, because it reads as Metis's own product (UI-R08). Still no logo.
2. **Header budget.** The credit position shows the real lifetime budget from the spend ledger in **both** modes: "بودجه: **$7.40** از $20.00", the amount left in accent bold, LTR-isolated (`ui_style.budget_html`, `demo_ui.header_budget`). No budget configured, or a ledger that cannot be read → "بودجه: نامعلوم", never a number. The mode appears only in the Fake/Live chip. The header reads the ledger only; it never writes it.
3. **Readable version names.** `config/demo/lever_names.toml` maps each version id pattern (a regular expression over the lever_id without its baseline suffix) to a short fa and en name and the owner pipeline: "name (A|B|C)". Named groups fill the name (thousands separators; Persian digits in fa). The raw id appears only in a small muted "شناسه / id" caption and in chart tooltips. An id with no pattern shows the raw id with "no display name". Every id in `reports/levers/` must have a name (tested), so a new result needs a row before it reaches the demo.
4. **One number formatter.** `wiring/ui_format.fmt(value, kind)`:
   - money and recorded units: 2 decimals at |v| ≥ 1 with thousands separators; below 1, 4 significant digits with trailing zeros dropped ("$0.001921", "$0.00032"); `$` for USD, the unit otherwise as a muted caption;
   - counts: thousands separators;
   - percentages: 1 decimal;
   - intervals: "[2.3%, 2.8%]".
   Rounding is half up. Values are never changed, only their text. Chart axes use the matching d3 formats (`AXIS_FORMAT`). In Streamlit markdown labels, `$` is escaped (`md_safe`), because Streamlit reads the text between two `$` signs as LaTeX.
5. **Compact Results layout.** A filter row, then tabs Cache / Context / Routing / Per bot. Inside a tab:
   - the version switch with the id caption;
   - the KPI row;
   - charts in two columns at 3:2, the wider first, so it sits on the right in fa: waterfall | donut, then version comparison | before-and-after blocks;
   - long tables in collapsed expanders labelled with a one-line summary from wiring.
   The version comparison is one horizontal bar chart per step, labelled with display names.
6. **Legends.** Every chart hides the Vega-Lite legend, which cannot be centred. Wiring draws an HTML row of square swatches and labels centred under the chart (`legend_html`), using the same colour scale as the chart (`series_scale`).
7. **Right-to-left charts.** In fa, horizontal bar charts put category labels on the right and grow from right to left (`bar_layout`). The before-and-after chart puts "before" on the right. Card titles and axis titles are Persian; numbers on axes stay LTR.
8. **Persian everywhere.** Every visible text built by `wiring.demo_ui` (banner details, detail sections and labels, failure texts, cost term names, routing badges, "served by") comes from the strings table through an optional translator; English stays the default and is unchanged. The calculations, the terms and their order are unchanged: `cost_view` and `waterfall_rows` keep their English keys, and the page translates at display time (`term_text`, `routing_kind_text`). Some text stays as it is, by rule, and is shown LTR where it is a block:
   - model ids;
   - units;
   - settings reasons (e.g. "live.enabled is false");
   - router decision texts;
   - routing results' stored assumptions, shown as an English data block (`data_list_html`);
   - SYNTHETIC preset titles.
   Language slice codes get names (`lang_code_*`); compare's "N of M" and tenant flags are translated in `lever_view`.

Consequence: this replaces the Stage 2 consequence that `wiring.demo_ui` texts stay English. A test renders both pages in fa and fails if a known English UI string remains.
