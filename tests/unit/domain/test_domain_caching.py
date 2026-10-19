"""Cache policy: eligibility, scope, key drafts, validity, store rules."""

from datetime import timedelta

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.contracts import (
    AttemptOutcome,
    Component,
    ComponentName,
    EntryStatus,
    FinishReason,
    IneligibleReason,
    InvalidReason,
    LookupOutcome,
    ScopeKind,
    StoreSkipReason,
)
from metis_auto.domain.caching import (
    CachePolicyConfig,
    KeyVariant,
    compose_key,
    eligibility,
    select_scope,
    store_decision,
    validate_entry,
)

CONFIG = CachePolicyConfig()


def _known_request():
    return ex.request().model_copy(update={"structured_input": Component.absent()})


def test_unknown_component_is_ineligible():
    request = ex.request()  # structured_input is unknown
    scope = select_scope(request, CONFIG)
    reason = eligibility(request, ex.routing_decision(), scope, CONFIG)
    assert reason == IneligibleReason.UNKNOWN_COMPONENT


def test_attachments_are_ineligible():
    request = _known_request().model_copy(
        update={"attachments": Component.present((ex.ATTACHMENT,))}
    )
    scope = select_scope(request, CONFIG)
    assert eligibility(request, ex.routing_decision(), scope, CONFIG) == (
        IneligibleReason.ATTACHMENTS
    )


def test_scope_needs_its_reference():
    config = CachePolicyConfig(scope=ScopeKind.USER)
    request = _known_request()  # no user_ref
    scope = select_scope(request, config)
    assert scope is None
    assert eligibility(request, ex.routing_decision(), scope, config) == (
        IneligibleReason.SCOPE_REF_MISSING
    )


def test_eligible_request_composes_a_full_key_with_the_target_group():
    request = _known_request()
    scope = select_scope(request, CONFIG)
    assert eligibility(request, ex.routing_decision(), scope, CONFIG) is None
    draft = compose_key(ex.request_measurements(), ex.routing_decision(), scope, CONFIG)
    assert draft.target_group == ex.GROUP
    assert draft.scope.kind == ScopeKind.SESSION
    assert [c.component for c in draft.components][0] == ComponentName.MESSAGE


def test_unsupported_treatments_are_rejected_until_stage_8():
    with pytest.raises(ValueError):
        KeyVariant(message_treatment="nfkc_casefold_ws")


def test_validity_ttl_and_status():
    entry, key = ex.cache_entry(), ex.cache_key()
    assert validate_entry(entry, key, ex.NOW, CONFIG).outcome == LookupOutcome.HIT
    late = ex.NOW + timedelta(seconds=CONFIG.ttl_seconds + 1)
    expired = validate_entry(entry, key, late, CONFIG)
    assert expired.outcome == LookupOutcome.MISS
    assert expired.invalid_reason == InvalidReason.EXPIRED
    stale = entry.model_copy(update={"status": EntryStatus.INVALIDATED})
    assert validate_entry(stale, key, ex.NOW, CONFIG).invalid_reason == (
        InvalidReason.STATUS
    )
    assert validate_entry(None, key, ex.NOW, CONFIG).outcome == LookupOutcome.MISS


@pytest.mark.parametrize(
    "update, reason",
    [
        ({"finish_reason": FinishReason.LENGTH}, StoreSkipReason.TRUNCATED),
        ({"unsatisfactory": True}, StoreSkipReason.UNSATISFACTORY),
    ],
)
def test_store_rules_skip_bad_answers(update, reason):
    record = ex.attempt_record().model_copy(update=update)
    assert record.outcome == AttemptOutcome.RESPONSE
    decision = store_decision(True, False, record, CONFIG)
    assert decision.skip_reason == reason


def test_store_rules_accept_a_complete_answer():
    record = ex.attempt_record().model_copy(update={"unsatisfactory": False})
    assert store_decision(True, False, record, CONFIG).store
    assert store_decision(True, True, record, CONFIG).skip_reason == (
        StoreSkipReason.SERVED_FROM_CACHE
    )
