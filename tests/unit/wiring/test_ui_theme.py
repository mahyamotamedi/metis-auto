"""The demo UI's design system (spec §2, Stage 2): tokens from
``config/demo/theme.toml`` for both modes, the CSS generator, the Altair config
per mode, the bundled font, LTR isolation and the header fragments. Config
files and wiring only, no Streamlit."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.wiring.demo_ui import BudgetView
from metis_auto.wiring.ui_config import (
    CHART_KEYS,
    COLOUR_KEYS,
    DEFAULT_LANGUAGE,
    DEFAULT_THEME,
    FONT_DIR,
    THEME_PATH,
    THEMES,
    TOGGLE_KEYS,
    load_strings,
    load_theme,
    translator,
    ui_state,
)
from metis_auto.wiring.ui_style import (
    LRI,
    PDI,
    altair_config,
    budget_html,
    css_variables,
    empty_state_html,
    font_face_css,
    header_brand_html,
    ltr,
    ltr_html,
    page_css,
)

REPO = Path(__file__).resolve().parents[3]
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
PAGE_FILES = [
    REPO / "scripts" / "demo_ui.py",
    REPO / "scripts" / "demo_pages" / "results.py",
    REPO / "scripts" / "demo_pages" / "workspace.py",
]
STYLE_FILE = REPO / "src" / "metis_auto" / "wiring" / "ui_style.py"


# --- tokens -------------------------------------------------------------------


def test_tokens_load_for_both_modes_with_no_missing_keys():
    assert THEMES == ("dark", "light") and DEFAULT_THEME == "dark"
    themes = {mode: load_theme(mode) for mode in THEMES}
    for mode, theme in themes.items():
        assert theme.mode == mode
        assert set(theme.colours) == set(COLOUR_KEYS), mode
        assert set(theme.toggle) == set(TOGGLE_KEYS), mode
        assert set(theme.chart) == set(CHART_KEYS), mode
        for value in (*theme.colours.values(), *theme.toggle.values()):
            assert re.fullmatch(r"#[0-9A-F]{6}", value), (mode, value)
        assert all(re.fullmatch(r"#[0-9A-F]{6}", v) for v in theme.chart.values())
        assert len(theme.brand_gradient) >= 2 and len(theme.cta_gradient) >= 2
    with pytest.raises(ValueError):
        load_theme("sepia")


def test_chart_palettes_change_with_the_mode():
    """The screenshots' series colours differ per mode (images 3-6)."""
    dark, light = load_theme("dark"), load_theme("light")
    for key in ("trend", "series_a", "series_b", "cat_1", "cat_2", "grid"):
        assert dark.chart[key] != light.chart[key], key
    assert dark.kinds["total"] == dark.chart["cat_1"]
    assert dark.kinds["saving"] == dark.chart["cat_2"]
    assert light.kinds["total"] == light.chart["cat_1"]


def test_a_missing_token_is_refused(tmp_path):
    text = THEME_PATH.read_text(encoding="utf-8")
    broken = tmp_path / "theme.toml"
    broken.write_text(re.sub(r"(?m)^surface = .*\n", "", text, count=1), "utf-8")
    with pytest.raises(ValueError, match="surface"):
        load_theme("dark", broken)


def test_every_value_records_its_source():
    """Owner decision (1): each value says whether it was sampled or estimated."""
    lines = [
        line
        for line in THEME_PATH.read_text(encoding="utf-8").splitlines()
        if re.match(r'^\w+ = \[?"#', line)
    ]
    assert len(lines) > 50
    for line in lines:
        assert re.search(r"# (sampled|estimated)", line), line


# --- CSS ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", THEMES)
@pytest.mark.parametrize("lang", ("fa", "en"))
def test_css_emits_every_token_as_a_variable(mode, lang):
    theme = load_theme(mode)
    variables = css_variables(theme)
    css = page_css(theme, lang)
    for key in COLOUR_KEYS:
        name = f"--{key.replace('_', '-')}"
        assert variables[name] == theme.colours[key]
        assert f"{name}: {theme.colours[key]};" in css
    for key in CHART_KEYS:
        assert f"--chart-{key.replace('_', '-')}: {theme.chart[key]};" in css
    for key in TOGGLE_KEYS:
        assert f"--toggle-{key}: {theme.toggle[key]};" in css
    assert "--brand-gradient: linear-gradient(" in css
    assert "--cta-gradient: linear-gradient(" in css
    assert f"--radius-card: {theme.size['radius_card']}px;" in css
    # outside the :root block, colours are only var(--...) references
    body = css.split("}", 1)[1]
    assert not HEX.search(body.replace("#vg-tooltip-element", ""))


