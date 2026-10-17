"""Events: the single measurement record (ADR-0012, observability.md §3).

An ``Event`` is an envelope plus one typed payload, discriminated by
``event_type``. No payload may contain a CONTENT field; a test enforces it
(QA-PRIV, FR-OBS-02).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ._base import (
    SCHEMA_VERSION,
    Component,
    ContractModel,
    Identifier,
    LoggedTimestamp,
    Name,
    NonNegFloat,
    NonNegInt,
    Privacy,
    UtcDatetime,
    Version,
    Versions,
    field,
)
from .accounting import CostEstimate, Money
from .attempts import AttemptRecord, DetectorVerdict
from .caching import CacheLookupResult, ScopeKind, StoreSkipReason
from .context import CompositionRecord
from .evaluation import ExclusionCount, MetricValue
from .features import RequestFeatures
from .measurement import ComponentMeasurement, MeasurementRecord
from .model_io import AttemptKind, ErrorClass
from .replay import PairingFlag
from .request import TrafficSource
from .response import ResponseMetadata, ResponseStatus, SpanName
from .routing import RoutingDecision


class RunMode(StrEnum):
    """FR-OBS-03: one schema for replay and online."""

    REPLAYED = "replayed"
    """Replay with recorded, logged, or live answers."""
    SIMULATED = "simulated"
    """Replay with fake answers."""
    LIVE = "live"
    """Online traffic."""


def _type(name: str) -> object:
    return field(Privacy.OPERATIONAL, "Discriminator.", default=name)


class RequestReceived(ContractModel):
    event_type: Literal["request_received"] = _type("request_received")
    components: tuple[ComponentMeasurement, ...] = field(
        Privacy.DERIVED, "State, size, fingerprint per component."
    )
    traffic_source: Component[TrafficSource] = field(
        Privacy.DERIVED,
        "Reserved (Q-21).",
        default_factory=Component[TrafficSource].unknown,
    )
    pairing_flag: PairingFlag | None = field(
        Privacy.OPERATIONAL, "Replay only.", default=None
    )


class FeaturesExtracted(ContractModel):
    event_type: Literal["features_extracted"] = _type("features_extracted")
    features: RequestFeatures = field(Privacy.DERIVED, "Features.")
    measurements: tuple[MeasurementRecord, ...] = field(
        Privacy.OPERATIONAL, "Measurement overhead.", default=()
    )


class RoutingDecided(ContractModel):
    event_type: Literal["routing_decided"] = _type("routing_decided")
    decision: RoutingDecision = field(Privacy.OPERATIONAL, "The decision.")


class CacheLookedUp(ContractModel):
    event_type: Literal["cache_lookup"] = _type("cache_lookup")
    result: CacheLookupResult = field(Privacy.OPERATIONAL, "One tier's outcome.")


class CacheStored(ContractModel):
    event_type: Literal["cache_stored"] = _type("cache_stored")
    entry_id: Identifier = field(Privacy.REFERENCE, "New entry.")
    key_variant: Name = field(Privacy.OPERATIONAL, "Variant.")
    scope: ScopeKind = field(Privacy.OPERATIONAL, "Scope kind.")
    semantic_indexed: bool = field(Privacy.OPERATIONAL, "Vector added to the index.")


class CacheStoreSkipped(ContractModel):
    event_type: Literal["cache_store_skipped"] = _type("cache_store_skipped")
    reason: StoreSkipReason = field(Privacy.OPERATIONAL, "Why.")


class ContextBuilt(ContractModel):
    event_type: Literal["context_built"] = _type("context_built")
    record: CompositionRecord = field(Privacy.DERIVED, "Composition record.")


class AttemptStarted(ContractModel):
    event_type: Literal["attempt_started"] = _type("attempt_started")
    kind: AttemptKind = field(Privacy.OPERATIONAL, "Why.")
    number: NonNegInt = field(Privacy.OPERATIONAL, "0 for primary.")
    model_id: Name = field(Privacy.OPERATIONAL, "Target.")
    provider: Name = field(Privacy.OPERATIONAL, "Provider.")


class AttemptFinished(ContractModel):
    event_type: Literal["attempt_finished"] = _type("attempt_finished")
    record: AttemptRecord = field(
        Privacy.OPERATIONAL, "Outcome, usage, cost, verdicts."
    )
    provider_model_version: str | None = field(
        Privacy.OPERATIONAL, "As reported.", default=None
    )


class RetryScheduled(ContractModel):
    event_type: Literal["retry_scheduled"] = _type("retry_scheduled")
    from_attempt_id: Identifier = field(Privacy.REFERENCE, "Failed attempt.")
    model_id: Name = field(Privacy.OPERATIONAL, "Same model.")
    error_class: ErrorClass = field(Privacy.OPERATIONAL, "Cause.")
    backoff_ms: NonNegFloat = field(Privacy.OPERATIONAL, "Wait.")


class FailoverTriggered(ContractModel):
    event_type: Literal["failover_triggered"] = _type("failover_triggered")
    from_model_id: Name = field(Privacy.OPERATIONAL, "From.")
    to_model_id: Name = field(Privacy.OPERATIONAL, "To.")
    equivalence_group: Name = field(Privacy.OPERATIONAL, "Shared group.")
    error_class: ErrorClass | None = field(Privacy.OPERATIONAL, "Cause.", default=None)


class EscalationTriggered(ContractModel):
    event_type: Literal["escalation_triggered"] = _type("escalation_triggered")
    from_model_id: Name = field(Privacy.OPERATIONAL, "From.")
    to_model_id: Name = field(Privacy.OPERATIONAL, "To.")
    from_tier: NonNegInt = field(Privacy.OPERATIONAL, "From tier.")
    to_tier: NonNegInt = field(Privacy.OPERATIONAL, "To tier.")
    verdicts: tuple[DetectorVerdict, ...] = field(
        Privacy.DERIVED, "Every verdict (FR-CASC-05)."
    )


class BudgetBlocked(ContractModel):
    event_type: Literal["budget_blocked"] = _type("budget_blocked")
    estimate: CostEstimate = field(Privacy.OPERATIONAL, "Pre-call estimate.")
    cap_remaining: Money | None = field(Privacy.OPERATIONAL, "Cap left.", default=None)


class ResponseReturned(ContractModel):
    event_type: Literal["response_returned"] = _type("response_returned")
    status: ResponseStatus = field(Privacy.OPERATIONAL, "OK or error.")
    metadata: ResponseMetadata = field(Privacy.OPERATIONAL, "Totals and flags.")


class EvaluationScored(ContractModel):
    event_type: Literal["evaluation_scored"] = _type("evaluation_scored")
    metrics: tuple[MetricValue, ...] = field(Privacy.DERIVED, "Per-case metrics.")


class RunStarted(ContractModel):
    event_type: Literal["run_started"] = _type("run_started")
    experiment_id: Name = field(Privacy.OPERATIONAL, "EXP ID.")
    manifest_ref: str = field(Privacy.OPERATIONAL, "Run-relative path of the manifest.")


class RunFinished(ContractModel):
    event_type: Literal["run_finished"] = _type("run_finished")
    cases_total: NonNegInt = field(Privacy.DERIVED, "Cases offered.")
    cases_run: NonNegInt = field(Privacy.DERIVED, "Cases replayed.")
    exclusions: tuple[ExclusionCount, ...] = field(
        Privacy.DERIVED, "FR-EVAL-08.", default=()
    )
    completed: bool = field(Privacy.OPERATIONAL, "False if the run stopped early.")


EventPayload = Annotated[
    RequestReceived
    | FeaturesExtracted
    | RoutingDecided
    | CacheLookedUp
    | CacheStored
    | CacheStoreSkipped
    | ContextBuilt
    | AttemptStarted
    | AttemptFinished
    | RetryScheduled
    | FailoverTriggered
    | EscalationTriggered
    | BudgetBlocked
    | ResponseReturned
    | EvaluationScored
    | RunStarted
    | RunFinished,
    Field(discriminator="event_type"),
]

PAYLOAD_TYPES: tuple[type[ContractModel], ...] = (
    RequestReceived,
    FeaturesExtracted,
    RoutingDecided,
    CacheLookedUp,
    CacheStored,
    CacheStoreSkipped,
    ContextBuilt,
    AttemptStarted,
    AttemptFinished,
    RetryScheduled,
    FailoverTriggered,
    EscalationTriggered,
    BudgetBlocked,
    ResponseReturned,
    EvaluationScored,
    RunStarted,
    RunFinished,
)

RUN_LEVEL_EVENTS = frozenset({"run_started", "run_finished"})


class Event(ContractModel):
    """Envelope plus payload (FR-OBS-02). Written by the event recorder."""

    schema_version: Version = field(
        Privacy.OPERATIONAL, "Contract version.", default=SCHEMA_VERSION
    )
    event_id: Identifier = field(Privacy.REFERENCE, "Unique and ordered within a run.")
    event_type: Name = field(Privacy.OPERATIONAL, "Equals payload.event_type.")
    run_id: Identifier = field(Privacy.REFERENCE, "Run or process lifetime.")
    run_mode: RunMode = field(Privacy.OPERATIONAL, "Replayed, simulated, or live.")
    request_id: Identifier | None = field(
        Privacy.REFERENCE, "None only for run-level events.", default=None
    )
    session_ref: Identifier | None = field(Privacy.REFERENCE, "Session.", default=None)
    case_id: Identifier | None = field(Privacy.REFERENCE, "Replay case.", default=None)
    attempt_id: Identifier | None = field(Privacy.REFERENCE, "Attempt.", default=None)
    parent_attempt_id: Identifier | None = field(
        Privacy.REFERENCE, "Previous attempt.", default=None
    )
    timestamp: UtcDatetime = field(Privacy.OPERATIONAL, "When emitted (aware UTC).")
    logged_timestamp: LoggedTimestamp | None = field(
        Privacy.OPERATIONAL, "Replay only: naive logged time (A-06).", default=None
    )
    span: SpanName | None = field(
        Privacy.OPERATIONAL, "Span this event closes.", default=None
    )
    duration_ms: NonNegFloat | None = field(
        Privacy.OPERATIONAL, "Span duration (monotonic clock).", default=None
    )
    versions: Versions = field(Privacy.OPERATIONAL, "Versions in force.")
    payload: EventPayload = field(Privacy.DERIVED, "Typed, content-free payload.")

    @model_validator(mode="after")
    def _check(self) -> Event:
        if self.event_type != self.payload.event_type:
            raise ValueError("event_type must equal payload.event_type")
        if (self.request_id is None) != (self.event_type in RUN_LEVEL_EVENTS):
            raise ValueError("request_id is required except on run-level events")
        if self.run_mode == RunMode.LIVE and (
            self.case_id is not None or self.logged_timestamp is not None
        ):
            raise ValueError("live events have no replay case or logged timestamp")
        if (self.span is None) != (self.duration_ms is None):
            raise ValueError("span and duration_ms are set together")
        return self
