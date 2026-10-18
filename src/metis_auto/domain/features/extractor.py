"""Feature extractor (CMP-04).

Responsibility: derive content-free features from a ``Request`` and the
``RequestMeasurements`` that application.measurement took (P-1). Pure.
Called by: application.pipeline (stage 2). Calls: contracts only.
Config: ``FeatureConfig``. Output feeds routing (CMP-05), the cache policy
(CMP-06), and evaluation strata (CMP-23).
Traces: FR-FEAT-01…05, FR-REQ-04 (unknown stays unknown, never zero).

Status: skeleton. Sizes, counts, states, and the instruction group are real;
language and code detection are TODO.
"""

from __future__ import annotations

from metis_auto.contracts import (
    ComponentMeasurement,
    ComponentName,
    ComponentState,
    ContractModel,
    Language,
    Request,
    RequestFeatures,
    RequestMeasurements,
    Role,
    TokenCount,
)

from ..accounting.tokens import sum_counts

FEATURE_SET_VERSION = "fs-0.1.0-skeleton"


class FeatureConfig(ContractModel):
    """Feature-set configuration. Owned by this policy (configuration §3 rule 5)."""

    version: str = FEATURE_SET_VERSION


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

    return RequestFeatures(
        feature_set_version=config.version,
        # TODO(Stage 8, FR-FEAT-03): a tested Persian/English/mixed detector,
        # re-implemented (never taken from the sample-EDA helpers, ADR-0008).
        language=Language.UNDETERMINED,
        message_chars=message.chars or 0,
        message_tokens=message.token_estimate,
        known_input_tokens=_sum_estimates(measurements.components),
        # TODO(Stage 8, FR-FEAT-01): code-presence detector.
        has_code=None,
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
        extra=dict(measurements.model_features),
    )


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
