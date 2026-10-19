"""Premium-baseline estimate (brief §5, FR-ACCT-05, ADR-0002, ADR-0020).

Responsibility: price what the premium model *would* have cost, without
calling it: input = the full, uncompressed context counted with the premium
model's tokenizer (no provider cache), plus its chat-template overhead;
output = the answer actually served, re-counted with the premium tokenizer
(the same answer length is assumed). Always a labelled estimate: caveat
``answer_length_assumed``, and ``reasoning_not_counted`` when the premium
model bills hidden reasoning (the estimate is then a lower bound).
Pure; the counts come from application.measurement (P-1).
Called by: application.accounting.
"""

from __future__ import annotations

from metis_auto.contracts import (
    AccountedUsage,
    CatalogueEntry,
    CostBasis,
    CostCaveat,
    CostStatus,
    Name,
    PriceTable,
    TokenCount,
    TokenUsage,
)

from .cost import cost_of
from .overhead import with_overhead
from .tokens import sum_counts


def baseline_estimate(
    baseline: Name,
    target: CatalogueEntry,
    full_context: TokenCount,
    overhead: TokenCount | None,
    answer: TokenCount,
    prices: PriceTable,
) -> AccountedUsage:
    """``full_context`` and ``answer`` must be counted with ``target``'s
    tokenizer (the caller's job)."""
    billed_input = with_overhead(full_context, overhead)
    usage = TokenUsage(
        model_id=target.model_id,
        input=billed_input,
        output=answer,
        total=sum_counts((billed_input, answer)),
        template_overhead=overhead,
    )
    cost = cost_of(usage, target, prices, CostBasis.BASELINE_ESTIMATE)
    if cost.status == CostStatus.COMPUTED:
        caveats = (CostCaveat.ANSWER_LENGTH_ASSUMED, *cost.caveats)
        cost = cost.model_copy(update={"caveats": tuple(dict.fromkeys(caveats))})
    return AccountedUsage(
        model_id=target.model_id, usage=usage, cost=cost, baseline=baseline
    )
