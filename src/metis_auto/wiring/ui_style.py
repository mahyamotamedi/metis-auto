"""The demo UI's design system as code (spec §2, Stage 2): CSS variables and
component styles, the Altair config per mode, the bundled font, LTR isolation,
and the small HTML fragments of the header and the states.

Every colour comes from ``wiring.ui_config.load_theme`` (``config/demo/
theme.toml``); this module names none (tested, UI-T05): outside the ``:root``
block the CSS only refers to ``var(--…)``. The page injects ``page_css`` as its
first element (UI-T04) and passes ``altair_config`` to every chart (UI-G05,
UI-G06). Fragments carry no message content: only strings from the strings
table and numbers, HTML-escaped.

Streamlit selectors (``data-testid``, ``data-baseweb``) are those of Streamlit
1.65.0 (requirements-ui.lock), checked in the browser on 2026-11-03; re-check
them on an upgrade.

Traceability: FR-FIN-02 (demo dashboard UI), FR-FEAT-03 (Persian first-class),
QA-PRIV (no content on screen beyond the user's own chat).
Called by: scripts/demo_ui.py, scripts/demo_pages/results.py, tests.
"""

from __future__ import annotations

import base64
import html
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from metis_auto.wiring.demo_ui import BudgetView
from metis_auto.wiring.ui_config import FONT_DIR, Text, Theme, direction

LRI, PDI = "⁦", "⁩"
"""Unicode left-to-right isolate and its end (UI-V07): plain-text isolation that
works in widget labels, metric values and chart text, where HTML cannot go."""
ICON_FONT = '"Material Symbols Rounded"'
"""Streamlit's bundled icon font (ligatures), reused for icons in fragments."""
PROTOTYPE_LABEL = "Metis-Auto prototype"
"""The app's name next to the wordmark (UI-R08, owner decision 2): a product
name, the same in every language."""


# --- LTR isolation (UI-V07) -------------------------------------------------------


def ltr(value: object) -> str:
    """``value`` as left-to-right isolated plain text (idempotent)."""
    text = str(value)
    if text.startswith(LRI) and text.endswith(PDI):
        return text
    return f"{LRI}{text}{PDI}"


def ltr_html(value: object) -> str:
    """``value`` HTML-escaped inside ``<bdi dir="ltr">`` (numbers, money, dates,
    token counts, model ids)."""
    return f'<bdi dir="ltr" class="mx-ltr">{html.escape(str(value))}</bdi>'


# --- tokens → CSS variables (UI-V03) ----------------------------------------------


def _var(key: str) -> str:
    return "--" + key.replace("_", "-")


def css_variables(theme: Theme) -> dict[str, str]:
    """Every token of ``theme`` as a CSS custom property."""
    out = {_var(k): v for k, v in theme.colours.items()}
    out |= {f"--chart-{k.replace('_', '-')}": v for k, v in theme.chart.items()}
    out |= {f"--toggle-{k.replace('_', '-')}": v for k, v in theme.toggle.items()}
    out["--brand-gradient"] = (
        f"linear-gradient(270deg, {', '.join(theme.brand_gradient)})"
    )
    out["--cta-gradient"] = f"linear-gradient(270deg, {', '.join(theme.cta_gradient)})"
    for key, value in theme.size.items():
        if isinstance(value, int):
            out[_var(key)] = f"{value}px"
    font = theme.font
    out["--font"] = f'"{font["family"]}", {font["fallback"]}'
    out["--font-mono"] = font["mono"]
    for key in ("size_base", "size_small", "size_tick", "size_value"):
        out[f"--font-{key.removeprefix('size_')}"] = f"{font[key]}px"
    out["--font-card-title"] = f"{font['size_card_title']}px"
    out["--font-wordmark"] = f"{font['size_wordmark']}px"
    out["--header-height"] = (
        f"{theme.size['header_row1'] + theme.size['header_row2']}px"
    )
    return out


