"""The benchmark's spend-guarded client and transient provider errors
(ADR-0053 amendment 2): a connection or timeout error charges the pre-call
estimate (conservative, never zero) and the run goes on; any other uncomputable
cost still stops it (ADR-0021); a streak of transient errors stops it too.
SYNTHETIC invocations, an in-memory ledger, no network."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.system import InMemorySpendLedger
from metis_auto.application.pipeline import SpendGuard
from metis_auto.contracts import AnswerSource, ErrorClass, ModelError
from metis_auto.wiring.benchmark import SpendGuardedClient

ESTIMATE = ex.cost_estimate()


class Scripted:
    """A live client that returns the scripted results in order."""

    source = AnswerSource.LIVE

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def invoke(self, invocation):
        self.calls += 1
        return self._results.pop(0)


def _error(error_class):
    return ModelError(
        error_class=error_class,
        retryable=True,
        provider_error_code=str(error_class.value),
        source=AnswerSource.LIVE,
    )


def _client(results, *, cap="1.00", **kw):
    ledger = InMemorySpendLedger(ex.usd(cap))
    guard = SpendGuard(ledger)
    live = Scripted(results)
    client = SpendGuardedClient(
        live,
        guard,
        estimate=lambda inv: ESTIMATE,
        actual=lambda inv, result: (
            ex.computed("0.01") if not isinstance(result, ModelError) else None
        ),
        **kw,
    )
    return client, guard, ledger, live


def _ok():
    return ex.model_results()[0]


@pytest.mark.parametrize("kind", [ErrorClass.CONNECTION, ErrorClass.TIMEOUT])
def test_a_transient_error_is_charged_the_estimate_and_the_run_goes_on(kind):
    client, guard, ledger, live = _client([_error(kind), _ok()])
    first = client.invoke(ex.model_invocation())
    assert isinstance(first, ModelError) and first.error_class == kind
    assert guard.stopped is None
    spent = ESTIMATE.cost.amount.amount
    assert ledger.remaining().amount == Decimal("1.00") - spent  # never free
    second = client.invoke(ex.model_invocation())  # the next call still goes out
    assert not isinstance(second, ModelError) and live.calls == 2
    assert ledger.remaining().amount == Decimal("1.00") - spent - Decimal("0.01")


def test_another_uncomputable_cost_still_stops_the_run():
    client, guard, ledger, live = _client([_error(ErrorClass.UNKNOWN), _ok()])
    client.invoke(ex.model_invocation())
    assert guard.stopped is not None
    refused = client.invoke(ex.model_invocation())
    assert isinstance(refused, ModelError)
    assert refused.provider_error_code == "spend_guard_refused" and live.calls == 1


def test_a_streak_of_transient_errors_stops_the_run():
    results = [_error(ErrorClass.CONNECTION)] * 3 + [_ok()]
    client, guard, _, live = _client(results, max_consecutive_transient=3)
    for _ in range(3):
        client.invoke(ex.model_invocation())
    assert guard.stopped is not None and "consecutive" in guard.stopped
    refused = client.invoke(ex.model_invocation())
    assert refused.provider_error_code == "spend_guard_refused" and live.calls == 3


def test_a_success_resets_the_streak():
    results = [
        _error(ErrorClass.CONNECTION),
        _error(ErrorClass.CONNECTION),
        _ok(),
        _error(ErrorClass.CONNECTION),
        _error(ErrorClass.CONNECTION),
        _ok(),
    ]
    client, guard, _, live = _client(results, max_consecutive_transient=3)
    for _ in range(6):
        client.invoke(ex.model_invocation())
    assert guard.stopped is None and live.calls == 6


def test_transient_errors_cannot_overspend_the_cap():
    one = ESTIMATE.cost.amount.amount
    client, guard, ledger, live = _client(
        [_error(ErrorClass.CONNECTION)] * 5, cap=str(one * 2)
    )
    client.invoke(ex.model_invocation())
    client.invoke(ex.model_invocation())
    refused = client.invoke(ex.model_invocation())  # nothing left for the estimate
    assert refused.provider_error_code == "spend_guard_refused" and live.calls == 2
    assert ledger.remaining().amount >= 0


def test_the_default_streak_limit_is_set():
    client, *_ = _client([])
    assert client.max_consecutive_transient >= 2
