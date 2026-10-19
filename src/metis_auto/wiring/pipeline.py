"""Pipeline factory (CMP-20): settings-level choices → a built ``RequestPipeline``.

Responsibility: map configured names to **promoted** components (routing
policies, context strategies, detectors), build the application services, and
inject adapters through ports. Refuses a live client without a spending cap
(ADR-0003). No decisions beyond that.
Called by: ``wiring.from_settings``, ``wiring.walking_skeleton``, tests, and
(Stage 8) the experiment runner via a factory.
Calls: application, domain, adapters (system defaults), ports.
Traces: QA-REPL ("one interface + one config entry"), ADR-0003, ADR-0009.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from metis_auto.adapters.system import SequentialIdSource, SystemClock
from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.events import EventRecorder
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.application.pipeline import PipelineConfig, RequestPipeline, SpendGuard
from metis_auto.contracts import (
    AnswerSource,
    ChatTemplate,
    Identifier,
    RunMode,
    Versions,
)
from metis_auto.domain.attempts import Detector, EmptyOutputDetector, TruncationDetector
from metis_auto.domain.context import ContextStrategy, PassThroughStrategy
from metis_auto.domain.routing import FixedModelPolicy, RoutingConfig, RoutingPolicy
from metis_auto.ports import (
    CacheStore,
    Clock,
    EventSink,
    IdSource,
    ModelClient,
    SpendLedger,
    Tokenizer,
)


def _fixed_model(config: RoutingConfig) -> RoutingPolicy:
    if config.fixed_model is None:
        raise ValueError("routing.policy = fixed_model needs routing.fixed_model")
    return FixedModelPolicy(config.fixed_model)


ROUTING_POLICIES: dict[str, Callable[[RoutingConfig], RoutingPolicy]] = {
    "fixed_model": _fixed_model,
    # TODO(Stage 8): rule_based; candidates load from experiments/ only.
}
CONTEXT_STRATEGIES: dict[str, Callable[[], ContextStrategy]] = {
    "pass_through": PassThroughStrategy,
}
DETECTORS: dict[str, Callable[[], Detector]] = {
    "truncation": TruncationDetector,
    "empty_output": EmptyOutputDetector,
}
"""Promoted components only (repository_structure §6.2). Adding a promoted
strategy = one entry here + one config value."""


def _lookup(registry: Mapping[str, Callable], name: str, kind: str) -> Callable:
    if name not in registry:
        raise ValueError(f"unknown or unpromoted {kind}: {name!r}")
    return registry[name]


def versions_for(
    config: PipelineConfig,
    fingerprinter: Fingerprinter,
    config_hash: str | None = None,
) -> Versions:
    """Versions in force (FR-OBS-02). ``config_hash`` comes from settings
    (configuration.md §3 rule 6); None when the config was built in code."""
    return Versions(
        config_hash=config_hash,
        fingerprint_key_id=fingerprinter.key_id,
        policies={
            config.routing.policy: "configured",
            config.context.strategy: "configured",
            "attempts": config.attempts.version,
        },
        feature_set=config.features.version,
        catalogue=config.catalogue.version,
        price_table=config.prices.version,
        key_schema=config.cache.key_schema_version,
    )


def build_pipeline(
    config: PipelineConfig,
    *,
    model_client: ModelClient,
    cache_store: CacheStore,
    sink: EventSink,
    fingerprint_key: bytes,
    run_id: Identifier,
    run_mode: RunMode,
    clock: Clock | None = None,
    ids: IdSource | None = None,
    spend_ledger: SpendLedger | None = None,
    tokenizers: Mapping[str, Tokenizer] | None = None,
    templates: Mapping[str, ChatTemplate] | None = None,
    config_hash: str | None = None,
    routing_policy: RoutingPolicy | None = None,
    context_strategy: ContextStrategy | None = None,
    candidate_versions: Mapping[str, str] | None = None,
) -> RequestPipeline:
    """Assemble a pipeline. ``fingerprint_key`` is a secret (ADR-0015): it goes
    to the measurement service only. ``routing_policy`` / ``context_strategy``
    inject an experiment's **candidate** (loaded by ``wiring.experiments``
    from ``experiments/`` only) in place of the configured promoted one;
    ``candidate_versions`` (name → version) then goes into ``Versions``."""
    clock = clock or SystemClock()
    ids = ids or SequentialIdSource(run_id)
    guard = None
    if model_client.source == AnswerSource.LIVE:
        if spend_ledger is None or spend_ledger.remaining() is None:
            raise ValueError("live calls need a spending cap (ADR-0003)")
        guard = SpendGuard(spend_ledger)
    fingerprinter = Fingerprinter(fingerprint_key)
    measurement = MeasurementService(
        fingerprinter,
        clock,
        ApproxCharsTokenizer(),
        tokenizers=tokenizers,
        templates=templates,
    )
    if routing_policy is None:
        routing_policy = _lookup(
            ROUTING_POLICIES, config.routing.policy, "routing policy"
        )(config.routing)
    context = (
        context_strategy
        or _lookup(CONTEXT_STRATEGIES, config.context.strategy, "context strategy")()
    )
    detectors = [
        _lookup(DETECTORS, name, "detector")() for name in config.attempts.detectors
    ]
    versions = versions_for(config, fingerprinter, config_hash)
    if candidate_versions:
        versions = versions.model_copy(
            update={"policies": {**versions.policies, **candidate_versions}}
        )
    recorder = EventRecorder(sink, clock, ids, run_id, run_mode, versions)
    return RequestPipeline(
        config=config,
        routing_policy=routing_policy,
        context_strategy=context,
        detectors=detectors,
        measurement=measurement,
        recorder=recorder,
        model_client=model_client,
        cache_store=cache_store,
        clock=clock,
        ids=ids,
        spend_guard=guard,
    )