@lru_cache(maxsize=2)
def font_face_css(folder: Path | None = None) -> str:
    """``@font-face`` rules for the bundled Vazirmatn files, embedded as base64:
    Streamlit 1.65.0 serves static files only from ``scripts/static/`` next to
    the main script and refuses paths that resolve outside it, so the fonts in
    ``assets/fonts/vazirmatn/`` are inlined (ADR-XXXX (demo-ui-design-system)).
    Offline, no CDN (UI-V08)."""
    from metis_auto.wiring.ui_config import load_theme

    folder = folder or FONT_DIR
    font = load_theme().font
    rules = []
    for entry in font["files"]:
        data = base64.b64encode((folder / entry["file"]).read_bytes()).decode()
        rules.append(
            "@font-face { "
            f'font-family: "{font["family"]}"; '
            f'src: url("data:font/woff2;base64,{data}") format("woff2"); '
            f"font-weight: {entry['weight']}; font-style: normal; "
            "font-display: swap; }"
        )
    return "\n".join(rules)


# --- the page CSS (UI-V01..V10, UI-H*, UI-C*, UI-K*, UI-T02) ----------------------
# Every rule below is scoped with ``:root`` by ``_scoped`` so it outranks
# Streamlit's own (emotion) class at equal specificity: those styles are
# inserted after ours.

_HIDE_CHROME = """
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stMainMenu"],
[data-testid="stAppDeployButton"], [data-testid="stStatusWidget"],
[data-testid="stHeaderActionElements"], [data-testid="stTopNavLinkContainer"],
[data-testid="stSidebarNav"] { display: none !important; }
[data-testid="stHeader"] { background: transparent; height: 0; min-height: 0;
  pointer-events: none; z-index: 1000000; }
[data-testid="stHeader"] button { pointer-events: auto; }
"""

_BASE = """
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {
  background: var(--bg); color: var(--text); }
.stApp, .stApp :is(p, span, div, label, input, textarea, button, li, td, th, a,
  h1, h2, h3, h4, h5, h6, summary, small) { font-family: var(--font); }
.stApp :is(code, pre, kbd), .stApp :is(code, pre) * { font-family: var(--font-mono); }
.stApp [data-testid="stIconMaterial"], .stApp .mx-icon {
  font-family: __ICON__ !important; font-weight: 400; letter-spacing: normal;
  font-style: normal; line-height: 1; }
.stApp [data-testid="stMarkdownContainer"] { color: inherit; }
.stApp :is(h1, h2, h3, h4) { color: var(--text); letter-spacing: 0; }
.stApp h1 { font-size: 26px; font-weight: 800; padding: 0; line-height: 1.5; }
.stApp h2 { font-size: var(--font-card-title); font-weight: 700; padding: 12px 0 0; }
.stApp h3 { font-size: 17px; font-weight: 700; padding: 8px 0 0; }
.stApp a { color: var(--accent-text); }
.stApp hr { border-color: var(--border); background: var(--border); }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
.stApp small { color: var(--text-muted); font-size: var(--font-small); }
[data-testid="stMainBlockContainer"] { max-width: 100%;
  padding: calc(var(--header-height) + 24px) var(--page-gutter) 48px; }
[data-testid="stBottomBlockContainer"] { padding-left: var(--page-gutter);
  padding-right: var(--page-gutter); }
.stApp ::selection { background: color-mix(in srgb, var(--accent) 30%, transparent); }
"""

_DIRECTION = """
[data-testid="stAppViewContainer"] { direction: rtl; }
[data-testid="stMainBlockContainer"], [data-testid="stSidebarContent"],
[data-testid="stBottomBlockContainer"], .st-key-mx-header, [role="dialog"],
[data-testid="stToast"], [role="listbox"] { direction: rtl; text-align: right; }
.stApp :is(textarea, input) { unicode-bidi: plaintext; text-align: start; }
[data-testid="stSidebar"] { border-inline-end: 0; border-inline-start: 1px solid
  var(--header-border); }
"""

_COMMON = """
.mx-ltr { direction: ltr; unicode-bidi: isolate; }
[data-testid="stVegaLiteChart"], [data-testid="stVegaLiteChart"] * { direction: ltr; }
[class*="st-key-rtl-"] { direction: rtl; text-align: right; width: 100%; }
[class*="st-key-ltr-"] { direction: ltr; text-align: left; width: 100%; }
[class*="st-key-rtl-"] > div, [class*="st-key-ltr-"] > div { width: 100%; }
[class*="st-key-rtl-"] :is(pre, code) { direction: ltr; text-align: left;
  unicode-bidi: isolate; }
[class*="st-key-rtl-"] :is(p, li) { line-height: 1.9; }
[class*="st-key-badge-"] p { font-size: var(--font-small); color: var(--text-muted);
  margin: 0; }
"""

