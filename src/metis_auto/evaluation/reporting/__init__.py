"""Feature-only comparison report: effects, coverage, scenarios, open items."""

from .render import to_markdown, to_plain
from .report import (
    ComparisonReport,
    EffectRow,
    OpenItem,
    ScenarioLine,
    build_comparison_report,
)

__all__ = [
    "ComparisonReport",
    "EffectRow",
    "OpenItem",
    "ScenarioLine",
    "build_comparison_report",
    "to_markdown",
    "to_plain",
]
