"""The decision-router cascade (ADR-0047 point 3;
routing.md §7).

For one request, after the cheap features and before routing:

1. **Gate** (``fast_rules``, 0 ms): a decisive cheap-feature rule
   (``domain.routing.decision.needs_decision``) → ``skipped(rules_decisive)``.
2. **State**: the minimised ``DecisionState`` (never instructions or
   retrieved text); none can be built → ``skipped(ineligible_state)``.
3. **Router cache**: the first backend of the chain with a valid entry for
   this state, question set and its last-seen model revision → ``answered``
   with ``cache_hit``; no backend is called.
4. **Backend chain** of the configured mode, in order, under the time left of
   the step's deadline (``router.deadline_ms``, tightened by the request's own
   deadline minus ``reserved_pipeline_ms``). Per backend: availability, the
   circuit breaker; for **hosted** backends also the approval check (a
   dataset-derived state is refused unless ``real_data_approved``) and the
   **spend guard** (a pre-call estimate within the cap; an unpriced backend
   only with ``allow_unpriced``, and then the guard stops after that call).
   A ``DecisionError`` or an answer that does not match the asked questions
   is a failure (counted by the breaker); the next backend is tried.
5. **Confidence gate**: an answer whose lowest reported confidence is below
   ``min_confidence`` becomes ``failed(low_confidence)`` (answers kept as soft
   signals only if ``keep_soft_signals``). With ``escalate_on_low_confidence``
   the next backend is tried first, while time and budget remain; a
   low-confidence answer is then never cached.

Never raises for expected failures: every outcome is a ``DecisionOutcome``,
and a failed or skipped step leaves routing to the rules (P-6). The step's
duration and cost are a ``MeasurementRecord`` (router overhead, FR-ROUTE-04,
FR-ACCT-03): local answers cost zero (``local_compute``); a hosted answer's
cost is its own, or not computed.

Called by: application.pipeline. Calls: domain.routing.decision, ports
``BaseRouter``, ``Clock``, ``Tokenizer``; the spend guard. Built by:
wiring.routers. Traces: FR-FEAT-02, FR-ROUTE-03/04, FR-FAIL-04/05,
FR-ACCT-03, QA-LAT, QA-PRIV, ADR-0018.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import Field

from metis_auto.contracts import (
    BackendAttempt,
    ContractModel,
    Cost,
    CostBasis,
    CostStatus,
    DecisionError,
    DecisionFailureReason,
    DecisionLatencySource,
    DecisionOutcome,
    DecisionQuestionSet,
    DecisionResult,
    DecisionSkipReason,
    DecisionState,
    DecisionStatus,
    ErrorClass,
    MeasurementRecord,
    Money,
    Name,
    NotComputedReason,
    Request,
    RequestFeatures,
)
from metis_auto.contracts.events import BackendCircuit
from metis_auto.domain.routing.decision import (
    GateConfig,
    StateConfig,
    build_state,
    cache_material,
    check_result,
    needs_decision,
    result_confidence,
)
from metis_auto.ports import BaseRouter, Clock, Tokenizer

from ..measurement import Fingerprinter
from ..pipeline.spend_guard import SpendGuard
from .cache import RouterResultCache
from .circuit import CircuitBreaker

CASCADE_VERSION = "0.1.0"
MEASUREMENT = "decision"


class CascadeConfig(ContractModel):
    """The cascade's settings, mapped by wiring from ``[router]`` and the
    policy's gate and state sections (application cannot read settings)."""

    mode: Name
    chain: tuple[Name, ...]
    timeouts_ms: dict[Name, float]
    deadline_ms: float = Field(gt=0)
    deadline_grace_ms: float = Field(default=10, ge=0)
    reserved_pipeline_ms: float = Field(default=0, ge=0)
    min_confidence: float = Field(default=0.6, ge=0, le=1)
    keep_soft_signals: bool = False
    escalate_on_low_confidence: bool = False
    """A-103: false (default) ends the chain on a low-confidence answer; true
    passes to the next backend while time and budget remain (R8 compares)."""
    confidence_questions: tuple[Name, ...] | None = None
    """Q-61: the question IDs whose confidence the gate reads (None: every
    answer). Wiring passes the mapping questions by default
    (``router.confidence_questions = "mapping"``)."""
    confidence_statistic: Literal["reported", "probability"] = "reported"
    """What the gate reads per answer (``domain.routing.decision.answer_strength``)."""
    real_data_approved: bool = False
    allow_unpriced: bool = False
    cache_enabled: bool = True
    cache_normalisation: Name | None = "persian_fold_v1"
    cache_max_entries: int = Field(default=10_000, gt=0)
    cache_ttl_s: float = Field(default=86_400, gt=0)
    circuit_failure_threshold: int = Field(default=3, ge=1)
    circuit_window_s: float = Field(default=60, gt=0)
    circuit_cooldown_s: float = Field(default=30, gt=0)
    gate: GateConfig = GateConfig()
    state: StateConfig = StateConfig()
    states_dataset_derived: bool = True
    """Run-level: the requests come from a dataset (replay, dev slice). True by
    default, the safe side: hosted backends then refuse the state unless
    ``real_data_approved``. A caller with SYNTHETIC or owner-written text only
    (the chat demo, R7) sets it false."""


