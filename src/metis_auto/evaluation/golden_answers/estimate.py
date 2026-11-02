"""Estimates for the rest of a run: who shares instructions, and what provider
prompt caching could save (pure, ADR-0030). Estimates, not promises: whether the
Metis wrapper passes caching through is not verified, and the pilot did not test
it (its records were not grouped)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from metis_auto.contracts import (
    CatalogueEntry,
    CostBasis,
    Fidelity,
    PriceTable,
    TokenCount,
    TokenUsage,
)
from metis_auto.domain.accounting.cost import cost_of
from metis_auto.evaluation.golden_answers.runner import Task

GPT_5_5_CACHE_INTERVAL = 2048
"""OpenAI prompt-caching guide, checked 2026-11-01: for GPT-5.5 the cache has
implicit breakpoints at regular 2,048-token intervals and needs the whole
rendered prefix to match."""


def sharing(tasks: Sequence[Task]) -> dict[str, int]:
    """Counts of records that share a bot, or identical leading instructions, with
    at least one other record in ``tasks``."""
    bots = Counter(t.bot_id for t in tasks if t.bot_id)
    keys = Counter(t.prefix_key for t in tasks if t.prefix_key)
    return {
        "records": len(tasks),
        "bots": len(bots),
        "records_sharing_a_bot": sum(n for n in bots.values() if n > 1),
        "bots_with_more_than_one_record": sum(n > 1 for n in bots.values()),
        "largest_bot_group": max(bots.values(), default=0),
        "records_sharing_identical_instructions": sum(
            n for n in keys.values() if n > 1
        ),
        "instruction_groups": len(keys),
        "records_without_instructions": sum(t.prefix_key is None for t in tasks),
    }


def cache_scenarios(
    ordered: Sequence[Task],
    entry: CatalogueEntry,
    prices: PriceTable,
    output_tokens_per_record: int,
    interval: int = GPT_5_5_CACHE_INTERVAL,
) -> dict[str, Any]:
    """Cost of ``ordered`` (already in run order) under three cache assumptions.
    The first record of each instruction group pays full price; later ones may
    read the instruction prefix from the cache.

    - ``none``: no caching (the worst case).
    - ``best_case``: every instruction token of a repeated group is cached.
    - ``documented_rule``: only whole ``interval``-token blocks of the prefix are
      cached (the documented GPT-5.5 behaviour).
    """
    seen: set[str] = set()
    cached = {"none": 0, "best_case": 0, "documented_rule": 0}
    cost = {name: Decimal(0) for name in cached}
    input_only = {name: Decimal(0) for name in cached}
    unpriced = 0
    for t in ordered:
        repeat = t.prefix_key is not None and t.prefix_key in seen
        if t.prefix_key is not None:
            seen.add(t.prefix_key)
        amounts = {
            "none": 0,
            "best_case": t.prefix_tokens if repeat else 0,
            "documented_rule": (t.prefix_tokens // interval) * interval
            if repeat
            else 0,
        }
        for name, tokens in amounts.items():
            tokens = min(tokens, t.input_tokens.tokens)
            totals = []
            for out in (0, output_tokens_per_record):
                usage = TokenUsage(
                    model_id=entry.model_id,
                    input=t.input_tokens,
                    output=TokenCount(
                        tokens=out, fidelity=Fidelity.APPROXIMATION, method="est@1"
                    ),
                    cached_input=TokenCount(
                        tokens=tokens, fidelity=Fidelity.APPROXIMATION, method="est@1"
                    )
                    if tokens
                    else None,
                )
                c = cost_of(usage, entry, prices, CostBasis.PRE_CALL_ESTIMATE)
                totals.append(None if c.amount is None else c.amount.amount)
            if None in totals:
                unpriced += 1
                continue
            input_only[name] += totals[0]
            cost[name] += totals[1]
            cached[name] += tokens
    return {
        name: {
            "cached_tokens": cached[name],
            "input_usd": str(input_only[name]),
            "total_usd": str(cost[name]),
            "total_usd_if_output_is_1_5x": str(
                cost[name] + (cost[name] - input_only[name]) / 2
            ),
        }
        for name in cached
    } | {"unpriced_records": unpriced}
