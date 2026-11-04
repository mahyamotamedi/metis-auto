"""Within-message chunk dedup (sprint winner S-6; DEMO selection, ADR-0066).
Re-implemented here from the semantics of
``experiments/context/exp-ctx-001-within-message-dedup`` (read as reference
only; ``metis_auto`` never imports ``experiments/``).

Rule: inside ONE message's retrieved context, an item is an **exact
duplicate** when an earlier item has the identical text. The first copy is
kept, the later ones are removed, and the remaining items keep their order.
Identity is the text, never a document reference: two references with one text
are duplicates, and one reference with two texts is not. An item with no text
(empty or whitespace only) is never a duplicate. Nothing else is touched:
instructions, history and the current message pass through unchanged. There
is no pointer or placeholder in the prompt (the sprint version had none); a
removed copy is simply absent, so no lossy rewrite exists.

Order with compression: dedup runs first, compression (if on) runs on what is
left. ``DedupConfig.enabled`` is off by default; a ``WithinMessageDedupStrategy``
with dedup off sends exactly what ``pass_through`` sends. Pure.
Called by: application.pipeline (reducer hook), wiring (registry).
Traces: FR-CTX-02, FR-CTX-03, ADR-0038 (the sprint's token-saving conversion).
"""

from __future__ import annotations

from dataclasses import dataclass

from metis_auto.contracts import (
    CatalogueEntry,
    Component,
    ComponentName,
    ContextAction,
    ContextPlan,
    PolicyRef,
    Request,
    RequestMeasurements,
    RetrievedContext,
    TargetTokenCounts,
)

from .dedup_config import DedupConfig
from .pass_through import PassThroughStrategy
from .policy import ContextConfig, ContextStrategy

DEDUP_VERSION = "1.0.1"
__all__ = ["DedupConfig", "DedupResult", "WithinMessageDedupStrategy", "deduplicate"]


@dataclass(frozen=True)
class DedupResult:
    """What a dedup pass did. Sizes only; ``request`` holds content."""

    request: Request
    items_total: int
    items_removed: int
    chars_removed: int


def deduplicate(request: Request) -> DedupResult:
    """``request`` with exact duplicate retrieved items removed (first kept).
    Returns the very same request object when nothing is removed."""
    retrieved = request.retrieved.value
    if retrieved is None:
        return DedupResult(request, 0, 0, 0)
    seen: set[str] = set()
    kept = []
    removed_chars = 0
    for item in retrieved.items:
        if item.text.strip() and item.text in seen:
            removed_chars += len(item.text)
            continue
        seen.add(item.text)
        kept.append(item)
    total = len(retrieved.items)
    if len(kept) == total:
        return DedupResult(request, total, 0, 0)
    reduced = request.model_copy(
        update={
            "retrieved": Component[RetrievedContext].present(
                retrieved.model_copy(update={"items": tuple(kept)})
            )
        }
    )
    return DedupResult(reduced, total, total - len(kept), removed_chars)


class WithinMessageDedupStrategy:
    """Context strategy ``within_message_dedup``: a layout strategy (default
    ``pass_through``) whose retrieved component is deduplicated first.

    ``reduce`` is the hook the pipeline calls before compression and before
    the target's tokens are counted, so counts, parts and the cost all describe
    the request actually sent. ``build`` only lays out that prepared request:
    compression may make distinct source chunks identical, so reducing again
    would invalidate the counts and trace. It marks the retrieved row
    ``deduplicated`` with the items before and after. Callers must run ``reduce``
    before measuring the target input, as the pipeline does."""

    def __init__(self, inner: ContextStrategy | None = None) -> None:
        self._inner = inner or PassThroughStrategy()

    @property
    def ref(self) -> PolicyRef:
        inner = self._inner.ref
        return PolicyRef(
            name=f"within_message_dedup:{inner.name}",
            version=f"{DEDUP_VERSION}+{inner.version}",
        )

    def reduce(self, request: Request, config: ContextConfig) -> DedupResult:
        if not config.dedup.enabled:
            return DedupResult(request, _count(request), 0, 0)
        return deduplicate(request)

    def build(
        self,
        request: Request,
        measurements: RequestMeasurements,
        counts: TargetTokenCounts,
        target: CatalogueEntry,
        config: ContextConfig,
        rerouted: bool,
    ) -> ContextPlan:
        plan = self._inner.build(
            request, measurements, counts, target, config, rerouted
        )
        if not config.dedup.enabled:
            return plan
        total = _original_items(measurements)
        kept = _count(request)
        if total is None or kept >= total:
            return plan
        rows = tuple(
            row.model_copy(
                update={
                    "action": ContextAction.DEDUPLICATED,
                    "fingerprint": None,  # of the original; not what was sent
                    "items_total": total,
                    "items_kept": kept,
                }
            )
            if row.component == ComponentName.RETRIEVED
            and row.action == ContextAction.KEPT
            else row
            for row in plan.record.components
        )
        record = plan.record.model_copy(
            update={"components": rows, "strategy": self.ref}
        )
        return plan.model_copy(update={"record": record})


def _count(request: Request) -> int:
    value = request.retrieved.value
    return len(value.items) if value is not None else 0


def _original_items(measurements: RequestMeasurements) -> int | None:
    for m in measurements.components:
        if m.component == ComponentName.RETRIEVED:
            return m.items
    return None
