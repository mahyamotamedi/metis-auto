"""Cache key, entry, lookup result, and store decision (CMP-06, CMP-11).

Structure from ADR-0011: a key is a keyed fingerprint over ordered component
states; the partition key is everything except the message; unknown never
matches in serving. Scope from ADR-0007 (``session`` by default).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from ._base import (
    SCHEMA_VERSION,
    ComponentState,
    ContractModel,
    Fingerprint,
    Identifier,
    Name,
    NonNegFloat,
    NonNegInt,
    Privacy,
    UtcDatetime,
    Version,
    Versions,
    field,
)
from .measurement import ComponentName, EmbedderRef, Embedding


class ScopeKind(StrEnum):
    SESSION = "session"
    USER = "user"
    GLOBAL = "global"


class CacheScope(ContractModel):
    """Who may reuse an entry. ``ref`` is the session or user reference."""

    kind: ScopeKind = field(Privacy.OPERATIONAL, "Sharing scope.")
    ref: Identifier | None = field(
        Privacy.REFERENCE, "Session or user ref; None for global.", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> CacheScope:
        if (self.kind == ScopeKind.GLOBAL) != (self.ref is None):
            raise ValueError("session and user scopes need a ref; global has none")
        return self


class KeyComponent(ContractModel):
    """One content component of a key: its state and, if present, fingerprint.

    ``treatment`` records how the variant built it (normalisation, history
    window), so differently built keys never compare equal by accident.
    """

    component: ComponentName = field(Privacy.OPERATIONAL, "Which component.")
    state: ComponentState = field(Privacy.DERIVED, "Present, absent, or unknown.")
    fingerprint: Fingerprint | None = field(
        Privacy.FINGERPRINT, "Set iff present.", default=None
    )
    treatment: Name = field(
        Privacy.OPERATIONAL, "e.g. nfkc_casefold_ws, last_4_turns, full."
    )

    @model_validator(mode="after")
    def _check(self) -> KeyComponent:
        if (self.state == ComponentState.PRESENT) != (self.fingerprint is not None):
            raise ValueError("fingerprint must be set exactly when present")
        return self


class CacheKeyDraft(ContractModel):
    """A composed key before fingerprinting (Stage 5).

    The cache policy (domain) decides the composition but holds no fingerprint
    key (ADR-0015), so it returns a draft. The measurement service seals it
    into a ``CacheKey`` by fingerprinting ``key_material()`` and
    ``partition_material()``.
    """

    key_schema_version: Version = field(
        Privacy.OPERATIONAL, "Bumps invalidate entries."
    )
    variant: Name = field(Privacy.OPERATIONAL, "Key variant, e.g. full, request_only.")
    serving_allowed: bool = field(
        Privacy.OPERATIONAL, "False for measurement-only variants (P-5)."
    )
    components: tuple[KeyComponent, ...] = field(
        Privacy.DERIVED, "Content components, in key order."
    )
    target_group: Name | None = field(
        Privacy.OPERATIONAL, "Target equivalence group; None if excluded by variant."
    )
    scope: CacheScope = field(Privacy.REFERENCE, "Sharing scope.")

    def key_material(self) -> dict[str, object]:
        """Everything in the key, as JSON-ready data (fingerprints, not content)."""
        return self.model_dump(mode="json")

    def partition_material(self) -> dict[str, object]:
        """The key without the message component (ADR-0011 point 3)."""
        material = self.key_material()
        material["components"] = [
            c for c in material["components"] if c["component"] != ComponentName.MESSAGE
        ]
        return material


class CacheKey(ContractModel):
    """A composed key (caching.md §1). Built by the cache policy for the
    serving variant, and by experiments for measurement variants."""

    key_schema_version: Version = field(
        Privacy.OPERATIONAL, "Bumps invalidate entries."
    )
    variant: Name = field(Privacy.OPERATIONAL, "Key variant, e.g. full, request_only.")
    serving_allowed: bool = field(
        Privacy.OPERATIONAL, "False for measurement-only variants (P-5)."
    )
    components: tuple[KeyComponent, ...] = field(
        Privacy.DERIVED, "Content components, in key order."
    )
    target_group: Name | None = field(
        Privacy.OPERATIONAL, "Target equivalence group; None if excluded by variant."
    )
    scope: CacheScope = field(Privacy.REFERENCE, "Sharing scope.")
    key: Fingerprint = field(Privacy.FINGERPRINT, "Fingerprint of the whole key.")
    partition_key: Fingerprint = field(
        Privacy.FINGERPRINT, "Fingerprint of everything except the message."
    )

    @property
    def has_unknown(self) -> bool:
        """True if any component is unknown: ineligible for serving (P-6)."""
        return any(c.state == ComponentState.UNKNOWN for c in self.components)


class EntryStatus(StrEnum):
    COMPLETE = "complete"
    INVALIDATED = "invalidated"


class CacheEntry(ContractModel):
    """A stored answer. Holds content; lives only in the cache store."""

    schema_version: Version = field(
        Privacy.OPERATIONAL, "Contract version.", default=SCHEMA_VERSION
    )
    entry_id: Identifier = field(Privacy.REFERENCE, "Entry ID.")
    key: CacheKey = field(Privacy.FINGERPRINT, "Key it was stored under.")
    answer: str = field(Privacy.CONTENT, "The stored answer.")
    producing_model_id: Name = field(Privacy.OPERATIONAL, "Model that answered.")
    producing_tier: NonNegInt = field(Privacy.OPERATIONAL, "Its tier.")
    created_at: UtcDatetime = field(Privacy.OPERATIONAL, "When stored.")
    status: EntryStatus = field(Privacy.OPERATIONAL, "Usable only when complete.")
    source_request_id: Identifier = field(
        Privacy.REFERENCE, "Request that produced it."
    )
    embedding: Embedding | None = field(
        Privacy.CONTENT, "Message embedding, if the semantic tier is on.", default=None
    )
    versions: Versions = field(Privacy.OPERATIONAL, "Versions at store time.")


class IndexMatch(ContractModel):
    """One vector-index result (``VectorIndex.query``)."""

    entry_id: Identifier = field(Privacy.REFERENCE, "Matched entry.")
    similarity: float = field(Privacy.DERIVED, "Similarity under the index's function.")
    embedder: EmbedderRef = field(Privacy.OPERATIONAL, "Embedder of both vectors.")


class CacheTier(StrEnum):
    EXACT = "exact"
    SEMANTIC = "semantic"


class LookupOutcome(StrEnum):
    HIT = "hit"
    MISS = "miss"
    INELIGIBLE = "ineligible"


class IneligibleReason(StrEnum):
    ATTACHMENTS = "attachments"
    UNKNOWN_COMPONENT = "unknown_component"
    TIME_SENSITIVE = "time_sensitive"
    SCOPE_REF_MISSING = "scope_ref_missing"
    NO_TARGET = "no_target"
    VARIANT_NOT_SERVING = "variant_not_serving"
    DISABLED = "disabled"
    NOT_FIRST_TURN = "not_first_turn"
    """The demo seed serves first-turn requests only (history absent)."""


class InvalidReason(StrEnum):
    """Why a found entry was not usable (the lookup becomes a miss)."""

    EXPIRED = "expired"
    STATUS = "status"
    TIER_TOO_LOW = "tier_too_low"
    BELOW_THRESHOLD = "below_threshold"
    VERIFIER_FAILED = "verifier_failed"


class CacheLookupResult(ContractModel):
    """Outcome of one tier's lookup (FR-XCACHE-06). One per tier tried."""

    tier: CacheTier = field(Privacy.OPERATIONAL, "Exact or semantic.")
    outcome: LookupOutcome = field(Privacy.OPERATIONAL, "Hit, miss, or ineligible.")
    ineligible_reason: IneligibleReason | None = field(
        Privacy.OPERATIONAL, "Set iff ineligible.", default=None
    )
    invalid_reason: InvalidReason | None = field(
        Privacy.OPERATIONAL, "Set when an entry was found but rejected.", default=None
    )
    key_variant: Name | None = field(Privacy.OPERATIONAL, "Variant used.", default=None)
    key: Fingerprint | None = field(Privacy.FINGERPRINT, "Key looked up.", default=None)
    scope: ScopeKind | None = field(Privacy.OPERATIONAL, "Scope kind.", default=None)
    entry_id: Identifier | None = field(
        Privacy.REFERENCE, "Matched entry; set on a hit.", default=None
    )
    similarity: float | None = field(
        Privacy.DERIVED, "Best similarity (semantic tier).", default=None
    )
    threshold: float | None = field(
        Privacy.OPERATIONAL, "Threshold in force (semantic tier).", default=None
    )
    embedder: EmbedderRef | None = field(
        Privacy.OPERATIONAL, "Embedder (semantic tier).", default=None
    )
    candidates_considered: NonNegInt | None = field(
        Privacy.DERIVED, "Index results examined (semantic tier).", default=None
    )
    key_schema_version: Version | None = field(
        Privacy.OPERATIONAL,
        "Key schema version looked up (Stage E6). Not populated by any "
        "production code yet: always None until the cache lookup fills it.",
        default=None,
    )
    entry_age_ms: NonNegFloat | None = field(
        Privacy.OPERATIONAL,
        "Age of the matched entry on a hit (Stage E6). Not populated by any "
        "production code yet: always None until the cache lookup fills it.",
        default=None,
    )
    not_evaluated: tuple[Name, ...] = field(
        Privacy.OPERATIONAL,
        "Configured checks that are no-ops, e.g. time_sensitivity (TODO-07).",
        default=(),
    )

    @model_validator(mode="after")
    def _check(self) -> CacheLookupResult:
        if (self.outcome == LookupOutcome.INELIGIBLE) != (
            self.ineligible_reason is not None
        ):
            raise ValueError("ineligible_reason must be set exactly when ineligible")
        if self.outcome == LookupOutcome.HIT:
            if self.entry_id is None or self.invalid_reason is not None:
                raise ValueError("a hit names its entry and has no invalid_reason")
            if self.tier == CacheTier.SEMANTIC and (
                self.similarity is None or self.threshold is None
            ):
                raise ValueError("a semantic hit records similarity and threshold")
        return self


class StoreSkipReason(StrEnum):
    NOT_ELIGIBLE = "not_eligible"
    SERVED_FROM_CACHE = "served_from_cache"
    NO_ANSWER = "no_answer"
    ERROR = "error"
    TRUNCATED = "truncated"
    CONTENT_FILTERED = "content_filtered"
    UNSATISFACTORY = "unsatisfactory"
    DISABLED = "disabled"


class CacheStoreDecision(ContractModel):
    """Whether the final answer may be stored (caching.md §2 store rules)."""

    store: bool = field(Privacy.OPERATIONAL, "Store or skip.")
    skip_reason: StoreSkipReason | None = field(
        Privacy.OPERATIONAL, "Set iff skipped.", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> CacheStoreDecision:
        if self.store == (self.skip_reason is not None):
            raise ValueError("skip_reason must be set exactly when not storing")
        return self
