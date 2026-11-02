"""INTERIM stand-in for the shared ``LeverResult`` JSON loader (S-2; FR-EVAL-07,
QA-REPRO). Interim, not the shared implementation.

The shared, frozen pydantic ``LeverResult`` (S-1, ``analysis/lever_result.py``)
does not exist yet. Until it does, ``result_from_json`` turns one
``reports/levers/<lever_id>.json`` mapping into a plain object with the fields
``analysis.compare.LeverResultLike`` reads. Switch-over: replace the body of
``result_from_json`` with ``LeverResult.model_validate(data)`` and ``is_result``
with a validation attempt, then delete this module
(docs/experiments/pipeline_b_interim_contracts.md, checklist).

Money is read only from decimal strings (or integers) into ``Decimal``; a float
amount is refused, so no binary rounding enters a saving.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

REQUIRED = frozenset(
    {
        "lever_id",
        "step",
        "version",
        "n_requests",
        "n_eligible",
        "baseline",
        "baseline_cost",
        "saving",
        "ci_low",
        "ci_high",
        "slices",
        "evidence_class",
        "correctness_state",
        "assumptions",
        "overhead_ms_p50",
        "overhead_ms_p95",
        "manifest",
    }
)
MANIFEST_REQUIRED = frozenset({"price_version", "data_revision"})


def is_result(data: object) -> bool:
    """True if ``data`` has every field the comparison reads."""
    return (
        isinstance(data, Mapping)
        and REQUIRED <= data.keys()
        and isinstance(data["manifest"], Mapping)
        and MANIFEST_REQUIRED <= data["manifest"].keys()
    )


def result_from_json(data: Mapping[str, object]) -> SimpleNamespace:
    """One result mapping → an object satisfying ``LeverResultLike``."""
    fields = dict(data)
    fields["baseline_cost"] = _amounts(data["baseline_cost"])
    fields["saving"] = _amounts(data["saving"])
    fields["slices"] = {k: _amounts(v) for k, v in _mapping(data["slices"]).items()}
    fields["assumptions"] = tuple(data["assumptions"])
    fields["manifest"] = SimpleNamespace(**_mapping(data["manifest"]))
    return SimpleNamespace(**fields)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expected a JSON object")
    return value


def _amounts(value: object) -> dict[str, Decimal]:
    return {k: _decimal(v) for k, v in _mapping(value).items()}


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ValueError("money must be a decimal string or an integer, never a float")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("money must be a decimal string") from exc
