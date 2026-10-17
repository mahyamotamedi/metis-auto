"""Latency spans, response metadata, and the final response (CMP-01 output).

Latency always says which lifecycle span it measures and where the number
came from (ADR-0006 point 4, observability.md §2).
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from pydantic import model_validator

from ._base import (
    ContractModel,
    Identifier,
    Name,
    NonNegFloat,
    NonNegInt,
    Privacy,
    Versions,
    field,
)
from .accounting import Cost, Savings
from .attempts import FailureReason
from .caching import CacheTier
from .tokens import TokenUsage


class SpanName(StrEnum):
    REQUEST = "request"
    MEASURE = "measure"
    FEATURES = "features"
    ROUTE = "route"
    CACHE_LOOKUP_EXACT = "cache_lookup.exact"
    CACHE_LOOKUP_SEMANTIC = "cache_lookup.semantic"
    EMBED = "embed"
    CONTEXT = "context"
    ATTEMPT = "attempt"
    MODEL_CALL = "model_call"
    MEASUREMENT_CALL = "measurement_call"
    """A router, judge, or verifier model call (overhead)."""
    CACHE_STORE = "cache_store"
    RESPOND = "respond"


class LatencyCategory(StrEnum):
    """ADR-0006 latency split."""

    OVERHEAD = "overhead"
    MODEL = "model"
    END_TO_END = "end_to_end"
    CONTAINER = "container"
    """Spans that only group children (attempt, respond); not summed."""
    POST_RESPONSE = "post_response"


SPAN_CATEGORY = MappingProxyType(
    {
        SpanName.REQUEST: LatencyCategory.END_TO_END,
        SpanName.MEASURE: LatencyCategory.OVERHEAD,
        SpanName.FEATURES: LatencyCategory.OVERHEAD,
        SpanName.ROUTE: LatencyCategory.OVERHEAD,
        SpanName.CACHE_LOOKUP_EXACT: LatencyCategory.OVERHEAD,
        SpanName.CACHE_LOOKUP_SEMANTIC: LatencyCategory.OVERHEAD,
        SpanName.EMBED: LatencyCategory.OVERHEAD,
        SpanName.CONTEXT: LatencyCategory.OVERHEAD,
        SpanName.MEASUREMENT_CALL: LatencyCategory.OVERHEAD,
        SpanName.ATTEMPT: LatencyCategory.CONTAINER,
        SpanName.MODEL_CALL: LatencyCategory.MODEL,
        SpanName.RESPOND: LatencyCategory.CONTAINER,
        SpanName.CACHE_STORE: LatencyCategory.POST_RESPONSE,
    }
)
"""Which latency each span counts toward (observability.md §2). ``embed`` is a
child of ``cache_lookup.semantic``; sum only one of them."""


class LatencySource(StrEnum):
    MEASURED_LOCAL = "measured_local"
    """Monotonic clock in this process. Indicative only offline (A-22)."""
    PROVIDER_REPORTED = "provider_reported"
    RECORDED = "recorded"
    SIMULATED = "simulated"
    """Injected by a fake client; measures nothing real."""


class SpanTiming(ContractModel):
    span: SpanName = field(Privacy.OPERATIONAL, "Lifecycle span.")
    duration_ms: NonNegFloat = field(Privacy.OPERATIONAL, "Duration.")
    source: LatencySource = field(Privacy.OPERATIONAL, "Where the number came from.")
    attempt_id: Identifier | None = field(
        Privacy.REFERENCE, "For attempt and call spans.", default=None
    )


class ResponseStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class ServedBy(StrEnum):
    CACHE = "cache"
    MODEL = "model"
    NONE = "none"


class ResponseMetadata(ContractModel):
    """Content-free account of how a request was answered (FR-API-01)."""

    request_id: Identifier = field(Privacy.REFERENCE, "Minted by the pipeline.")
    caller_request_ref: Identifier | None = field(
        Privacy.REFERENCE, "Echo of the caller's ref.", default=None
    )
    served_by: ServedBy = field(Privacy.OPERATIONAL, "Cache, model, or none.")
    final_model_id: Name | None = field(
        Privacy.OPERATIONAL,
        "Model of the returned answer (cache: producing model).",
        default=None,
    )
    cache_tier: CacheTier | None = field(Privacy.OPERATIONAL, "On a hit.", default=None)
    cache_entry_id: Identifier | None = field(
        Privacy.REFERENCE, "On a hit.", default=None
    )
    attempt_ids: tuple[Identifier, ...] = field(
        Privacy.REFERENCE, "All attempts, in order.", default=()
    )
    answer_usage: TokenUsage | None = field(
        Privacy.DERIVED, "Usage of the returned answer's attempt.", default=None
    )
    total_cost: Cost = field(
        Privacy.OPERATIONAL, "All attempts plus overhead (FR-ACCT-03)."
    )
    overhead_cost: Cost = field(
        Privacy.OPERATIONAL, "Router, embedder, judge, verifier."
    )
    avoided_cost: Cost | None = field(
        Privacy.OPERATIONAL, "On a cache hit (FR-ACCT-04).", default=None
    )
    savings: tuple[Savings, ...] = field(
        Privacy.OPERATIONAL, "One per configured baseline.", default=()
    )
    spans: tuple[SpanTiming, ...] = field(
        Privacy.OPERATIONAL, "Span timings.", default=()
    )
    retries: NonNegInt = field(Privacy.OPERATIONAL, "Retry attempts.", default=0)
    failovers: NonNegInt = field(Privacy.OPERATIONAL, "Failover attempts.", default=0)
    escalations: NonNegInt = field(
        Privacy.OPERATIONAL, "Escalation attempts.", default=0
    )
    unsatisfactory_returned: bool = field(
        Privacy.DERIVED, "Returned an answer a detector flagged.", default=False
    )
    failure: FailureReason | None = field(
        Privacy.OPERATIONAL, "Set iff status is error.", default=None
    )
    versions: Versions = field(Privacy.OPERATIONAL, "Versions in force.")


class FinalResponse(ContractModel):
    """What the pipeline returns. Expected failures are an error status, not an
    exception (ADR-0010 point 6)."""

    status: ResponseStatus = field(Privacy.OPERATIONAL, "OK or error.")
    answer: str | None = field(Privacy.CONTENT, "Set iff OK.", default=None)
    metadata: ResponseMetadata = field(Privacy.OPERATIONAL, "How it was answered.")

    @model_validator(mode="after")
    def _check(self) -> FinalResponse:
        ok = self.status == ResponseStatus.OK
        if ok != (self.answer is not None):
            raise ValueError("answer is set exactly when status is ok")
        if ok == (self.metadata.failure is not None):
            raise ValueError("metadata.failure is set exactly when status is error")
        if ok and self.metadata.served_by == ServedBy.NONE:
            raise ValueError("an ok response is served by cache or model")
        return self