_HEADER = """
.st-key-mx-header { position: fixed; top: 0; left: 0; right: 0; z-index: 999990;
  background: var(--header); border-bottom: 1px solid var(--header-border);
  padding: 0 var(--page-gutter); gap: 0; width: 100%; }
.st-key-mx-header-row1 { height: var(--header-row1); min-height: var(--header-row1);
  align-items: center; flex-wrap: nowrap; }
.st-key-mx-header-row2 { height: var(--header-row2); min-height: var(--header-row2);
  align-items: flex-start; gap: 6px; flex-wrap: nowrap; }
.st-key-mx-header-tools { align-items: center; gap: 22px; flex-wrap: nowrap; }
.mx-brand { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.mx-wordmark { font-size: var(--font-wordmark); font-weight: 800; color: var(--text);
  line-height: 1; }
.mx-brand-sub { font-size: 11px; color: var(--text-muted); border: 1px solid
  var(--border); border-radius: var(--radius-pill); padding: 2px 8px;
  line-height: 1.4; }
.mx-budget { font-size: 15px; color: var(--text); white-space: nowrap; }
.mx-budget b { color: var(--accent-text); font-weight: 700; }
.mx-chip { display: inline-flex; align-items: center; gap: 6px; height: 28px;
  padding: 0 12px; border-radius: var(--radius-pill); border: 1px solid var(--border);
  background: transparent; color: var(--text); font-size: var(--font-small);
  white-space: nowrap; }
.mx-chip .mx-icon { font-size: 17px; color: var(--text-muted); }
.mx-chip--fake .mx-dot { background: var(--success); }
.mx-chip--live { border-color: color-mix(in srgb, var(--warning) 45%, transparent);
  color: var(--warning); }
.mx-chip--live .mx-dot { background: var(--warning); }
.mx-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
/* navigation tabs (UI-H03): label with a line icon, active = filled pill */
.st-key-mx-header-row2 [data-testid="stPageLink-NavLink"] {
  height: var(--tab-height); padding: 0 14px; border-radius: var(--radius-control);
  gap: 8px; background: transparent; text-decoration: none; margin: 0; }
.st-key-mx-header-row2 [data-testid="stPageLink-NavLink"] :is(p, span) {
  color: var(--nav-text) !important; font-size: 15px; font-weight: 500; }
.st-key-mx-header-row2 [data-testid="stPageLink-NavLink"]
  [data-testid="stIconMaterial"] {
  font-size: 20px; }
.st-key-mx-header-row2 [data-testid="stPageLink-NavLink"]:hover {
  background: color-mix(in srgb, var(--elevated) 55%, transparent); }
.st-key-mx-header-row2 [class*="st-key-mxtab-active"]
  [data-testid="stPageLink-NavLink"] {
  background: var(--elevated); }
.st-key-mx-header-row2 [class*="st-key-mxtab-active"]
  [data-testid="stPageLink-NavLink"] p {
  font-weight: 700; color: var(--text) !important; }
/* theme toggle (UI-T01, images 3 and 4): pill track, white knob with sun or moon;
   on (dark) puts the knob at the end of the line: left in RTL, as in image 4 */
.st-key-ui_dark [data-testid="stCheckbox"] label { gap: 0; min-height: 0; }
.st-key-ui_dark [data-testid="stCheckbox"] label > div:first-of-type {
  width: var(--toggle-width); height: var(--toggle-height); border-radius:
  var(--radius-pill); background: var(--toggle-track) !important; padding: 0 2px;
  justify-content: flex-start; align-items: center; margin: 0; }
.st-key-ui_dark [data-testid="stCheckbox"] label[data-selected="true"] >
  div:first-of-type {
  justify-content: flex-end; }
.st-key-ui_dark [data-testid="stCheckbox"] label > div:first-of-type > div {
  width: 20px; height: 20px; transform: none !important; background:
  var(--toggle-knob) !important; border-radius: 50%; display: flex;
  align-items: center; justify-content: center; box-shadow: 0 1px 2px
  color-mix(in srgb, var(--shadow) 30%, transparent); }
.st-key-ui_dark [data-testid="stCheckbox"] label > div:first-of-type > div::after {
  font-family: __ICON__; content: "__KNOB_ICON__"; font-size: 15px; line-height: 1;
  color: var(--toggle-icon); }
.st-key-ui_dark [data-testid="stWidgetLabel"] { display: none; }
/* language switch (فا / EN): a compact pill pair */
.st-key-ui_lang [role="radiogroup"] { gap: 0; border: 1px solid var(--border);
  border-radius: var(--radius-pill); padding: 2px; }
.st-key-ui_lang button { min-height: 26px; height: 26px; padding: 0 12px; border: 0;
  border-radius: var(--radius-pill); background: transparent;
  color: var(--text-muted); }
.st-key-ui_lang button :is(p, span, div) { color: inherit;
  font-size: var(--font-small); }
.st-key-ui_lang button[aria-checked="true"] { background: var(--elevated);
  color: var(--text); font-weight: 700; }
"""

