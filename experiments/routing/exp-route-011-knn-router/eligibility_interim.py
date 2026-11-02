"""INTERIM eligibility for R-B3 (stand-in for Parham's R-0 ``routing_base``,
which is on no branch on 2026-11-02). Labelled: every result that uses it says
``LABEL`` and stays out of any final comparison. Switch-over: replace the
injected function with ``analysis.routing_base.eligible_models`` (same
``(row, catalogue, prices, rules)`` shape) and delete this file
(``docs/experiments/pipeline_b_interim_contracts_day3.md``, Day 3).

A candidate is eligible for a request only if it is in ``rules["candidates"]``,
enabled in the catalogue, not in ``rules["retiring"]``, priced in the price
table, and has a **known** context window and output limit that the request
fits (effective input + output tokens <= window, output <= limit; an unknown
limit excludes the model, FR-ROUTE-05). The catalogue verifies no modality or
tool capability ("unverified = unsupported"), so a request with an attachment,
or from a bot with functions configured, gets no candidate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

LABEL = "interim eligibility, not the shared routing base"


def _limit(entry: Mapping[str, Any], name: str) -> float | None:
    value = entry.get(name)
    if isinstance(value, Mapping):
        value = value.get("value")
    return None if value is None else float(value)


def _missing(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def interim_eligible_models(
    row: Mapping[str, Any],
    catalogue: Mapping[str, Any],
    prices: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> tuple[str, ...]:
    inp, outp = row.get("input_tokens"), row.get("output_tokens")
    if _missing(inp) or _missing(outp):
        return ()
    if not _missing(row.get("u_att_n")) and float(row["u_att_n"]) > 0:
        return ()
    if not _missing(row.get("bot_n_functions")) and float(row["bot_n_functions"]) > 0:
        return ()
    priced = {str(p["price_ref"]) for p in prices.get("prices", [])}
    retiring = set(rules.get("retiring", ()))
    entries = {str(m["model_id"]): m for m in catalogue.get("models", [])}
    out = []
    for model in rules["candidates"]:
        m = entries.get(model)
        if m is None or not m.get("enabled", False) or model in retiring:
            continue
        if str(m.get("price_ref")) not in priced:
            continue
        window, limit = _limit(m, "context_window"), _limit(m, "max_output_tokens")
        if window is None or limit is None:
            continue
        if inp + outp <= window and outp <= limit:
            out.append(model)
    return tuple(out)
