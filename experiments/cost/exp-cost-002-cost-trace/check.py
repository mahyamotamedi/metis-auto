"""F-2 cost trace: split each message's recorded ``totalCost`` into named blocks,
so that the remainder outside the four EDA blocks (fees, input, output, cached)
is labelled and not hidden (final plan F-2; FR-ACCT-01, H-7, QA-REPRO).

Uses ``analysis.billing.parse_billing`` for the billing state (``null``,
``empty_list``, ``malformed``, ``items``) and walks the same JSON items for the
logged ``costBreakdown`` keys. Money is ``Decimal`` built from each value's
``repr``, so the blocks of a message sum **exactly** to its total.

Blocks per item (evidence: *observed* for named breakdown keys, *metadata-derived*
for the usage/fixed split of items without a breakdown):

- ``fees`` (``per_call``), ``input`` (``input_tokens``), ``output``
  (``output_tokens``), ``cached`` (``cached_input_tokens``), ``cache_write``
  (``cache_write_tokens``): the logged ``costBreakdown`` amounts;
- ``breakdown_other``: any other ``costBreakdown`` key (counted by name);
- ``breakdown_gap``: total minus the breakdown sum, when a breakdown exists
  (non-numeric breakdown values stay in the gap and are counted);
- items with no or an empty ``costBreakdown``: ``unbroken_usage`` (``usageCost``)
  and ``unbroken_fixed`` (``fixedCost``) when both are numeric, with any
  difference in ``unresolved``; otherwise the whole total is ``unresolved``.

Signed values are kept (no clipping). An item whose ``totalCost`` is not a
number has an unknown cost and is left out of the total and of every block (it
is counted). A message whose state is not ``items`` has an unknown total
(``None``), never zero. ``incomeBreakdown`` and income fields are never cost.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from metis_auto.analysis.billing import parse_billing

BREAKDOWN_KEYS = {
    "per_call": "fees",
    "input_tokens": "input",
    "output_tokens": "output",
    "cached_input_tokens": "cached",
    "cache_write_tokens": "cache_write",
}
BLOCKS = (
    "fees",
    "input",
    "output",
    "cached",
    "cache_write",
    "breakdown_other",
    "breakdown_gap",
    "unbroken_usage",
    "unbroken_fixed",
    "unresolved",
)
EDA_BLOCKS = ("fees", "input", "output", "cached")
"""The four blocks of the EDA's ``cost.split.*`` claims; the rest is "other"."""

LABELS = {
    "fees": "per-call fees (costBreakdown.per_call)",
    "input": "input tokens (costBreakdown.input_tokens)",
    "output": "output tokens (costBreakdown.output_tokens)",
    "cached": "cached input tokens (costBreakdown.cached_input_tokens)",
    "cache_write": "cache writes (costBreakdown.cache_write_tokens)",
    "breakdown_other": "other costBreakdown keys",
    "breakdown_gap": "total minus breakdown on items that have a breakdown",
    "unbroken_usage": "usage cost of items logged without a costBreakdown",
    "unbroken_fixed": "fixed cost of items logged without a costBreakdown",
    "unresolved": "items without a breakdown and without a usage/fixed split",
}
COUNTS = (
    "items",
    "items_not_dict",
    "items_total_unknown",
    "items_no_breakdown",
    "items_empty_breakdown",
    "breakdown_values_malformed",
    "negative_entries",
    "unbroken_with_tokens",
    "unbroken_with_web_search",
    "unbroken_with_audio",
    "unbroken_with_cache_write",
)


