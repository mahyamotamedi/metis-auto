"""The four baselines on the full requests frame (final plan S-3; FR-EVAL-02,
FR-REQ-04; Review Focus 3).

``baseline_costs`` returns, per baseline key (the keys of ``compare.BASELINES``):

- ``as_logged``: **recorded** cost units. Blocks ``fees`` and ``token_cost``
  from ``levers.with_blocks`` (fee proxy: 0.002 per per-call item). ``total``
  is their sum.
- ``premium_gpt_5_5``: every request's logged tokens at the premium model's
  price (estimate only; the model is never called, ADR-0026).
- ``todays_models``: every request's logged tokens at the price of the model it
  ran on. A model without a catalogue entry or a price is unknown, not zero.
- ``best_single_cheap``: every request's logged tokens at the one callable
  model that is cheapest over all of them (cost only; quality, capability and
  context limits are not checked here, routing_base does that in R-0).
  Callable = ``enabled`` in the catalogue and priced in the price table.

The three repriced baselines are in **price-file units** (USD per the price
table's ``per_tokens``) and carry only ``token_cost``: per-call fees are not on
the token price list, and recorded units are never mixed with repriced ones. A
missing ``fees`` key means unknown in these units, not zero. "Other" cost
(F-2: web search, cache writes and the rest) is inside ``token_cost`` (owner
decision 2026-11-02: two blocks).

Each baseline also has ``total`` (``compare`` reads it before summing blocks)
and the counts ``n_requests`` (LLM rows), ``n_known`` and ``n_unknown``
(FR-EVAL-08). Workflow rows (``llm_request`` False) are never counted. Copy only
the cost keys into a ``LeverResult.baseline_cost``.

Repricing (the EDA's ``reprice``, re-implemented): effective input is
``a_bill_inputTokens``, plus ``a_bill_cachedInputTokens`` for the models in
``cached_separately`` (they report cached tokens outside the input count;
``cached_reported_separately`` finds them with the EDA's rule). Cached tokens are
capped at the effective input and priced at ``cached_input``; a price row with
``min_input_tokens`` / ``max_input_tokens`` is a context tier chosen by the
effective input. Token counts are assumed model-independent (tokenizers
differ): a *simulation*, labelled so by the caller.

Public row-level helpers for lever versions (S-6b): ``token_counts``,
``lower_uncached_input`` (a context saving comes out of uncached input only)
and ``repriced_row_costs`` (per-row cost of each repriced baseline, tier chosen
again by the lowered input). ADR-0038.

Decision record: ADR-0036,
``docs/adr/0036-replay-scope-split-and-baselines.md``.

Layer: pure pandas over injected data. No settings, no files.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal

import numpy as np
import pandas as pd

from metis_auto.analysis.levers import ReplayContext, block_column, with_blocks

BASELINE_KEYS = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")


def cached_reported_separately(req: pd.DataFrame) -> frozenset[str]:
    """Models whose billed rows mostly report more cached than input tokens.

    The EDA's rule: over rows with ``a_billing_state == "items"`` and input
    tokens above 0, the share with cached > input is above one half.
    """
    b = req[(req["a_billing_state"] == "items") & (req["a_bill_inputTokens"] > 0)]
    above = b["a_bill_cachedInputTokens"].fillna(0) > b["a_bill_inputTokens"]
    share = above.groupby(b["bot_provider_model"]).mean()
    return frozenset(share[share > 0.5].index)


def best_single_cheap_model(
    req: pd.DataFrame,
    ctx: ReplayContext,
    *,
    cached_separately: frozenset[str] = frozenset(),
) -> str:
    """The callable model with the lowest repriced cost over all known rows.

    Ties go to the first model in alphabetical order.
    """
    prices, per_tokens = _prices(ctx.price_table)
    tokens = _tokens(req, cached_separately)
    known = _llm(req) & tokens.notna().all(axis=1)
    best: tuple[float, str] | None = None
    for model in sorted(_callable(ctx.catalogue, prices)):
        cost = _reprice(tokens[known], prices[_price_ref(ctx.catalogue, model)])
        total = math.fsum(cost.to_numpy()) / per_tokens
        if best is None or total < best[0]:
            best = (total, model)
    if best is None:
        raise ValueError("no callable model: none is enabled and priced")
    return best[1]


def baseline_costs(
    req: pd.DataFrame,
    ctx: ReplayContext,
    *,
    premium_model: str,
    cached_separately: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Decimal]]:
    """The four baselines, keyed as ``BASELINE_KEYS`` (see the module docstring)."""
    prices, per_tokens = _prices(ctx.price_table)
    premium_ref = _price_ref(ctx.catalogue, premium_model)
    if premium_ref not in prices:
        raise ValueError(f"premium model {premium_model} has no price")
    llm = _llm(req)
    tokens = _tokens(req, cached_separately)
    known = llm & tokens.notna().all(axis=1)

    def repriced(ref_of_row: pd.Series) -> dict[str, Decimal]:
        priced = known & ref_of_row.isin(list(prices))
        cost = pd.Series(np.nan, index=req.index)
        for ref, rows in ref_of_row[priced].groupby(ref_of_row[priced]):
            cost[rows.index] = _reprice(tokens.loc[rows.index], prices[ref])
        token_cost = _decimal(math.fsum(cost[priced].to_numpy()) / per_tokens)
        return {"token_cost": token_cost, "total": token_cost} | _counts(llm, priced)

    cheap = best_single_cheap_model(req, ctx, cached_separately=cached_separately)
    logged_ref = req["bot_provider_model"].map(_price_refs(ctx.catalogue))
    return {
        "premium_gpt_5_5": repriced(pd.Series(premium_ref, index=req.index)),
        "as_logged": _as_logged(req, llm),
        "todays_models": repriced(logged_ref),
        "best_single_cheap": repriced(
            pd.Series(_price_ref(ctx.catalogue, cheap), index=req.index)
        ),
    }


REPRICED_KEYS = ("premium_gpt_5_5", "todays_models", "best_single_cheap")


def token_counts(
    req: pd.DataFrame, cached_separately: frozenset[str] = frozenset()
) -> pd.DataFrame:
    """Effective ``input``, ``cached`` (capped at input) and ``output`` tokens per
    row, by the repricing rule above. Unknown tokens stay NaN."""
    return _tokens(req, cached_separately)


def lower_uncached_input(tokens: pd.DataFrame, wanted: pd.Series) -> pd.DataFrame:
    """Lower ``input`` by ``wanted`` tokens, taken from the **uncached** part only.

    The saving is capped at ``input - cached``; ``cached`` and ``output`` are
    unchanged. Adds ``saved``, the tokens actually removed (NaN where the tokens
    or ``wanted`` are unknown). Rule of ADR-0038.
    """
    out = tokens.copy()
    room = (tokens["input"] - tokens["cached"]).clip(lower=0)
    want = wanted.reindex(tokens.index).astype(float)
    saved = np.minimum(want.clip(lower=0), room).where(want.notna() & room.notna())
    out["saved"] = saved
    out["input"] = tokens["input"] - saved
    return out


def repriced_row_costs(
    req: pd.DataFrame,
    ctx: ReplayContext,
    *,
    premium_model: str,
    cached_separately: frozenset[str] = frozenset(),
    tokens: pd.DataFrame | None = None,
    cheap_model: str | None = None,
) -> pd.DataFrame:
    """Per-row cost of each repriced baseline (``REPRICED_KEYS``), price-file units.

    Same rule as ``baseline_costs``; the column sums equal its ``token_cost``.
    ``tokens`` replaces the logged counts (for example after
    ``lower_uncached_input``), so the tier is chosen again by the new input.
    ``cheap_model`` fixes the best single cheap model; by default it is chosen
    on the logged tokens. NaN: workflow row, unknown tokens or no price.
    """
    prices, per_tokens = _prices(ctx.price_table)
    premium_ref = _price_ref(ctx.catalogue, premium_model)
    if premium_ref not in prices:
        raise ValueError(f"premium model {premium_model} has no price")
    if tokens is None:
        tokens = _tokens(req, cached_separately)
    if cheap_model is None:
        cheap_model = best_single_cheap_model(
            req, ctx, cached_separately=cached_separately
        )
    known = _llm(req) & tokens[["input", "cached", "output"]].notna().all(axis=1)
    refs = {
        "premium_gpt_5_5": pd.Series(premium_ref, index=req.index),
        "todays_models": req["bot_provider_model"].map(_price_refs(ctx.catalogue)),
        "best_single_cheap": pd.Series(
            _price_ref(ctx.catalogue, cheap_model), index=req.index
        ),
    }
    out = pd.DataFrame(index=req.index)
    for key in REPRICED_KEYS:
        ref_of_row = refs[key]
        priced = known & ref_of_row.isin(list(prices))
        cost = pd.Series(np.nan, index=req.index)
        for ref, rows in ref_of_row[priced].groupby(ref_of_row[priced]):
            cost[rows.index] = _reprice(tokens.loc[rows.index], prices[ref])
        out[key] = cost / per_tokens
    return out


def _as_logged(req: pd.DataFrame, llm: pd.Series) -> dict[str, Decimal]:
    blocks = with_blocks(req)
    cols = [block_column(b) for b in ("fees", "token_cost")]
    known = llm & blocks[cols].notna().all(axis=1)
    fees = math.fsum(blocks.loc[known, cols[0]].to_numpy(dtype=float))
    token = math.fsum(blocks.loc[known, cols[1]].to_numpy(dtype=float))
    return {
        "fees": _decimal(fees),
        "token_cost": _decimal(token),
        "total": _decimal(fees + token),
    } | _counts(llm, known)


def _counts(llm: pd.Series, known: pd.Series) -> dict[str, Decimal]:
    n, k = int(llm.sum()), int((llm & known).sum())
    return {
        "n_requests": Decimal(n),
        "n_known": Decimal(k),
        "n_unknown": Decimal(n - k),
    }


def _llm(req: pd.DataFrame) -> pd.Series:
    if "llm_request" not in req or req["llm_request"].isna().any():
        raise ValueError("llm_request is missing or unknown; run the scope step first")
    return req["llm_request"].astype(bool)


def _tokens(req: pd.DataFrame, cached_separately: frozenset[str]) -> pd.DataFrame:
    """Effective input, cached (capped at input) and output tokens per row."""
    raw_in = req["a_bill_inputTokens"]
    cached = req["a_bill_cachedInputTokens"].fillna(0).where(raw_in.notna())
    add = req["bot_provider_model"].isin(cached_separately)
    eff_in = raw_in + cached.where(add, 0)
    return pd.DataFrame(
        {
            "input": eff_in,
            "cached": np.minimum(cached, eff_in),
            "output": req["a_bill_outputTokens"],
        },
        index=req.index,
    )


def _reprice(tokens: pd.DataFrame, tiers: list[Mapping[str, object]]) -> pd.Series:
    """Cost in price units x ``per_tokens`` (divided once, by the caller)."""
    cost = pd.Series(np.nan, index=tokens.index)
    eff = tokens["input"]
    for p in tiers:
        lo = _bound(p.get("min_input_tokens"), 0.0)
        hi = _bound(p.get("max_input_tokens"), np.inf)
        m = (eff >= lo) & (eff <= hi)
        cost[m] = (
            (eff - tokens["cached"])[m] * float(p["input"])
            + tokens["cached"][m] * float(p["cached_input"])
            + tokens["output"][m] * float(p["output"])
        )
    return cost


def _bound(value: object, default: float) -> float:
    """A tier bound; missing (None or NaN, as in a price frame) is open."""
    return default if value is None or pd.isna(value) else float(value)


def _prices(
    table: Mapping[str, object] | pd.DataFrame,
) -> tuple[dict[str, list[Mapping[str, object]]], float]:
    """Price rows grouped by ``price_ref`` (one row per context tier)."""
    if isinstance(table, pd.DataFrame):
        rows, per = table.to_dict("records"), 1_000_000
    else:
        rows, per = list(table.get("prices", [])), table.get("per_tokens", 1_000_000)
    out: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        for key in ("input", "output", "cached_input"):
            if key not in row or row[key] is None:
                raise ValueError(f"price {row.get('price_ref')} has no {key} price")
        out.setdefault(str(row["price_ref"]), []).append(row)
    return out, float(per)


def _models(catalogue: Mapping[str, object] | pd.DataFrame) -> list[Mapping]:
    if isinstance(catalogue, pd.DataFrame):
        return catalogue.to_dict("records")
    return list(catalogue.get("models", []))


def _price_refs(catalogue: Mapping[str, object] | pd.DataFrame) -> dict[str, str]:
    return {str(m["model_id"]): str(m["price_ref"]) for m in _models(catalogue)}


def _price_ref(catalogue: Mapping[str, object] | pd.DataFrame, model: str) -> str:
    refs = _price_refs(catalogue)
    if model not in refs:
        raise ValueError(f"model {model} is not in the catalogue, so it has no price")
    return refs[model]


def _callable(catalogue: Mapping[str, object] | pd.DataFrame, prices: Mapping) -> list:
    return [
        str(m["model_id"])
        for m in _models(catalogue)
        if bool(m.get("enabled", False)) and str(m["price_ref"]) in prices
    ]


def _decimal(value: float) -> Decimal:
    """Fixed nine-decimal Decimal (and no negative zero), as in ``levers``."""
    return Decimal(f"{value + 0.0:.9f}")
