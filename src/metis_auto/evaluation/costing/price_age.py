"""Price-table age (Stage E2; framework §2.3).

Reports the price table's check date, its age at ``as_of``, and whether it
exceeds a **configured** maximum age. There is no default maximum: unset means
the staleness question is not evaluated, and the report says what follows from
that. The dates come from the entries' own evidence (``checked_on``) and
``effective_from`` (None = the page states none); the oldest check date among
the entries is the one used, because a table is as fresh as its oldest row.
Pure: ``as_of`` is passed in, never read from a clock.
Status: provisional (Stage E2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from metis_auto.contracts import PriceTable

_CONSEQUENCE = {
    "not_evaluated": (
        "max_age_days is unset, so staleness is not judged: every cost is "
        "computed from this table as it is and carries its version and check "
        "date, and nothing warns when prices may have changed."
    ),
    "fresh": "Costs use this table; its age is within the configured maximum.",
    "stale": (
        "The table is older than the configured maximum: treat every cost "
        "computed from it as possibly out of date until prices are re-checked."
    ),
    "undefined": "The table's age cannot be computed; see the reason.",
}


@dataclass(frozen=True)
class PriceAge:
    version: str
    checked_on: date | None
    """Oldest check date among the entries."""
    newest_checked_on: date | None
    effective_from: date | None
    """None when the source states none (unknown)."""
    as_of: date
    age_days: int | None
    max_age_days: int | None
    state: str
    """``fresh``, ``stale``, ``not_evaluated`` (no maximum), or ``undefined``."""
    reason: str | None
    consequence: str


def price_table_age(
    prices: PriceTable, *, as_of: date, max_age_days: int | None
) -> PriceAge:
    if max_age_days is not None and max_age_days < 0:
        raise ValueError("max_age_days must not be negative")
    checks = [e.evidence.checked_on for e in prices.entries if e.evidence is not None]
    starts = {e.effective_from for e in prices.entries}
    effective = next(iter(starts)) if len(starts) == 1 else None
    oldest = min(checks) if checks else None
    newest = max(checks) if checks else None

    def report(state: str, reason: str | None, age: int | None) -> PriceAge:
        return PriceAge(
            version=prices.version,
            checked_on=oldest,
            newest_checked_on=newest,
            effective_from=effective,
            as_of=as_of,
            age_days=age,
            max_age_days=max_age_days,
            state=state,
            reason=reason,
            consequence=_CONSEQUENCE[state],
        )

    if oldest is None:
        return report("undefined", "no_checked_on", None)
    age = (as_of - oldest).days
    if age < 0:
        return report("undefined", "as_of_before_check_date", None)
    if max_age_days is None:
        return report("not_evaluated", "max_age_unset", age)
    return report("stale" if age > max_age_days else "fresh", None, age)