_SIDEBAR = """
[data-testid="stSidebar"] { background: var(--header); border-inline-end: 1px solid
  var(--header-border); top: var(--header-height);
  height: calc(100vh - var(--header-height)); }
[data-testid="stSidebar"] > div, [data-testid="stSidebarContent"] {
  background: var(--header); color: var(--text); }
[data-testid="stSidebarHeader"] { height: 36px; min-height: 36px; padding: 4px 8px; }
[data-testid="stSidebarUserContent"] { padding-top: 0; }
[data-testid="stSidebar"] h2 { font-size: 16px; padding-top: 4px; }
"""

_CARDS = """
[class*="st-key-mx-card"], [class*="st-key-mx-kpi"] { background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: var(--card-padding); box-shadow: 0 1px 2px
  color-mix(in srgb, var(--shadow) 4%, transparent); }
[class*="st-key-mx-kpi"] { min-height: var(--kpi-min-height); gap: 6px;
  justify-content: flex-start; flex: 1 1 0; min-width: 120px; }
[class*="st-key-mx-row"] { gap: var(--card-gap); flex-wrap: wrap; }
[class*="st-key-mx-kpi-cost"] { padding: 12px; min-width: 0;
  min-height: 96px; flex-shrink: 1; }
[class*="st-key-mx-kpi-cost"] [data-testid="stMetricValue"] :is(div, p) {
  font-size: 18px; }
[class*="st-key-mx-kpi-cost"] [data-testid="stMetricLabel"] :is(div, p) {
  white-space: normal; overflow: visible; }
[data-testid="stMetricValue"] :is(div, p) { overflow: visible; text-overflow: clip; }
[class*="st-key-mx-row-cost"] { gap: 12px; flex-wrap: nowrap; }
[class*="st-key-mx-filters"] { gap: 12px; }
[class*="st-key-mx-sec-"] { gap: 16px; margin-top: 12px; }
.mx-card-title { font-size: var(--font-card-title); font-weight: 700;
  color: var(--text);
  margin: 0 0 4px; line-height: 1.5; }
.mx-section-title { font-size: 18px; font-weight: 700; color: var(--text);
  white-space: nowrap; }
[data-testid="stMetric"] { background: transparent; border: 0; padding: 0; }
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {
  color: var(--text-muted); font-size: var(--font-small); font-weight: 500; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] :is(div, p) {
  color: var(--text); font-size: var(--font-value); font-weight: 700;
  font-variant-numeric: tabular-nums; unicode-bidi: isolate; line-height: 1.35; }
[class*="st-key-mx-kpi"] [data-testid="stCaptionContainer"] p { margin: 0; }
"""

