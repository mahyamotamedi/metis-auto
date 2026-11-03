"""Demo UI configuration that the pages read through wiring (spec UI-V06,
UI-T05; ADR-0024: no logic, text or colour in the page).

- ``load_strings``: the strings table ``config/demo/ui_strings.toml``; every key
  holds every language in ``LANGUAGES`` (``fa`` first, the default), else the
  file is refused. Persian is a placeholder until reviewed (K-2/K-3), shown by
  ``Strings.persian_reviewed``.
- ``direction``: ``rtl`` for Persian, ``ltr`` for English (UI-V09: English is
  never forced right-to-left).
- ``chart_theme``: chart colours and grid opacities from
  ``config/demo/theme.toml`` (a Stage 1 placeholder that Stage 2 replaces).

Traceability: FR-FIN-02 (demo dashboard UI), FR-FEAT-03 (Persian is first-class),
QA-PRIV (no content in config).
Called by: wiring.lever_view, scripts/demo_pages/results.py, tests.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

STRINGS_PATH = Path("config") / "demo" / "ui_strings.toml"
THEME_PATH = Path("config") / "demo" / "theme.toml"
LANGUAGES = ("fa", "en")
LANGUAGE_NAMES = {"fa": "فارسی", "en": "English"}
"""Each language in itself (the switch reads the same in both languages)."""
PLACEHOLDER = "[PLACEHOLDER: Persian review]"


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


def direction(lang: str) -> str:
    if lang not in LANGUAGES:
        raise ValueError(f"language {lang!r} is not one of {LANGUAGES}")
    return "rtl" if lang == "fa" else "ltr"


@dataclass(frozen=True)
class ChartTheme:
    colours: Mapping[str, str]
    grid_opacity: float
    domain_opacity: float


def chart_theme(path: Path | None = None) -> ChartTheme:
    chart = tomllib.loads((path or THEME_PATH).read_text(encoding="utf-8"))["chart"]
    return ChartTheme(
        colours={k: chart[k] for k in ("total", "saving")},
        grid_opacity=float(chart["grid_opacity"]),
        domain_opacity=float(chart["domain_opacity"]),
    )