def _dec(value: Any) -> Decimal | None:
    """A finite number as an exact ``Decimal``; ``None`` otherwise."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    d = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    return d if d.is_finite() else None


def _positive(value: Any) -> bool:
    d = _dec(value)
    return d is not None and d > 0


def _empty() -> dict[str, Any]:
    return {
        "blocks": {b: Decimal(0) for b in BLOCKS},
        "counts": dict.fromkeys(COUNTS, 0),
        "other_keys": Counter(),
    }


def trace_message(raw: str | None) -> dict[str, Any]:
    """Blocks, counts and total of one message's billing JSON (see module doc).
    A non-string value (``None``, or NaN from a frame) is missing billing."""
    raw = raw if isinstance(raw, str) else None
    state = parse_billing(raw)["billing_state"]
    out = _empty() | {"state": state, "total": None}
    if state != "items":
        return out
    blocks, counts, other = out["blocks"], out["counts"], out["other_keys"]
    total = Decimal(0)
    for it in json.loads(raw):  # type: ignore[arg-type]
        counts["items"] += 1
        if not isinstance(it, dict):
            counts["items_not_dict"] += 1
            continue
        item_total = _dec(it.get("totalCost"))
        if item_total is None:
            counts["items_total_unknown"] += 1
            continue
        total += item_total
        counts["negative_entries"] += item_total < 0
        bd = it.get("costBreakdown")
        if isinstance(bd, dict) and bd:
            covered = Decimal(0)
            for key, value in bd.items():
                d = _dec(value)
                if d is None:
                    counts["breakdown_values_malformed"] += 1
                    continue
                counts["negative_entries"] += d < 0
                block = BREAKDOWN_KEYS.get(key)
                if block is None:
                    block = "breakdown_other"
                    other[key] += 1
                blocks[block] += d
                covered += d
            blocks["breakdown_gap"] += item_total - covered
            continue
        counts[
            "items_empty_breakdown" if isinstance(bd, dict) else "items_no_breakdown"
        ] += 1
        counts["unbroken_with_tokens"] += _positive(it.get("inputTokens")) or _positive(
            it.get("outputTokens")
        )
        counts["unbroken_with_web_search"] += _positive(it.get("webSearchCalls"))
        counts["unbroken_with_audio"] += _positive(
            it.get("audioInputTokens")
        ) or _positive(it.get("audioOutputTokens"))
        counts["unbroken_with_cache_write"] += _positive(it.get("cacheWriteTokens"))
        usage, fixed = _dec(it.get("usageCost")), _dec(it.get("fixedCost"))
        if isinstance(bd, dict) or usage is None or fixed is None:
            blocks["unresolved"] += item_total
            continue
        blocks["unbroken_usage"] += usage
        blocks["unbroken_fixed"] += fixed
        blocks["unresolved"] += item_total - usage - fixed
    out["total"] = total
    return out


def reconcile(traces: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate message traces: totals, blocks, shares, coverage, the identity
    check, a labelled waterfall and the two ``levers.py`` blocks (``fees`` and
    ``token_cost`` = everything else)."""
    agg = _empty()
    by_state: Counter[str] = Counter()
    total = Decimal(0)
    n = 0
    for t in traces:
        n += 1
        by_state[t["state"]] += 1
        if t["total"] is None:
            continue
        total += t["total"]
        for b in BLOCKS:
            agg["blocks"][b] += t["blocks"][b]
        for c in COUNTS:
            agg["counts"][c] += t["counts"][c]
        agg["other_keys"].update(t["other_keys"])
    blocks = agg["blocks"]
    block_sum = sum(blocks.values(), Decimal(0))
    shares = {b: (float(v / total) if total else None) for b, v in blocks.items()}
    waterfall = [
        {
            "block": b,
            "group": b if b in EDA_BLOCKS else "other",
            "label": LABELS[b],
            "amount": blocks[b],
            "share": shares[b],
        }
        for b in BLOCKS
    ]
    other = sum((blocks[b] for b in BLOCKS if b not in EDA_BLOCKS), Decimal(0))
    return {
        "total": total,
        "blocks": blocks,
        "shares": shares,
        "other_total": other,
        "other_share": float(other / total) if total else None,
        "waterfall": waterfall,
        "lever_blocks": {"fees": blocks["fees"], "token_cost": total - blocks["fees"]},
        "counts": agg["counts"],
        "other_keys": dict(agg["other_keys"]),
        "coverage": {
            "messages": n,
            "by_state": dict(by_state),
            "messages_cost_known": by_state.get("items", 0),
        },
        "check": {"blocks_minus_total": block_sum - total},
    }
