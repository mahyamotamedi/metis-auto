"""The Gemini live check: plan and settings (ADR-0043,
ADR-0042).

Responsibility: the no-call half of ``scripts/live_gemini_check.py``. ``plan``
lists every reason the check would refuse (no catalogue row, endpoint not an
enabled ``google_genai`` one, no thinking budget, estimate not computed or at
or above the run cap) and the spend guard's pre-call estimate: counted input
plus the generation limit **plus the thinking budget** as output, since
thinking tokens bill as output and whether ``maxOutputTokens`` bounds them is
unverified (2026-11-02). ``overrides`` fixes one model, one attempt, a small
output cap, the run cap, and the thinking budget. The live half reuses
``wrapper_check.run`` (real pipeline, spend guard, ledger, recording).
Called by: ``scripts/live_gemini_check.py``, tests. Status: provisional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from metis_auto.contracts import CostStatus
from metis_auto.domain.context import reserved_output
from metis_auto.settings import ApiFormat, EndpointStatus, LoadedSettings

from .from_settings import build_accounting_service, pipeline_config
from .live import live_overrides
from .wrapper_check import check_request

DEFAULT_MODEL = "gemini-2.5-flash"
"""A Metis pricing-page ID (docs/references/metis_pricing_2026-10-18.csv);
not in the catalogue yet: adding it is part of the enabling step."""
OUTPUT_CAP = 64
"""Generation limit for the check (tokens)."""
MAX_TOTAL_ESTIMATE = Decimal("0.01")
"""Run cap (USD) for the check, on the pre-call estimate; also set as the
pipeline's ``[budget] run_cap`` so the spend guard enforces it."""


@dataclass(frozen=True)
class GeminiPlan:
    model_id: str
    input_tokens: int | None = None
    output_limit: int | None = None
    thinking_budget: int | None = None
    estimate: Decimal | None = None
    currency: str = "USD"
    reasons: list[str] = field(default_factory=list)
    """Why the check would refuse; empty = it may run (with owner approval)."""


def overrides(model_id: str, thinking_budget: int | None) -> dict[str, Any]:
    """Caller overrides (layer 6) for the check."""
    o = live_overrides(model_id, allow_unknown_window=True, single_attempt=True)
    o["pipeline.context.max_output_tokens_cap"] = OUTPUT_CAP
    o["budget.run_cap"] = str(MAX_TOTAL_ESTIMATE)
    if thinking_budget is not None:
        o[f"model_options.{model_id}.thinking_budget"] = thinking_budget
    return o


def plan(loaded: LoadedSettings, model_id: str) -> GeminiPlan:
    """No call. Every refusal reason, and the estimate when computable."""
    entry = next(
        (e for e in loaded.reference.catalogue.entries if e.model_id == model_id),
        None,
    )
    if entry is None:
        return GeminiPlan(
            model_id,
            reasons=[f"{model_id}: no catalogue row (part of the enabling step)"],
        )
    reasons: list[str] = []
    endpoints = loaded.reference.endpoints
    endpoint = endpoints.get(entry.provider) if endpoints else None
    if endpoint is None or endpoint.api_format != ApiFormat.GOOGLE_GENAI:
        reasons.append(f"{model_id}: not a google_genai (Gemini) model")
    elif endpoint.status != EndpointStatus.ENABLED:
        reasons.append(f"the {entry.provider!r} endpoint is {endpoint.status.value}")
    options = loaded.settings.model_options.get(model_id)
    budget = options.thinking_budget if options else None
    if budget is None:
        reasons.append(f"{model_id}: no thinking budget set (--thinking-budget)")

    accounting = build_accounting_service(loaded)
    limit = reserved_output(entry, pipeline_config(loaded).context)
    estimate = accounting.pre_call_estimate(
        check_request(), model_id, limit + (budget or 0)
    )
    amount = estimate.cost.amount
    computed = estimate.cost.status == CostStatus.COMPUTED and amount is not None
    if not computed:
        reasons.append(f"{model_id}: the cost estimate is not computed")
    elif amount.amount >= MAX_TOTAL_ESTIMATE:
        reasons.append(
            f"the estimate {amount.amount} {amount.currency} reaches the run cap "
            f"{MAX_TOTAL_ESTIMATE} USD"
        )
    return GeminiPlan(
        model_id=model_id,
        input_tokens=estimate.input_tokens.tokens,
        output_limit=limit,
        thinking_budget=budget,
        estimate=amount.amount if computed else None,
        currency=amount.currency if computed else "USD",
        reasons=reasons,
    )
