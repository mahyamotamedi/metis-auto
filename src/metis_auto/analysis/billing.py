"""Parse the logged ``billing`` JSON into per-message aggregates.

``billing`` is a list of call items per AI message. Token fields are
**provider-reported or Metis-recorded usage** (observed fact, provenance of the
counts unverified). ``totalCost`` is Metis's recorded cost and ``totalIncome`` the
amount charged; neither is re-derived here. Missing is unknown, not zero:
messages without a billing list get ``billing_state`` != "items".

Traces: FR-ACCT-*, ADR-0006, ADR-0020.
"""

from __future__ import annotations

import json
from typing import Any

_SUM_FIELDS = (
    "callCount",
    "inputTokens",
    "outputTokens",
    "cachedInputTokens",
    "cacheWriteTokens",
    "audioInputTokens",
    "audioOutputTokens",
    "webSearchCalls",
    "groundingSearchQueries",
    "billableSeconds",
    "totalCost",
    "usageCost",
    "fixedCost",
    "totalIncome",
)


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def parse_billing(raw: str | None) -> dict[str, object]:
    """Aggregate one billing JSON string.

    ``billing_state``: ``null`` (no value), ``empty_list``, ``malformed``, ``items``.
    ``n_items`` counts list entries; ``n_token_items`` counts entries with
    ``inputTokens`` > 0 (model calls, as opposed to per-call fixed charges).
    """
    out: dict[str, object] = {"billing_state": "null", "n_items": 0, "n_token_items": 0}
    if raw is None:
        return out
    try:
        items = json.loads(raw)
    except ValueError:
        out["billing_state"] = "malformed"
        return out
    if not isinstance(items, list):
        out["billing_state"] = "malformed"
        return out
    if not items:
        out["billing_state"] = "empty_list"
        return out
    out["billing_state"] = "items"
    sums = {f: 0.0 for f in _SUM_FIELDS}
    n_tok = 0
    per_call_only = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        for f in _SUM_FIELDS:
            sums[f] += _num(it.get(f))
        n_tok += _num(it.get("inputTokens")) > 0
        bd = it.get("costBreakdown")
        if isinstance(bd, dict) and set(bd) == {"per_call"}:
            per_call_only += 1
    out["n_items"] = len(items)
    out["n_token_items"] = n_tok
    out["n_per_call_only_items"] = per_call_only
    out.update({f"bill_{k}": v for k, v in sums.items()})
    # Largest single call input (the main answer call usually dominates).
    out["bill_max_item_input_tokens"] = max(
        (_num(i.get("inputTokens")) for i in items if isinstance(i, dict)), default=0.0
    )
    return out


def usd_per_million(cost: float, tokens: float) -> float | None:
    """Recorded cost per million tokens, ``None`` when there are no tokens."""
    return None if tokens <= 0 else cost / tokens * 1e6