@dataclass(frozen=True)
class RouterStep:
    """What the pipeline emits for the step (content-free)."""

    outcome: DecisionOutcome
    circuits: tuple[BackendCircuit, ...]
    measurement: MeasurementRecord


def _zero() -> Cost:
    return Cost(
        status=CostStatus.COMPUTED,
        basis=CostBasis.LOCAL_COMPUTE,
        amount=Money(amount=Decimal("0"), currency="USD"),
    )


def _not_computed() -> Cost:
    return Cost(
        status=CostStatus.NOT_COMPUTED,
        basis=CostBasis.ACTUAL,
        reason=NotComputedReason.USAGE_UNKNOWN,
    )


def _sum(costs: list[Cost]) -> Cost | None:
    """None when nothing was called; not computed if any part is not."""
    if not costs:
        return None
    if any(c.status != CostStatus.COMPUTED or c.amount is None for c in costs):
        return Cost(
            status=CostStatus.NOT_COMPUTED,
            basis=CostBasis.ACTUAL,
            reason=NotComputedReason.COMPONENT_NOT_COMPUTED,
        )
    currencies = {c.amount.currency for c in costs if c.amount is not None}
    if len(currencies) > 1:
        return Cost(
            status=CostStatus.NOT_COMPUTED,
            basis=CostBasis.ACTUAL,
            reason=NotComputedReason.CURRENCY_MISMATCH,
        )
    hosted = [c for c in costs if c.basis != CostBasis.LOCAL_COMPUTE]
    total = sum((c.amount.amount for c in costs if c.amount), Decimal(0))
    return Cost(
        status=CostStatus.COMPUTED,
        basis=CostBasis.ACTUAL if hosted else CostBasis.LOCAL_COMPUTE,
        amount=Money(amount=total, currency=currencies.pop()),
        price_refs=tuple(dict.fromkeys(r for c in hosted for r in c.price_refs)),
        price_table_version=next(
            (c.price_table_version for c in hosted if c.price_table_version), None
        ),
    )


