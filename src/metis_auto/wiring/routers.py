"""Decision-router factory (ADR-0047, R4): ``[router]``
settings → a ``RouterSpec`` that ``build_pipeline`` turns into a ``RouterCascade``.

Responsibility: map the configured mode, chain, deadline, cache, breaker and
approvals onto the cascade's config; build the chain's backends; refuse what
cannot run. ``router.mode = "off"`` builds nothing (the pipeline is then
unchanged).

Backends: ``fake`` (scripted, offline; profiles below), ``thx01`` (in
process, pinned files, R5), ``systemone_http`` (a loopback server such as
Mizan on llama-server, R5), ``jev_metis`` (Mode 1, hosted, R6) and
``llm_system_one`` (the Mode 1 backup over the live answering client, R6).
The heavy adapters are imported only when built. Tests, the slice replay and
the benchmark may inject backends.

Hosted backends need a spend ledger with a cap (ADR-0003, ADR-0018); the
cascade gets its own ``SpendGuard`` over that ledger, so a stop on the router
side does not stop answering calls, while the lifetime and run caps are
shared. Called by: wiring.from_settings, wiring.router_replay, tests.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from metis_auto.adapters.routers import FakeDecisionBackend
from metis_auto.application.routing import CascadeConfig
from metis_auto.contracts import (
    CostBasis,
    DecisionQuestionSet,
    Fidelity,
    TokenCount,
)
from metis_auto.domain.accounting.cost import cost_of, pre_call_estimate
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.domain.routing.decision import mapping_question_ids
from metis_auto.ports import BaseRouter, Clock, ModelClient, SpendLedger
from metis_auto.settings import (
    FakeBackendSettings,
    JevMetisBackendSettings,
    LlmSystemOneBackendSettings,
    LoadedSettings,
    RouterAssetTable,
    RouterMode,
    RouterSettings,
    SettingsError,
    SystemOneHttpBackendSettings,
    Thx01BackendSettings,
    backend_kind,
)

BackendFactory = Callable[[Clock], Mapping[str, BaseRouter]]


def fake_profiles(ids) -> dict[str, dict[str, float | str]]:
    """Scripted answers per fake profile, keyed by the configured question
    IDs. ``neutral``: the fake's defaults (first option, middle level, 0.5)."""
    return {
        "neutral": {},
        "cheap": {
            ids.complexity: 0.0,
            ids.needs_reasoning: 0.1,
            ids.cheap_model_ok: 0.9,
            ids.intent: "chitchat",
            ids.depends_on_history: 0.2,
        },
        "complex": {
            ids.complexity: 3.0,
            ids.needs_reasoning: 0.9,
            ids.cheap_model_ok: 0.1,
            ids.intent: "analysis",
            ids.depends_on_history: 0.6,
        },
    }


@dataclass(frozen=True)
class RouterSpec:
    """What ``build_pipeline`` needs to build the cascade (it owns the clock
    and the fingerprint key)."""

    config: CascadeConfig
    backends: BackendFactory
    questions: DecisionQuestionSet
    spend_ledger: SpendLedger | None = None

    def hosted(self, built: Mapping[str, BaseRouter]) -> tuple[str, ...]:
        return tuple(n for n in self.config.chain if built[n].kind == "hosted")


