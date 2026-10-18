"""Measurement service (CMP-02; lifecycle stages 1, 5, and 6).

Responsibility: take every measurement domain policies need, using ports or
the fingerprint key: component fingerprints, sizes, cheap token estimates
(stage 1), per-target token counts (stage 5), token usage when a client
reports none (stage 6), and sealing cache keys. Records each measurement's
method and duration (FR-ROUTE-04 overhead).
Called by: application.pipeline. Calls: ports ``Tokenizer``, ``Clock``
(``Embedder`` and model-based features are TODO(Stage 8)); the Fingerprinter.
Built by: wiring. Traces: P-1, FR-FEAT-02, FR-ACCT-01, FR-CTX-01, ADR-0015.
"""

from __future__ import annotations

from collections.abc import Mapping

from metis_auto.contracts import (
    CacheKey,
    CacheKeyDraft,
    CatalogueEntry,
    ComponentMeasurement,
    ComponentName,
    ComponentState,
    ComponentTokens,
    MeasurementRecord,
    Request,
    RequestMeasurements,
    TargetTokenCounts,
    TokenCount,
    TokenUsage,
)
from metis_auto.domain.accounting import sum_counts
from metis_auto.ports import Clock, Embedder, Tokenizer

from .fingerprints import Fingerprinter, canonical


class MeasurementService:
    def __init__(
        self,
        fingerprinter: Fingerprinter,
        clock: Clock,
        default_tokenizer: Tokenizer,
        tokenizers: Mapping[str, Tokenizer] | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._fp = fingerprinter
        self._clock = clock
        self._default = default_tokenizer
        self._tokenizers = dict(tokenizers or {})
        self._embedder = embedder  # TODO(Stage 8): semantic tier and embedding routers

    @property
    def key_id(self) -> str:
        return self._fp.key_id

    # --- stage 1 -------------------------------------------------------------

    def measure(self, request: Request) -> RequestMeasurements:
        """Content-free description of every component. Estimates use the
        default tokenizer, so they are target-independent."""
        start = self._clock.monotonic_ms()
        components = (
            self._message(request),
            self._texts(
                ComponentName.HISTORY,
                request.history.state,
                [t.text for t in request.history.value or ()],
                [t.model_dump(mode="json") for t in request.history.value or ()],
            ),
            self._texts(
                ComponentName.INSTRUCTIONS,
                request.instructions.state,
                [request.instructions.value] if request.instructions.value else [],
                request.instructions.value,
                items=False,
            ),
            self._texts(
                ComponentName.RETRIEVED,
                request.retrieved.state,
                [i.text for i in request.retrieved.value.items]
                if request.retrieved.value
                else [],
                request.retrieved.value.model_dump(mode="json")
                if request.retrieved.value
                else None,
            ),
            ComponentMeasurement(
                # Attachment content is never inspected (NG-07): count only.
                component=ComponentName.ATTACHMENTS,
                state=request.attachments.state,
                items=len(request.attachments.value or ())
                if request.attachments.value
                else None,
            ),
            self._structured(request),
        )
        record = MeasurementRecord(
            measurement="fingerprint_and_size",
            backend=f"hmac-sha256@1+{self._default.ref}",
            duration_ms=self._clock.monotonic_ms() - start,
        )
        # TODO(Stage 8, FR-FEAT-02): model-based features (semantic intent) and
        # the message embedding, each with its own MeasurementRecord and cost.
        return RequestMeasurements(
            components=components,
            fingerprint_key_id=self._fp.key_id,
            records=(record,),
        )

    def _message(self, request: Request) -> ComponentMeasurement:
        text = request.message
        if not text.strip():  # attachment-only message (A-39): empty is absent
            return ComponentMeasurement(
                component=ComponentName.MESSAGE, state=ComponentState.ABSENT, chars=0
            )
        return ComponentMeasurement(
            component=ComponentName.MESSAGE,
            state=ComponentState.PRESENT,
            fingerprint=self._fp.fingerprint("message", text),
            chars=len(text),
            token_estimate=self._default.count(text),
        )

    def _texts(
        self,
        name: ComponentName,
        state: ComponentState,
        texts: list[str],
        payload: object,
        items: bool = True,
    ) -> ComponentMeasurement:
        if state != ComponentState.PRESENT:
            return ComponentMeasurement(component=name, state=state)
        return ComponentMeasurement(
            component=name,
            state=state,
            fingerprint=self._fp.fingerprint(name.value, payload),
            chars=sum(len(t) for t in texts),
            items=len(texts) if items else None,
            token_estimate=sum_counts(self._default.count(t) for t in texts),
        )

    def _structured(self, request: Request) -> ComponentMeasurement:
        component = request.structured_input
        if component.value is None:
            return ComponentMeasurement(
                component=ComponentName.STRUCTURED_INPUT, state=component.state
            )
        text = canonical(component.value)
        return ComponentMeasurement(
            component=ComponentName.STRUCTURED_INPUT,
            state=component.state,
            fingerprint=self._fp.fingerprint("structured_input", component.value),
            chars=len(text),
            token_estimate=self._default.count(text),
        )

    # --- stage 4 -------------------------------------------------------------

    def seal_key(self, draft: CacheKeyDraft) -> CacheKey:
        return self._fp.seal(draft)

    # --- stages 5 and 6 --------------------------------------------------------

    def tokenizer_for(self, target: CatalogueEntry) -> Tokenizer:
        """The target's tokenizer, or the default approximation if none is
        registered (the count's fidelity says which)."""
        ref = target.tokenizer_ref
        return self._tokenizers.get(ref, self._default) if ref else self._default

    def target_counts(
        self, request: Request, target: CatalogueEntry
    ) -> TargetTokenCounts:
        """Per-component counts with the target's tokenizer, for the components
        the context strategy sends. TODO(Stage 8): structured input (A-16)."""
        tok = self.tokenizer_for(target)
        groups: list[tuple[ComponentName, list[str]]] = []
        if request.instructions.value:
            groups.append((ComponentName.INSTRUCTIONS, [request.instructions.value]))
        if request.history.value:
            groups.append(
                (ComponentName.HISTORY, [t.text for t in request.history.value])
            )
        if request.retrieved.value:
            items = [i.text for i in request.retrieved.value.items]
            groups.append((ComponentName.RETRIEVED, items))
        groups.append((ComponentName.MESSAGE, [request.message]))
        components = []
        for name, texts in groups:
            per_item = tuple(tok.count(t) for t in texts)
            components.append(
                ComponentTokens(
                    component=name,
                    total=sum_counts(per_item),
                    per_item=per_item if len(texts) > 1 else (),
                )
            )
        return TargetTokenCounts(model_id=target.model_id, components=tuple(components))

    def counted_usage(
        self, target: CatalogueEntry, input_tokens: TokenCount | None, answer: str
    ) -> TokenUsage | None:
        """Usage for a response that reported none: the counted input of the
        plan plus the answer counted with the target's tokenizer."""
        if input_tokens is None:
            return None
        output = self.tokenizer_for(target).count(answer)
        return TokenUsage(
            model_id=target.model_id,
            input=input_tokens,
            output=output,
            total=sum_counts((input_tokens, output)),
        )
