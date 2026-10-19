"""Token-count arithmetic that keeps fidelity honest (FR-ACCT-01, H-7).

A sum's fidelity is the worst of its parts (``FIDELITY_ORDER``). Pure.
Called by: domain.features, domain.context, domain.accounting.cost,
application.measurement.
"""

from __future__ import annotations

from collections.abc import Iterable

from metis_auto.contracts import Fidelity, TokenCount
from metis_auto.contracts.tokens import FIDELITY_ORDER


def worst_fidelity(fidelities: Iterable[Fidelity]) -> Fidelity | None:
    found = list(fidelities)
    return max(found, key=FIDELITY_ORDER.index) if found else None


def sum_counts(counts: Iterable[TokenCount]) -> TokenCount | None:
    """Sum of counts, or None if there are none. Mixed methods → ``mixed``."""
    found = list(counts)
    if not found:
        return None
    methods = sorted({c.method for c in found})
    return TokenCount(
        tokens=sum(c.tokens for c in found),
        fidelity=worst_fidelity(c.fidelity for c in found),
        method=methods[0] if len(methods) == 1 else "mixed",
    )