def cascade_config(
    router: RouterSettings,
    policy: DecisionRouterConfig,
    *,
    states_dataset_derived: bool = True,
) -> CascadeConfig:
    chain = router.active_chain()
    return CascadeConfig(
        mode=router.mode.value,
        chain=chain,
        timeouts_ms={name: router.backends[name].timeout_ms for name in chain},
        deadline_ms=router.deadline_ms,
        deadline_grace_ms=router.deadline_grace_ms,
        reserved_pipeline_ms=router.reserved_pipeline_ms,
        min_confidence=router.min_confidence,
        keep_soft_signals=router.keep_soft_signals,
        escalate_on_low_confidence=router.escalate_on_low_confidence,
        confidence_questions=mapping_question_ids(policy.questions)
        if router.confidence_questions == "mapping"
        else None,
        confidence_statistic=router.confidence_statistic,
        real_data_approved=router.real_data_approved,
        allow_unpriced=router.allow_unpriced,
        cache_enabled=router.cache.enabled,
        cache_normalisation=router.cache.normalisation,
        cache_max_entries=router.cache.max_entries,
        cache_ttl_s=router.cache.ttl_s,
        circuit_failure_threshold=router.circuit.failure_threshold,
        circuit_window_s=router.circuit.window_s,
        circuit_cooldown_s=router.circuit.cooldown_s,
        gate=policy.gate,
        state=policy.state,
        states_dataset_derived=states_dataset_derived,
    )


def backend_builder(
    name: str,
    settings,
    policy: DecisionRouterConfig,
    *,
    assets: RouterAssetTable | None,
    assets_root: Path,
    loaded: LoadedSettings | None = None,
    questions: DecisionQuestionSet | None = None,
    model_client: Callable[[], ModelClient] | None = None,
) -> Callable[[Clock], BaseRouter]:
    """One backend from its settings: ``fake``, ``thx01`` (in process, loaded
    and sha256-checked when built), ``systemone_http`` (a loopback server),
    ``jev_metis`` (Mode 1, the Metis key and the router price table from
    ``loaded``) and ``llm_system_one`` (the Mode 1 backup over the live
    answering client, or ``model_client`` in tests). Hosted backends are
    called only through the cascade's approval check and spend guard."""
    if isinstance(settings, FakeBackendSettings):
        script = fake_profiles(policy.questions)[settings.profile]
        return lambda clock: FakeDecisionBackend(
            clock,
            name=name,
            kind=backend_kind(settings),
            latency_ms=settings.latency_ms,
            script=script,
        )
    if isinstance(settings, Thx01BackendSettings):
        spec = assets.get(settings.asset) if assets is not None else None
        if spec is None:
            raise SettingsError(f"router asset {settings.asset!r} is not configured")

        def thx01(clock: Clock) -> BaseRouter:
            from metis_auto.adapters.routers.thx01_local import (  # noqa: PLC0415
                PinnedFile,
                Thx01LocalBackend,
            )

            backend = Thx01LocalBackend(
                clock,
                name=name,
                model_dir=assets_root / spec.ref / (spec.revision or "unpinned"),
                revision=spec.revision,
                files=[PinnedFile(f.path, f.sha256, f.size_bytes) for f in spec.files],
                threads=settings.threads,
                runtime=settings.runtime,
                state_format=settings.state_format,
            )
            if backend.available().available:
                backend.load()  # never on the request path
            return backend

        return thx01
    if isinstance(settings, SystemOneHttpBackendSettings):

        def http(clock: Clock) -> BaseRouter:
            from metis_auto.adapters.routers.systemone_http import (  # noqa: PLC0415
                SystemOneHttpBackend,
            )

            return SystemOneHttpBackend(
                clock,
                name=name,
                base_url=settings.base_url,
                model=settings.model,
                health_path=settings.health_path,
                health_timeout_ms=settings.health_timeout_ms,
                state_format=settings.state_format,
            )

        return http
    if isinstance(settings, JevMetisBackendSettings):
        api_key = loaded.secrets.metis_api_key if loaded is not None else None
        router_prices = loaded.reference.router_prices if loaded is not None else None

        def jev(clock: Clock) -> BaseRouter:
            from metis_auto.adapters.routers.jev_metis import (  # noqa: PLC0415
                JevMetisBackend,
            )

            return JevMetisBackend(
                clock,
                name=name,
                base_url=settings.base_url,
                model=settings.model,
                api_key=api_key,
                prices=router_prices,
                price_ref=settings.price_ref,
                questions=questions,
                state_format=settings.state_format,
            )

        return jev
    if isinstance(settings, LlmSystemOneBackendSettings):
        return _llm_system_one(name, settings, loaded, model_client)
    raise SettingsError(  # pragma: no cover - the settings union is closed
        f"decision backend {name!r} has an unknown type {settings.type!r}"
    )


