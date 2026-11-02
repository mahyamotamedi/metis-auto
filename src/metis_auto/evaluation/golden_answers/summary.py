"""The content-free summary of a run (pure). Counts, rates, quantiles and cost only:
nothing here can hold a prompt or an answer, and the stratum values are opaque
labels (ADR-0030)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

MEDIA_CAVEAT = "text_model_cannot_fulfil_media"
STRATUM_KEYS = (
    "primary_intent",
    "language_group",
    "cohort",
    "bot_class",
    "position",
    "target_length",
    "complexity_proxy",
)
COMPATIBLE_LANGUAGE = {
    "persian": {"persian", "mixed", "structured"},
    "english": {"english", "mixed", "structured"},
}
"""Answer script groups that do not count as a language mismatch for a request in
the key's group. Only persian and english requests are checked: the other groups
have no single expected answer script. A script-based proxy, not a judgement."""


def quantile(sorted_values: Sequence[float], q: float) -> float | None:
    """Nearest-rank quantile; identical on every platform."""
    if not sorted_values:
        return None
    rank = max(1, -(-len(sorted_values) * int(q * 1000) // 1000))
    return sorted_values[rank - 1]


def language_mismatch(request_group: str, answer_group: str | None) -> bool | None:
    """True/False for a checked request, None when not evaluated."""
    allowed = COMPATIBLE_LANGUAGE.get(request_group)
    if allowed is None or answer_group is None:
        return None
    return answer_group not in allowed


def summarise(
    rows: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    manifest: Mapping[str, Any],
    planned: int,
) -> dict[str, Any]:
    """``rows``: one mapping per stored record with the keys of the table (no
    answer text) plus ``strata`` and ``caveats``. ``planned``: records the run
    was meant to cover."""
    answered = [r for r in rows if r["status"] == "answered"]
    failed = [r for r in rows if r["status"] == "failed"]
    checked = [
        language_mismatch(r["strata"]["language_group"], r["answer_language_group"])
        for r in answered
    ]
    evaluated = [c for c in checked if c is not None]
    return {
        "run_id": run_id,
        "manifest": dict(manifest),
        "records": {
            "planned": planned,
            "stored": len(rows),
            "answered": len(answered),
            "failed": len(failed),
            "not_yet_run": planned - len(rows),
        },
        "failures_by_reason": dict(
            sorted(Counter(r["error_class"] for r in failed).items())
        ),
        "finish_reasons": dict(
            sorted(Counter(r["finish_reason"] for r in answered).items())
        ),
        "truncated": {
            "count": sum(r["finish_reason"] == "length" for r in answered),
            "rate": _rate(
                sum(r["finish_reason"] == "length" for r in answered), len(answered)
            ),
        },
        "language_mismatch": {
            "evaluated": len(evaluated),
            "mismatches": sum(evaluated),
            "rate": _rate(sum(evaluated), len(evaluated)),
            "note": "script-based proxy; persian and english requests only",
        },
        "latency_ms": _latency(rows),
        "tokens": {
            key: sum(r[key] or 0 for r in rows)
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_tokens",
            )
        },
        "cost_usd": str(sum((r["cost_usd"] or Decimal(0) for r in rows), Decimal(0))),
        "cost_not_computed": sum(r["cost_state"] != "reported" for r in answered),
        "by_stratum": {key: _by(rows, key) for key in STRATUM_KEYS if _has(rows, key)},
        "caveats": dict(
            sorted(Counter(c for r in rows for c in set(r["caveats"])).items())
        ),
        "media_generation_reported_apart": _media(rows),
    }


def _media(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    subset = [r for r in rows if MEDIA_CAVEAT in set(r["caveats"])]
    answered = [r for r in subset if r["status"] == "answered"]
    return {
        "caveat": MEDIA_CAVEAT,
        "records": len(subset),
        "answered": len(answered),
        "failed": len(subset) - len(answered),
        "truncated": sum(r["finish_reason"] == "length" for r in answered),
        "cost_usd": str(sum((r["cost_usd"] or Decimal(0) for r in subset), Decimal(0))),
    }


def _latency(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = sorted(r["latency_ms"] for r in rows if r["latency_ms"] is not None)
    return {
        "n": len(values),
        "p50": quantile(values, 0.5),
        "p90": quantile(values, 0.9),
        "p99": quantile(values, 0.99),
        "max": values[-1] if values else None,
    }


def _has(rows: Sequence[Mapping[str, Any]], key: str) -> bool:
    return any(key in r["strata"] for r in rows)


def _by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, int]]:
    table: dict[str, Counter] = {}
    for r in rows:
        table.setdefault(r["strata"].get(key, "unknown"), Counter())[r["status"]] += 1
    return {
        value: {"answered": c["answered"], "failed": c["failed"]}
        for value, c in sorted(table.items())
    }


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None
