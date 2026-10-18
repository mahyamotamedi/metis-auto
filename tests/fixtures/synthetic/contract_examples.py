"""SYNTHETIC example instances of every contract (Stage 4).

All text is invented and starts with ``[SYNTHETIC]`` so a leak is easy to spot.
Nothing here comes from any dataset. Model IDs, providers, versions, and
sources are placeholders, not real catalogue entries or prices.

``fingerprint`` and ``key_id`` are the reference implementation of the
algorithm in ADR-0015 amendment 1, with a fixed synthetic test key. Stage 5
moves the implementation into ``application/measurement``; these test vectors
then check it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from metis_auto.contracts import (
    ActionKind,
    AnswerSource,
    AttachmentRef,
    AttemptAction,
    AttemptKind,
    AttemptOutcome,
    AttemptRecord,
    AttemptState,
    CacheEntry,
    CacheKey,
    CacheKeyDraft,
    CacheLookupResult,
    CacheScope,
    CacheStoreDecision,
    CacheTier,
    Capability,
    CatalogueEntry,
    CodeVersion,
    Component,
    ComponentComposition,
    ComponentMeasurement,
    ComponentName,
    ComponentState,
    ComponentTokens,
    CompositionRecord,
    ContextAction,
    ContextPlan,
    Cost,
    CostBasis,
    CostEstimate,
    CostStatus,
    CounterfactualSource,
    DataQualityFlag,
    DetectorVerdict,
    EmbedderRef,
    Embedding,
    EntryStatus,
    ErrorClass,
    EvaluationResult,
    Event,
    ExclusionCount,
    Fidelity,
    FinalResponse,
    FinishReason,
    IndexMatch,
    InputPart,
    Interval,
    JudgeScore,
    KeyComponent,
    Language,
    LatencySource,
    Limit,
    LoggedMessage,
    LookupOutcome,
    MeasurementRecord,
    MetricName,
    MetricState,
    MetricValue,
    Modality,
    ModelCatalogue,
    ModelError,
    ModelInvocation,
    ModelNoAnswer,
    ModelResponse,
    Money,
    NoAnswerReason,
    NotComputedReason,
    OverflowOutcome,
    PairingFlag,
    PairingMethod,
    PartRole,
    PolicyRef,
    PriceEntry,
    PriceTable,
    Provenance,
    Reference,
    ReplayCase,
    Request,
    RequestFeatures,
    RequestMeasurements,
    ResponseMetadata,
    ResponseStatus,
    RetrievedContext,
    RetrievedItem,
    Role,
    RoutingDecision,
    RunManifest,
    RunMode,
    Savings,
    ScopeKind,
    ServedBy,
    Session,
    Sourced,
    SpanName,
    SpanTiming,
    StratumKey,
    StratumResult,
    TargetTokenCounts,
    TokenCount,
    TokenType,
    TokenUsage,
    TrafficSource,
    Turn,
    Versions,
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
    EvaluationScored,
    FailoverTriggered,
    FeaturesExtracted,
    RequestReceived,
    ResponseReturned,
    RetryScheduled,
    RoutingDecided,
    RunFinished,
    RunStarted,
)

MARKER = "[SYNTHETIC]"

SYNTHETIC_TEST_KEY = b"SYNTHETIC-TEST-KEY--metis-auto--not-a-secret--0001"
"""Fixed test key (ADR-0015 point 4). Never used outside tests."""


# --- Fingerprint reference implementation (ADR-0015 amendment 1) ---------------


def canonical(payload: object) -> str:
    """Text payloads as-is; structured payloads as canonical JSON."""
    if isinstance(payload, str):
        return payload
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def fingerprint(purpose: str, payload: object, key: bytes = SYNTHETIC_TEST_KEY) -> str:
    message = b"metis-fp/1\x1f" + purpose.encode() + b"\x1f"
    message += canonical(payload).encode("utf-8")
    return "fp1:" + hmac.new(key, message, hashlib.sha256).hexdigest()


def key_id(key: bytes = SYNTHETIC_TEST_KEY) -> str:
    return (
        "kid1:" + hmac.new(key, b"metis-fp-key-id/1", hashlib.sha256).hexdigest()[:16]
    )


# --- Building blocks --------------------------------------------------------------

NOW = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)
LOGGED = datetime(2026, 5, 1, 14, 2, 3)  # naive on purpose (A-06)
SOURCE = Sourced(source="SYNTHETIC placeholder source", checked_on=date(2026, 10, 17))
POLICY = PolicyRef(name="fixed_model", version="0.0.0-synthetic")
VERSIONS = Versions(
    config_hash="synthetic-config-hash",
    fingerprint_key_id=key_id(),
    policies={"fixed_model": "0.0.0-synthetic"},
    feature_set="fs-0.0.0-synthetic",
    catalogue="cat-0.0.0-synthetic",
    price_table="prices-0.0.0-synthetic",
    key_schema="ks-1",
)

MESSAGE = f"{MARKER} سلام، لطفاً ساعت کاری فروشگاه را بگویید."
INSTRUCTIONS = f"{MARKER} You are a helpful assistant for a demo shop."
HISTORY = (
    Turn(role=Role.USER, text=f"{MARKER} Hello"),
    Turn(role=Role.ASSISTANT, text=f"{MARKER} سلام! چطور می‌توانم کمک کنم؟"),
)
RETRIEVED = RetrievedContext(
    items=(
        RetrievedItem(text=f"{MARKER} Opening hours: 9 to 17.", document_ref="doc-1"),
        RetrievedItem(text=f"{MARKER} Closed on holidays.", score=0.42),
    ),
    query=Component[str].present(f"{MARKER} opening hours"),
)
ATTACHMENT = AttachmentRef(
    modality=Modality.IMAGE,
    media_type="image/png",
    locator=f"{MARKER}-inline-payload",
)

FP_MESSAGE = fingerprint("message", MESSAGE)
FP_INSTRUCTIONS = fingerprint("instructions", INSTRUCTIONS)
FP_HISTORY = fingerprint("history", [t.model_dump(mode="json") for t in HISTORY])
FP_RETRIEVED = fingerprint("retrieved", RETRIEVED.model_dump(mode="json"))

MODEL = "synthetic-small"
MODEL_LARGE = "synthetic-large"
GROUP = "synthetic-group-a"


def tokens(n: int, fidelity: Fidelity = Fidelity.APPROXIMATION) -> TokenCount:
    method = "approx-chars-div-4@1" if fidelity is Fidelity.APPROXIMATION else "x@1"
    return TokenCount(tokens=n, fidelity=fidelity, method=method)


def usd(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency="USD")


def computed(amount: str, basis: CostBasis = CostBasis.ACTUAL) -> Cost:
    return Cost(
        status=CostStatus.COMPUTED,
        basis=basis,
        amount=usd(amount),
        price_table_version="prices-0.0.0-synthetic",
        price_refs=("synthetic-small-price",),
        token_fidelity=Fidelity.APPROXIMATION,
    )


def not_computed(reason: NotComputedReason = NotComputedReason.PRICE_UNKNOWN) -> Cost:
    return Cost(status=CostStatus.NOT_COMPUTED, basis=CostBasis.ACTUAL, reason=reason)


# --- One instance per contract -----------------------------------------------------


def request() -> Request:
    return Request(
        message=MESSAGE,
        history=Component.present(HISTORY),
        instructions=Component.present(INSTRUCTIONS),
        retrieved=Component.present(RETRIEVED),
        attachments=Component.absent(),
        structured_input=Component.unknown("not_supplied"),
        traffic_source=Component.present(
            TrafficSource(kind="embedded_bot", provenance=Provenance.DECLARED)
        ),
        session_ref="sess-synthetic-1",
        caller_request_ref="caller-req-1",
        deadline_ms=30_000,
    )


def component_measurements() -> tuple[ComponentMeasurement, ...]:
    def present(name: ComponentName, fp: str, chars: int, items: int | None = None):
        return ComponentMeasurement(
            component=name,
            state=ComponentState.PRESENT,
            fingerprint=fp,
            chars=chars,
            items=items,
            token_estimate=tokens(max(1, chars // 4)),
        )

    return (
        present(ComponentName.MESSAGE, FP_MESSAGE, len(MESSAGE)),
        present(ComponentName.INSTRUCTIONS, FP_INSTRUCTIONS, len(INSTRUCTIONS)),
        present(ComponentName.HISTORY, FP_HISTORY, 40, items=2),
        present(ComponentName.RETRIEVED, FP_RETRIEVED, 60, items=2),
        ComponentMeasurement(
            component=ComponentName.ATTACHMENTS, state=ComponentState.ABSENT
        ),
        ComponentMeasurement(
            component=ComponentName.STRUCTURED_INPUT, state=ComponentState.UNKNOWN
        ),
    )


EMBEDDER = EmbedderRef(embedder_id="fake-embedder", version="0.0.0", dimensions=3)


def request_measurements() -> RequestMeasurements:
    return RequestMeasurements(
        components=component_measurements(),
        fingerprint_key_id=key_id(),
        embedding=Embedding(embedder=EMBEDDER, vector=(0.1, 0.2, 0.3)),
        model_features={"intent": "faq_lookup"},
        records=(
            MeasurementRecord(
                measurement="fingerprint", backend="hmac@1", duration_ms=0.2
            ),
        ),
    )


def target_token_counts() -> TargetTokenCounts:
    return TargetTokenCounts(
        model_id=MODEL,
        components=(
            ComponentTokens(component=ComponentName.MESSAGE, total=tokens(12)),
            ComponentTokens(
                component=ComponentName.HISTORY,
                total=tokens(10),
                per_item=(tokens(2), tokens(8)),
            ),
        ),
    )


def request_features() -> RequestFeatures:
    return RequestFeatures(
        feature_set_version="fs-0.0.0-synthetic",
        language=Language.PERSIAN,
        message_chars=len(MESSAGE),
        message_tokens=tokens(12),
        has_code=False,
        attachment_count=0,
        turn_depth=1,
        history_chars=40,
        instructions_state=ComponentState.PRESENT,
        instructions_chars=len(INSTRUCTIONS),
        instructions_group=FP_INSTRUCTIONS,
        retrieved_state=ComponentState.PRESENT,
        retrieved_items=2,
        retrieved_chars=60,
        structured_input_state=ComponentState.UNKNOWN,
        traffic_source_state=ComponentState.PRESENT,
        traffic_source_kind="embedded_bot",
        traffic_source_provenance=Provenance.DECLARED,
        extra={"length_bucket": "short", "persian_share": 0.8},
    )


def model_catalogue() -> ModelCatalogue:
    def entry(model_id: str, tier: int, price_ref: str | None) -> CatalogueEntry:
        return CatalogueEntry(
            model_id=model_id,
            provider="synthetic-provider",
            provider_model_name=f"{model_id}-api-name",
            tier=tier,
            equivalence_group=GROUP if tier == 0 else "synthetic-group-b",
            context_window=Limit(value=8_000, evidence=SOURCE),
            max_output_tokens=Limit(),
            capabilities=(Capability(name="image_input", verified=False),),
            tokenizer_ref="approx-chars-div-4",
            price_ref=price_ref,
            enabled=True,
        )

    return ModelCatalogue(
        version="cat-0.0.0-synthetic",
        entries=(entry(MODEL, 0, "synthetic-small-price"), entry(MODEL_LARGE, 1, None)),
    )


def price_table() -> PriceTable:
    return PriceTable(
        version="prices-0.0.0-synthetic",
        entries=(
            # Placeholder: amount unknown, so costs come out "not computed".
            PriceEntry(
                price_ref="synthetic-small-price",
                token_type=TokenType.INPUT,
                per_tokens=1_000_000,
                currency="USD",
            ),
        ),
    )


def routing_decision() -> RoutingDecision:
    return RoutingDecision(
        target_model_id=MODEL,
        equivalence_group=GROUP,
        tier=0,
        eligible=(MODEL, MODEL_LARGE),
        chain=(MODEL_LARGE,),
        policy=POLICY,
        reason_code="fixed_model",
        features_used=(),
    )


def cache_key() -> CacheKey:
    def comp(
        name: ComponentName, fp: str | None, treatment: str = "full"
    ) -> KeyComponent:
        state = ComponentState.PRESENT if fp else ComponentState.ABSENT
        return KeyComponent(
            component=name, state=state, fingerprint=fp, treatment=treatment
        )

    return CacheKey(
        key_schema_version="ks-1",
        variant="full",
        serving_allowed=True,
        components=(
            comp(ComponentName.MESSAGE, FP_MESSAGE, "nfkc_casefold_ws"),
            comp(ComponentName.INSTRUCTIONS, FP_INSTRUCTIONS),
            comp(ComponentName.HISTORY, FP_HISTORY),
            comp(ComponentName.RETRIEVED, FP_RETRIEVED),
            comp(ComponentName.STRUCTURED_INPUT, None),
        ),
        target_group=GROUP,
        scope=CacheScope(kind=ScopeKind.SESSION, ref="sess-synthetic-1"),
        key=fingerprint("cache_key", "synthetic-key-material"),
        partition_key=fingerprint("partition_key", "synthetic-partition-material"),
    )


def cache_key_draft() -> CacheKeyDraft:
    return CacheKeyDraft(**cache_key().model_dump(exclude={"key", "partition_key"}))


def cache_entry() -> CacheEntry:
    return CacheEntry(
        entry_id="entry-1",
        key=cache_key(),
        answer=f"{MARKER} فروشگاه از ساعت ۹ تا ۱۷ باز است.",
        producing_model_id=MODEL,
        producing_tier=0,
        created_at=NOW,
        status=EntryStatus.COMPLETE,
        source_request_id="req-0",
        embedding=Embedding(embedder=EMBEDDER, vector=(0.1, 0.2, 0.3)),
        versions=VERSIONS,
    )


def index_match() -> IndexMatch:
    return IndexMatch(entry_id="entry-1", similarity=0.93, embedder=EMBEDDER)


def cache_lookup_results() -> tuple[CacheLookupResult, ...]:
    return (
        CacheLookupResult(
            tier=CacheTier.EXACT,
            outcome=LookupOutcome.MISS,
            key_variant="full",
            key=cache_key().key,
            scope=ScopeKind.SESSION,
            not_evaluated=("time_sensitivity",),
        ),
        CacheLookupResult(
            tier=CacheTier.SEMANTIC,
            outcome=LookupOutcome.HIT,
            key_variant="full",
            scope=ScopeKind.SESSION,
            entry_id="entry-1",
            similarity=0.93,
            threshold=0.9,
            embedder=EMBEDDER,
            candidates_considered=3,
        ),
        CacheLookupResult(
            tier=CacheTier.EXACT,
            outcome=LookupOutcome.INELIGIBLE,
            ineligible_reason="unknown_component",
        ),
    )


def composition_record() -> CompositionRecord:
    return CompositionRecord(
        model_id=MODEL,
        strategy=PolicyRef(name="pass_through", version="1"),
        components=(
            ComponentComposition(
                component=ComponentName.INSTRUCTIONS,
                state=ComponentState.PRESENT,
                action=ContextAction.KEPT,
                fingerprint=FP_INSTRUCTIONS,
                tokens=tokens(11),
            ),
            ComponentComposition(
                component=ComponentName.STRUCTURED_INPUT,
                state=ComponentState.UNKNOWN,
                action=ContextAction.NOT_APPLICABLE,
            ),
        ),
        input_tokens=tokens(45),
        reserved_output_tokens=512,
        context_window=8_000,
        overflow=OverflowOutcome.FITS,
        composition_fingerprint=fingerprint("composition", "synthetic-parts"),
    )


def context_plan() -> ContextPlan:
    return ContextPlan(
        model_id=MODEL,
        parts=(
            InputPart(
                role=PartRole.INSTRUCTIONS,
                text=INSTRUCTIONS,
                component=ComponentName.INSTRUCTIONS,
            ),
            InputPart(
                role=PartRole.USER, text=MESSAGE, component=ComponentName.MESSAGE
            ),
        ),
        record=composition_record(),
    )


def model_invocation() -> ModelInvocation:
    return ModelInvocation(
        request_id="req-1",
        attempt_id="att-1",
        attempt_kind=AttemptKind.PRIMARY,
        model_id=MODEL,
        parts=context_plan().parts,
        max_output_tokens=512,
        timeout_ms=10_000,
        case_id="case-1",
        composition_fingerprint=composition_record().composition_fingerprint,
    )


def model_results() -> tuple[ModelResponse, ModelError, ModelNoAnswer]:
    usage = TokenUsage(
        model_id=MODEL,
        input=tokens(45, Fidelity.PROVIDER_REPORTED),
        output=tokens(20, Fidelity.PROVIDER_REPORTED),
    )
    return (
        ModelResponse(
            text=f"{MARKER} فروشگاه از ساعت ۹ تا ۱۷ باز است.",
            finish_reason=FinishReason.COMPLETE,
            usage=usage,
            provider_latency_ms=12.5,
            source=AnswerSource.FAKE,
        ),
        ModelError(
            error_class=ErrorClass.RATE_LIMITED,
            retryable=True,
            source=AnswerSource.FAKE,
        ),
        ModelNoAnswer(reason=NoAnswerReason.NOT_RECORDED, source=AnswerSource.RECORDED),
    )


def detector_verdict() -> DetectorVerdict:
    return DetectorVerdict(
        detector="language_mismatch",
        version="0.0.0",
        state="evaluated",
        value=0.0,
        threshold=0.5,
        fired=False,
    )


def attempt_record() -> AttemptRecord:
    return AttemptRecord(
        attempt_id="att-1",
        number=0,
        kind=AttemptKind.PRIMARY,
        model_id=MODEL,
        provider="synthetic-provider",
        outcome=AttemptOutcome.RESPONSE,
        source=AnswerSource.FAKE,
        finish_reason=FinishReason.COMPLETE,
        usage=model_results()[0].usage,
        cost=not_computed(),
        duration_ms=12.5,
        verdicts=(detector_verdict(),),
        unsatisfactory=False,
    )


def attempt_state() -> AttemptState:
    return AttemptState(
        request_id="req-1",
        decision=routing_decision(),
        attempts=(attempt_record(),),
        deadline_remaining_ms=25_000,
    )


def attempt_actions() -> tuple[AttemptAction, ...]:
    return (
        AttemptAction(
            action=ActionKind.INVOKE,
            reason="primary",
            target_model_id=MODEL,
            kind=AttemptKind.PRIMARY,
        ),
        AttemptAction(
            action=ActionKind.RETURN, reason="satisfactory", return_attempt_id="att-1"
        ),
        AttemptAction(
            action=ActionKind.FAIL,
            reason="chain_exhausted",
            failure="all_attempts_failed",
        ),
    )


def cost_estimate() -> CostEstimate:
    return CostEstimate(
        model_id=MODEL,
        input_tokens=tokens(45),
        assumed_output_tokens=512,
        cost=computed("0.0004", CostBasis.PRE_CALL_ESTIMATE),
    )


def savings() -> tuple[Savings, ...]:
    return (
        Savings(
            baseline="as_logged",
            status=CostStatus.COMPUTED,
            amount=usd("0.0001"),
            baseline_cost=computed("0.0005", CostBasis.BASELINE_ESTIMATE),
            actual_cost=computed("0.0004"),
        ),
        Savings(
            baseline="premium",
            status=CostStatus.NOT_COMPUTED,
            baseline_cost=not_computed(NotComputedReason.BASELINE_UNSET),
            actual_cost=computed("0.0004"),
        ),
    )


def response_metadata() -> ResponseMetadata:
    return ResponseMetadata(
        request_id="req-1",
        caller_request_ref="caller-req-1",
        served_by=ServedBy.MODEL,
        final_model_id=MODEL,
        attempt_ids=("att-1",),
        answer_usage=model_results()[0].usage,
        total_cost=computed("0.0004"),
        overhead_cost=computed("0"),
        savings=savings(),
        spans=(
            SpanTiming(
                span=SpanName.ROUTE,
                duration_ms=0.3,
                source=LatencySource.MEASURED_LOCAL,
            ),
            SpanTiming(
                span=SpanName.MODEL_CALL,
                duration_ms=12.5,
                source=LatencySource.SIMULATED,
                attempt_id="att-1",
            ),
        ),
        versions=VERSIONS,
    )


def final_responses() -> tuple[FinalResponse, ...]:
    ok = FinalResponse(
        status=ResponseStatus.OK,
        answer=model_results()[0].text,
        metadata=response_metadata(),
    )
    # model_validate, not model_copy: fixtures must pass validation.
    error_meta = ResponseMetadata.model_validate(
        response_metadata().model_dump()
        | {"served_by": "none", "final_model_id": None, "failure": "no_eligible_model"}
    )
    return ok, FinalResponse(status=ResponseStatus.ERROR, metadata=error_meta)


def session() -> Session:
    return Session(
        session_ref=fingerprint("session_ref", "synthetic-session-1"),
        dataset="synthetic_v0",
        stratum="stratum-a",
        logged_created_at=LOGGED,
        messages=(
            LoggedMessage(
                position=0, role=Role.USER, text=MESSAGE, logged_timestamp=LOGGED
            ),
            LoggedMessage(
                position=1,
                role=Role.ASSISTANT,
                text=f"{MARKER} Answer one.",
                logged_timestamp=LOGGED,
                model_label=Component.present("Synthetic-Label-X"),
                provider_label=Component.unknown("null_in_log"),
                instructions=Component.present(INSTRUCTIONS),
                retrieved=Component.unknown("not_in_log"),
            ),
            LoggedMessage(
                position=2, role=Role.ASSISTANT, text=f"{MARKER} Answer two."
            ),
        ),
    )


def replay_case() -> ReplayCase:
    sess = session()
    return ReplayCase(
        case_id="case-1",
        session_ref=sess.session_ref,
        turn_index=0,
        request=Request(
            message=MESSAGE,
            history=Component.absent(),
            instructions=Component.present(INSTRUCTIONS),
            retrieved=Component.unknown("not_in_log"),
            attachments=Component.present((ATTACHMENT,)),
            session_ref=sess.session_ref,
        ),
        references=(
            Reference(position=1, text=f"{MARKER} Answer one."),
            Reference(position=2, text=f"{MARKER} Answer two."),
        ),
        pairing_method=PairingMethod.HEURISTIC_ARRAY_ORDER,
        pairing_flag=PairingFlag.MULTIPLE_ANSWERS,
        logged_timestamp=LOGGED,
        stratum="stratum-a",
        quality_flags=(
            DataQualityFlag(
                component=ComponentName.RETRIEVED, flag="possibly_truncated"
            ),
        ),
    )


def metric_values() -> tuple[MetricValue, ...]:
    return (
        MetricValue(
            name=MetricName.CANDIDATE_HIT_RATE,
            state=MetricState.MEASURED,
            value=0.1,
            unit="ratio",
            n=50,
            interval=Interval(
                low=0.04, high=0.2, level=0.95, method="bootstrap_percentile"
            ),
            key_variant="full",
            scope="session",
        ),
        MetricValue(
            name=MetricName.HIT_CORRECTNESS,
            state=MetricState.UNMEASURED,
            n=0,
            reason="no_judge_configured",
        ),
        MetricValue(
            name=MetricName.COST_PER_REQUEST,
            state=MetricState.NOT_COMPUTED,
            n=50,
            reason="price_unknown",
        ),
    )


def judge_scores() -> tuple[JudgeScore, ...]:
    return (
        JudgeScore(
            judge="fake-judge@0",
            rubric="helpfulness_v0",
            state=MetricState.MEASURED,
            score=4.0,
            cost=not_computed(),
        ),
        JudgeScore(
            judge="fake-judge@0",
            rubric="helpfulness_v0",
            state=MetricState.UNMEASURED,
            reason="no_answer",
        ),
    )


def evaluation_result() -> EvaluationResult:
    return EvaluationResult(
        run_id="run-1",
        experiment_id="exp-synthetic-0",
        counterfactual_source=CounterfactualSource.FAKE,
        cases_total=50,
        cases_covered=50,
        baselines=("as_logged", "premium"),
        results=(
            StratumResult(stratum=(), n_cases=50, metrics=metric_values()),
            StratumResult(
                stratum=(StratumKey(dimension="category", value="stratum-a"),),
                n_cases=12,
                metrics=metric_values(),
            ),
        ),
        exclusions=(ExclusionCount(reason="no_preceding_user", count=2),),
    )


def run_manifest() -> RunManifest:
    return RunManifest(
        run_id="run-1",
        experiment_id="exp-synthetic-0",
        started_at=NOW,
        code=CodeVersion(commit="0000000", dirty=True),
        dataset="synthetic_v0",
        seed=7,
        versions=VERSIONS,
        counterfactual_source=CounterfactualSource.FAKE,
        prompt_composition_assumption="logged_instructions_full_history_logged_rag",
        history_mode="logged_history",
        ordering_rule="session_then_array_order",
        pairing_flags_included=(PairingFlag.CLEAN, PairingFlag.MULTIPLE_ANSWERS),
        live_calls=False,
        hardware="synthetic-dev-machine",
    )


def events() -> tuple[Event, ...]:
    """One event per payload type, as the recorder would emit them in replay."""
    _, error, _ = model_results()
    payloads = (
        RequestReceived(
            components=component_measurements(),
            traffic_source=Component.present(
                TrafficSource(kind="embedded_bot", provenance=Provenance.DECLARED)
            ),
            pairing_flag=PairingFlag.MULTIPLE_ANSWERS,
        ),
        FeaturesExtracted(
            features=request_features(), measurements=request_measurements().records
        ),
        RoutingDecided(decision=routing_decision()),
        CacheLookedUp(result=cache_lookup_results()[0]),
        CacheStored(
            entry_id="entry-2",
            key_variant="full",
            scope=ScopeKind.SESSION,
            semantic_indexed=False,
        ),
        CacheStoreSkipped(reason="served_from_cache"),
        ContextBuilt(record=composition_record()),
        AttemptStarted(
            kind=AttemptKind.PRIMARY,
            number=0,
            model_id=MODEL,
            provider="synthetic-provider",
        ),
        AttemptFinished(record=attempt_record()),
        RetryScheduled(
            from_attempt_id="att-1",
            model_id=MODEL,
            error_class=error.error_class,
            backoff_ms=100,
        ),
        FailoverTriggered(
            from_model_id=MODEL,
            to_model_id="synthetic-small-b",
            equivalence_group=GROUP,
        ),
        EscalationTriggered(
            from_model_id=MODEL,
            to_model_id=MODEL_LARGE,
            from_tier=0,
            to_tier=1,
            verdicts=(detector_verdict(),),
        ),
        BudgetBlocked(estimate=cost_estimate(), cap_remaining=usd("0.0001")),
        ResponseReturned(status=ResponseStatus.OK, metadata=response_metadata()),
        EvaluationScored(metrics=metric_values()),
        RunStarted(experiment_id="exp-synthetic-0", manifest_ref="manifest.json"),
        RunFinished(cases_total=50, cases_run=48, completed=True),
    )
    out = []
    for i, payload in enumerate(payloads):
        run_level = payload.event_type in ("run_started", "run_finished")
        out.append(
            Event(
                event_id=f"evt-{i:04d}",
                event_type=payload.event_type,
                run_id="run-1",
                run_mode=RunMode.SIMULATED,
                request_id=None if run_level else "req-1",
                session_ref=None if run_level else "sess-synthetic-1",
                case_id=None if run_level else "case-1",
                timestamp=NOW,
                logged_timestamp=None if run_level else LOGGED,
                span=SpanName.ROUTE
                if payload.event_type == "routing_decided"
                else None,
                duration_ms=0.3 if payload.event_type == "routing_decided" else None,
                versions=VERSIONS,
                payload=payload,
            )
        )
    return tuple(out)


def store_decisions() -> tuple[CacheStoreDecision, ...]:
    return (
        CacheStoreDecision(store=True),
        CacheStoreDecision(store=False, skip_reason="truncated"),
    )


def all_examples() -> dict[str, object]:
    """Every example, keyed by a readable name. Used by the round-trip tests."""
    examples: dict[str, object] = {
        "request": request(),
        "request_measurements": request_measurements(),
        "target_token_counts": target_token_counts(),
        "request_features": request_features(),
        "model_catalogue": model_catalogue(),
        "price_table": price_table(),
        "routing_decision": routing_decision(),
        "cache_key": cache_key(),
        "cache_key_draft": cache_key_draft(),
        "cache_entry": cache_entry(),
        "index_match": index_match(),
        "context_plan": context_plan(),
        "model_invocation": model_invocation(),
        "attempt_state": attempt_state(),
        "cost_estimate": cost_estimate(),
        "response_metadata": response_metadata(),
        "session": session(),
        "replay_case": replay_case(),
        "evaluation_result": evaluation_result(),
        "run_manifest": run_manifest(),
    }
    groups = {
        "cache_lookup": cache_lookup_results(),
        "model_result": model_results(),
        "attempt_action": attempt_actions(),
        "savings": savings(),
        "final_response": final_responses(),
        "store_decision": store_decisions(),
        "judge_score": judge_scores(),
        "event": events(),
    }
    for prefix, items in groups.items():
        for i, item in enumerate(items):
            examples[f"{prefix}[{i}]"] = item
    return examples
