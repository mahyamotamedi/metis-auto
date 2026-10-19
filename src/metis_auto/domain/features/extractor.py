"""Feature extractor (CMP-04).

Responsibility: derive content-free features from a ``Request`` and the
``RequestMeasurements`` that application.measurement took (P-1). Pure.
Called by: application.pipeline (stage 2). Calls: contracts only.
Config: ``FeatureConfig``. Output feeds routing (CMP-05), the cache policy
(CMP-06), and evaluation strata (CMP-23).
Traces: FR-FEAT-01…05, FR-REQ-04 (unknown stays unknown, never zero).

Status: sizes, counts, states, and the instruction group since Stage 5;
language, code, length bucket, greeting, and per-turn history features
(sticky routing) since the Demo milestone (``detectors``, ADR-0023); coding
intent since its amendment 2 (A-71).
"""

from __future__ import annotations

from metis_auto.contracts import (
    ComponentMeasurement,
    ComponentName,
    ComponentState,
    ContractModel,
    Request,
    RequestFeatures,
    RequestMeasurements,
    Role,
    TokenCount,
    TurnFeatures,
)

from ..accounting.tokens import sum_counts
from .detectors import (
    CodeConfig,
    CodingIntentConfig,
    GreetingConfig,
    LanguageConfig,
    detect_code,
    detect_coding_intent,
    detect_language,
    is_greeting,
    length_bucket,
)

FEATURE_SET_VERSION = "fs-0.3.0-demo"


class FeatureConfig(ContractModel):
    """Feature-set configuration. Owned by this policy (configuration §3 rule 5).
    Thresholds and phrases are placeholders (A-43 style)."""

    version: str = FEATURE_SET_VERSION
    language: LanguageConfig = LanguageConfig()
    code: CodeConfig = CodeConfig()
    coding_intent: CodingIntentConfig = CodingIntentConfig()
    greeting: GreetingConfig = GreetingConfig()
    length_bounds: tuple[int, ...] = (80, 400, 2000)
    """Character bounds of the length buckets (0: < 80, 1: < 400, …)."""


def extract_features(
    request: Request, measurements: RequestMeasurements, config: FeatureConfig
) -> RequestFeatures:
    """Features of one request. ``None`` means unknown, never zero."""
    by_name = {m.component: m for m in measurements.components}
    message = by_name[ComponentName.MESSAGE]
    history = by_name[ComponentName.HISTORY]
    instructions = by_name[ComponentName.INSTRUCTIONS]
    retrieved = by_name[ComponentName.RETRIEVED]
    attachments = by_name[ComponentName.ATTACHMENTS]
    traffic = request.traffic_source

    text = request.message
    has_code = detect_code(text, config.code)
    return RequestFeatures(
        feature_set_version=config.version,
        language=detect_language(text, config.language),
        message_chars=message.chars or 0,
        message_tokens=message.token_estimate,
        known_input_tokens=_sum_estimates(measurements.components),
        has_code=has_code,
        has_coding_intent=detect_coding_intent(text, has_code, config.coding_intent),
        length_bucket=length_bucket(len(text), config.length_bounds),
        is_greeting=is_greeting(text, config.greeting),
        attachment_count=_count(attachments),
        attachment_modalities=_modalities(request),
        turn_depth=_turn_depth(request),
        history_chars=_size(history),
        instructions_state=instructions.state,
        instructions_chars=_size(instructions),
        # TODO(Stage 8, FR-XCACHE-03): group by *normalised* instructions; the
        # raw-text fingerprint is used until normalisation variants exist.
        instructions_group=instructions.fingerprint,
        retrieved_state=retrieved.state,
        retrieved_items=_count(retrieved),
        retrieved_chars=_size(retrieved),
        structured_input_state=by_name[ComponentName.STRUCTURED_INPUT].state,
        traffic_source_state=traffic.state,
        traffic_source_kind=traffic.value.kind if traffic.value else None,
        traffic_source_provenance=traffic.value.provenance if traffic.value else None,
        history_turns=history_turn_features(request, config),
        extra=dict(measurements.model_features),
    )


def history_turn_features(
    request: Request, config: FeatureConfig
) -> tuple[TurnFeatures, ...]:
    """Each earlier user turn's features and the producer of the assistant turn
    that answered it (the next assistant turn before the next user turn)."""
    turns = request.history.value or ()
    out = []
    for i, turn in enumerate(turns):
        if turn.role != Role.USER:
            continue
        following = turns[i + 1] if i + 1 < len(turns) else None
        answer = following if following and following.role == Role.ASSISTANT else None
        producer = answer.producer if answer is not None else None
        has_code = detect_code(turn.text, config.code)
        out.append(
            TurnFeatures(
                language=detect_language(turn.text, config.language),
                has_code=has_code,
                has_coding_intent=detect_coding_intent(
                    turn.text, has_code, config.coding_intent
                ),
                length_bucket=length_bucket(len(turn.text), config.length_bounds),
                is_greeting=is_greeting(turn.text, config.greeting),
                producer_state=producer.state
                if producer is not None
                else ComponentState.ABSENT,
                producer=producer.value if producer is not None else None,
            )
        )
    return tuple(out)


def _size(m: ComponentMeasurement) -> int | None:
    if m.state == ComponentState.UNKNOWN:
        return None
    return m.chars if m.state == ComponentState.PRESENT else 0


def _count(m: ComponentMeasurement) -> int | None:
    if m.state == ComponentState.UNKNOWN:
        return None
    return m.items if m.state == ComponentState.PRESENT else 0


def _modalities(request: Request) -> tuple:
    refs = request.attachments.value or ()
    return tuple(dict.fromkeys(a.modality for a in refs))


def _turn_depth(request: Request) -> int | None:
    state = request.history.state
    if state == ComponentState.UNKNOWN:
        return None
    turns = request.history.value or ()
    return sum(1 for t in turns if t.role == Role.USER)


def _sum_estimates(components: tuple[ComponentMeasurement, ...]) -> TokenCount | None:
    return sum_counts(c.token_estimate for c in components if c.token_estimate)
