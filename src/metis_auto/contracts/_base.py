"""Shared building blocks for every contract (docs/architecture/contracts.md §2).

- ``ContractModel``: frozen, rejects unknown fields.
- ``Privacy`` and ``field()``: every field declares a privacy class.
- ``Component``: the present / absent / unknown tri-state (P-6, FR-REQ-01/04).
- Constrained scalar types: identifiers, fingerprints, versions, timestamps.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Generic, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

SCHEMA_VERSION = "0.2"
"""Version of the contract package. Persisted contracts carry it.

While 0.x, any change bumps the minor version and data written under another
0.x minor is not guaranteed readable (contracts.md §2.7).
"""


class ContractModel(BaseModel):
    """Base for all contracts: immutable, and typos in field names fail."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Privacy(StrEnum):
    """Privacy class of a field (contracts.md §2.2, QA-PRIV, ADR-0015).

    CONTENT may exist only inside the content boundary (request path, cache
    store, gitignored data). Every other class may appear in events, manifests,
    logs, and reports.
    """

    CONTENT = "content"
    """Raw text, answers, attachment locators, embedding vectors."""
    FINGERPRINT = "fingerprint"
    """Keyed fingerprint of content (ADR-0015)."""
    REFERENCE = "reference"
    """Opaque identifier: minted IDs, caller refs, opaque strata."""
    DERIVED = "derived"
    """Sizes, counts, flags, scores, and enumerations computed from content."""
    OPERATIONAL = "operational"
    """Non-content metadata: model IDs, versions, times, money, config."""
    INHERIT = "inherit"
    """Generic containers only: takes the class of the enclosing field."""


def field(privacy: Privacy, description: str, **kwargs: Any) -> Any:
    """A pydantic ``Field`` that records the privacy class and a description."""
    return Field(
        description=description, json_schema_extra={"privacy": privacy.value}, **kwargs
    )


def privacy_of(model: type[BaseModel], name: str) -> Privacy | None:
    """The declared privacy class of ``model.name``, or None if undeclared."""
    extra = model.model_fields[name].json_schema_extra
    if isinstance(extra, dict) and "privacy" in extra:
        return Privacy(extra["privacy"])
    return None


# --- Scalar types --------------------------------------------------------------

Identifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:\-]+$"),
]
"""Opaque ID: minted by Metis (run, request, attempt, event, case, entry) or an
opaque caller reference. Never a raw identifier from a dataset."""

Fingerprint = Annotated[str, StringConstraints(pattern=r"^fp1:[0-9a-f]{64}$")]
"""Keyed content fingerprint, ``fp1:`` + 64 hex chars (ADR-0015 amendment 1)."""

Name = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_.:\-]*$"
    ),
]
"""Lower-case machine name: policy names, reason codes, model IDs, groups."""

Version = Annotated[str, StringConstraints(min_length=1, max_length=64)]

FeatureValue = float | int | bool | Name | None
"""A derived feature value. Strings must be codes (``Name``), so free text,
and therefore content, cannot be stored as a feature (FR-FEAT-05)."""

NonNegInt = Annotated[int, Field(ge=0)]
PosInt = Annotated[int, Field(gt=0)]
NonNegFloat = Annotated[float, Field(ge=0)]


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("must be timezone-aware UTC")
    return value


def _require_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        raise ValueError("logged timestamps are naive; timezone unknown (A-06)")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
"""A time Metis records itself: always aware UTC (FR-REQ-05)."""

LoggedTimestamp = Annotated[datetime, AfterValidator(_require_naive)]
"""A timestamp copied from a dataset: naive, timezone unknown (A-06, FR-REQ-05).
Never compared with ``UtcDatetime`` values."""


# --- Tri-state component ---------------------------------------------------------


class ComponentState(StrEnum):
    """P-6: unknown is not absent."""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


T = TypeVar("T")


def _is_empty(value: object) -> bool:
    """O-4: empty or whitespace-only strings, empty sequences, and empty mappings
    are empty."""
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, tuple | list | Mapping) and len(value) == 0


class Component(ContractModel, Generic[T]):  # noqa: UP046 (form verified with pydantic 2.10)
    """An optional request component that is present, absent, or unknown.

    ``value`` is set exactly when ``state`` is present. ``unknown_reason`` may be
    set only when unknown (e.g. ``not_in_log``, ``not_supplied``). An empty value
    (empty or whitespace-only string, empty sequence, empty mapping) is never
    present: producers record it as absent (O-4, decided 2026-10-18).
    """

    state: ComponentState = field(Privacy.DERIVED, "Present, absent, or unknown.")
    value: T | None = field(
        Privacy.INHERIT, "The component; set only when present.", default=None
    )
    unknown_reason: Name | None = field(
        Privacy.DERIVED, "Why the state is unknown (code).", default=None
    )

    @model_validator(mode="after")
    def _check_state(self) -> Component[T]:
        if (self.state == ComponentState.PRESENT) != (self.value is not None):
            raise ValueError("value must be set exactly when state is present")
        if _is_empty(self.value):
            raise ValueError("an empty value is recorded as absent, not present (O-4)")
        if self.unknown_reason is not None and self.state != ComponentState.UNKNOWN:
            raise ValueError("unknown_reason is only allowed when state is unknown")
        return self

    @classmethod
    def present(cls, value: T) -> Component[T]:
        return cls(state=ComponentState.PRESENT, value=value)

    @classmethod
    def absent(cls) -> Component[T]:
        return cls(state=ComponentState.ABSENT)

    @classmethod
    def unknown(cls, reason: str | None = None) -> Component[T]:
        return cls(state=ComponentState.UNKNOWN, unknown_reason=reason)


class PolicyRef(ContractModel):
    """Which policy (or strategy, backend) produced something, and its version."""

    name: Name = field(Privacy.OPERATIONAL, "Configured policy name.")
    version: Version = field(Privacy.OPERATIONAL, "Policy version string.")


class Versions(ContractModel):
    """Versions in force for an event, entry, or run (FR-OBS-02, FR-EVAL-07).

    None means "not involved here", not "unknown".
    """

    contracts: Version = field(
        Privacy.OPERATIONAL, "Contract schema version.", default=SCHEMA_VERSION
    )
    config_hash: str | None = field(
        Privacy.OPERATIONAL, "Hash of the non-secret settings.", default=None
    )
    fingerprint_key_id: str | None = field(
        Privacy.OPERATIONAL, "ID of the fingerprint key (ADR-0015).", default=None
    )
    policies: dict[Name, Version] = field(
        Privacy.OPERATIONAL, "Policy name → version.", default_factory=dict
    )
    feature_set: Version | None = field(
        Privacy.OPERATIONAL, "Feature set.", default=None
    )
    catalogue: Version | None = field(
        Privacy.OPERATIONAL, "Model catalogue.", default=None
    )
    price_table: Version | None = field(
        Privacy.OPERATIONAL, "Price table.", default=None
    )
    key_schema: Version | None = field(
        Privacy.OPERATIONAL, "Cache key schema.", default=None
    )
    embedder: Version | None = field(
        Privacy.OPERATIONAL, "Embedder ID@version.", default=None
    )
    judge: Version | None = field(
        Privacy.OPERATIONAL, "Judge ID@version.", default=None
    )
