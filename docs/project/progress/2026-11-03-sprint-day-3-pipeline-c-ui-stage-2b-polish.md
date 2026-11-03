## Sprint Day 3, Pipeline C: UI Stage 2b, visual polish of the design system (2026-11-03)

Branch `ui-stage2b-polish` (from `main` at ebf8f51, #41). **Awaiting review.** `git fetch`: `origin/main` head is ebf8f51. Source: the owner's review of Stage 2 (2026-11-03, eight points), spec `docs/design/metis-auto-ui-spec.md` (UI-R01..R11), images 3 to 6 in `docs/design/metis-screens/`. Rules recorded as [ADR-0052](../../adr/0052-demo-ui-design-system.md) Amendment 1. Traceability: FR-FIN-02, FR-FEAT-03, FR-REQ-04, QA-PRIV.

- **(1) Wordmark:** "متیس‌اتو" / "Metis-Auto" with the "نمونه‌ی آزمایشی" / "prototype" pill.
- **(2) Header budget:** the real lifetime budget from the spend ledger in both modes ("بودجه: $7.40 از $20.00"); unreadable or absent → "نامعلوم". The mode appears only in the chip. New `demo_ui.header_budget`.
- **(3) Version names:** new `config/demo/lever_names.toml` (21 patterns, owners A/B/C); `lever_view.load_lever_names` / `display_name`. The raw id appears only in a muted caption or a tooltip. Tested: every id in `reports/levers/` has a name.
- **(4) Numbers:** new `wiring/ui_format.py`, `fmt`, the one formatter (19 test cases), used by lever_view, ui_style and the chat page. `md_safe` escapes `$` in markdown labels: Streamlit reads `$…$` as LaTeX, and the browser check found it garbling the budget bars.
- **(5) Layout:** Results in tabs Cache / Context / Routing / Per bot; KPI row; charts 60/40; tables folded with one-line summaries; one comparison bar chart per step. New per-tab KPIs:
  - Cache tab: the chosen cache version's monitor counts;
  - Per bot tab: traffic-weighted saving, bots, tenants over the cap.
  New charts in the Per bot tab: share of the saving per bot (first 15) and share of requests per tenant (over-cap tenants in the warning colour).
- **(6) Legends:** HTML, centred under each chart; Vega legends hidden (tested on the specs).
- **(7) RTL bars:** labels on the right and bars right to left in fa (tested on the specs).
- **(8) Persian:** about 90 strings from `wiring.demo_ui` moved to the strings table (English unchanged; calculations and order unchanged); language codes and compare's "N of M" and tenant flags translated. Test: both pages in fa show no known English UI string. These stay English by rule:
  - model ids and units;
  - settings reasons;
  - router decision texts;
  - routing results' stored assumptions (an LTR data block);
  - SYNTHETIC preset titles.
- **Tests:** baseline 2114 passed / 26 skipped → 2152 passed / 26 skipped. New: `tests/unit/wiring/test_ui_polish.py` (34). Extended: `tests/integration/test_demo_ui_app.py` (+3), `test_demo_ui_view.py` (+1). Two Stage 2 theme tests were updated to the new rules (wordmark, budget).
- **Screens:** Headless Chrome (CDP), 1470 × 803, in `runs/demo/screens/stage2b/` (git-ignored):
  - `chat|results` × `dark|light` × `fa|en`;
  - `chat-*-messages.png`;
  - `results-*-fa-full.png` and `results-dark-fa-full-{context,routing,per-bot}.png`.
- **Open:** Persian review (K-2/K-3); the per-message detail values keep the chat's own formatting ("0.000162 USD"); remaining visual differences from images 3 to 6 are listed in the stage report.
