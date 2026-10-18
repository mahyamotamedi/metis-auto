"""The request pipeline (CMP-01; request_lifecycle.md, ADR-0010).

Responsibility: run the fixed stage order for one request — receive, measure,
features, route, cache lookup, context build, attempt loop, store, respond —
emitting an event at every decision point. It **coordinates and measures**;
every decision is a call into ``domain`` (P-1). Expected failures return a
``FinalResponse`` with an error status; exceptions mean programming or
configuration errors.

Called by: callers of the in-process API (scripts, tests, the replay harness;
later the gateway). Calls: domain.{features, routing, caching, context,
attempts, accounting}; application.{measurement, events}; ports
``ModelClient``, ``CacheStore``, ``Clock``, ``IdSource`` (and ``SpendLedger``
via the spend guard). Built by: wiring. Config: ``PipelineConfig``.
Traces: FR-API-01, FR-OBS-01, FR-ACCT-03…05, FR-CASC-*, FR-FAIL-*, ADR-0010.

Status: walking skeleton. TODO markers name the missing pieces: semantic tier,
re-route on context overflow, savings per baseline, model-based measurements.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from metis_auto.contracts import (
    ActionKind,
    AnswerSource,
    AttemptAction,
    AttemptKind,
    AttemptOutcome,
    AttemptRecord,
    AttemptState,
    CacheEntry,
    CacheKey,
    CacheLookupResult,
    CacheTier,
    CatalogueEntry,
    ContextPlan,
    Cost,
    CostBasis,
    EntryStatus,
    ErrorClass,
    FailureReason,
    FinalResponse,
    Identifier,
    LatencySource,
    LookupOutcome,
    ModelError,
    ModelInvocation,
    ModelNoAnswer,
    ModelResponse,
    ModelResult,
    OverflowOutcome,
    Request,
    RequestFeatures,
    RequestMeasurements,
    ResponseMetadata,
    ResponseStatus,
    RoutingDecision,
    ServedBy,
    SpanName,
    SpanTiming,
    TokenUsage,
)
from metis_auto.contracts.events import (
    AttemptFinished,
    AttemptStarted,
    BudgetBlocked,
    CacheLookedUp,
    CacheStored,
    CacheStoreSkipped,
    ContextBuilt,
    EscalationTriggered,
    FailoverTriggered,
    FeaturesExtracted,
    RequestReceived,
    ResponseReturned,
    RetryScheduled,
    RoutingDecided,
)
from metis_auto.domain import accounting, attempts, caching, features, routing
from metis_auto.domain.attempts import Detector
from metis_auto.domain.context import ContextStrategy
from metis_auto.domain.routing import RoutingPolicy
from metis_auto.ports import CacheStore, Clock, IdSource, ModelClient

from ..events import EventRecorder
from ..measurement import MeasurementService
from .config import PipelineConfig
from .spend_guard import SpendGuard

_LATENCY_SOURCE = {
    AnswerSource.FAKE: LatencySource.SIMULATED,
    AnswerSource.NONE: LatencySource.SIMULATED,
    AnswerSource.LOGGED: LatencySource.RECORDED,
    AnswerSource.RECORDED: LatencySource.RECORDED,
    AnswerSource.LIVE: LatencySource.MEASURED_LOCAL,
}


@dataclass
class _Run:
    """Working state of one request. In memory only: it holds content."""

    request_id: Identifier
    request: Request
    case_id: Identifier | None
    logged_timestamp: datetime | None
    started_ms: float
    spans: list[SpanTiming] = field(default_factory=list)
    records: list[AttemptRecord] = field(default_factory=list)
    responses: dict[str, ModelResponse] = field(default_factory=dict)
    plans: dict[str, ContextPlan] = field(default_factory=dict)
    measurements: RequestMeasurements | None = None


class RequestPipeline:
    def __init__(
        self,
        *,
        config: PipelineConfig,
        routing_policy: RoutingPolicy,
        context_strategy: ContextStrategy,
        detectors: Sequence[Detector],
        measurement: MeasurementService,
        recorder: EventRecorder,
        model_client: ModelClient,
        cache_store: CacheStore,
        clock: Clock,
        ids: IdSource,
        spend_guard: SpendGuard | None = None,
    ) -> None:
        if model_client.source == AnswerSource.LIVE and spend_guard is None:
            raise ValueError("a live model client needs a spend guard (ADR-0003)")
        self._config = config
        self._routing_policy = routing_policy
        self._context = context_strategy
        self._detectors = tuple(detectors)
        self._measurement = measurement
        self._recorder = recorder
        self._client = model_client
        self._store = cache_store
        self._clock = clock
        self._ids = ids
        self._guard = spend_guard
        self._entries = {e.model_id: e for e in config.catalogue.entries}

    # --- the in-process API (FR-API-01) ---

    def handle(
        self,
        request: Request,
        *,
        case_id: Identifier | None = None,
        logged_timestamp: datetime | None = None,
    ) -> FinalResponse:
        """Answer one request. ``case_id`` and ``logged_timestamp`` are set by
        the replay harness only (never visible to policies)."""
        run = self._receive(request, case_id, logged_timestamp)
        measurements = self._measure(run)
        feats = self._extract_features(run, measurements)
        decision = self._route(run, feats)
        lookup, entry, key = self._cache_lookup(run, measurements, decision)
        if entry is not None:
            return self._respond_from_cache(run, decision, entry)
        action = self._attempt_loop(run, decision)
        self._store_answer(run, action, key, lookup)
        return self._respond(run, action)

    # --- stage 0: receive ---

    def _receive(
        self,
        request: Request,
        case_id: Identifier | None,
        logged_timestamp: datetime | None,
    ) -> _Run:
        return _Run(
            request_id=self._ids.new_id("req"),
            request=request,
            case_id=case_id,
            logged_timestamp=logged_timestamp,
            started_ms=self._clock.monotonic_ms(),
        )

    # --- stage 1: measure ---

    def _measure(self, run: _Run) -> RequestMeasurements:
        start = self._clock.monotonic_ms()
        measurements = self._measurement.measure(run.request)
        run.measurements = measurements
        self._span(run, SpanName.MEASURE, start)
        # Emitted once the component states are known (lifecycle §2).
        self._emit(
            run,
            RequestReceived(
                components=measurements.components,
                traffic_source=run.request.traffic_source,
            ),
        )
        return measurements

    # --- stage 2: features ---

    def _extract_features(
        self, run: _Run, measurements: RequestMeasurements
    ) -> RequestFeatures:
        start = self._clock.monotonic_ms()
        feats = features.extract_features(
            run.request, measurements, self._config.features
        )
        duration = self._span(run, SpanName.FEATURES, start)
        self._emit(
            run,
            FeaturesExtracted(features=feats, measurements=measurements.records),
            span=SpanName.FEATURES,
            duration_ms=duration,
        )
        return feats

    # --- stage 3: route ---

    def _route(self, run: _Run, feats: RequestFeatures) -> RoutingDecision:
        start = self._clock.monotonic_ms()
        decision = routing.route(
            feats,
            self._config.catalogue,
            self._routing_policy,
            self._config.routing,
        )
        duration = self._span(run, SpanName.ROUTE, start)
        self._emit(
            run,
            RoutingDecided(decision=decision),
            span=SpanName.ROUTE,
            duration_ms=duration,
        )
        return decision

    # --- stage 4: cache lookup ---

    def _cache_lookup(
        self,
        run: _Run,
        measurements: RequestMeasurements,
        decision: RoutingDecision,
    ) -> tuple[CacheLookupResult, CacheEntry | None, CacheKey | None]:
        """Exact tier only. TODO(Stage 8): semantic tier (embed, index query,
        threshold) when ``config.cache.semantic_enabled``."""
        start = self._clock.monotonic_ms()
        config = self._config.cache
        scope = caching.select_scope(run.request, config)
        reason = caching.eligibility(run.request, decision, scope, config)
        key: CacheKey | None = None
        entry: CacheEntry | None = None
        if reason is not None:
            result = caching.ineligible_result(reason, config)
        else:
            assert scope is not None  # eligibility checked it
            draft = caching.compose_key(measurements, decision, scope, config)
            key = self._measurement.seal_key(draft)
            found = self._store.get(key.key)
            result = caching.validate_entry(found, key, self._clock.now(), config)
            entry = found if result.outcome == LookupOutcome.HIT else None
        duration = self._span(run, SpanName.CACHE_LOOKUP_EXACT, start)
        self._emit(
            run,
            CacheLookedUp(result=result),
            span=SpanName.CACHE_LOOKUP_EXACT,
            duration_ms=duration,
        )
        return result, entry, key

    def _respond_from_cache(
        self, run: _Run, decision: RoutingDecision, entry: CacheEntry
    ) -> FinalResponse:
        target = self._entries[decision.target_model_id]
        counts = self._measurement.target_counts(run.request, target)
        input_tokens = accounting.sum_counts(c.total for c in counts.components)
        usage = self._measurement.counted_usage(target, input_tokens, entry.answer)
        avoided = accounting.cost_of(
            usage, target, self._config.prices, CostBasis.AVOIDED_ESTIMATE
        )
        overhead = self._overhead_cost()
        metadata = self._metadata(
            run,
            served_by=ServedBy.CACHE,
            final_model_id=entry.producing_model_id,
            cache_entry=entry,
            total_cost=overhead,
            overhead_cost=overhead,
            avoided_cost=avoided,
        )
        return self._finish(
            run,
            FinalResponse(
                status=ResponseStatus.OK, answer=entry.answer, metadata=metadata
            ),
        )

    # --- stage 5: context build (per distinct target) ---

    def _plan_for(
        self, run: _Run, target: CatalogueEntry, attempt_id: str
    ) -> ContextPlan:
        if target.model_id in run.plans:
            return run.plans[target.model_id]
        start = self._clock.monotonic_ms()
        counts = self._measurement.target_counts(run.request, target)
        plan = self._context.build(
            run.request,
            run.measurements,
            counts,
            target,
            self._config.context,
            rerouted=False,  # TODO(Stage 8): re-route on overflow
        )
        duration = self._span(run, SpanName.CONTEXT, start)
        self._emit(
            run,
            ContextBuilt(record=plan.record),
            attempt_id=attempt_id,
            span=SpanName.CONTEXT,
            duration_ms=duration,
        )
        run.plans[target.model_id] = plan
        return plan

    # --- stage 6: attempt loop (ADR-0013) ---

    def _attempt_loop(self, run: _Run, decision: RoutingDecision) -> AttemptAction:
        limit = self._config.attempts.max_attempts + 1
        for _ in range(limit):
            action = attempts.next_action(
                self._attempt_state(run, decision),
                self._config.catalogue,
                self._config.attempts,
            )
            if action.action != ActionKind.INVOKE:
                return action
            self._announce(run, decision, action)
            if action.backoff_ms:
                self._clock.sleep_ms(action.backoff_ms)
            run.records.append(self._attempt(run, action))
        raise RuntimeError("attempt policy did not terminate within max_attempts")

    def _attempt_state(self, run: _Run, decision: RoutingDecision) -> AttemptState:
        deadline = run.request.deadline_ms or self._config.default_deadline_ms
        remaining = None
        if deadline is not None:
            remaining = deadline - (self._clock.monotonic_ms() - run.started_ms)
        return AttemptState(
            request_id=run.request_id,
            decision=decision,
            attempts=tuple(run.records),
            deadline_remaining_ms=remaining,
            budget_remaining=self._guard.remaining() if self._guard else None,
        )

    def _announce(
        self, run: _Run, decision: RoutingDecision, action: AttemptAction
    ) -> None:
        """Retry, failover, and escalation events, before the new attempt."""
        if not run.records:
            return
        last = run.records[-1]
        target = action.target_model_id
        if action.kind == AttemptKind.RETRY:
            payload = RetryScheduled(
                from_attempt_id=last.attempt_id,
                model_id=target,
                error_class=last.error_class or ErrorClass.UNKNOWN,
                backoff_ms=action.backoff_ms or 0.0,
            )
        elif action.kind == AttemptKind.FAILOVER:
            payload = FailoverTriggered(
                from_model_id=last.model_id,
                to_model_id=target,
                equivalence_group=self._entries[target].equivalence_group,
                error_class=last.error_class,
            )
        elif action.kind == AttemptKind.ESCALATION:
            payload = EscalationTriggered(
                from_model_id=last.model_id,
                to_model_id=target,
                from_tier=self._entries[last.model_id].tier,
                to_tier=self._entries[target].tier,
                verdicts=last.verdicts,
            )
        else:
            return
        self._emit(run, payload, attempt_id=last.attempt_id)

    def _attempt(self, run: _Run, action: AttemptAction) -> AttemptRecord:
        target = self._entries[action.target_model_id]
        attempt_id = self._ids.new_id("att")
        parent = run.records[-1].attempt_id if run.records else None
        base = dict(
            attempt_id=attempt_id,
            parent_attempt_id=parent,
            number=len(run.records),
            kind=action.kind,
            model_id=target.model_id,
            provider=target.provider,
        )
        self._emit(
            run,
            AttemptStarted(
                kind=action.kind,
                number=len(run.records),
                model_id=target.model_id,
                provider=target.provider,
            ),
            attempt_id=attempt_id,
            parent_attempt_id=parent,
        )
        plan = self._plan_for(run, target, attempt_id)
        if plan.record.overflow not in (
            OverflowOutcome.FITS,
            OverflowOutcome.TRIMMED_TO_FIT,
        ):
            # TODO(Stage 8): REROUTE_REQUESTED re-runs routing once with a
            # minimum window (lifecycle §1 re-entry). Until then an overflow is
            # recorded as a context_overflow attempt that made no call.
            record = AttemptRecord(
                **base,
                outcome=AttemptOutcome.ERROR,
                error_class=ErrorClass.CONTEXT_OVERFLOW,
            )
            return self._finish_attempt(run, record, None, None)

        reserved = plan.record.reserved_output_tokens
        if self._client.source == AnswerSource.LIVE:
            input_tokens = plan.record.input_tokens
            assert input_tokens is not None  # the message is always counted
            estimate = accounting.pre_call_estimate(
                target, input_tokens, reserved or 0, self._config.prices
            )
            assert self._guard is not None  # enforced in __init__
            if not self._guard.allows(estimate):
                self._emit(
                    run,
                    BudgetBlocked(
                        estimate=estimate, cap_remaining=self._guard.remaining()
                    ),
                    attempt_id=attempt_id,
                )
                record = AttemptRecord(**base, outcome=AttemptOutcome.BUDGET_BLOCKED)
                return self._finish_attempt(run, record, None, None)

        invocation = ModelInvocation(
            request_id=run.request_id,
            attempt_id=attempt_id,
            attempt_kind=action.kind,
            model_id=target.model_id,
            parts=plan.parts,
            attachments=run.request.attachments.value or (),
            max_output_tokens=reserved or None,
            timeout_ms=self._config.attempt_timeout_ms,
            case_id=run.case_id,
        )
        start = self._clock.monotonic_ms()
        result = self._client.invoke(invocation)
        duration = self._clock.monotonic_ms() - start
        record = self._record(base, target, plan, result, duration)
        if isinstance(result, ModelResponse):
            run.responses[attempt_id] = result
        if self._client.source == AnswerSource.LIVE and self._guard is not None:
            self._guard.charge(record.cost)
        return self._finish_attempt(run, record, result, duration)

    def _record(
        self,
        base: dict[str, object],
        target: CatalogueEntry,
        plan: ContextPlan,
        result: ModelResult,
        duration: float,
    ) -> AttemptRecord:
        if isinstance(result, ModelNoAnswer):
            # A coverage gap, not a call: no cost (ADR-0014).
            return AttemptRecord(
                **base, outcome=AttemptOutcome.NO_ANSWER, source=result.source
            )
        if isinstance(result, ModelError):
            # Charged, but the provider reported no usage: cost not computed.
            return AttemptRecord(
                **base,
                outcome=AttemptOutcome.ERROR,
                source=result.source,
                error_class=result.error_class,
                cost=accounting.cost_of(None, target, self._config.prices),
                duration_ms=duration,
            )
        usage = result.usage or self._measurement.counted_usage(
            target, plan.record.input_tokens, result.text
        )
        verdicts = attempts.run_detectors(result, self._detectors)
        return AttemptRecord(
            **base,
            outcome=AttemptOutcome.RESPONSE,
            source=result.source,
            finish_reason=result.finish_reason,
            usage=usage,
            cost=accounting.cost_of(usage, target, self._config.prices),
            duration_ms=duration,
            verdicts=verdicts,
            unsatisfactory=attempts.is_unsatisfactory(verdicts),
        )

    def _finish_attempt(
        self,
        run: _Run,
        record: AttemptRecord,
        result: ModelResult | None,
        duration: float | None,
    ) -> AttemptRecord:
        span = None
        if duration is not None and result is not None:
            span = SpanName.MODEL_CALL
            run.spans.append(
                SpanTiming(
                    span=SpanName.MODEL_CALL,
                    duration_ms=duration,
                    source=_LATENCY_SOURCE[result.source],
                    attempt_id=record.attempt_id,
                )
            )
        version = (
            result.provider_model_version if isinstance(result, ModelResponse) else None
        )
        self._emit(
            run,
            AttemptFinished(record=record, provider_model_version=version),
            attempt_id=record.attempt_id,
            parent_attempt_id=record.parent_attempt_id,
            span=span,
            duration_ms=duration if span else None,
        )
        return record

    # --- stage 7: store ---

    def _store_answer(
        self,
        run: _Run,
        action: AttemptAction,
        key: CacheKey | None,
        lookup: CacheLookupResult,
    ) -> None:
        start = self._clock.monotonic_ms()
        final = self._returned_record(run, action)
        eligible = lookup.outcome != LookupOutcome.INELIGIBLE and key is not None
        decision = caching.store_decision(
            eligible, served_from_cache=False, final=final, config=self._config.cache
        )
        if decision.store and key is not None and final is not None:
            target = self._entries[final.model_id]
            entry = CacheEntry(
                entry_id=self._ids.new_id("entry"),
                key=key,
                answer=run.responses[final.attempt_id].text,
                producing_model_id=final.model_id,
                producing_tier=target.tier,
                created_at=self._clock.now(),
                status=EntryStatus.COMPLETE,
                source_request_id=run.request_id,
                versions=self._recorder.versions,
            )
            self._store.put(entry)
            payload = CacheStored(
                entry_id=entry.entry_id,
                key_variant=key.variant,
                scope=key.scope.kind,
                semantic_indexed=False,  # TODO(Stage 8): VectorIndex.add
            )
        else:
            payload = CacheStoreSkipped(reason=decision.skip_reason)
        duration = self._span(run, SpanName.CACHE_STORE, start)
        self._emit(run, payload, span=SpanName.CACHE_STORE, duration_ms=duration)

    # --- stage 8: respond ---

    def _respond(self, run: _Run, action: AttemptAction) -> FinalResponse:
        attempt_costs = [r.cost for r in run.records if r.cost is not None]
        overhead = self._overhead_cost()
        total = accounting.total_cost(
            [*attempt_costs, overhead],
            CostBasis.ACTUAL,
            self._config.prices,
            self._config.accounting,
        )
        final = self._returned_record(run, action)
        if final is None:
            metadata = self._metadata(
                run,
                served_by=ServedBy.NONE,
                total_cost=total,
                overhead_cost=overhead,
                failure=action.failure or FailureReason.ALL_ATTEMPTS_FAILED,
            )
            response = FinalResponse(status=ResponseStatus.ERROR, metadata=metadata)
        else:
            metadata = self._metadata(
                run,
                served_by=ServedBy.MODEL,
                final_model_id=final.model_id,
                answer_usage=final.usage,
                total_cost=total,
                overhead_cost=overhead,
                unsatisfactory_returned=action.unsatisfactory_returned,
            )
            response = FinalResponse(
                status=ResponseStatus.OK,
                answer=run.responses[final.attempt_id].text,
                metadata=metadata,
            )
        return self._finish(run, response)

    def _finish(self, run: _Run, response: FinalResponse) -> FinalResponse:
        duration = self._span(run, SpanName.REQUEST, run.started_ms)
        metadata = response.metadata.model_copy(update={"spans": tuple(run.spans)})
        response = response.model_copy(update={"metadata": metadata})
        self._emit(
            run,
            ResponseReturned(status=response.status, metadata=metadata),
            span=SpanName.REQUEST,
            duration_ms=duration,
        )
        return response

    # --- helpers ---

    def _returned_record(
        self, run: _Run, action: AttemptAction
    ) -> AttemptRecord | None:
        if action.action != ActionKind.RETURN:
            return None
        return next(r for r in run.records if r.attempt_id == action.return_attempt_id)

    def _overhead_cost(self) -> Cost:
        """Router, embedder, judge, verifier calls (FR-ACCT-03). None exist yet:
        TODO(Stage 8) sum the costs on ``MeasurementRecord``s."""
        return accounting.total_cost(
            [], CostBasis.ACTUAL, self._config.prices, self._config.accounting
        )

    def _metadata(
        self,
        run: _Run,
        *,
        served_by: ServedBy,
        total_cost: Cost,
        overhead_cost: Cost,
        final_model_id: str | None = None,
        cache_entry: CacheEntry | None = None,
        avoided_cost: Cost | None = None,
        answer_usage: TokenUsage | None = None,
        unsatisfactory_returned: bool = False,
        failure: FailureReason | None = None,
    ) -> ResponseMetadata:
        kinds = [r.kind for r in run.records]
        return ResponseMetadata(
            request_id=run.request_id,
            caller_request_ref=run.request.caller_request_ref,
            served_by=served_by,
            final_model_id=final_model_id,
            cache_tier=CacheTier.EXACT if cache_entry else None,  # semantic: TODO
            cache_entry_id=cache_entry.entry_id if cache_entry else None,
            attempt_ids=tuple(r.attempt_id for r in run.records),
            answer_usage=answer_usage,
            total_cost=total_cost,
            overhead_cost=overhead_cost,
            avoided_cost=avoided_cost,
            # TODO(Stage 8): savings per configured baseline (FR-ACCT-05).
            retries=kinds.count(AttemptKind.RETRY),
            failovers=kinds.count(AttemptKind.FAILOVER),
            escalations=kinds.count(AttemptKind.ESCALATION),
            unsatisfactory_returned=unsatisfactory_returned,
            failure=failure,
            versions=self._recorder.versions,
        )

    def _span(self, run: _Run, name: SpanName, start_ms: float) -> float:
        duration = max(0.0, self._clock.monotonic_ms() - start_ms)
        run.spans.append(
            SpanTiming(
                span=name, duration_ms=duration, source=LatencySource.MEASURED_LOCAL
            )
        )
        return duration

    def _emit(self, run: _Run, payload, **kwargs) -> None:
        self._recorder.emit(
            payload,
            request_id=run.request_id,
            session_ref=run.request.session_ref,
            case_id=run.case_id,
            logged_timestamp=run.logged_timestamp,
            **kwargs,
        )
