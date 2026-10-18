"""Accounting service (CMP-09 use case; MP Stage 7, brief §5–§6).

Responsibility: given a request and an answer for a named catalogue model,
report input, output, and total tokens and the estimated cost, each with its
fidelity, price-table version, and caveats; estimate the premium baseline
without calling it; and decompose a served response's cost into the brief's
savings terms. Counting goes through the measurement service (tokenizer
ports, chat templates); every decision and sum is pure domain code (P-1).
Called by: scripts, tests, (Demo milestone) the UI through wiring.
Calls: application.measurement, domain.accounting. Built by: wiring.
Traces: FR-ACCT-01…05, ADR-0002, ADR-0020.
"""

from __future__ import annotations

from metis_auto.contracts import (
    AccountedUsage,
    CatalogueEntry,
    CostBasis,
    FinalResponse,
    ModelCatalogue,
    Name,
    PriceTable,
    Request,
    SavingsDecomposition,
    ServedBy,
    TokenCount,
    TokenUsage,
)
from metis_auto.domain import accounting

from ..measurement import MeasurementService, request_roles


class AccountingService:
    def __init__(
        self,
        measurement: MeasurementService,
        catalogue: ModelCatalogue,
        prices: PriceTable,
    ) -> None:
        self._measurement = measurement
        self._entries = {e.model_id: e for e in catalogue.entries}
        self._prices = prices

    def entry(self, model_id: str) -> CatalogueEntry:
        if model_id not in self._entries:
            raise KeyError(f"model {model_id!r} is not in the catalogue")
        return self._entries[model_id]

    def content_tokens(self, request: Request, model_id: str) -> TokenCount:
        """The full request's content (instructions, history, retrieved,
        message) counted with the model's tokenizer; no framing."""
        target = self.entry(model_id)
        counts = self._measurement.target_counts(request, target)
        total = accounting.sum_counts(c.total for c in counts.components)
        assert total is not None  # the message is always counted
        return total

    def account(
        self,
        request: Request,
        model_id: str,
        answer: str,
        usage: TokenUsage | None = None,
        basis: CostBasis = CostBasis.ACTUAL,
    ) -> AccountedUsage:
        """Tokens and cost of ``answer`` to ``request`` on ``model_id``.
        Provider-reported ``usage`` wins when given; otherwise everything is
        counted locally (full request plus chat-template overhead, answer
        re-counted), and the fidelity says so."""
        target = self.entry(model_id)
        if usage is None:
            usage = self._measurement.counted_usage(
                target,
                self.content_tokens(request, model_id),
                answer,
                request_roles(request),
            )
            assert usage is not None
        cost = accounting.cost_of(usage, target, self._prices, basis)
        return AccountedUsage(model_id=model_id, usage=usage, cost=cost)

    def premium_estimate(
        self, request: Request, answer: str, model_id: str, baseline: Name = "premium"
    ) -> AccountedUsage:
        """Brief §5: the premium model on the full, uncompressed context (no
        provider cache), its answer assumed to be ``answer`` re-counted with
        the premium tokenizer. Never calls a model."""
        target = self.entry(model_id)
        return accounting.baseline_estimate(
            baseline,
            target,
            self.content_tokens(request, model_id),
            self._measurement.overhead_for(target, request_roles(request)),
            self._measurement.tokenizer_for(target).count(answer),
            self._prices,
        )

    def decompose(
        self,
        request: Request,
        response: FinalResponse,
        *,
        premium_model_id: str,
        chosen_model_id: str | None = None,
        sent_request: Request | None = None,
    ) -> SavingsDecomposition:
        """Brief §6 for one served message. ``request`` is the full,
        uncompressed request; ``sent_request`` what the context strategy sent
        (default: the same, i.e. pass-through). The chosen model defaults to
        the model that produced the answer."""
        meta = response.metadata
        chosen = chosen_model_id or meta.final_model_id
        answer = response.answer
        if chosen is None or answer is None:
            raise ValueError("decompose needs a served answer and its model")
        hit = meta.served_by == ServedBy.CACHE
        reported = None if hit else meta.answer_usage
        output = reported.output if reported and reported.output else None

        def undiscounted(req: Request) -> AccountedUsage:
            counted = self.account(
                req, chosen, answer, basis=CostBasis.AVOIDED_ESTIMATE
            )
            if output is None:
                return counted
            usage = counted.usage.model_copy(
                update={
                    "output": output,
                    "reasoning": reported.reasoning if reported else None,
                    "total": accounting.sum_counts((counted.usage.input, output)),
                }
            )
            return self.account(
                req, chosen, answer, usage=usage, basis=CostBasis.AVOIDED_ESTIMATE
            )

        full = undiscounted(request)
        sent = full if sent_request is None else undiscounted(sent_request)
        target = self.entry(chosen)
        return accounting.decompose_message(
            premium=self.premium_estimate(request, answer, premium_model_id).cost,
            chosen_full=full.cost,
            chosen_sent=sent.cost,
            served_from_cache=hit,
            provider_cache_discount=None
            if hit
            else accounting.provider_cache_discount(reported, target, self._prices),
            actually_paid=meta.total_cost,
        )
