"""Walking skeleton (Stage 5): the whole pipeline offline, with fakes.

Responsibility: build a runnable pipeline from **synthetic** reference data —
a placeholder catalogue (not real models) and a price table with no amounts,
so every cost comes out "not computed" — with the fake model client, the
in-memory cache store, and an in-memory event sink. No network, no keys.
Called by: scripts/run_walking_skeleton.py, tests/integration.
Calls: wiring.pipeline, adapters.

TODO(Stage 6): the synthetic catalogue and prices move to ``config/`` once the
file format and the settings loader exist; the fingerprint key then comes
from the environment through settings.
"""

from __future__ import annotations

from datetime import date

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.application.pipeline import PipelineConfig, RequestPipeline
from metis_auto.contracts import (
    Capability,
    CatalogueEntry,
    Component,
    Limit,
    ModelCatalogue,
    PriceEntry,
    PriceTable,
    Request,
    Role,
    RunMode,
    Sourced,
    TokenType,
    Turn,
)
from metis_auto.domain.routing import FixedModelConfig, RoutingConfig
from metis_auto.ports import CacheStore, Clock, EventSink, IdSource, ModelClient

from .pipeline import build_pipeline

SYNTHETIC = "[SYNTHETIC]"
_EVIDENCE = Sourced(
    source="SYNTHETIC walking-skeleton placeholder, not a real model",
    checked_on=date(2026, 10, 18),
)


def _entry(model_id: str, provider: str, tier: int, group: str) -> CatalogueEntry:
    return CatalogueEntry(
        model_id=model_id,
        provider=provider,
        provider_model_name=f"{model_id}-synthetic",
        tier=tier,
        equivalence_group=group,
        context_window=Limit(value=16_000, evidence=_EVIDENCE),
        max_output_tokens=Limit(value=1_000, evidence=_EVIDENCE),
        capabilities=(Capability(name="image_input", verified=False),),
        tokenizer_ref="approx-chars-div-4",
        price_ref=f"{model_id}-price",
        enabled=True,
    )


def synthetic_catalogue() -> ModelCatalogue:
    """Two tiers; tier 0 has two equivalent models on different providers, so
    failover and escalation are both exercisable."""
    return ModelCatalogue(
        version="cat-synthetic-skeleton-1",
        entries=(
            _entry("synthetic-small-a", "synthetic-provider-a", 0, "synthetic-tier0"),
            _entry("synthetic-small-b", "synthetic-provider-b", 0, "synthetic-tier0"),
            _entry("synthetic-large", "synthetic-provider-a", 1, "synthetic-tier1"),
        ),
    )


def placeholder_prices(catalogue: ModelCatalogue) -> PriceTable:
    """Prices with **no amounts**: unknown, so costs are "not computed"
    (FR-ACCT-02). Real prices arrive in Stage 7 with sources and dates."""
    return PriceTable(
        version="prices-placeholder-1",
        entries=tuple(
            PriceEntry(
                price_ref=e.price_ref,
                token_type=t,
                per_tokens=1_000_000,
                currency="USD",
            )
            for e in catalogue.entries
            if e.price_ref
            for t in (TokenType.INPUT, TokenType.OUTPUT)
        ),
    )


def skeleton_config() -> PipelineConfig:
    catalogue = synthetic_catalogue()
    return PipelineConfig(
        catalogue=catalogue,
        prices=placeholder_prices(catalogue),
        routing=RoutingConfig(
            policy="fixed_model",
            fixed_model=FixedModelConfig(model_id="synthetic-small-a"),
            chain=("synthetic-large",),
        ),
    )


def build_walking_skeleton(
    fingerprint_key: bytes,
    *,
    config: PipelineConfig | None = None,
    model_client: ModelClient | None = None,
    cache_store: CacheStore | None = None,
    sink: EventSink | None = None,
    clock: Clock | None = None,
    ids: IdSource | None = None,
    run_id: str = "run-walking-skeleton",
) -> RequestPipeline:
    return build_pipeline(
        config or skeleton_config(),
        model_client=model_client or FakeModelClient(),
        cache_store=cache_store or InMemoryCacheStore(),
        sink=sink if sink is not None else InMemoryEventSink(),
        fingerprint_key=fingerprint_key,
        run_id=run_id,
        run_mode=RunMode.SIMULATED,
        clock=clock,
        ids=ids,
    )


def demo_requests() -> tuple[Request, ...]:
    """Synthetic requests: a first turn, the same request again in the same
    session (an exact cache hit), and a request with an unknown component
    (cache-ineligible, P-6)."""
    first = Request(
        message=f"{SYNTHETIC} سلام، ساعت کاری فروشگاه چیست؟",
        history=Component.absent(),
        instructions=Component.present(f"{SYNTHETIC} You answer shop questions."),
        retrieved=Component.absent(),
        attachments=Component.absent(),
        structured_input=Component.absent(),
        session_ref="sess-demo-1",
    )
    follow_up = Request(
        message=f"{SYNTHETIC} And on holidays?",
        history=Component.present(
            (
                Turn(role=Role.USER, text=first.message),
                Turn(role=Role.ASSISTANT, text=f"{SYNTHETIC} 9 to 17."),
            )
        ),
        instructions=first.instructions,
        session_ref="sess-demo-1",
    )
    return first, first, follow_up
