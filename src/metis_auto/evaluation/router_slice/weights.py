"""Per-record traffic weights of the routing dev slice (pure; owner,
2026-11-02).

The slice is balanced by design (floors, ceilings and minimums), so a plain
mean over it describes the slice, not the traffic. Each record carries
``weight = traffic share of its cohort / slice share of its cohort``; a
traffic-weighted metric is ``Σ wᵢ·mᵢ / Σ wᵢ``, reported next to the balanced
one (R8). The weights average 1 over the slice when every traffic cohort is
present in it; a cohort with traffic but no record cannot be weighted, and
its traffic share is reported as uncovered.

Traces: FR-EVAL-04/06, ADR-XXXX (system-one-decision-router) point 10.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

WEIGHT_DIGITS = 6
"""Rounded so the committed ``ids.csv`` is byte-stable across platforms."""


@dataclass(frozen=True)
class StratumWeight:
    traffic: int
    traffic_share: float
    records: int
    slice_share: float
    weight: float | None
    """None when the stratum has no record in the slice."""


def traffic_weights(
    slice_counts: Mapping[str, int], traffic_counts: Mapping[str, int]
) -> dict[str, StratumWeight]:
    """Value → weight row, for every value seen in the traffic or the slice."""
    n_slice = sum(slice_counts.values())
    n_traffic = sum(traffic_counts.values())
    if n_slice <= 0 or n_traffic <= 0:
        raise ValueError("traffic weights need a non-empty slice and traffic")
    out: dict[str, StratumWeight] = {}
    for value in sorted(set(slice_counts) | set(traffic_counts)):
        records = slice_counts.get(value, 0)
        traffic = traffic_counts.get(value, 0)
        t_share = traffic / n_traffic
        s_share = records / n_slice
        if records and not traffic:
            raise ValueError(f"stratum {value!r} is in the slice but not the traffic")
        out[value] = StratumWeight(
            traffic=traffic,
            traffic_share=t_share,
            records=records,
            slice_share=s_share,
            weight=round(t_share / s_share, WEIGHT_DIGITS) if records else None,
        )
    return out


def uncovered_share(weights: Mapping[str, StratumWeight]) -> float:
    """Traffic share of the strata with no record in the slice."""
    return sum(w.traffic_share for w in weights.values() if not w.records)


def format_weight(weight: float | None) -> str:
    return "" if weight is None else f"{weight:.{WEIGHT_DIGITS}f}"