def test_css_direction_follows_the_language():
    theme = load_theme("dark")
    layout = '[data-testid="stAppViewContainer"] { direction: rtl; }'
    assert layout in page_css(theme, "fa")
    assert layout not in page_css(theme, "en")  # UI-V09
    assert "--dir: rtl;" in page_css(theme, "fa")
    assert "--dir: ltr;" in page_css(theme, "en")


def test_css_has_focus_rings_and_no_avoid_list_styles():
    css = page_css(load_theme("light"), "fa")
    assert ":focus-visible" in css and "var(--accent)" in css  # UI-K02
    assert "backdrop-filter" not in css  # UI-V02: no glassmorphism
    assert "@keyframes" not in css  # no animations of our own
    assert css.count("var(--brand-gradient)") + css.count("var(--cta-gradient)") <= 3


def test_no_hex_colour_outside_the_theme_file():
    """UI-T05: page files and the CSS generator name no colour."""
    for path in [*PAGE_FILES, STYLE_FILE]:
        source = path.read_text(encoding="utf-8")
        assert not HEX.findall(source), path.name
        assert "rgb(" not in source and "hsl(" not in source, path.name


# --- font ---------------------------------------------------------------------


def test_font_is_bundled_locally_and_never_from_a_cdn():
    css = font_face_css()
    theme = load_theme()
    for entry in theme.font["files"]:
        assert (REPO / FONT_DIR / entry["file"]).is_file(), entry["file"]
        assert f"font-weight: {entry['weight']};" in css
    assert css.count("@font-face") == len(theme.font["files"])
    assert "data:font/woff2;base64," in css
    assert "http://" not in css and "https://" not in css and "url(app/" not in css
    assert (REPO / FONT_DIR / "OFL.txt").is_file()
    assert "Vazirmatn" in page_css(theme, "fa")


# --- Altair -------------------------------------------------------------------


@pytest.mark.parametrize("mode", THEMES)
def test_altair_config_uses_the_mode_palette(mode):
    theme = load_theme(mode)
    config = altair_config(theme, "fa")
    assert config["background"] == theme.colours["surface"]
    assert config["axis"]["gridColor"] == theme.chart["grid"]
    assert config["axis"]["gridDash"]  # dashed grid (images 3-6)
    assert config["axis"]["labelColor"] == theme.colours["text_muted"]
    assert config["axis"]["domainColor"] == theme.chart["axis"]
    assert config["legend"]["orient"] == "bottom"
    assert config["legend"]["symbolType"] == "square"
    assert config["range"]["category"][:2] == [
        theme.chart["cat_1"],
        theme.chart["cat_2"],
    ]
    assert config["line"]["color"] == theme.chart["trend"]
    assert config["arc"]["stroke"] == theme.colours["border"]  # hairline gaps
    assert config["view"]["stroke"] is None
    assert theme.font["family"] in config["font"]


def test_altair_configs_differ_between_modes():
    dark = altair_config(load_theme("dark"), "en")
    light = altair_config(load_theme("light"), "en")
    assert dark["range"]["category"] != light["range"]["category"]
    assert dark["background"] != light["background"]


# --- LTR isolation (UI-V07) -----------------------------------------------------


def test_ltr_isolates_numbers_money_and_model_ids():
    assert ltr("$0.001921") == f"{LRI}$0.001921{PDI}"
    assert ltr(ltr("gpt-4.1-nano")) == f"{LRI}gpt-4.1-nano{PDI}"  # idempotent
    assert ltr(12345) == f"{LRI}12345{PDI}"
    html = ltr_html("gpt-4.1-nano <b>")
    assert html.startswith('<bdi dir="ltr"') and "&lt;b&gt;" in html


# --- strings and state ----------------------------------------------------------


def _keys_used_in_pages() -> set[str]:
    found: set[str] = set()
    for path in PAGE_FILES:
        source = path.read_text(encoding="utf-8")
        found |= set(re.findall(r"\bS\(\s*\"([a-z0-9_]+)\"", source))
        found |= set(re.findall(r"labels\[\"([a-z0-9_]+)\"\]", source))
    return found


def test_every_key_used_by_the_pages_exists_in_fa_and_en():
    strings = load_strings()
    used = _keys_used_in_pages()
    assert len(used) > 40  # the chat page and the header go through the table too
    missing = sorted(k for k in used if k not in strings.table)
    assert missing == []
    for key in used:
        assert strings.text(key, "fa").strip() and strings.text(key, "en").strip()


def test_translator_fills_fields_and_wraps_none():
    t = translator(load_strings(), "en")
    assert t("nav_results") == "Results"
    assert "3" in t("notice_new_user", n=3)