_CONTROLS = """
/* dropdowns (UI-K01): react-aria combobox in Streamlit 1.65 */
[data-testid="stSelectbox"] [role="group"] { background: var(--control);
  border: 1px solid var(--border); border-radius: var(--radius-control);
  min-height: var(--control-height); }
[data-testid="stSelectbox"] [role="group"]:focus-within { border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent); }
[data-testid="stSelectbox"] [role="group"] :is(input, button) {
  background: transparent; color: var(--text); border: 0; }
[data-testid="stSelectbox"] [role="group"] svg { color: var(--text-muted); }
[role="listbox"] { background: var(--control); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--radius-control); }
[role="listbox"] [role="option"] { color: var(--text); background: transparent; }
[role="listbox"] [role="option"]:is(:hover, [data-focused="true"],
  [aria-selected="true"]) {
  background: var(--elevated); }
[data-testid="stPopover"], [data-testid="stSelectboxVirtualDropdown"] {
  background: var(--control); }
/* inputs (UI-K08) */
[data-testid="stTextAreaRootElement"], [data-testid="stTextInputRootElement"] {
  background: var(--control); border: 1px solid var(--border);
  border-radius: var(--radius-control); }
[data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stTextInputRootElement"]:focus-within { border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent); }
.stApp :is(textarea, input) { color: var(--text); background: transparent;
  caret-color: var(--accent); }
.stApp :is(textarea, input)::placeholder { color: var(--text-muted); opacity: 1; }
[data-testid="stWidgetLabel"] :is(p, label) { color: var(--text); font-weight: 500; }
/* buttons (UI-K04): primary accent, secondary outlined, tertiary text */
.stApp button[data-testid^="stBaseButton"] { min-height: var(--button-height);
  border-radius: var(--radius-control); font-weight: 500; }
.stApp button[data-testid="stBaseButton-primary"] { background: var(--accent);
  border: 1px solid var(--accent); color: var(--on-accent); }
.stApp button[data-testid="stBaseButton-primary"] :is(p, span) { color:
  var(--on-accent); }
.stApp button[data-testid="stBaseButton-secondary"] { background: transparent;
  border: 1px solid var(--border); color: var(--text); }
.stApp button[data-testid="stBaseButton-secondary"]:hover { border-color: var(--accent);
  color: var(--accent-text); }
.stApp button[data-testid="stBaseButton-tertiary"] { background: transparent;
  border: 0; color: var(--accent-text); min-height: 28px; padding: 0; }
.stApp button[data-testid="stBaseButton-tertiary"] p { color: var(--accent-text); }
.stApp button:disabled { opacity: 0.45; cursor: not-allowed; }
/* reusable styles for Stages 3 and 4: pills and the one gradient CTA per screen */
[class*="st-key-mx-pill"] button { border-radius: var(--radius-pill); }
[class*="st-key-mx-cta"] button { background: var(--cta-gradient); border: 0;
  border-radius: var(--radius-pill); color: var(--on-accent); font-weight: 700;
  padding: 0 28px; }
[class*="st-key-mx-cta"] button :is(p, span) { color: var(--on-accent); }
/* toggles (UI-K03): react-aria switch; on = accent, off = elevated track */
[data-testid="stCheckbox"] label > div:first-of-type { background: var(--elevated); }
[data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {
  background: var(--accent); }
[data-testid="stCheckbox"] label > div:first-of-type > div { background:
  var(--toggle-knob); }
[data-testid="stCheckbox"] label :is(p, span) { color: var(--text); }
/* radios */
[data-testid="stRadioOption"] > div:first-of-type > div:first-child {
  border-color: var(--text-muted); background: transparent; }
[data-testid="stRadioOption"][data-selected="true"] > div:first-of-type >
  div:first-child {
  border-color: var(--accent); background: var(--accent); }
[data-testid="stRadioOption"][data-selected="true"] > div:first-of-type >
  div:first-child > div {
  background: var(--on-accent); }
[data-testid="stRadioOption"] p { color: var(--text); }
/* segmented controls and pills */
[data-testid="stButtonGroup"] button { border-color: var(--border);
  background: var(--control); color: var(--text); }
[data-testid="stButtonGroup"] button[aria-checked="true"] { background: var(--elevated);
  color: var(--text); border-color: var(--accent); }
/* focus ring on every control (UI-K02) */
.stApp :is(button, a, input, textarea, summary, [role="tab"], [role="switch"],
  [role="radio"], [role="checkbox"], [role="combobox"], [tabindex]):focus-visible {
  outline: var(--focus-ring) solid var(--accent) !important; outline-offset: 2px; }
[data-testid="stCheckbox"] label:has(input:focus-visible) > div:first-of-type,
[data-testid="stRadioOption"]:has(input:focus-visible) > div:first-of-type {
  outline: var(--focus-ring) solid var(--accent); outline-offset: 2px;
  border-radius: var(--radius-pill); }
/* tabs */
[data-testid="stTabs"] [role="tablist"] { gap: 16px; border-bottom: 1px solid
  var(--border); }
[data-testid="stTab"] { color: var(--text-muted); background: transparent; }
[data-testid="stTab"] p { color: inherit; font-size: 14px; }
[data-testid="stTab"][aria-selected="true"] { color: var(--text); font-weight: 700; }
[data-testid="stTab"] .react-aria-SelectionIndicator { background: var(--accent); }
/* expanders, tooltips, toasts, dialogs */
[data-testid="stExpander"] details { background: transparent; border: 1px solid
  var(--border); border-radius: var(--radius-control); }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary :is(p, span) {
  color: var(--text); }
[data-testid="stExpander"] summary:hover :is(p, span) { color: var(--accent-text); }
[data-testid="stTooltipContent"], [role="tooltip"] { background: var(--header);
  color: var(--text); border: 1px solid var(--border); }
[data-testid="stToast"] { background: var(--header); color: var(--text);
  border: 1px solid var(--border); }
[role="dialog"] { background: var(--surface); color: var(--text); }
/* progress (budget bars) */
[data-testid="stProgressBarTrack"] { background: var(--elevated);
  border-radius: var(--radius-pill); }
[data-testid="stProgressBarTrack"] > div { background: var(--accent);
  border-radius: var(--radius-pill); }
[data-testid="stProgress"] p { color: var(--text-muted); font-size: var(--font-small); }
/* tables */
[data-testid="stTable"] table { border-collapse: collapse; width: 100%;
  background: transparent; border: 0; }
[data-testid="stTable"] :is(th, td) { border: 0; border-bottom: 1px solid
  var(--border); padding: 8px 10px; text-align: start !important;
  font-size: var(--font-small); background: transparent; color: var(--text);
  unicode-bidi: plaintext; }
[data-testid="stTable"] th { color: var(--text-muted); font-weight: 500; }
[data-testid="stTable"], [data-testid="stTable"] > div { border-color: var(--border);
  border-radius: var(--radius-control); }
[data-testid="stTable"] tbody th { color: var(--text); }
/* chat (UI-K08) */
[data-testid="stChatMessage"] { background: var(--surface); border: 1px solid
  var(--border); border-radius: 12px; padding: 12px 16px; gap: 12px; }
[data-testid="stChatMessage"], [data-testid="stChatMessage"] :is(p, li, strong, em) {
  color: var(--text); }
.stApp :not(pre) > code { background: var(--elevated); color: var(--text);
  border-radius: 4px; padding: 1px 6px; font-size: 0.85em; }
.stApp pre { background: var(--control); border: 1px solid var(--border);
  border-radius: var(--radius-control); }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: var(--elevated); border-color: transparent; }
[data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {
  background: var(--accent); color: var(--on-accent); border-radius: 50%; }
[data-testid="stChatInput"] > div { background: var(--control); border: 1px solid
  var(--border); border-radius: 12px; }
[data-testid="stChatInput"] > div div { background-color: transparent; }
[data-testid="stChatInput"]:focus-within > div { border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent); }
[data-testid="stChatInputSubmitButton"] { background: var(--accent);
  color: var(--on-accent); border-radius: var(--radius-control); }
[data-testid="stChatInputSubmitButton"]:disabled { background: var(--elevated);
  color: var(--text-muted); }
"""

