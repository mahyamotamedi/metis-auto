"""Demo UI configuration that the pages read through wiring (spec UI-V03,
UI-V06, UI-T03, UI-T05; ADR-0024: no logic, text or colour in the page).

- ``load_strings``: the strings table ``config/demo/ui_strings.toml``; every key
  holds every language in ``LANGUAGES`` (``fa`` first, the default), else the
  file is refused. Persian is a placeholder until reviewed (K-2/K-3), shown by
  ``Strings.persian_reviewed``. ``translator`` binds it to one language.
- ``direction``: ``rtl`` for Persian, ``ltr`` for English (UI-V09: English is
  never forced right-to-left).
- ``load_theme``: the design tokens of one mode (``dark`` default, ``light``)
  from ``config/demo/theme.toml``, the only file that names a colour; a missing
  token in either mode refuses the file.
- ``ui_state``: theme and language from the session or the URL query
  parameters (``?theme=dark|light&lang=fa|en``, UI-T03); unknown values fall
  back to the defaults.

Traceability: FR-FIN-02 (demo dashboard UI), FR-FEAT-03 (Persian is first-class),
QA-PRIV (no content in config).
Called by: wiring.lever_view, wiring.ui_style, scripts/demo_ui.py,
scripts/demo_pages/results.py, tests.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

STRINGS_PATH = Path("config") / "demo" / "ui_strings.toml"
THEME_PATH = Path("config") / "demo" / "theme.toml"
FONT_DIR = Path("assets") / "fonts" / "vazirmatn"
LANGUAGES = ("fa", "en")
DEFAULT_LANGUAGE = LANGUAGES[0]
LANGUAGE_NAMES = {"fa": "فارسی", "en": "English"}
"""Each language in itself (the switch reads the same in both languages)."""
LANGUAGE_SHORT = {"fa": "فا", "en": "EN"}
"""The header's compact language switch (owner decision 2, 2026-11-03)."""
PLACEHOLDER = "[PLACEHOLDER: Persian review]"
THEMES = ("dark", "light")
DEFAULT_THEME = THEMES[0]
COLOUR_KEYS = (
    "bg",
    "header",
    "surface",
    "control",
    "elevated",
    "border",
    "header_border",
    "text",
    "text_muted",
    "nav_text",
    "accent",
    "accent_text",
    "on_accent",
    "success",
    "warning",
    "danger",
    "info",
    "shadow",
)
TOGGLE_KEYS = ("track", "knob", "icon")
CHART_KEYS = (
    "trend",
    "trend_fill",
    "series_a",
    "series_b",
    "cat_1",
    "cat_2",
    "grid",
    "axis",
    "tooltip_bg",
)
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")


@dataclass(frozen=True)
class Strings:
    table: Mapping[str, Mapping[str, str]]
    persian_reviewed: bool

    def keys(self) -> tuple[str, ...]:
        return tuple(self.table)

    def text(self, key: str, lang: str, **fields: object) -> str:
        """The string for ``key`` in ``lang``; format fields filled if given."""
        template = self.table[key][lang]
        return template.format(**fields) if fields else template


def load_strings(path: Path | None = None) -> Strings:
    data = tomllib.loads((path or STRINGS_PATH).read_text(encoding="utf-8"))
    meta = data.pop("meta", {})
    table: dict[str, dict[str, str]] = {}
    for section in data.values():
        for key, entry in section.items():
            if key in table:
                raise ValueError(f"string key {key!r} is defined twice")
            missing = [
                lang
                for lang in LANGUAGES
                if not isinstance(entry, dict) or not str(entry.get(lang, "")).strip()
            ]
            if missing:
                raise ValueError(f"string {key!r} lacks {', '.join(missing)}")
            table[key] = {lang: entry[lang] for lang in LANGUAGES}
    return Strings(table, persian_reviewed=meta.get("persian_review") != PLACEHOLDER)


Text = Callable[..., str]
"""``t(key, **fields)``: one string in the bound language."""


def translator(strings: Strings, lang: str) -> Text:
    direction(lang)  # refuses an unknown language

    def t(key: str, **fields: object) -> str:
        return strings.text(key, lang, **fields)

    return t


def direction(lang: str) -> str:
    if lang not in LANGUAGES:
        raise ValueError(f"language {lang!r} is not one of {LANGUAGES}")
    return "rtl" if lang == "fa" else "ltr"


# --- theme tokens (UI-V03) ----------------------------------------------------


@dataclass(frozen=True)
class Theme:
    mode: str
    colours: Mapping[str, str]
    toggle: Mapping[str, str]
    chart: Mapping[str, str]
    brand_gradient: tuple[str, ...]
    cta_gradient: tuple[str, ...]
    landing: Mapping[str, str]
    size: Mapping[str, Any]
    font: Mapping[str, Any]

    @property
    def kinds(self) -> dict[str, str]:
        """Bar colours by kind (waterfalls and comparisons): totals, savings and
        extra cost, from the mode's categorical palette."""
        return {
            "total": self.chart["cat_1"],
            "saving": self.chart["cat_2"],
            "extra cost": self.chart["series_b"],
        }


@lru_cache(maxsize=4)
def _theme_data(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _section(data: Mapping[str, Any], keys: tuple[str, ...], where: str) -> dict:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ValueError(f"theme {where} lacks {', '.join(missing)}")
    bad = [k for k in keys if not _HEX.fullmatch(str(data[k]))]
    if bad:
        raise ValueError(f"theme {where}: not a #RRGGBB colour: {', '.join(bad)}")
    return {k: str(data[k]).upper() for k in keys}


def load_theme(mode: str = DEFAULT_THEME, path: Path | None = None) -> Theme:
    if mode not in THEMES:
        raise ValueError(f"theme {mode!r} is not one of {THEMES}")
    data = _theme_data(path or THEME_PATH)
    tokens = data.get(mode, {})
    brand = data["brand"]
    return Theme(
        mode=mode,
        colours=_section(tokens, COLOUR_KEYS, mode),
        toggle=_section(tokens.get("toggle", {}), TOGGLE_KEYS, f"{mode}.toggle"),
        chart=_section(tokens.get("chart", {}), CHART_KEYS, f"{mode}.chart"),
        brand_gradient=tuple(c.upper() for c in brand["gradient"]),
        cta_gradient=tuple(c.upper() for c in brand["cta"]),
        landing=dict(data.get("landing", {})),
        size=dict(data["size"]),
        font=dict(data["font"]),
    )


# --- theme and language state (UI-T03) ------------------------------------------


def _first(value: object) -> str | None:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return None if value is None else str(value)


def ui_state(
    query: Mapping[str, object],
    *,
    theme: str | None = None,
    lang: str | None = None,
) -> tuple[str, str]:
    """``(theme, lang)``: the session's choice, else the URL's, else the
    defaults (dark, fa). Values that are not known modes or languages are
    ignored, so a hand-edited URL never breaks the page."""
    theme = next(
        (v for v in (theme, _first(query.get("theme"))) if v in THEMES),
        DEFAULT_THEME,
    )
    lang = next(
        (v for v in (lang, _first(query.get("lang"))) if v in LANGUAGES),
        DEFAULT_LANGUAGE,
    )
    return theme, lang
