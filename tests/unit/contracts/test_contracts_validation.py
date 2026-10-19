"""Minimal validation rules on contracts (contracts.md §2 and §3).

Each test pairs a valid synthetic example with the smallest change that breaks
one rule. Rules are about shape and internal consistency only, never policy.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fixtures.synthetic import contract_examples as ex
from pydantic import ValidationError

from metis_auto.contracts import (
    ActionKind,
    AttemptAction,
    CacheKey,
    CacheLookupResult,
    CacheScope,
    CacheStoreDecision,
    CacheTier,
    Capability,
    Component,
    ComponentState,
    Cost,
    CostBasis,
    CostStatus,
    DetectorVerdict,
    EvaluationResult,
    Event,
    FinalResponse,
    LookupOutcome,
    MetricName,
    MetricState,
    MetricValue,
    ModelResult,
    PairingFlag,
    PriceEntry,
    Request,
    ResponseStatus,
    RetrievedContext,
    RoutingDecision,
    RunManifest,
    RunMode,
    Savings,
    ScopeKind,
    StratumResult,
    TrafficSource,
    Turn,
)
from metis_auto.contracts.events import RunStarted

# --- Base types --------------------------------------------------------------


def test_component_value_iff_present():
    assert Component[str].present("x").value == "x"
    with pytest.raises(ValidationError):
        Component[str](state=ComponentState.PRESENT)
    with pytest.raises(ValidationError):
        Component[str](state=ComponentState.ABSENT, value="x")


@pytest.mark.parametrize("empty", ["", "   ", "\n\t", (), [], {}])
def test_empty_value_is_never_present(empty):
    # O-4 (decided 2026-10-18): producers record empty values as absent.
    with pytest.raises(ValidationError):
        Component.present(empty)


def test_empty_rule_applies_inside_a_request():
    with pytest.raises(ValidationError):
        Request(message="m", instructions=Component.present("  "))
    with pytest.raises(ValidationError):
        Request(message="m", history=Component.present(()))
    with pytest.raises(ValidationError):
        RetrievedContext(items=())
    with pytest.raises(ValidationError):
        Request(message="m", structured_input=Component.present({}))
    assert Request(message="m", history=Component.absent()).history.value is None
    filled = Request(message="m", structured_input=Component.present({"k": None}))
    assert filled.structured_input.value == {"k": None}  # non-empty mapping


@pytest.mark.parametrize("message", ["", "  ", "\n"])
@pytest.mark.parametrize("attachments", ["absent", "unknown"])
def test_empty_message_needs_attachments(message, attachments):
    # Decided 2026-10-18: an empty message is allowed only for an
    # attachment-only message. Online-phase rule; the sample has none.
    state = getattr(Component, attachments)()
    with pytest.raises(ValidationError):
        Request(message=message, attachments=state)


def test_attachment_only_message_is_allowed():
    request = Request(message=" ", attachments=Component.present((ex.ATTACHMENT,)))
    assert request.attachments.state == ComponentState.PRESENT


def test_unknown_reason_only_when_unknown():
    assert Component[str].unknown("not_in_log").unknown_reason == "not_in_log"
    with pytest.raises(ValidationError):
        Component[str](state=ComponentState.ABSENT, unknown_reason="not_in_log")


def test_component_value_is_type_checked():
    with pytest.raises(ValidationError):
        Request(message="m", history=Component.present(("not a turn",)))


def test_request_components_default_to_unknown():
    # P-6: the conservative default; a caller must say "absent" explicitly.
    request = Request(message=f"{ex.MARKER} hi")
    for name in ("history", "instructions", "retrieved", "attachments"):
        assert getattr(request, name).state == ComponentState.UNKNOWN
    assert request.traffic_source.state == ComponentState.UNKNOWN


def test_traffic_source_is_an_open_code_enumeration():
    assert (
        TrafficSource(kind="partner_api", provenance="declared").kind == "partner_api"
    )
    with pytest.raises(ValidationError):
        TrafficSource(kind="Embedded Bot", provenance="declared")
    with pytest.raises(ValidationError):
        TrafficSource(kind="embedded_bot", provenance="guessed")


def test_contracts_are_frozen_and_reject_unknown_fields():
    turn = Turn(role="user", text=f"{ex.MARKER} hi")
    with pytest.raises(ValidationError):
        turn.text = "changed"
    with pytest.raises(ValidationError):
        Turn(role="user", text="x", speaker="y")


def test_roles_are_generic_not_dataset_names():
    with pytest.raises(ValidationError):
        Turn(role="bot", text="x")  # the sample loader maps bot -> assistant


def test_identifier_and_fingerprint_formats():
    with pytest.raises(ValidationError):
        Request(message="x", session_ref="has spaces")
    good = ex.fingerprint("message", "x")
    assert good.startswith("fp1:") and len(good) == 68
    with pytest.raises(ValidationError):
        CacheKey.model_validate(ex.cache_key().model_dump() | {"key": "deadbeef"})


def test_feature_values_cannot_hold_free_text():
    features = ex.request_features()
    with pytest.raises(ValidationError):
        type(features).model_validate(
            features.model_dump() | {"extra": {"note": f"{ex.MARKER} free text"}}
        )


# --- Timestamps --------------------------------------------------------------


def test_metis_times_must_be_aware_utc():
    data = ex.run_manifest().model_dump()
    for bad in (
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=3, minutes=30))),
    ):
        with pytest.raises(ValidationError):
            RunManifest.model_validate(data | {"started_at": bad})


def test_logged_timestamps_must_stay_naive():
    data = ex.replay_case().model_dump()
    with pytest.raises(ValidationError):
        type(ex.replay_case()).model_validate(
            data | {"logged_timestamp": datetime(2026, 5, 1, tzinfo=UTC)}
        )


# --- Accounting --------------------------------------------------------------


def test_cost_is_computed_with_provenance_or_explicitly_not_computed():
    with pytest.raises(ValidationError):
        Cost(status=CostStatus.COMPUTED, basis=CostBasis.ACTUAL, amount=ex.usd("1"))
    with pytest.raises(ValidationError):
        Cost(status=CostStatus.NOT_COMPUTED, basis=CostBasis.ACTUAL)
    with pytest.raises(ValidationError):
        Cost(
            status=CostStatus.NOT_COMPUTED,
            basis=CostBasis.ACTUAL,
            reason="price_unknown",
            amount=ex.usd("0"),
        )


def test_savings_need_both_costs():
    with pytest.raises(ValidationError):
        Savings(
            baseline="premium",
            status=CostStatus.COMPUTED,
            amount=ex.usd("1"),
            baseline_cost=ex.not_computed(),
            actual_cost=ex.computed("1"),
        )


def test_money_rejects_bad_currency():
    with pytest.raises(ValidationError):
        ex.usd("1").model_validate({"amount": "1", "currency": "usd"})


# --- Reference data ----------------------------------------------------------


def test_verified_facts_need_evidence():
    with pytest.raises(ValidationError):
        Capability(name="image_input", verified=True)
    with pytest.raises(ValidationError):
        PriceEntry(
            price_ref="p",
            token_type="input",
            amount="1",
            per_tokens=1000,
            currency="USD",
        )


def test_catalogue_ids_are_unique():
    catalogue = ex.model_catalogue()
    with pytest.raises(ValidationError):
        type(catalogue)(version="v", entries=catalogue.entries + catalogue.entries[:1])


# --- Routing and caching -----------------------------------------------------


def test_routing_target_must_be_eligible_and_complete():
    data = ex.routing_decision().model_dump()
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(data | {"eligible": ("synthetic-large",)})
    with pytest.raises(ValidationError):
        RoutingDecision.model_validate(data | {"target_model_id": None})
    none = RoutingDecision.model_validate(
        data
        | {
            "target_model_id": None,
            "equivalence_group": None,
            "tier": None,
            "eligible": (),
            "reason_code": "no_eligible_model",
        }
    )
    assert none.target_model_id is None


def test_scope_refs():
    assert CacheScope(kind=ScopeKind.GLOBAL).ref is None
    with pytest.raises(ValidationError):
        CacheScope(kind=ScopeKind.SESSION)
    with pytest.raises(ValidationError):
        CacheScope(kind=ScopeKind.GLOBAL, ref="sess-1")


def test_cache_key_reports_unknown_components():
    key = ex.cache_key()
    assert not key.has_unknown
    unknown = key.components[0].model_copy(
        update={"state": ComponentState.UNKNOWN, "fingerprint": None}
    )
    assert key.model_copy(update={"components": (unknown,)}).has_unknown


def test_lookup_result_consistency():
    with pytest.raises(ValidationError):
        CacheLookupResult(tier=CacheTier.EXACT, outcome=LookupOutcome.INELIGIBLE)
    with pytest.raises(ValidationError):
        CacheLookupResult(tier=CacheTier.EXACT, outcome=LookupOutcome.HIT)
    with pytest.raises(ValidationError):
        CacheLookupResult(
            tier=CacheTier.SEMANTIC, outcome=LookupOutcome.HIT, entry_id="entry-1"
        )


def test_store_decision_needs_a_reason_to_skip():
    with pytest.raises(ValidationError):
        CacheStoreDecision(store=False)
    with pytest.raises(ValidationError):
        CacheStoreDecision(store=True, skip_reason="truncated")


# --- Model results and attempts ----------------------------------------------


def test_model_result_is_discriminated_by_outcome():
    from pydantic import TypeAdapter

    adapter = TypeAdapter(ModelResult)
    for result in ex.model_results():
        parsed = adapter.validate_json(result.model_dump_json())
        assert type(parsed) is type(result)
    with pytest.raises(ValidationError):
        adapter.validate_python({"outcome": "maybe", "source": "fake"})


def test_attempt_action_fields_match_the_action():
    with pytest.raises(ValidationError):
        AttemptAction(action=ActionKind.INVOKE, reason="primary")
    with pytest.raises(ValidationError):
        AttemptAction(action=ActionKind.FAIL, reason="x")
    with pytest.raises(ValidationError):
        AttemptAction(action=ActionKind.RETURN, reason="x", failure="no_answer")


def test_attempt_record_outcome_fields():
    data = ex.attempt_record().model_dump()
    with pytest.raises(ValidationError):
        type(ex.attempt_record()).model_validate(data | {"outcome": "error"})


def test_detector_that_did_not_run_cannot_fire():
    with pytest.raises(ValidationError):
        DetectorVerdict(
            detector="judge", version="0", state="not_evaluated", fired=True
        )


def test_final_response_status_consistency():
    ok, error = ex.final_responses()
    with pytest.raises(ValidationError):
        FinalResponse(status=ResponseStatus.OK, metadata=ok.metadata)
    with pytest.raises(ValidationError):
        FinalResponse(status=ResponseStatus.ERROR, answer="x", metadata=error.metadata)
    with pytest.raises(ValidationError):
        FinalResponse(status=ResponseStatus.OK, answer="x", metadata=error.metadata)


# --- Replay ------------------------------------------------------------------


def test_replay_case_pairing_rules():
    data = ex.replay_case().model_dump()
    case_type = type(ex.replay_case())
    with pytest.raises(ValidationError):
        case_type.model_validate(data | {"pairing_flag": PairingFlag.NO_PRECEDING_USER})
    with pytest.raises(ValidationError):
        case_type.model_validate(data | {"pairing_flag": PairingFlag.CLEAN})
    no_reference = case_type.model_validate(
        data | {"references": (), "pairing_flag": PairingFlag.CLEAN}
    )
    assert no_reference.references == ()


def test_session_messages_keep_log_order():
    session = ex.session()
    with pytest.raises(ValidationError):
        type(session).model_validate(
            session.model_dump() | {"messages": session.model_dump()["messages"][::-1]}
        )


# --- Evaluation and events ---------------------------------------------------


def test_hit_rate_is_never_reported_alone():
    rate = ex.metric_values()[0]
    with pytest.raises(ValidationError):
        StratumResult(stratum=(), n_cases=1, metrics=(rate,))


def test_metric_states():
    with pytest.raises(ValidationError):
        MetricValue(name=MetricName.AGREEMENT, state=MetricState.UNMEASURED, n=0)
    with pytest.raises(ValidationError):
        MetricValue(
            name=MetricName.TOTAL_COST, state=MetricState.MEASURED, value=1.0, n=3
        )
    with pytest.raises(ValidationError):
        MetricValue(
            name=MetricName.JUDGE_SCORE, state=MetricState.MEASURED, value=4.0, n=3
        )


def test_every_run_reports_the_as_logged_baseline():
    data = ex.evaluation_result().model_dump()
    with pytest.raises(ValidationError):
        EvaluationResult.model_validate(data | {"baselines": ("premium",)})
    with pytest.raises(ValidationError):
        EvaluationResult.model_validate(data | {"cases_covered": 51})


def test_live_runs_need_a_cap_and_live_sources_need_live_runs():
    data = ex.run_manifest().model_dump()
    with pytest.raises(ValidationError):
        RunManifest.model_validate(data | {"live_calls": True})
    with pytest.raises(ValidationError):
        RunManifest.model_validate(data | {"counterfactual_source": "live"})


def test_event_envelope_rules():
    event = ex.events()[2]
    data = event.model_dump()
    with pytest.raises(ValidationError):
        Event.model_validate(data | {"event_type": "cache_lookup"})
    with pytest.raises(ValidationError):
        Event.model_validate(data | {"request_id": None})
    with pytest.raises(ValidationError):
        Event.model_validate(
            data | {"run_mode": RunMode.LIVE}
        )  # has a case and log time
    with pytest.raises(ValidationError):
        Event.model_validate(data | {"duration_ms": None})
    run_level = Event(
        event_id="evt-9",
        event_type="run_started",
        run_id="run-1",
        run_mode=RunMode.LIVE,
        timestamp=ex.NOW,
        versions=ex.VERSIONS,
        payload=RunStarted(experiment_id="exp-0", manifest_ref="manifest.json"),
    )
    assert run_level.request_id is None
