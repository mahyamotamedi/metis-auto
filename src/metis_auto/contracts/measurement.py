"""What the measurement service (CMP-02) hands to domain policies (P-1).

Every port call is a measurement: fingerprints, token counts, embeddings,
model-based features. Each records its method and overhead (FR-ROUTE-04,
FR-SCACHE-05).
"""

from __future__ import annotations

from enum import StrEnum

from ._base import (
    ComponentState,
    ContractModel,
    FeatureValue,
    Fingerprint,
    Identifier,
    Name,
    NonNegFloat,
    NonNegInt,
    PosInt,
    Privacy,
    Version,
    field,
)
from .accounting import Cost
from .tokens import TokenCount


class ComponentName(StrEnum):
    """Request components, as named in keys, records, and events."""

    MESSAGE = "message"
    HISTORY = "history"
    INSTRUCTIONS = "instructions"
    RETRIEVED = "retrieved"
    ATTACHMENTS = "attachments"
    STRUCTURED_INPUT = "structured_input"


class ComponentMeasurement(ContractModel):
    """Content-free description of one request component."""

    component: ComponentName = field(Privacy.OPERATIONAL, "Which component.")
    state: ComponentState = field(Privacy.DERIVED, "Present, absent, or unknown.")
    fingerprint: Fingerprint | None = field(
        Privacy.FINGERPRINT, "Keyed fingerprint; only when present.", default=None
    )
    chars: NonNegInt | None = field(Privacy.DERIVED, "Character length.", default=None)
    items: NonNegInt | None = field(
        Privacy.DERIVED, "Turns, retrieved items, or attachments.", default=None
    )
    token_estimate: TokenCount | None = field(
        Privacy.DERIVED, "Cheap estimate (target-independent).", default=None
    )


class MeasurementRecord(ContractModel):
    """Overhead of one measurement (time, and cost if it called a model)."""

    measurement: Name = field(Privacy.OPERATIONAL, "e.g. fingerprint, embed, intent.")
    backend: Version = field(Privacy.OPERATIONAL, "Backend ID@version.")
    duration_ms: NonNegFloat = field(Privacy.OPERATIONAL, "Monotonic-clock duration.")
    cost: Cost | None = field(
        Privacy.OPERATIONAL, "Cost if the measurement called a model.", default=None
    )
    attempt_id: Identifier | None = field(
        Privacy.REFERENCE, "Attempt ID when it was a model call.", default=None
    )


class EmbedderRef(ContractModel):
    """Which embedder produced a vector. Vectors from different embedders are
    never compared (caching.md §2)."""

    embedder_id: Name = field(Privacy.OPERATIONAL, "Embedder ID.")
    version: Version = field(Privacy.OPERATIONAL, "Embedder version.")
    dimensions: PosInt = field(Privacy.OPERATIONAL, "Vector length.")


class Embedding(ContractModel):
    """A vector. Treated as content: it never leaves the cache store (A-32)."""

    embedder: EmbedderRef = field(Privacy.OPERATIONAL, "Producer.")
    vector: tuple[float, ...] = field(Privacy.CONTENT, "The vector.")


class RequestMeasurements(ContractModel):
    """All measurements taken before features (lifecycle stage 1)."""

    components: tuple[ComponentMeasurement, ...] = field(
        Privacy.DERIVED, "One entry per component."
    )
    fingerprint_key_id: str = field(
        Privacy.OPERATIONAL, "ID of the key the fingerprints used (ADR-0015)."
    )
    embedding: Embedding | None = field(
        Privacy.CONTENT, "Message embedding, if a consumer needs one.", default=None
    )
    model_features: dict[Name, FeatureValue] = field(
        Privacy.DERIVED,
        "Measured model-based features, e.g. semantic intent (FR-FEAT-02).",
        default_factory=dict,
    )
    records: tuple[MeasurementRecord, ...] = field(
        Privacy.OPERATIONAL, "Overhead of each measurement.", default=()
    )


class ComponentTokens(ContractModel):
    """Token counts of one component for one target model."""

    component: ComponentName = field(Privacy.OPERATIONAL, "Which component.")
    total: TokenCount = field(Privacy.DERIVED, "Whole component.")
    per_item: tuple[TokenCount, ...] = field(
        Privacy.DERIVED, "Per turn, retrieved item, etc., in order.", default=()
    )


class TargetTokenCounts(ContractModel):
    """Counts with the target's tokenizer, for the context stage (stage 5)."""

    model_id: Name = field(Privacy.OPERATIONAL, "Target model.")
    components: tuple[ComponentTokens, ...] = field(
        Privacy.DERIVED, "Present components only."
    )
