"""Shared types for the comparison metrics (Stage E1; evaluation framework
§0.1, §0.8, §1, §6).

An ``OutcomeTable`` holds, per request, the cost and quality each candidate
model would have had (from a recorded sampling run, ``recorded`` or ``live``
counterfactual sources, ADR-0014), plus the provenance of those numbers and
whether the quality scores are validated (the Persian judge gate, §0.4). An
``Estimate`` is one reported number: it says whether it is measured, why it
is not, its n, its interval, and its provenance. Nothing here has a default
threshold: every minimum, margin and level is passed in by the caller (from
config), and an unset one yields a stated non-answer, never a guess.
Pure, stdlib only. Called by: evaluation code and experiments.
Status: provisional (Stage E1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from metis_auto.contracts import Language

PRIMARY_LANGUAGE = Language.PERSIAN.value
PROVENANCES = ("measured", "estimated", "simulated")
STATES = ("measured", "insufficient", "not_evaluated", "undefined")


@dataclass(frozen=True)
class Outcome:
    """What one model did (or would have done) on one request."""

    cost: float | None = None
    quality: float | None = None

    @property
    def complete(self) -> bool:
        return self.cost is not None and self.quality is not None


@dataclass(frozen=True)
class EvalRequest:
    request_id: str
    session_ref: str
    language: str
    outcomes: Mapping[str, Outcome]


@dataclass(frozen=True)
class OutcomeTable:
    requests: tuple[EvalRequest, ...]
    cost_provenance: str
    quality_provenance: str
    quality_validated: bool
    """True only if the judge or ratings passed the Persian agreement gate
    for this slice (§0.4). Unvalidated quality cannot feed non-inferiority
    claims or oracle labels."""

    def __post_init__(self) -> None:
        for p in (self.cost_provenance, self.quality_provenance):
            if p not in PROVENANCES:
                raise ValueError(f"provenance must be one of {PROVENANCES}")
        ids = [r.request_id for r in self.requests]
        if len(set(ids)) != len(ids):
            raise ValueError("request_id values must be unique")

    @property
    def provenance(self) -> str:
        return f"cost={self.cost_provenance},quality={self.quality_provenance}"

    def subset(self, requests: tuple[EvalRequest, ...]) -> OutcomeTable:
        return OutcomeTable(
            requests,
            self.cost_provenance,
            self.quality_provenance,
            self.quality_validated,
        )

    def language(self, language: str) -> OutcomeTable:
        return self.subset(tuple(r for r in self.requests if r.language == language))


@dataclass(frozen=True)
class Estimate:
    """One reported number. ``value`` is set only when ``state`` is
    ``measured``; otherwise ``reason`` says why not."""

    state: str
    n: int
    provenance: str
    value: float | None = None
    interval: tuple[float, float] | None = None
    level: float | None = None
    method: str | None = None
    reason: str | None = None
    extra: Mapping[str, float | str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"state must be one of {STATES}")
        if self.state == "measured" and self.value is None:
            raise ValueError("a measured estimate needs a value")
        if self.state != "measured" and (self.value is not None or not self.reason):
            raise ValueError("a non-measured estimate needs a reason and no value")

    @property
    def measured(self) -> bool:
        return self.state == "measured"

    @property
    def claims_allowed(self) -> bool:
        """A ranking or significance claim needs a measured value and an
        interval; a point value alone supports neither."""
        return self.measured and self.interval is not None


def not_measured(state: str, reason: str, n: int, provenance: str) -> Estimate:
    return Estimate(state=state, n=n, provenance=provenance, reason=reason)


def sufficient(n: int, min_n: int | None) -> tuple[bool, str | None]:
    """(enough, reason). An unset minimum is never enough."""
    if min_n is None:
        return False, "min_n_unset"
    if n < min_n:
        return False, "n_below_minimum"
    return True, None
