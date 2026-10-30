"""Duplicate-prompt groups and leakage-safe splits for evaluation (spec §0.3)."""

from .groups import (
    DuplicateSummary,
    SplitResult,
    TextItem,
    duplicate_groups,
    duplicate_summary,
    leakage_safe_split,
)

__all__ = [
    "DuplicateSummary",
    "SplitResult",
    "TextItem",
    "duplicate_groups",
    "duplicate_summary",
    "leakage_safe_split",
]
