"""Which benchmark arms may be called (P-1; final plan "Paid branch").

An answering arm is callable only if it is in the catalogue, enabled, priced in
the price table, served by an enabled OpenAI-compatible endpoint family, and not
on the configured ``not_callable`` list (models a live check found gone on
Metis). Anything else is **refused with a reason**, never called and never a
crash: the plan prints the reasons, and a run plans calls for callable arms
only. Pure. Traces: FR-ROUTE-05 (unknowns exclude), ADR-0018 point 2 (no
uncallable model), ADR-0053. Status: provisional.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from metis_auto.contracts import CatalogueEntry, PriceTable


@dataclass(frozen=True)
class ArmStatus:
    model_id: str
    callable: bool
    reason: str | None
    """Why not callable (None when callable)."""
    tier: int | None = None
    provider: str | None = None


def _priced(prices: PriceTable, price_ref: str | None) -> bool:
    if price_ref is None:
        return False
    return any(
        e.price_ref == price_ref and e.amount is not None for e in prices.entries
    )


def check_arms(
    requested: Sequence[str],
    *,
    catalogue: Iterable[CatalogueEntry],
    prices: PriceTable,
    enabled_families: Iterable[str],
    not_callable: Mapping[str, str],
) -> tuple[ArmStatus, ...]:
    """One status per requested arm, in the requested order (duplicates kept
    once). The configured ``not_callable`` reason wins over everything else,
    because it is the observed fact (a live check)."""
    entries = {e.model_id: e for e in catalogue}
    families = set(enabled_families)
    out: list[ArmStatus] = []
    seen: set[str] = set()
    for model in requested:
        if model in seen:
            continue
        seen.add(model)
        entry = entries.get(model)
        tier = entry.tier if entry else None
        provider = entry.provider if entry else None
        reason: str | None
        if model in not_callable:
            reason = not_callable[model]
        elif entry is None:
            reason = "not in the catalogue"
        elif not entry.enabled:
            reason = "disabled in the catalogue"
        elif not _priced(prices, entry.price_ref):
            reason = f"not priced in {prices.version}"
        elif entry.provider not in families:
            reason = f"no enabled OpenAI-compatible endpoint for '{entry.provider}'"
        else:
            reason = None
        out.append(ArmStatus(model, reason is None, reason, tier, provider))
    return tuple(out)


def callable_arms(statuses: Iterable[ArmStatus]) -> tuple[str, ...]:
    return tuple(s.model_id for s in statuses if s.callable)