class RouterCascade:
    def __init__(
        self,
        config: CascadeConfig,
        *,
        backends: Mapping[str, BaseRouter],
        questions: DecisionQuestionSet,
        clock: Clock,
        fingerprinter: Fingerprinter,
        tokenizer: Tokenizer,
        spend_guard: SpendGuard | None = None,
    ) -> None:
        missing = [name for name in config.chain if name not in backends]
        if missing:
            raise ValueError(f"router chain names unbuilt backends: {missing}")
        missing_timeouts = [n for n in config.chain if n not in config.timeouts_ms]
        if missing_timeouts:
            raise ValueError(f"no timeout for backends {missing_timeouts}")
        hosted = [n for n in config.chain if backends[n].kind == "hosted"]
        if hosted and spend_guard is None:
            raise ValueError(
                f"hosted decision backends need a spend guard (ADR-0003): {hosted}"
            )
        self._config = config
        self._backends = dict(backends)
        self._questions = questions
        self._clock = clock
        self._fp = fingerprinter
        self._tokenizer = tokenizer
        self._guard = spend_guard
        self.breaker = CircuitBreaker(
            clock,
            failure_threshold=config.circuit_failure_threshold,
            window_s=config.circuit_window_s,
            cooldown_s=config.circuit_cooldown_s,
        )
        self.cache = RouterResultCache(
            clock, max_entries=config.cache_max_entries, ttl_s=config.cache_ttl_s
        )

    @property
    def mode(self) -> str:
        return self._config.mode

    @property
    def questions(self) -> DecisionQuestionSet:
        return self._questions

    @property
    def guard_stopped(self) -> str | None:
        return self._guard.stopped if self._guard is not None else None

    # ------------------------------------------------------------------ step
    def decide(self, request: Request, features: RequestFeatures) -> RouterStep:
        cfg = self._config
        start = self._clock.monotonic_ms()
        circuits = tuple(
            BackendCircuit(backend=name, state=self.breaker.state(name))
            for name in cfg.chain
        )

        def done(outcome_args: dict, costs: list[Cost], backend: str) -> RouterStep:
            total = max(0.0, self._clock.monotonic_ms() - start)
            outcome = DecisionOutcome(
                question_set_version=self._questions.version
                if outcome_args.get("status") != DecisionStatus.SKIPPED
                else None,
                total_ms=total,
                **outcome_args,
            )
            measurement = MeasurementRecord(
                measurement=MEASUREMENT,
                backend=backend,
                duration_ms=total,
                cost=_sum(costs),
            )
            return RouterStep(outcome, circuits, measurement)

        cascade_ref = f"router-cascade@{CASCADE_VERSION}"
        gate = needs_decision(features, cfg.gate)
        if gate is not None:
            return done(
                {
                    "status": DecisionStatus.SKIPPED,
                    "skip_reason": DecisionSkipReason.RULES_DECISIVE,
                    "rule_id": gate.rule_id,
                },
                [],
                cascade_ref,
            )
        state = build_state(
            request,
            features,
            cfg.state,
            dataset_derived=cfg.states_dataset_derived,
        )
        if state is None:
            return done(
                {
                    "status": DecisionStatus.SKIPPED,
                    "skip_reason": DecisionSkipReason.INELIGIBLE_STATE,
                },
                [],
                cascade_ref,
            )
        if not cfg.chain:
            return done(
                {
                    "status": DecisionStatus.FAILED,
                    "failure_reason": DecisionFailureReason.NO_BACKEND,
                },
                [],
                cascade_ref,
            )

        state_fp = self._fp.fingerprint(
            "decision_state", cache_material(state, cfg.cache_normalisation)
        )
        cache_key = self._fp.fingerprint(
            "router_cache",
            {
                "state": state_fp,
                "questions": self._questions.version,
                "language": self._questions.language_variant.value,
            },
        )
        if cfg.cache_enabled:
            for name in cfg.chain:
                cached = self.cache.get(name, cache_key)
                if cached is not None:
                    lookup_ms = max(0.0, self._clock.monotonic_ms() - start)
                    hit = cached.model_copy(
                        update={
                            "cache_hit": True,
                            "latency_ms": lookup_ms,
                            "latency_source": DecisionLatencySource.MEASURED_LOCAL,
                            "usage": None,
                            "cost": _zero(),
                            "state_fingerprint": state_fp,
                        }
                    )
                    return self._gated(hit, (), [_zero()], done)

        budget = cfg.deadline_ms
        if features.deadline_ms is not None:
            budget = min(budget, features.deadline_ms - cfg.reserved_pipeline_ms)
        attempts: list[BackendAttempt] = []
        costs: list[Cost] = []
        last_failure = DecisionFailureReason.NO_BACKEND
        last_error: ErrorClass | None = None
        low_result: DecisionResult | None = None
        for name in cfg.chain:
            backend = self._backends[name]
            remaining = budget - (self._clock.monotonic_ms() - start)
            refusal, estimate = self._refusal(name, backend, state, remaining)
            if refusal is not None:
                attempts.append(
                    BackendAttempt(
                        backend=backend.ref,
                        answered=False,
                        failure_reason=refusal,
                        latency_ms=0.0,
                    )
                )
                last_failure, last_error = refusal, None
                if refusal == DecisionFailureReason.TIMEOUT:
                    break  # no time left for any later backend
                continue
            timeout = min(cfg.timeouts_ms[name], remaining)
            reply = backend.decide(
                state, self._questions, timeout_ms=timeout + cfg.deadline_grace_ms
            )
            overran = reply.latency_ms > timeout
            cost = self._charge(backend, reply, estimate)
            if cost is not None:
                costs.append(cost)
            failure, error = self._failure_of(reply)
            if failure is not None:
                self.breaker.record_failure(name)
                attempts.append(
                    BackendAttempt(
                        backend=backend.ref,
                        answered=False,
                        failure_reason=failure,
                        error_class=error,
                        latency_ms=reply.latency_ms,
                        overran_deadline=overran,
                    )
                )
                last_failure, last_error = failure, error
                continue
            assert isinstance(reply, DecisionResult)
            self.breaker.record_success(name)
            result = reply.model_copy(update={"state_fingerprint": state_fp})
            escalate = cfg.escalate_on_low_confidence and self._low(result)
            if cfg.cache_enabled and not escalate:
                self.cache.put(name, cache_key, result)
            else:
                self.cache.observe(name, result.model_revision)
            attempts.append(
                BackendAttempt(
                    backend=backend.ref,
                    answered=True,
                    latency_ms=reply.latency_ms,
                    overran_deadline=overran,
                )
            )
            if escalate:
                # A-103 option: try the next backend while time and budget remain.
                low_result = result
                last_failure, last_error = DecisionFailureReason.LOW_CONFIDENCE, None
                continue
            return self._gated(result, tuple(attempts), costs, done)
        if low_result is not None:
            # An answer did come back, only below the gate: that is the outcome,
            # whatever a later backend did.
            last_failure, last_error = DecisionFailureReason.LOW_CONFIDENCE, None
        keep_soft = low_result is not None and cfg.keep_soft_signals
        return done(
            {
                "status": DecisionStatus.FAILED,
                "soft_result": low_result if keep_soft else None,
                "failure_reason": last_failure,
                "error_class": last_error
                if last_failure == DecisionFailureReason.ERROR
                else None,
                "attempts": tuple(attempts),
            },
            costs,
            cascade_ref,
        )

    # --------------------------------------------------------------- helpers
    def _gated(self, result: DecisionResult, attempts, costs, done) -> RouterStep:
        backend = f"{result.backend.name}@{result.backend.version}"
        if self._low(result):
            return done(
                {
                    "status": DecisionStatus.FAILED,
                    "failure_reason": DecisionFailureReason.LOW_CONFIDENCE,
                    "soft_result": result if self._config.keep_soft_signals else None,
                    "attempts": attempts,
                },
                costs,
                backend,
            )
        return done(
            {
                "status": DecisionStatus.ANSWERED,
                "result": result,
                "attempts": attempts,
            },
            costs,
            backend,
        )

    def _refusal(
        self, name: str, backend: BaseRouter, state: DecisionState, remaining: float
    ):
        """Why ``backend`` is not called now (None: call it), and the pre-call
        estimate of a hosted backend. Order: time, availability, approval,
        spend guard, circuit (the breaker's half-open trial is taken last)."""
        if remaining <= 0:
            return DecisionFailureReason.TIMEOUT, None
        if not backend.available().available:
            return DecisionFailureReason.UNAVAILABLE, None
        estimate = None
        if backend.kind == "hosted":
            if state.dataset_derived and not self._config.real_data_approved:
                return DecisionFailureReason.REAL_DATA_NOT_APPROVED, None
            estimate = backend.estimate_cost(self._state_tokens(state))
            if not self._spend_allows(estimate):
                return DecisionFailureReason.BUDGET_BLOCKED, estimate
        if not self.breaker.allows(name):
            return DecisionFailureReason.CIRCUIT_OPEN, estimate
        return None, estimate

    def _low(self, result: DecisionResult) -> bool:
        """Below the confidence gate. No reported confidence is not low
        (A-105); it also never satisfies a mapping rule's confidence (P-6)."""
        confidence = result_confidence(
            result,
            self._config.confidence_questions,
            self._config.confidence_statistic,
        )
        return confidence is not None and confidence < self._config.min_confidence

    def _state_tokens(self, state: DecisionState) -> int:
        text = state.message
        if state.previous_user_turn.value:
            text += "\n" + state.previous_user_turn.value
        return self._tokenizer.count(text).tokens

    def _spend_allows(self, estimate) -> bool:
        guard = self._guard
        if guard is None or guard.stopped is not None:
            return False
        if estimate is None or estimate.cost.status != CostStatus.COMPUTED:
            return self._config.allow_unpriced and guard.remaining() is not None
        return guard.allows(estimate)

    def _charge(self, backend: BaseRouter, reply, estimate) -> Cost | None:
        """The attempt's cost; hosted calls are charged to the ledger."""
        if backend.kind == "local":
            return _zero()
        guard = self._guard
        assert guard is not None  # enforced in __init__
        actual = reply.cost if isinstance(reply, DecisionResult) else None
        computed = (
            actual is not None
            and actual.status == CostStatus.COMPUTED
            and actual.amount is not None
        )
        if estimate is not None and estimate.cost.status == CostStatus.COMPUTED:
            guard.charge(actual if computed else None, estimate)
        elif computed and actual is not None and actual.amount is not None:
            guard.charge_amount(actual.amount)
        else:
            guard.stop(
                "an unpriced decision backend was called (allow_unpriced); "
                "no further hosted router calls in this run"
            )
        return actual if computed else _not_computed()

    def _failure_of(
        self, reply: DecisionResult | DecisionError
    ) -> tuple[DecisionFailureReason | None, ErrorClass | None]:
        if isinstance(reply, DecisionError):
            if reply.invalid_response:
                return DecisionFailureReason.INVALID_RESPONSE, None
            if reply.error_class == ErrorClass.TIMEOUT:
                return DecisionFailureReason.TIMEOUT, None
            return DecisionFailureReason.ERROR, reply.error_class
        if check_result(reply, self._questions) is not None:
            return DecisionFailureReason.INVALID_RESPONSE, None
        return None, None
