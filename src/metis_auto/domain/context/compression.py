"""Context compression decisions (Demo milestone, EXPERIMENTAL; context plan
X3, brief §9, ADR-0023).

Responsibility: decide **which** texts a compressor may shorten, rebuild the
request from the compressed texts, summarise what changed (sizes only), and
mark the composition record. The compressor itself (LLMLingua-2, a local
model) is a port called by application (P-1); this module never calls it.
Rules: only the configured components (default: history and retrieved
context); **instructions never by default** (an explicit
``compress_instructions`` opt-in exists for experiment arms only, brief §9);
the current message never; texts shorter than ``min_chars`` are left alone.
Pure. Called by: application.pipeline. Config: ``CompressionConfig``
(placeholders). Status: unpromoted demo strategy: needs a quality-preserving
ablation (FR-CTX-03) before it could be anything else. Traces: FR-CTX-02.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import Field

from metis_auto.contracts import (
    Component,
    ComponentName,
    ContextAction,
    ContextPlan,
    ContractModel,
    Name,
    PolicyRef,
    Request,
    RetrievedContext,
)
from metis_auto.contracts.events import CompressedComponent

COMPRESSIBLE = (ComponentName.HISTORY, ComponentName.RETRIEVED)


class CompressionConfig(ContractModel):
    enabled: bool = False
    compressor: Name = "llmlingua-2-xlm-roberta-large-meetingbank"
    """A ``ref`` in ``config/reference/compressors.toml``."""
    rate: float = Field(default=0.5, gt=0, le=1)
    """Target share of the compressor's tokens kept, per text."""
    components: tuple[ComponentName, ...] = COMPRESSIBLE
    min_chars: int = Field(default=200, ge=0)
    """Shorter texts are left as they are (compressing them saves little)."""
    compress_instructions: bool = False
    """Experiment arms only (context plan X6 c). Never on by default."""


@dataclass(frozen=True)
class Target:
    """One text the compressor may shorten: component and item index."""

    component: ComponentName
    index: int
    text: str


@dataclass(frozen=True)
class Compressed:
    text: str
    tokens_before: int
    tokens_after: int


def targets(request: Request, config: CompressionConfig) -> tuple[Target, ...]:
    """Texts to compress, in request order. Never the message."""
    allowed = set(config.components) & set(COMPRESSIBLE)
    if config.compress_instructions:
        allowed.add(ComponentName.INSTRUCTIONS)
    found: list[Target] = []
    if ComponentName.INSTRUCTIONS in allowed and request.instructions.value:
        found.append(Target(ComponentName.INSTRUCTIONS, 0, request.instructions.value))
    if ComponentName.HISTORY in allowed:
        for i, turn in enumerate(request.history.value or ()):
            found.append(Target(ComponentName.HISTORY, i, turn.text))
    if ComponentName.RETRIEVED in allowed and request.retrieved.value:
        for i, item in enumerate(request.retrieved.value.items):
            found.append(Target(ComponentName.RETRIEVED, i, item.text))
    return tuple(t for t in found if len(t.text) >= config.min_chars)


def apply(
    request: Request, results: Mapping[tuple[ComponentName, int], Compressed]
) -> Request:
    """``request`` with each compressed text substituted. An empty result keeps
    the original text (a component must not become empty, O-4)."""

    def text(component: ComponentName, index: int, original: str) -> str:
        found = results.get((component, index))
        return found.text if found is not None and found.text.strip() else original

    update: dict[str, object] = {}
    if (ComponentName.INSTRUCTIONS, 0) in results and request.instructions.value:
        update["instructions"] = Component[str].present(
            text(ComponentName.INSTRUCTIONS, 0, request.instructions.value)
        )
    if request.history.value and any(c == ComponentName.HISTORY for c, _ in results):
        turns = tuple(
            t.model_copy(update={"text": text(ComponentName.HISTORY, i, t.text)})
            for i, t in enumerate(request.history.value)
        )
        update["history"] = Component.present(turns)
    retrieved = request.retrieved.value
    if retrieved and any(c == ComponentName.RETRIEVED for c, _ in results):
        items = tuple(
            item.model_copy(
                update={"text": text(ComponentName.RETRIEVED, i, item.text)}
            )
            for i, item in enumerate(retrieved.items)
        )
        update["retrieved"] = Component[RetrievedContext].present(
            retrieved.model_copy(update={"items": items})
        )
    return request.model_copy(update=update) if update else request


def summary(
    request: Request,
    config: CompressionConfig,
    results: Mapping[tuple[ComponentName, int], Compressed],
) -> tuple[CompressedComponent, ...]:
    """Per component: items compressed and skipped, characters and compressor
    tokens before and after. Sizes only."""
    eligible = {(t.component, t.index): t for t in targets(request, config)}
    totals: dict[ComponentName, int] = {}
    if request.instructions.value and config.compress_instructions:
        totals[ComponentName.INSTRUCTIONS] = 1
    if ComponentName.HISTORY in config.components and request.history.value:
        totals[ComponentName.HISTORY] = len(request.history.value)
    if ComponentName.RETRIEVED in config.components and request.retrieved.value:
        totals[ComponentName.RETRIEVED] = len(request.retrieved.value.items)
    rows = []
    for component, total in totals.items():
        done = [
            (eligible[key], r)
            for key, r in results.items()
            if key[0] == component and key in eligible
        ]
        rows.append(
            CompressedComponent(
                component=component,
                items_compressed=len(done),
                items_skipped=total - len(done),
                chars_before=sum(len(t.text) for t, _ in done),
                chars_after=sum(len(r.text) for _, r in done),
                tokens_before=sum(r.tokens_before for _, r in done),
                tokens_after=sum(r.tokens_after for _, r in done),
            )
        )
    return tuple(rows)


def mark(
    plan: ContextPlan, compressed: tuple[ComponentName, ...], compressor: PolicyRef
) -> ContextPlan:
    """The plan with compressed components' action set to ``compressed`` and
    the strategy name suffixed with ":<compressor>"."""
    rows = tuple(
        row.model_copy(update={"action": ContextAction.COMPRESSED})
        if row.component in compressed and row.action == ContextAction.KEPT
        else row
        for row in plan.record.components
    )
    strategy = PolicyRef(
        name=f"{plan.record.strategy.name}:{compressor.name}",
        version=f"{plan.record.strategy.version}+{compressor.version}",
    )
    record = plan.record.model_copy(update={"components": rows, "strategy": strategy})
    return plan.model_copy(update={"record": record})
