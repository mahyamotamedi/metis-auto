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
from typing import TYPE_CHECKING

from metis_auto.adapters.system import SequentialIdSource, SystemClock
from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.events import EventRecorder
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.application.pipeline import PipelineConfig, RequestPipeline, SpendGuard
from metis_auto.application.routing import CASCADE_VERSION, RouterCascade
from metis_auto.contracts import (
    AnswerSource,
    ChatTemplate,
    Identifier,
    RunMode,
    Versions,
)
from metis_auto.domain.attempts import Detector, EmptyOutputDetector, TruncationDetector
from metis_auto.domain.context import ContextStrategy, PassThroughStrategy
from metis_auto.domain.features import router_feature_set
from metis_auto.domain.routing import (
    DecisionRouterConfig,
    DecisionRouterPolicy,
    FixedModelPolicy,
    RoutingPolicy,
    RuleBasedConfig,
    RuleBasedPolicy,
    StickyConfig,
    StickyPolicy,
)
from metis_auto.ports import (
    CacheStore,
    Clock,
    EventSink,
    IdSource,
    ModelClient,
    SpendLedger,
    TextCompressor,
    Tokenizer,
)

if TYPE_CHECKING:
    from .routers import RouterSpec


def _fixed_model(config: PipelineConfig) -> RoutingPolicy:
    if config.routing.fixed_model is None:
        raise ValueError("routing.policy = fixed_model needs routing.fixed_model")
    return FixedModelPolicy(config.routing.fixed_model)


def _rule_based(config: PipelineConfig) -> RoutingPolicy:
    rules = config.routing.rule_based or RuleBasedConfig()
    return RuleBasedPolicy(rules, config.catalogue, config.prices)


def _decision_router_policy(config: PipelineConfig) -> DecisionRouterPolicy:
    return DecisionRouterPolicy(
        config.routing.decision_router or DecisionRouterConfig(),
        config.routing.rule_based or RuleBasedConfig(),
        config.catalogue,
        config.prices,
    )


def _decision_router(config: PipelineConfig) -> RoutingPolicy:
    return _decision_router_policy(config)


def _sticky(config: PipelineConfig) -> RoutingPolicy:
    sticky = config.routing.sticky or StickyConfig()
    return StickyPolicy(
        sticky,
        config.routing.rule_based or RuleBasedConfig(),
        config.catalogue,
        config.prices,
        decision_router=_decision_router_policy(config)
        if sticky.inner == "decision_router"
        else None,
    )


ROUTING_POLICIES: dict[str, Callable[[PipelineConfig], RoutingPolicy]] = {
    "fixed_model": _fixed_model,
    # Demo components (Demo milestone, ADR-0023): placeholders until the
    # routing-plan experiments give evidence. Candidates load from
    # experiments/ only.
    "rule_based": _rule_based,
    "sticky": _sticky,
    # Decision router (ADR-0047): placeholder until
    # exp-route-013 gives evidence; without decision answers (router.mode = "off") it
    # falls back to the rules, then the safe tier.
    "decision_router": _decision_router,
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
    compressor: TextCompressor | None = None,
    router: RouterSpec | None = None,
) -> RequestPipeline:
    """Assemble a pipeline. ``fingerprint_key`` is a secret (ADR-0015): it goes
    to the measurement service only. ``routing_policy`` / ``context_strategy``
    inject an experiment's **candidate** (loaded by ``wiring.experiments``
    from ``experiments/`` only) in place of the configured promoted one;
    ``candidate_versions`` (name → version) then goes into ``Versions``.
    ``compressor`` is needed when ``context.compression.enabled`` (built by
    ``wiring.compression``). ``router`` (``wiring.routers.router_spec``)
    builds the decision-router cascade; None (``router.mode = "off"``)
    leaves the pipeline exactly as without it. With a router, the feature
    set becomes ``fs-0.4.0-router`` and the versions name the cascade and
    each backend."""
    clock = clock or SystemClock()
    ids = ids or SequentialIdSource(run_id)
    guard = None
    if model_client.source == AnswerSource.LIVE:
        if spend_ledger is None or spend_ledger.remaining() is None:
            raise ValueError("live calls need a spending cap (ADR-0003)")
        guard = SpendGuard(spend_ledger)
    if router is not None:
        features = config.features.model_copy(
            update={"version": router_feature_set(config.features.version)}
        )
        config = config.model_copy(update={"features": features})
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
        )(config)
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
    if compressor is not None and config.context.compression.enabled:
        versions = versions.model_copy(
            update={
                "policies": {
                    **versions.policies,
                    f"compressor.{compressor.ref.name}": compressor.ref.version,
                }
            }
        )
    cascade = None
    if router is not None:
        cascade, router_versions = _build_cascade(router, clock, fingerprinter)
        versions = versions.model_copy(
            update={"policies": {**versions.policies, **router_versions}}
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
        compressor=compressor if config.context.compression.enabled else None,
        decision_router=cascade,
    )


def _build_cascade(
    router: RouterSpec, clock: Clock, fingerprinter: Fingerprinter
) -> tuple[RouterCascade, dict[str, str]]:
    """The cascade over the spec's backends; hosted ones need a capped ledger
    (ADR-0003) and get their own spend guard over it."""
    backends = router.backends(clock)
    hosted = router.hosted(backends)
    guard = None
    if hosted:
        ledger = router.spend_ledger
        if ledger is None or ledger.remaining() is None:
            raise ValueError(
                f"hosted decision backends {list(hosted)} need a spending cap "
                "(ADR-0003)"
            )
        guard = SpendGuard(ledger)
    cascade = RouterCascade(
        router.config,
        backends=backends,
        questions=router.questions,
        clock=clock,
        fingerprinter=fingerprinter,
        tokenizer=ApproxCharsTokenizer(),
        spend_guard=guard,
    )
    versions = {f"router.{router.config.mode}": CASCADE_VERSION}
    for name in router.config.chain:
        versions[f"router.backend.{name}"] = backends[name].ref.version
    versions["router.questions"] = (
        f"{router.questions.version}/{router.questions.language_variant.value}"
    )
    return cascade, versions
