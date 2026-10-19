"""Walking skeleton (Stage 5; config moved to files in Stage 6).

Responsibility: build a runnable pipeline from **synthetic** reference data —
a placeholder catalogue (not real models) and an empty price table, so every
cost comes out "not computed" — with the fake model client, the in-memory
cache store, and an in-memory event sink. No network, no keys.
The reference data and routing come from ``config/profiles/walking_skeleton.toml``
(loaded at the experiment layer over ``config/defaults.toml``, ADR-0019).
Called by: scripts/run_walking_skeleton.py, tests/integration.
Calls: settings, wiring.from_settings, wiring.pipeline, adapters.
"""

from __future__ import annotations

from collections.abc import Mapping

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.application.pipeline import PipelineConfig, RequestPipeline
from metis_auto.contracts import Component, Request, Role, RunMode, Turn
from metis_auto.ports import CacheStore, Clock, EventSink, IdSource, ModelClient
from metis_auto.settings import LoadedSettings, default_config_dir, load_settings

from .from_settings import pipeline_config
from .pipeline import build_pipeline

SYNTHETIC = "[SYNTHETIC]"
PROFILE = "profiles/walking_skeleton.toml"


def skeleton_settings(
    *, hermetic: bool = True, environ: Mapping[str, str] | None = None
) -> LoadedSettings:
    """Defaults plus the walking-skeleton profile. ``hermetic`` (tests) ignores
    the environment, ``.env``, and ``config/local.toml``; the script loads them
    so ``METIS_FINGERPRINT_KEY`` and logging settings apply."""
    profile = default_config_dir(environ) / PROFILE
    if hermetic:
        return load_settings(experiment=profile, environ={}, dotenv=None, runtime=None)
    return load_settings(experiment=profile, environ=environ)


def skeleton_config() -> PipelineConfig:
    return pipeline_config(skeleton_settings())


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
    config_hash: str | None = None,
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
        config_hash=config_hash,
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
