"""Cache policy (CMP-06; caching.md §1–§3).

Responsibility: decide whether a request may use the cache, compose its key
(as a ``CacheKeyDraft``: domain holds no fingerprint key, ADR-0015), judge a
found entry, and decide whether a final answer may be stored. Pure.
Called by: application.pipeline (stages 4 and 7). Calls: contracts only.
Config: ``CachePolicyConfig``. Status: structure decided; rules provisional.

Implemented now: exact tier, the serving variant ``full`` with ``literal``
message and ``full`` history treatments, ``session``/``user``/``global`` scope
selection, TTL and status validity. TODO markers name what is missing.

**Demo settings (Demo milestone, ADR-0023; off by default, never serving
defaults):** the ``demo_bot_level`` scope rule (ADR-0016 S-b shape: ``global``
only when instructions are present, so entries are shared across the users
of one bot through the instructions fingerprint in the key), and the
**demo seed**: logged first-turn answers stored under a message-only key
variant (``demo_seed_msg_only``) that is looked up only when the seed is
enabled and only for first-turn requests.
Traces: FR-XCACHE-01…09, FR-SCACHE-*, ADR-0007, ADR-0011, P-5, P-6.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import model_validator

from metis_auto.contracts import (
    AttemptOutcome,
    AttemptRecord,
    CacheEntry,
    CacheKey,
    CacheKeyDraft,
    CacheLookupResult,
    CacheScope,
    CacheStoreDecision,
    CacheTier,
    ComponentName,
    ComponentState,
    ContractModel,
    EntryStatus,
    FinishReason,
    IneligibleReason,
    InvalidReason,
    KeyComponent,
    LookupOutcome,
    Name,
    Request,
    RequestMeasurements,
    RoutingDecision,
    ScopeKind,
    StoreSkipReason,
)

SUPPORTED_TREATMENTS = {"literal", "full"}
"""Treatments the measurement service can fingerprint today. TODO(Stage 8,
FR-XCACHE-03): whitespace and NFKC + casefold normalisation, history windows."""

NOT_EVALUATED = ("time_sensitivity",)
"""TODO-07: no time-sensitivity detector yet; the check reports itself."""

KEY_COMPONENTS = (
    ComponentName.MESSAGE,
    ComponentName.INSTRUCTIONS,
    ComponentName.HISTORY,
    ComponentName.RETRIEVED,
    ComponentName.STRUCTURED_INPUT,
)
"""Content components of the full key, in key order (caching.md §1)."""


class KeyVariant(ContractModel):
    """A key composition. Narrow variants are measurement-only (P-5)."""

    name: Name = "full"
    serving_allowed: bool = True
    components: tuple[ComponentName, ...] = KEY_COMPONENTS
    include_target_group: bool = True
    message_treatment: Name = "literal"
    history_treatment: Name = "full"

    @model_validator(mode="after")
    def _supported(self) -> KeyVariant:
        treatments = {self.message_treatment, self.history_treatment}
        if not treatments <= SUPPORTED_TREATMENTS:
            raise ValueError(f"treatments supported so far: {SUPPORTED_TREATMENTS}")
        return self


class ScopeRule(StrEnum):
    FIXED = "fixed"
    """Always the configured ``scope`` (the serving default)."""
    DEMO_BOT_LEVEL = "demo_bot_level"
    """DEMO ONLY (ADR-0023): ``global`` when instructions are present (shared
    by every user of the same bot: same instructions, retrieved context,
    history, and target group are all in the key), else the configured scope.
    ADR-0016's S-b shape without its traffic-source rule and prerequisites
    (time-sensitivity detector, false-hit rates, privacy review), which is why
    it is a labelled demo setting and not a serving option."""


class DemoSeedConfig(ContractModel):
    """DEMO ONLY (ADR-0023): a few logged first-turn answers, served on an exact
    message match. Off by default. Logged answers are shown locally and never
    sent to a provider."""

    enabled: bool = False
    variant: Name = "demo_seed_msg_only"
    key_schema_version: str = "ks-demo-seed-1"
    first_turn_only: bool = True


class CachePolicyConfig(ContractModel):
    """Provisional defaults: conservative (P-5, ADR-0007)."""

    enabled: bool = True
    key_schema_version: str = "ks-1"
    variant: KeyVariant = KeyVariant()
    scope: ScopeKind = ScopeKind.SESSION
    ttl_seconds: int | None = 86_400
    """Provisional default (FR-XCACHE-09); None means no expiry."""
    attachments_ineligible: bool = True  # A-19
    semantic_enabled: bool = False
    """TODO(Stage 8): semantic tier (embed, VectorIndex.query, threshold)."""
    scope_rule: ScopeRule = ScopeRule.FIXED
    demo_seed: DemoSeedConfig = DemoSeedConfig()


def select_scope(request: Request, config: CachePolicyConfig) -> CacheScope | None:
    """The sharing scope for this request, or None if its reference is missing.

    ``traffic_source`` is deliberately not read (reserved, ADR-0016 proposed).
    """
    if (
        config.scope_rule == ScopeRule.DEMO_BOT_LEVEL
        and request.instructions.state == ComponentState.PRESENT
    ):
        return CacheScope(kind=ScopeKind.GLOBAL)
    if config.scope == ScopeKind.GLOBAL:
        return CacheScope(kind=ScopeKind.GLOBAL)
    ref = request.session_ref if config.scope == ScopeKind.SESSION else request.user_ref
    return None if ref is None else CacheScope(kind=config.scope, ref=ref)


def eligibility(
    request: Request,
    decision: RoutingDecision,
    scope: CacheScope | None,
    config: CachePolicyConfig,
) -> IneligibleReason | None:
    """Why the request may not use the cache, or None if it may (caching.md §2)."""
    if not config.enabled:
        return IneligibleReason.DISABLED
    if not config.variant.serving_allowed:
        return IneligibleReason.VARIANT_NOT_SERVING
    if decision.target_model_id is None:
        return IneligibleReason.NO_TARGET
    attachments = request.attachments.state
    if config.attachments_ineligible and attachments == ComponentState.PRESENT:
        return IneligibleReason.ATTACHMENTS
    states = {
        ComponentName.HISTORY: request.history.state,
        ComponentName.INSTRUCTIONS: request.instructions.state,
        ComponentName.RETRIEVED: request.retrieved.state,
        ComponentName.STRUCTURED_INPUT: request.structured_input.state,
        ComponentName.ATTACHMENTS: attachments,  # unknown could hide attachments
    }
    if any(state == ComponentState.UNKNOWN for state in states.values()):
        return IneligibleReason.UNKNOWN_COMPONENT  # P-6: unknown never matches
    if scope is None:
        return IneligibleReason.SCOPE_REF_MISSING
    return None


def compose_key(
    measurements: RequestMeasurements,
    decision: RoutingDecision,
    scope: CacheScope,
    config: CachePolicyConfig,
) -> CacheKeyDraft:
    """The key draft for the configured variant. Uses the measurement
    fingerprints, which are of the literal text (see SUPPORTED_TREATMENTS)."""
    by_name = {m.component: m for m in measurements.components}
    variant = config.variant
    components = []
    for name in variant.components:
        m = by_name[name]
        treatment = {
            ComponentName.MESSAGE: variant.message_treatment,
            ComponentName.HISTORY: variant.history_treatment,
        }.get(name, "full")
        components.append(
            KeyComponent(
                component=name,
                state=m.state,
                fingerprint=m.fingerprint
                if m.state == ComponentState.PRESENT
                else None,
                treatment=treatment,
            )
        )
    return CacheKeyDraft(
        key_schema_version=config.key_schema_version,
        variant=variant.name,
        serving_allowed=variant.serving_allowed,
        components=tuple(components),
        target_group=decision.equivalence_group
        if variant.include_target_group
        else None,
        scope=scope,
    )


def ineligible_result(
    reason: IneligibleReason,
    config: CachePolicyConfig,
    scope: CacheScope | None = None,
) -> CacheLookupResult:
    return CacheLookupResult(
        tier=CacheTier.EXACT,
        outcome=LookupOutcome.INELIGIBLE,
        ineligible_reason=reason,
        key_variant=config.variant.name,
        scope=scope.kind if scope is not None else config.scope,
        not_evaluated=NOT_EVALUATED,
    )


# --- demo seed (DEMO ONLY, ADR-0023) ------------------------------------------


def seed_eligibility(
    request: Request, config: CachePolicyConfig
) -> IneligibleReason | None:
    """Why the demo seed may not answer this request, or None if it may."""
    seed = config.demo_seed
    if not (config.enabled and seed.enabled):
        return IneligibleReason.DISABLED
    if request.attachments.state == ComponentState.PRESENT:
        return IneligibleReason.ATTACHMENTS
    if request.attachments.state == ComponentState.UNKNOWN:
        return IneligibleReason.UNKNOWN_COMPONENT
    if seed.first_turn_only:
        if request.history.state == ComponentState.UNKNOWN:
            return IneligibleReason.UNKNOWN_COMPONENT
        if request.history.state == ComponentState.PRESENT:
            return IneligibleReason.NOT_FIRST_TURN
    if not request.message.strip():
        return IneligibleReason.UNKNOWN_COMPONENT
    return None


def compose_seed_key(
    measurements: RequestMeasurements, config: CachePolicyConfig
) -> CacheKeyDraft:
    """Message-only key of the demo seed: no instructions, history, retrieved
    context, or target group; global scope. ``serving_allowed`` stays False:
    it is not a serving variant (P-5), only the labelled demo seed reads it."""
    message = next(
        m for m in measurements.components if m.component == ComponentName.MESSAGE
    )
    return CacheKeyDraft(
        key_schema_version=config.demo_seed.key_schema_version,
        variant=config.demo_seed.variant,
        serving_allowed=False,
        components=(
            KeyComponent(
                component=ComponentName.MESSAGE,
                state=message.state,
                fingerprint=message.fingerprint
                if message.state == ComponentState.PRESENT
                else None,
                treatment="literal",
            ),
        ),
        target_group=None,
        scope=CacheScope(kind=ScopeKind.GLOBAL),
    )


def seed_ineligible_result(
    reason: IneligibleReason, config: CachePolicyConfig
) -> CacheLookupResult:
    return CacheLookupResult(
        tier=CacheTier.EXACT,
        outcome=LookupOutcome.INELIGIBLE,
        ineligible_reason=reason,
        key_variant=config.demo_seed.variant,
        scope=ScopeKind.GLOBAL,
        not_evaluated=NOT_EVALUATED,
    )


def validate_entry(
    entry: CacheEntry | None, key: CacheKey, now: datetime, config: CachePolicyConfig
) -> CacheLookupResult:
    """Exact-tier outcome for a looked-up entry (validity at lookup)."""
    invalid: InvalidReason | None = None
    if entry is not None:
        if entry.status != EntryStatus.COMPLETE:
            invalid = InvalidReason.STATUS
        elif config.ttl_seconds is not None and now - entry.created_at > timedelta(
            seconds=config.ttl_seconds
        ):
            invalid = InvalidReason.EXPIRED
        # TODO(open, caching.md §2): producing-tier rule (InvalidReason.TIER_TOO_LOW).
    hit = entry is not None and invalid is None
    return CacheLookupResult(
        tier=CacheTier.EXACT,
        outcome=LookupOutcome.HIT if hit else LookupOutcome.MISS,
        invalid_reason=invalid,
        key_variant=key.variant,
        key=key.key,
        scope=key.scope.kind,
        entry_id=entry.entry_id if hit else None,
        not_evaluated=NOT_EVALUATED,
    )


def store_decision(
    eligible: bool,
    served_from_cache: bool,
    final: AttemptRecord | None,
    config: CachePolicyConfig,
) -> CacheStoreDecision:
    """Store rules (caching.md §2): only a final, satisfactory, complete answer
    to an eligible request that was not itself served from cache."""

    def skip(reason: StoreSkipReason) -> CacheStoreDecision:
        return CacheStoreDecision(store=False, skip_reason=reason)

    if not config.enabled:
        return skip(StoreSkipReason.DISABLED)
    if served_from_cache:
        return skip(StoreSkipReason.SERVED_FROM_CACHE)
    if not eligible:
        return skip(StoreSkipReason.NOT_ELIGIBLE)
    if final is None or final.outcome == AttemptOutcome.NO_ANSWER:
        return skip(StoreSkipReason.NO_ANSWER)
    if final.outcome != AttemptOutcome.RESPONSE:
        return skip(StoreSkipReason.ERROR)
    if final.finish_reason == FinishReason.LENGTH:
        return skip(StoreSkipReason.TRUNCATED)
    if final.finish_reason == FinishReason.CONTENT_FILTER:
        return skip(StoreSkipReason.CONTENT_FILTERED)
    if final.finish_reason != FinishReason.COMPLETE:
        return skip(StoreSkipReason.ERROR)
    if final.unsatisfactory:
        return skip(StoreSkipReason.UNSATISFACTORY)
    return CacheStoreDecision(store=True)
