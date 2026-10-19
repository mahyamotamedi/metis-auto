"""Baselines (CMP-22): as-logged (mandatory) and premium (ADR-0002)."""

from .as_logged import (
    AsLoggedCost,
    LabelResolution,
    as_logged_cost,
    premium_cost,
    resolve_label,
)

__all__ = [
    "AsLoggedCost",
    "LabelResolution",
    "as_logged_cost",
    "premium_cost",
    "resolve_label",
]