def _llm_system_one(
    name: str,
    settings: LlmSystemOneBackendSettings,
    loaded: LoadedSettings | None,
    model_client: Callable[[], ModelClient] | None,
) -> Callable[[Clock], BaseRouter]:
    """The Mode 1 backup over the live answering client (built only when the
    backend is built, so a chain without it never needs the ``live`` extra).
    Its price comes from the catalogue entry's price row, like any answer."""
    entry = None
    prices = None
    if loaded is not None:
        entry = next(
            (
                e
                for e in loaded.reference.catalogue.entries
                if e.model_id == settings.model_id
            ),
            None,
        )
        prices = loaded.reference.prices
    if loaded is not None and entry is None:
        raise SettingsError(
            f"router backend {name!r}: model {settings.model_id!r} is not in the "
            "catalogue"
        )

    def cost(usage):
        return cost_of(usage, entry, prices, CostBasis.ACTUAL)

    def estimate(tokens: int):
        return pre_call_estimate(
            entry,
            TokenCount(
                tokens=tokens,
                fidelity=Fidelity.APPROXIMATION,
                method="state_tokens+prompt_chars/2",
            ),
            settings.max_output_tokens,
            prices,
        )

    def build(clock: Clock) -> BaseRouter:
        from metis_auto.adapters.routers.llm_system_one import (  # noqa: PLC0415
            LlmSystemOneBackend,
        )

        client = None
        if model_client is not None:
            client = model_client()
        elif loaded is not None:
            from .live import build_live_client  # noqa: PLC0415

            client = build_live_client(loaded, "router-llm-system-one")
        priced = entry is not None and prices is not None
        return LlmSystemOneBackend(
            clock,
            name=name,
            client=client,
            model_id=settings.model_id,
            cost=cost if priced else None,
            estimate=estimate if priced else None,
            max_output_tokens=settings.max_output_tokens,
            state_format=settings.state_format,
        )

    return build


def configured_backends(
    router: RouterSettings,
    policy: DecisionRouterConfig,
    *,
    assets: RouterAssetTable | None = None,
    assets_root: Path = Path("data/routers"),
    loaded: LoadedSettings | None = None,
    questions: DecisionQuestionSet | None = None,
) -> BackendFactory:
    """The chain's backends from settings."""
    builders = {
        name: backend_builder(
            name,
            router.backends[name],
            policy,
            assets=assets,
            assets_root=assets_root,
            loaded=loaded,
            questions=questions,
        )
        for name in router.active_chain()
    }

    def build(clock: Clock) -> dict[str, BaseRouter]:
        return {name: make(clock) for name, make in builders.items()}

    return build


def router_spec(
    loaded: LoadedSettings,
    policy: DecisionRouterConfig,
    *,
    backends: BackendFactory | None = None,
    spend_ledger: SpendLedger | None = None,
    states_dataset_derived: bool = True,
) -> RouterSpec | None:
    """None when ``router.mode = "off"``. ``backends`` replaces the configured
    ones (tests, the slice replay); it must build every name of the chain."""
    router = loaded.settings.router
    if router.mode == RouterMode.OFF:
        return None
    table = loaded.reference.router_questions
    questions = (
        table.get(router.question_set, router.question_language) if table else None
    )
    if questions is None:
        raise SettingsError(
            f"router question set {router.question_set!r} "
            f"({router.question_language.value}) is not loaded"
        )
    return RouterSpec(
        config=cascade_config(
            router, policy, states_dataset_derived=states_dataset_derived
        ),
        backends=backends
        or configured_backends(
            router,
            policy,
            assets=loaded.reference.routers,
            assets_root=loaded.path(loaded.settings.paths.router_assets),
            loaded=loaded,
            questions=questions,
        ),
        questions=questions,
        spend_ledger=spend_ledger,
    )
