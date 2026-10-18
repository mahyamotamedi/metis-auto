"""``pass_through`` context strategy (context_construction.md §2, reference).

Responsibility: keep every present component as supplied, in the default
order instructions → history → retrieved → message, and record what was sent.
Unknown components are carried as unknown, never filled in (P-6). Pure.
Called by: application.pipeline (stage 5, built by wiring). Calls:
domain.context.policy. Status: decided (reference). Traces: FR-CTX-01, H-1.
"""

from __future__ import annotations

from metis_auto.contracts import (
    CatalogueEntry,
    ComponentComposition,
    ComponentName,
    ComponentState,
    CompositionRecord,
    ContextAction,
    ContextPlan,
    InputPart,
    PartRole,
    PolicyRef,
    Request,
    RequestMeasurements,
    Role,
    TargetTokenCounts,
)

from ..accounting.tokens import sum_counts
from .policy import ContextConfig, check_fit, reserved_output

_TURN_ROLE = {Role.USER: PartRole.USER, Role.ASSISTANT: PartRole.ASSISTANT}


class PassThroughStrategy:
    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(name="pass_through", version="1.0.0")

    def build(
        self,
        request: Request,
        measurements: RequestMeasurements,
        counts: TargetTokenCounts,
        target: CatalogueEntry,
        config: ContextConfig,
        rerouted: bool,
    ) -> ContextPlan:
        parts = _parts(request)
        tokens = {c.component: c.total for c in counts.components}
        rows = []
        for m in measurements.components:
            present = m.state == ComponentState.PRESENT
            rows.append(
                ComponentComposition(
                    component=m.component,
                    state=m.state,
                    action=ContextAction.KEPT
                    if present
                    else ContextAction.NOT_APPLICABLE,
                    fingerprint=m.fingerprint if present else None,
                    tokens=tokens.get(m.component) if present else None,
                    items_total=m.items if present else None,
                    items_kept=m.items if present else None,
                )
            )
        total = sum_counts(tokens.values())
        record = CompositionRecord(
            model_id=target.model_id,
            strategy=self.ref,
            components=tuple(rows),
            input_tokens=total,
            reserved_output_tokens=reserved_output(target, config),
            context_window=target.context_window.value,
            overflow=check_fit(total.tokens if total else 0, target, config, rerouted),
            # TODO(Stage 8, ADR-0014): composition fingerprint for recorded-replay
            # lookup; needs the fingerprint key, so application will set it.
        )
        return ContextPlan(model_id=target.model_id, parts=parts, record=record)


def _parts(request: Request) -> tuple[InputPart, ...]:
    parts: list[InputPart] = []
    if request.instructions.value is not None:
        parts.append(
            InputPart(
                role=PartRole.INSTRUCTIONS,
                text=request.instructions.value,
                component=ComponentName.INSTRUCTIONS,
            )
        )
    for i, turn in enumerate(request.history.value or ()):
        parts.append(
            InputPart(
                role=_TURN_ROLE[turn.role],
                text=turn.text,
                component=ComponentName.HISTORY,
                item_index=i,
            )
        )
    if request.retrieved.value is not None:
        for i, item in enumerate(request.retrieved.value.items):
            parts.append(
                InputPart(
                    role=PartRole.RETRIEVED,
                    text=item.text,
                    component=ComponentName.RETRIEVED,
                    item_index=i,
                )
            )
    # TODO(Stage 8): structured-input config is not sent; how it reaches a model
    # is unknown (A-16).
    parts.append(
        InputPart(
            role=PartRole.USER, text=request.message, component=ComponentName.MESSAGE
        )
    )
    return tuple(parts)
