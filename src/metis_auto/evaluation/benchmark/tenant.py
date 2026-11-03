"""Tenant cap check for a benchmark sample (Review Focus 5, S-3: "no tenant
above 35% of any sample").

A tenant is one account. A **pooled** cohort (a label that groups many
accounts, such as golden-v1's "Remaining accounts", 127 accounts) is never
treated as one tenant; its whole count is reported as an upper bound on any one
of its accounts, and the check passes for it when even that bound is within the
cap. Output is content-free: shares and counts, with tenants named by rank
(``tenant_rank:1`` is the largest), never by account label. Pure.
Traces: QA-PRIV, Review Focus 5, ADR-0053.
Status: provisional.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantCheck:
    records: int
    cap: float
    largest_single_share: float
    """Share of the largest single account (pooled cohorts excluded)."""
    pooled_upper_bound_share: float
    """Largest pooled cohort's share: an upper bound for any one of its accounts."""
    shares_by_rank: tuple[float, ...]
    """Single-account shares, largest first."""
    passes: bool
    note: str


def check_tenant_cap(
    tenants: Iterable[str | None],
    *,
    cap: float,
    pooled: Iterable[str] = (),
) -> TenantCheck:
    """``tenants``: one tenant label per record (None = unknown, its own
    tenant, as ``analysis.replay_scope.cap_tenant_share`` does)."""
    if not 0 < cap <= 1:
        raise ValueError("cap must be in (0, 1]")
    pooled_set = set(pooled)
    counts = Counter("__unknown__" if t is None else t for t in tenants)
    total = sum(counts.values())
    if total == 0:
        raise ValueError("no records")
    single = sorted((n for t, n in counts.items() if t not in pooled_set), reverse=True)
    pooled_counts = [n for t, n in counts.items() if t in pooled_set]
    largest = single[0] / total if single else 0.0
    pooled_bound = max(pooled_counts) / total if pooled_counts else 0.0
    passes = largest <= cap and pooled_bound <= cap
    if passes:
        note = "no tenant above the cap"
    elif largest > cap:
        note = "a single tenant is above the cap"
    else:
        note = (
            "a pooled cohort's upper bound is above the cap; "
            "its per-account counts are needed"
        )
    return TenantCheck(
        records=total,
        cap=cap,
        largest_single_share=round(largest, 4),
        pooled_upper_bound_share=round(pooled_bound, 4),
        shares_by_rank=tuple(round(n / total, 4) for n in single),
        passes=passes,
        note=note,
    )
