"""The decision router inside the pipeline (ADR-XXXX (system-one-decision-router), R4).

- Router off: every event and response is byte-identical to the pre-R4
  pipeline (digests captured before the cascade existed).
- Router on (fake backend): the ``decision_measured`` event and the
  ``route.decide`` span, ``fs-0.4.0-router``, answers in the features the
  policy sees, router overhead in ``overhead_cost``, router versions.
- Settings: backends not built in R4 are refused with a clear message; a
  hosted chain needs the live permission. SYNTHETIC text, fakes only.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest
from fixtures.synthetic.router_off_cases import GOLDEN, KEY, _now, requests, run_cases

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.routers import FakeDecisionBackend
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.adapters.system import FakeClock, SequentialIdSource
from metis_auto.contracts import (
    CostStatus,
    DecisionFailureReason,
    DecisionStatus,
    RouterPath,
    RunMode,
    SpanName,
)
from metis_auto.domain.features import ROUTER_FEATURE_SET_VERSION
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.settings import SettingsError, load_settings
from metis_auto.wiring.from_settings import (
    build_pipeline_from_settings,
    pipeline_config,
)

FAKE_LOCAL = {
    "router.mode": "local",
    "router.backends.fake": {"type": "fake", "enabled": True, "profile": "cheap"},
    "router.chains.local": ["fake"],
}


def loaded(policy: str = "decision_router", **overrides):
    return load_settings(
        environ={},
        dotenv=None,
        runtime=None,
        overrides={"pipeline.routing.policy": policy, **overrides},
    )


def build(settings, **kwargs):
    sink = InMemoryEventSink()
    pipeline = build_pipeline_from_settings(
        settings,
        model_client=FakeModelClient(),
        cache_store=InMemoryCacheStore(),
        sink=sink,
        run_id="run-router",
        run_mode=RunMode.REPLAYED,
        clock=FakeClock(_now(), step_ms=0.5),
        ids=SequentialIdSource("run-router"),
        fingerprint_key_bytes=KEY,
        **kwargs,
    )
    return pipeline, sink


def test_router_off_is_byte_identical_to_the_pipeline_before_the_router():
    assert run_cases() == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_router_off_builds_no_cascade_and_emits_no_decision():
    pipeline, sink = build(loaded())
    for r in requests():
        pipeline.handle(r)
    assert pipeline.decision_router is None
    types = {e.payload.event_type for e in sink.events}
    assert "decision_measured" not in types
    assert all(e.versions.feature_set == "fs-0.3.0-demo" for e in sink.events)


def test_router_on_measures_decides_and_accounts_the_overhead():
    pipeline, sink = build(loaded(**FAKE_LOCAL))
    paths = Counter()
    for r in requests():
        response, trace = pipeline.handle_traced(r)
        if trace.decision.router_summary is not None:
            paths[trace.decision.router_summary.path] += 1
        assert response.metadata.overhead_cost.status == CostStatus.COMPUTED
        assert response.metadata.overhead_cost.amount.amount == 0
        spans = [s.span for s in response.metadata.spans]
        assert spans.count(SpanName.ROUTE_DECIDE) == 1
    assert paths[RouterPath.FAST_RULES] >= 2  # code, long message
    assert paths[RouterPath.SLOW_LOCAL] >= 2
    assert paths[RouterPath.FAST_CACHE] == 1  # the repeated question
    events = sink.events
    assert all(e.versions.feature_set == ROUTER_FEATURE_SET_VERSION for e in events)
    policies = events[0].versions.policies
    assert policies["router.local"] and policies["router.backend.fake"]
    assert policies["router.questions"] == "routing_qs_v1/en"
    decided = [e for e in events if e.payload.event_type == "decision_measured"]
    assert len(decided) == len(requests())
    assert all(e.span == SpanName.ROUTE_DECIDE for e in decided)
    assert all(e.payload.router_mode == "local" for e in decided)
    assert all(e.payload.measurement.measurement == "decision" for e in decided)
    # The features event carries the decision the policy saw.
    features = [e for e in events if e.payload.event_type == "features_extracted"]
    assert all(e.payload.features.decision is not None for e in features)
    answered = [
        e
        for e in features
        if e.payload.features.decision.status == DecisionStatus.ANSWERED
    ]
    assert answered
    # Order per request: decision before features before routing.
    first = [
        e.payload.event_type for e in events if e.request_id == events[0].request_id
    ]
    assert first.index("decision_measured") < first.index("features_extracted")
    assert first.index("features_extracted") < first.index("routing_decided")


def test_with_the_router_on_events_still_hold_no_text():
    pipeline, sink = build(loaded(**FAKE_LOCAL))
    for r in requests():
        pipeline.handle(r)
    for e in sink.events:
        if e.payload.event_type == "response_returned":
            continue  # carries no message text, but the fake answer is SYNTHETIC
        text = e.model_dump_json()
        assert "[SYNTHETIC]" not in text and "فروشگاه" not in text


def test_shadow_mode_measures_without_changing_a_fixed_route():
    off, _ = build(loaded("fixed_model"))
    on, sink = build(loaded("fixed_model", **FAKE_LOCAL))
    for r in requests():
        a = off.handle(r).metadata.final_model_id
        b = on.handle(r).metadata.final_model_id
        assert a == b
    assert any(e.payload.event_type == "decision_measured" for e in sink.events)


def test_an_unpinned_or_uninstalled_thx01_degrades_to_the_rules(tmp_path):
    """R5: THX-01 builds from settings; without the extra or the pinned files it
    is unavailable, so every request falls back (never a download, never an
    error). The asset folder is an empty temporary one, so the result does not
    depend on whether this machine has pinned the model (the owner's has)."""
    settings = loaded(
        **{
            "router.mode": "local",
            "router.backends.thx01.enabled": True,
            "paths.router_assets": str(tmp_path),
        }
    )
    pipeline, sink = build(settings)
    for r in requests():
        assert pipeline.handle(r).status.value in ("ok", "error")
    decided = [e for e in sink.events if e.payload.event_type == "decision_measured"]
    reasons = {e.payload.outcome.failure_reason for e in decided} - {None}
    assert reasons == {DecisionFailureReason.UNAVAILABLE}
    assert pipeline.decision_router.mode == "local"


def test_jev_needs_the_live_permission():
    """R6: Jev is built from settings, but a hosted chain still needs the live
    permission (runtime switch, both caps, the key) before any pipeline exists."""
    settings = loaded(
        **{"router.mode": "hosted", "router.backends.jev_metis.enabled": True}
    )
    with pytest.raises(SettingsError, match="hosted decision backends refused"):
        build(settings)


def test_jev_is_built_from_settings_and_unavailable_without_a_key():
    from metis_auto.adapters.routers.jev_metis import JevMetisBackend
    from metis_auto.contracts import AvailabilityReason
    from metis_auto.wiring.routers import router_spec

    settings = loaded(
        **{"router.mode": "hosted", "router.backends.jev_metis.enabled": True}
    )
    spec = router_spec(settings, DecisionRouterConfig())
    jev = spec.backends(FakeClock(_now()))["jev_metis"]
    assert isinstance(jev, JevMetisBackend) and jev.kind == "hosted"
    assert jev.available().reason == AvailabilityReason.NOT_CONFIGURED
    est = jev.estimate_cost(100)
    assert est is not None and est.cost.price_refs == ("metis-jev-latest",)


def test_a_hosted_backend_without_a_capped_ledger_is_refused():
    from metis_auto.wiring.pipeline import build_pipeline
    from metis_auto.wiring.routers import RouterSpec, router_spec

    settings = loaded(**FAKE_LOCAL)
    spec = router_spec(settings, DecisionRouterConfig())
    hosted_spec = RouterSpec(
        config=spec.config,
        backends=lambda clock: {"fake": FakeDecisionBackend(clock, kind="hosted")},
        questions=spec.questions,
    )
    with pytest.raises(ValueError, match="spending cap"):
        build_pipeline(
            pipeline_config(settings),
            model_client=FakeModelClient(),
            cache_store=InMemoryCacheStore(),
            sink=InMemoryEventSink(),
            fingerprint_key=KEY,
            run_id="run-router",
            run_mode=RunMode.REPLAYED,
            router=hosted_spec,
        )


def test_router_events_carry_no_message_text():
    """R9 privacy audit: with the decision router on, no event (decision,
    routing, response) carries the message, the previous turn or the
    instructions; only derived features, answers and counts (QA-PRIV)."""
    pipeline, sink = build(loaded(**FAKE_LOCAL))
    reqs = requests()
    for r in reqs:
        pipeline.handle(r)
    assert any(e.payload.event_type == "decision_measured" for e in sink.events)
    dumped = "\n".join(e.model_dump_json() for e in sink.events)
    for r in reqs:
        assert r.message not in dumped
        if r.instructions.value:
            assert r.instructions.value not in dumped
    assert "[SYNTHETIC]" not in dumped