_STATES = """
/* banners (UI-K06) and error cards (UI-K05) */
[data-testid="stAlertContainer"] { border-radius: var(--radius-control); border: 1px
  solid var(--border); color: var(--text); background: var(--surface); }
[data-testid="stAlertContainer"] :is(p, li, div, span, strong) { color: var(--text); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {
  background: color-mix(in srgb, var(--info) 9%, var(--surface));
  border-color: color-mix(in srgb, var(--info) 35%, transparent); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {
  background: color-mix(in srgb, var(--warning) 10%, var(--surface));
  border-color: color-mix(in srgb, var(--warning) 40%, transparent); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
  background: color-mix(in srgb, var(--danger) 10%, var(--surface));
  border-color: color-mix(in srgb, var(--danger) 45%, transparent); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
  background: color-mix(in srgb, var(--success) 10%, var(--surface));
  border-color: color-mix(in srgb, var(--success) 40%, transparent); }
[data-testid="stAlertContainer"] [data-testid="stIconMaterial"] { color:
  var(--text-muted); }
/* empty, disabled and loading states (UI-K05) */
.mx-empty { display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 28px 16px; border: 1px dashed var(--border); border-radius:
  var(--radius-card); color: var(--text-muted); text-align: center; }
.mx-empty .mx-icon { font-size: 28px; color: var(--text-muted); }
.mx-empty-line { color: var(--text); font-size: var(--font-base); }
.mx-empty-action { color: var(--text-muted); font-size: var(--font-small);
  max-width: 520px; }
.mx-reason { color: var(--text-muted); font-size: var(--font-small); }
[data-testid="stSpinner"] i { border-color: var(--accent) transparent transparent; }
[data-testid="stSpinner"] p { color: var(--text-muted); }
/* chart tooltips follow the theme (UI-G06) */
#vg-tooltip-element { background: var(--chart-tooltip-bg) !important; color:
  var(--text) !important; border: 1px solid var(--border) !important; border-radius:
  var(--radius-control) !important; font-family: var(--font) !important; box-shadow:
  0 4px 12px color-mix(in srgb, var(--shadow) 14%, transparent) !important; }
#vg-tooltip-element td.key { color: var(--text-muted) !important; }
#vg-tooltip-element td.value { color: var(--text) !important; }
[data-testid="stVegaLiteChart"] details, .vega-embed summary { display: none; }
"""


