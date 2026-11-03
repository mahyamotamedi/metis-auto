"""The demo UI's strings table and chart colours (spec UI-V06, UI-T05; Stage 1
uses only the Results page's keys). Config files only, no Streamlit."""

from __future__ import annotations

import re

import pytest

from metis_auto.wiring.ui_config import (
    LANGUAGES,
    STRINGS_PATH,
    THEME_PATH,
    chart_theme,
    direction,
    load_strings,
)


def test_every_key_has_every_language_and_persian_is_marked_placeholder():
    strings = load_strings()
    assert strings.keys()
    for key in strings.keys():
        for lang in LANGUAGES:
            assert strings.text(key, lang).strip(), (key, lang)
    assert "[PLACEHOLDER: Persian review]" in STRINGS_PATH.read_text(encoding="utf-8")
    assert strings.persian_reviewed is False


def test_missing_language_or_key_is_refused(tmp_path):
    path = tmp_path / "strings.toml"
    path.write_text(
        '[meta]\npersian_review = "[PLACEHOLDER: Persian review]"\n'
        '[results]\ntitle = { en = "Results" }\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fa"):
        load_strings(path)
    with pytest.raises(KeyError):
        load_strings().text("no_such_key", "en")


def test_format_fields_are_filled():
    strings = load_strings()
    assert "0.35" in strings.text("flag_over_cap", "en", cap="0.35")


def test_direction_per_language():
    assert direction("fa") == "rtl" and direction("en") == "ltr"
    with pytest.raises(ValueError):
        direction("de")


def test_chart_colours_live_only_in_the_theme_file():
    theme = chart_theme()
    assert set(theme.colours) == {"total", "saving"}
    assert all(re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in theme.colours.values())
    assert 0 < theme.grid_opacity < 1 and 0 < theme.domain_opacity <= 1
    assert THEME_PATH.name == "theme.toml"