def test_query_parameters_restore_theme_and_language():
    assert ui_state({}) == (DEFAULT_THEME, DEFAULT_LANGUAGE) == ("dark", "fa")
    assert ui_state({"theme": "light", "lang": "en"}) == ("light", "en")
    assert ui_state({"theme": ["light"], "lang": ["en"]}) == ("light", "en")
    assert ui_state({"theme": "neon", "lang": "de"}) == ("dark", "fa")  # refused
    # the session's choice wins over a stale URL value
    assert ui_state({"theme": "light"}, theme="dark", lang="en") == ("dark", "en")


# --- header fragments -------------------------------------------------------------


def test_brand_is_a_text_wordmark_without_an_imitation_logo():
    t = translator(load_strings(), "fa")
    html = header_brand_html(t)
    # Stage 2b (owner review point 1): متیس‌اتو, never Metis's name alone
    assert "متیس‌اتو" in html and "نمونه‌ی آزمایشی" in html
    assert "<svg" not in html and "<img" not in html  # no logo asset in the repo
    assert not (REPO / "assets" / "brand" / "logo.svg").exists()


def test_budget_shows_the_amount_left_without_a_top_up():
    """Stage 2b (owner review point 2): the real budget in both modes; the
    mode is only in the chip."""
    strings = load_strings()
    fa, en = translator(strings, "fa"), translator(strings, "en")
    assert "نامعلوم" in budget_html(fa, budget=None)
    assert "unknown" in budget_html(en, budget=None)
    budget = BudgetView(
        currency="USD",
        lifetime_spent=Decimal("2.5"),
        lifetime_cap=Decimal("10"),
        lifetime_fraction=0.25,
        run_spent=Decimal("0"),
        run_cap=None,
        run_fraction=None,
        warn_at=(0.5, 0.8),
        crossed=None,
    )
    html = budget_html(en, budget=budget)
    assert "7.50" in html and '<bdi dir="ltr"' in html
    assert "+" not in html.replace("&#43;", "")  # no top-up button


def test_empty_state_is_icon_line_and_action_never_a_bare_block():
    html = empty_state_html("inbox", "No lever results yet.", "Run a replay")
    assert "inbox" in html and "No lever results yet." in html
    assert "Run a replay" in html and 'class="mx-empty"' in html


def test_dynamic_keys_exist_and_banner_titles_match_the_backend():
    """Keys the chat page builds from values (routing, compression, banner
    state) exist; the English banner titles equal ``wiring.demo_ui``'s."""
    from metis_auto.wiring.chat import CompressionMode, RoutingMode
    from metis_auto.wiring.demo_ui import (
        DEMO_CAVEAT,
        PREMIUM_CAVEATS,
        blocked_banner,
        live_banner,
    )

    strings = load_strings()
    keys = [f"routing_{m.value}" for m in RoutingMode]
    keys += [f"compression_{m.value}" for m in CompressionMode]
    keys += [
        f"router_{m}"
        for m in ("off", "local", "hosted", "hybrid_local_first", "hybrid_hosted_first")
    ]
    keys += ["mode_fake_option", "mode_live_option", "nav_chat", "nav_results"]
    for key in keys:
        assert strings.text(key, "fa") and strings.text(key, "en"), key
    banners = [
        live_banner(live=False, allowed=True, reasons=()),
        live_banner(live=True, allowed=True, reasons=()),
        live_banner(live=True, allowed=True, reasons=(), stopped="[SYNTHETIC]"),
        blocked_banner("[SYNTHETIC]"),
    ]
    for banner in banners:
        assert strings.text(f"banner_{banner.state}", "en") == banner.title
    assert strings.text("premium_caveat", "en") == PREMIUM_CAVEATS
    assert strings.text("demo_caveat", "en") == DEMO_CAVEAT


def test_streamlit_first_paint_uses_the_dark_tokens():
    """UI-T04: ``.streamlit/config.toml`` [theme] equals the dark tokens."""
    import tomllib

    config = tomllib.loads((REPO / ".streamlit" / "config.toml").read_text("utf-8"))
    theme, dark = config["theme"], load_theme("dark")
    assert theme["base"] == "dark"
    assert theme["primaryColor"] == dark.colours["accent"]
    assert theme["backgroundColor"] == dark.colours["bg"]
    assert theme["secondaryBackgroundColor"] == dark.colours["header"]
    assert theme["textColor"] == dark.colours["text"]
    assert theme["borderColor"] == dark.colours["border"]
    assert theme["linkColor"] == dark.colours["accent_text"]
    assert theme["font"].startswith(dark.font["family"])