def _split_selectors(head: str) -> list[str]:
    """Split a selector list at top-level commas (not inside ``:is(…)``)."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(head):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(head[start:i])
            start = i + 1
    parts.append(head[start:])
    return [p.strip() for p in parts if p.strip()]


def _scoped(css: str) -> str:
    """Prefix every selector with ``:root`` (one class of specificity)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.sub(
        r"([^{}]+)\{",
        lambda m: ", ".join(f":root {s}" for s in _split_selectors(m.group(1))) + " {",
        css,
    )


def page_css(theme: Theme, lang: str) -> str:
    """The whole style sheet for one mode and language, ``<style>`` included:
    the ``:root`` variables first, then the font, then rules that only use
    ``var(--…)``."""
    rtl = direction(lang) == "rtl"
    variables = css_variables(theme) | {"--dir": direction(lang)}
    root = ":root { " + " ".join(f"{k}: {v};" for k, v in variables.items())
    root += f" color-scheme: {theme.mode}; }}"
    knob = "dark_mode" if theme.mode == "dark" else "light_mode"
    blocks = [
        _HIDE_CHROME,
        _BASE,
        _DIRECTION if rtl else "",
        _COMMON,
        _HEADER,
        _SIDEBAR,
        _CARDS,
        _CONTROLS,
        _STATES,
    ]
    rules = _scoped("\n".join(b for b in blocks if b))
    rules = rules.replace("__ICON__", ICON_FONT).replace("__KNOB_ICON__", knob)
    return f"<style>{root}\n{font_face_css()}\n{rules}</style>"


# --- Altair (UI-G01..G07) -------------------------------------------------------------


def altair_config(theme: Theme, lang: str) -> dict[str, Any]:
    """A Vega-Lite ``config`` for one mode: the screenshots' look (dashed faint
    grid, thin muted axes, square legend swatches centred below, the mode's
    palettes). Charts stay left to right in both languages (dates, money and
    model ids read LTR); titles live in the card, not in the chart."""
    direction(lang)
    c, chart, font = theme.colours, theme.chart, theme.font
    family = f"{font['family']}, {font['fallback']}"
    return {
        "background": c["surface"],
        "font": family,
        "padding": {"top": 8, "right": 8, "bottom": 4, "left": 4},
        "view": {"stroke": None},
        "axis": {
            "gridColor": chart["grid"],
            "gridDash": [3, 3],
            "gridWidth": 1,
            "domainColor": chart["axis"],
            "domainWidth": 1,
            "tickColor": chart["axis"],
            "tickSize": 4,
            "labelColor": c["text_muted"],
            "labelFont": family,
            "labelFontSize": font["size_tick"],
            "labelPadding": 4,
            "titleColor": c["text_muted"],
            "titleFont": family,
            "titleFontSize": font["size_small"] - 1,
            "titleFontWeight": 500,
            "titlePadding": 8,
        },
        "legend": {
            "orient": "bottom",
            "direction": "horizontal",
            "symbolType": "square",
            "symbolSize": 80,
            "symbolStrokeWidth": 0,
            "labelColor": c["text"],
            "labelFont": family,
            "labelFontSize": font["size_small"] - 1,
            "titleColor": c["text_muted"],
            "columnPadding": 18,
            "padding": 6,
        },
        "title": {
            "color": c["text"],
            "font": family,
            "fontSize": 16,
            "fontWeight": 700,
        },
        "range": {
            "category": [
                chart["cat_1"],
                chart["cat_2"],
                chart["series_a"],
                chart["series_b"],
                chart["trend"],
            ],
        },
        "line": {"color": chart["trend"], "strokeWidth": 2, "interpolate": "monotone"},
        "area": {
            "color": chart["trend_fill"],
            "line": False,
            "interpolate": "monotone",
        },
        "point": {"color": chart["trend"], "filled": True, "size": 30},
        "bar": {"color": chart["cat_1"], "cornerRadiusEnd": 3},
        "arc": {"stroke": c["border"], "strokeWidth": 1},
        "text": {"color": c["text_muted"], "font": family},
    }


