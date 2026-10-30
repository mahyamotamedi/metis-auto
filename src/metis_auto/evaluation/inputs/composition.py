"""Full-prompt input token counts per replay case and model (Stage E3;
evaluation framework §2.1, §0.5).

Responsibility: for each replay case, the assumed full input (instructions,
history, retrieved context, message; no compression, no attachments, no
structured input, A-16) counted per component with each catalogue model's own
tokenizer through the existing ``MeasurementService``, plus the chat-template
framing and a chars/4-style reference count (the service's default tokenizer
through a catalogue entry with no tokenizer). Also the case's strata
(language, length bucket, turn depth, retrieved context, instructions and
attachments present, opaque category) and a keyed fingerprint of the instruction text,
used **in memory only** to count how often instructions repeat; it is never
written to a report.

Assumed component order for prefix reasoning: instructions, history,
retrieved, message (``request_roles``; A-55). Language is the existing
placeholder detector (A-43), not validated. Counts are local estimates, never
billed tokens; the exact fidelity is the tokenizer's. Pure given the service.
Status: provisional (Stage E3). Sample-derived outputs are provisional (ADR-0008).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from metis_auto.application.measurement import (
    Fingerprinter,
    MeasurementService,
    request_roles,
)
from metis_auto.contracts import (
    CatalogueEntry,
    ComponentName,
    ComponentState,
    ReplayCase,
    Request,
    TokenCount,
)
from metis_auto.domain.accounting import worst_fidelity
from metis_auto.domain.features import detect_language, length_bucket
from metis_auto.domain.features.detectors import LanguageConfig

ORDER = (
    ComponentName.INSTRUCTIONS.value,
    ComponentName.HISTORY.value,
    ComponentName.RETRIEVED.value,
    ComponentName.MESSAGE.value,
)
REFERENCE = "chars_div_4_reference"
"""Key of the reference (default-tokenizer) count in ``CaseInputs``."""


@dataclass(frozen=True)
class ModelInput:
    components: Mapping[str, int]
    """Tokens per component present, in ``ORDER``."""
    template_overhead: int | None
    content_fidelity: str
    """Worst fidelity among the component counts (framing excluded)."""

    @property
    def content_tokens(self) -> int:
        return sum(self.components.values())

    @property
    def total_tokens(self) -> int:
        """Billed-input estimate: content plus framing (None framing = 0)."""
        return self.content_tokens + (self.template_overhead or 0)


@dataclass(frozen=True)
class CaseInputs:
    case_id: str
    session_ref: str
    strata: Mapping[str, str]
    chars: Mapping[str, int]
    per_model: Mapping[str, ModelInput]
    reference: ModelInput
    instructions_group: str | None = field(default=None, repr=False)
    """Keyed fingerprint of the literal instruction text; in memory only."""


def _chars(request: Request) -> dict[str, int]:
    out: dict[str, int] = {}
    if request.instructions.value:
        out[ORDER[0]] = len(request.instructions.value)
    if request.history.value:
        out[ORDER[1]] = sum(len(t.text) for t in request.history.value)
    if request.retrieved.value:
        out[ORDER[2]] = sum(len(i.text) for i in request.retrieved.value.items)
    out[ORDER[3]] = len(request.message)
    return out


def _flag(component_state: ComponentState) -> str:
    return {"present": "yes", "absent": "no", "unknown": "unknown"}[
        component_state.value
    ]


def _model_input(
    measurement: MeasurementService, entry: CatalogueEntry, request: Request
) -> ModelInput:
    counts = measurement.target_counts(request, entry)
    components = {c.component.value: c.total.tokens for c in counts.components}
    fidelity = worst_fidelity(c.total.fidelity for c in counts.components)
    overhead: TokenCount | None = measurement.overhead_for(
        entry, request_roles(request)
    )
    return ModelInput(
        components={k: components[k] for k in ORDER if k in components},
        template_overhead=None if overhead is None else overhead.tokens,
        content_fidelity=fidelity.value if fidelity else "unknown",
    )


def case_inputs(
    case: ReplayCase,
    *,
    measurement: MeasurementService,
    entries: Sequence[CatalogueEntry],
    fingerprinter: Fingerprinter,
    language: LanguageConfig,
    length_bounds: Sequence[int],
) -> CaseInputs:
    request = case.request
    reference_entry = entries[0].model_copy(update={"tokenizer_ref": None})
    instructions = request.instructions.value
    strata = {
        "language": detect_language(request.message, language).value,
        "length_bucket": str(length_bucket(len(request.message), tuple(length_bounds))),
        "turn_depth": "first" if case.turn_index == 0 else "later",
        "retrieved": _flag(request.retrieved.state),
        "instructions": _flag(request.instructions.state),
        "attachments": _flag(request.attachments.state),
    }
    if case.stratum is not None:
        strata["category"] = case.stratum
    return CaseInputs(
        case_id=case.case_id,
        session_ref=case.session_ref,
        strata=strata,
        chars=_chars(request),
        per_model={e.model_id: _model_input(measurement, e, request) for e in entries},
        reference=_model_input(measurement, reference_entry, request),
        instructions_group=(
            fingerprinter.fingerprint("instructions", instructions)
            if instructions
            else None
        ),
    )
