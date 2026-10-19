"""Walking-skeleton smoke tests (Stage 5 exit criterion): the whole pipeline
runs end to end offline, with fakes, no network and no keys.

Every request goes through the real ``RequestPipeline`` built by wiring; only
the adapters are fakes (P-2).
"""

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.providers import (
    FakeModelClient,
    FaultInjectingClient,
    Quality,
    QualityInjectingClient,
)
from metis_auto.adapters.sinks import InMemoryEventSink, JsonLinesEventSink
from metis_auto.adapters.system import FakeClock, SequentialIdSource
from metis_auto.contracts import (
    AnswerSource,
    CacheTier,
    Component,
    CostStatus,
    ErrorClass,
    Event,
    FailureReason,
    IneligibleReason,
    LookupOutcome,
    ModelError,
    PairingFlag,
    PairingMethod,
    ReplayCase,
    ResponseStatus,
    RunMode,
    ServedBy,
)
from metis_auto.evaluation.replay import replay
from metis_auto.wiring.pipeline import build_pipeline
from metis_auto.wiring.walking_skeleton import (
    build_walking_skeleton,
    demo_requests,
    skeleton_config,
)

KEY = ex.SYNTHETIC_TEST_KEY


def _pipeline(client=None, sink=None):
    sink = sink if sink is not None else InMemoryEventSink()
    pipeline = build_walking_skeleton(
        KEY,
        model_client=client,
        sink=sink,
        clock=FakeClock(ex.NOW, step_ms=0.5),
        ids=SequentialIdSource("run-test"),
    )
    return pipeline, sink


def _types(sink, request_id):
    return [e.event_type for e in sink.events if e.request_id == request_id]


def test_miss_then_exact_hit_then_ineligible():
    pipeline, sink = _pipeline()
    first, again, follow_up = (pipeline.handle(r) for r in demo_requests())

    assert first.status == ResponseStatus.OK
    assert first.metadata.served_by == ServedBy.MODEL
    assert first.metadata.final_model_id == "synthetic-small-a"
    assert ex.MARKER in first.answer
    assert _types(sink, first.metadata.request_id) == [
        "request_received",
        "features_extracted",
        "routing_decided",
        "cache_lookup",
        "attempt_started",
        "context_built",
        "attempt_finished",
        "cache_stored",
        "response_returned",
    ]
    # Placeholder prices have no amounts: cost is "not computed", never zero.
    assert first.metadata.total_cost.status == CostStatus.NOT_COMPUTED

    assert again.metadata.served_by == ServedBy.CACHE
    assert again.metadata.cache_tier == CacheTier.EXACT
    assert again.answer == first.answer and again.metadata.attempt_ids == ()

    lookups = [
        e.payload.result
        for e in sink.events
        if e.event_type == "cache_lookup"
        and e.request_id == follow_up.metadata.request_id
    ]
    # The follow-up leaves retrieved context unknown, so it may not use the cache.
    assert lookups[0].outcome == LookupOutcome.INELIGIBLE
    assert lookups[0].ineligible_reason == IneligibleReason.UNKNOWN_COMPONENT


def test_events_are_content_free_and_well_formed():
    pipeline, sink = _pipeline()
    for request in demo_requests():
        pipeline.handle(request)
    assert sink.events
    for event in sink.events:
        assert ex.MARKER not in event.model_dump_json()
        assert event.run_mode == RunMode.SIMULATED
        assert event.versions.fingerprint_key_id == ex.key_id()
    ids = [e.event_id for e in sink.events]
    assert len(ids) == len(set(ids))


def test_retry_then_failover_with_fault_injection():
    timeout = ModelError(
        error_class=ErrorClass.TIMEOUT, retryable=True, source=AnswerSource.FAKE
    )
    client = FaultInjectingClient(FakeModelClient(), [timeout, timeout, timeout])
    pipeline, sink = _pipeline(client)
    response = pipeline.handle(demo_requests()[0])
    assert response.status == ResponseStatus.OK
    assert response.metadata.retries == 2 and response.metadata.failovers == 1
    assert response.metadata.final_model_id == "synthetic-small-b"
    types = _types(sink, response.metadata.request_id)
    assert types.count("retry_scheduled") == 2
    assert types.count("failover_triggered") == 1
    # Failed attempts are charged; with no reported usage the total is unknown.
    assert response.metadata.total_cost.status == CostStatus.NOT_COMPUTED


def test_escalation_on_truncated_answer():
    client = QualityInjectingClient(FakeModelClient(), [Quality.TRUNCATED])
    pipeline, sink = _pipeline(client)
    response = pipeline.handle(demo_requests()[0])
    assert response.metadata.escalations == 1
    assert response.metadata.final_model_id == "synthetic-large"
    assert not response.metadata.unsatisfactory_returned
    escalation = next(e for e in sink.events if e.event_type == "escalation_triggered")
    assert any(
        v.detector == "truncation" and v.fired for v in escalation.payload.verdicts
    )
    # A truncated answer was never the final one, so the final one is stored.
    assert "cache_stored" in _types(sink, response.metadata.request_id)


def test_no_eligible_model_is_an_error_response_not_an_exception():
    pipeline, _ = _pipeline()
    request = demo_requests()[0].model_copy(
        update={"attachments": Component.present((ex.ATTACHMENT,))}
    )  # image input is unverified on every synthetic model
    response = pipeline.handle(request)
    assert response.status == ResponseStatus.ERROR
    assert response.metadata.failure == FailureReason.NO_ELIGIBLE_MODEL
    assert response.answer is None


def test_live_client_is_refused_without_a_spending_cap():
    class Live(FakeModelClient):
        @property
        def source(self):
            return AnswerSource.LIVE

    with pytest.raises(ValueError, match="spending cap"):
        build_pipeline(
            skeleton_config(),
            model_client=Live(),
            cache_store=None,
            sink=InMemoryEventSink(),
            fingerprint_key=KEY,
            run_id="run-live",
            run_mode=RunMode.LIVE,
        )


def test_replay_harness_runs_cases_through_the_same_pipeline(tmp_path):
    path = tmp_path / "runs" / "events.jsonl"
    sink = JsonLinesEventSink(path)
    pipeline, _ = _pipeline(sink=sink)
    case = ReplayCase(
        case_id="case-1",
        session_ref="sess-demo-1",
        turn_index=0,
        request=demo_requests()[0],
        references=(),
        pairing_method=PairingMethod.HEURISTIC_ARRAY_ORDER,
        pairing_flag=PairingFlag.CLEAN,
        logged_timestamp=ex.LOGGED,
    )
    outcomes = replay([case], pipeline)
    sink.close()
    assert outcomes[0].case_id == "case-1"
    assert outcomes[0].response.status == ResponseStatus.OK
    events = [Event.model_validate_json(line) for line in path.read_text().splitlines()]
    assert all(e.case_id == "case-1" for e in events)
    assert all(e.logged_timestamp == ex.LOGGED for e in events)
    assert ex.MARKER not in path.read_text(encoding="utf-8")