# --- fragments: header, chips, states ------------------------------------------------


def _icon(name: str) -> str:
    return f'<span class="mx-icon" aria-hidden="true">{html.escape(name)}</span>'


def header_brand_html(t: Text) -> str:
    """The text wordmark and the prototype label (UI-H02, UI-R08): no logo is
    drawn; ``assets/brand/logo.svg`` does not exist, and the Metis logo is never
    redrawn or cropped."""
    return (
        '<div class="mx-brand">'
        f'<span class="mx-wordmark">{html.escape(t("brand_wordmark"))}</span>'
        f'<span class="mx-brand-sub mx-ltr">{PROTOTYPE_LABEL}</span>'
        "</div>"
    )


def chip_html(text: str, *, kind: str = "neutral", icon: str | None = None) -> str:
    """A small rounded chip (mode, local demo); ``kind`` picks the dot colour."""
    lead = _icon(icon) if icon else ""
    if kind in ("fake", "live"):
        lead = '<span class="mx-dot" aria-hidden="true"></span>'
    css = f"mx-chip mx-chip--{html.escape(kind)}"
    return f'<span class="{css}">{lead}{html.escape(text)}</span>'


def _money(value: Decimal, currency: str) -> str:
    return f"${value:,.2f}" if currency == "USD" else f"{value:,.2f} {currency}"


def budget_html(t: Text, *, live: bool, budget: BudgetView | None) -> str:
    """The budget in the place of Metis's credit (UI-H04): fake mode says so;
    live mode shows the lifetime budget left. No top-up (nothing fake)."""
    if not live:
        return f'<div class="mx-budget"><b>{html.escape(t("fake_mode"))}</b></div>'
    if budget is None:
        return f'<div class="mx-budget">{html.escape(t("budget_none"))}</div>'
    left = max(budget.lifetime_cap - budget.lifetime_spent, Decimal(0))
    return (
        f'<div class="mx-budget" title="{html.escape(t("budget_title"))}">'
        f"{html.escape(t('budget_left'))} "
        f"<b>{ltr_html(_money(left, budget.currency))}</b>"
        "</div>"
    )


def labelled(name: str, value: str) -> str:
    """``name: value``, for the filter row's selects, whose own label is hidden
    as in the screenshots' filter controls."""
    return f"{name}: {value}"


def kind_rows(rows: list[dict[str, Any]], t: Text) -> list[dict[str, Any]]:
    """Waterfall rows with the bar kind translated (``kind_label``) for the
    legend; the rows are otherwise unchanged (UI-G07)."""
    return [
        row | {"kind_label": t(f"kind_{row['kind'].replace(' ', '_')}")} for row in rows
    ]


def kind_scale(theme: Theme, t: Text) -> tuple[list[str], list[str]]:
    """Legend domain (translated kinds) and colours, in the same order."""
    kinds = theme.kinds
    return [t(f"kind_{k.replace(' ', '_')}") for k in kinds], list(kinds.values())


def card_title_html(title: str) -> str:
    return f'<div class="mx-card-title">{html.escape(title)}</div>'


def section_title_html(title: str) -> str:
    return f'<div class="mx-section-title">{html.escape(title)}</div>'


def empty_state_html(icon: str, line: str, action: str | None = None) -> str:
    """UI-K05 empty state: an icon, one line and the action that fills it;
    never a bare gray block (image 6's workflow card)."""
    hint = f'<div class="mx-empty-action">{html.escape(action)}</div>' if action else ""
    return (
        f'<div class="mx-empty">{_icon(icon)}'
        f'<div class="mx-empty-line">{html.escape(line)}</div>{hint}</div>'
    )


def reason_html(text: str) -> str:
    """The one-line reason under a disabled control (UI-K05, UI-R04)."""
    return f'<div class="mx-reason">{_icon("block")} {html.escape(text)}</div>'
