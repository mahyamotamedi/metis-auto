"""Lever base: ``StepVersion``, ``ReplayContext`` and ``combine`` (final plan S-1).

A *step version* is a small function from a requests frame to a modified copy of
it. ``combine`` applies one cache, one context and one routing version in that
order, so a request served from cache gets no context or routing saving
(Review Focus 1; QA-REPRO; H-3, X1, X5). Results are **simulations** on logged
requests: a cache hit is a *candidate* hit, and quality is not measured.

Frame contract (columns are the real names in ``requests.parquet``; the others
are added by S-3 or by a version):

- ``llm_request`` (bool, S-3): False for workflow rows, which have no billing.
  ``combine`` never gives such a row to a version, and ``summarise_slices``
  never counts one in a cost or a hit. Unknown is never zero (FR-REQ-01, P-6).
- ``block_fees`` and ``block_token_cost``: the two cost blocks, in the unstated
  recorded units. ``with_blocks`` derives them from ``a_bill_totalCost`` and
  ``a_n_per_call_only_items``. The fee block is a proxy (0.002 per per-call
  item; 97.6% of per-call rows are exactly that amount, ledger
  ``fee.per_call_modal_share``). Checked 2026-11-02 against the billing table:
  the proxy sums to 181.3 units against 190.7 recorded (35.8% against 37.6% of
  cost), 908 messages differ, and totals agree (506.7). The proxy therefore
  understates the fee by about 5% and overstates ``block_token_cost`` by the
  same amount. ``block_token_cost`` is everything else
  (input, output, cached and other). The input, output and cached costs are not
  in ``requests.parquet``, so they are not separate blocks (decided 2026-11-02).
- ``served_from_cache`` (bool): set by cache versions, which also zero every
  cost block on hit rows.

Recorded cost is never mixed with repriced cost. A version that reprices
(routing) must write a repriced column, label it so in its ``LeverResult``
assumptions, and not add it to a recorded baseline.

WARNING for routing repricing (Review Focus 3, task R-A3): ``a_bill_inputTokens``
is the raw logged value and **excludes cached tokens for five models** (see
``reports/full_eda/tables/cached_token_convention.csv``; the EDA adds them back
in memory). This module does not resolve that. Repricing must follow the same
rule as the EDA, with a test.

Layer: pure pandas over injected data. No settings, no git, no files.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

import pandas as pd

Step = Literal["cache", "context", "routing"]

BLOCKS = ("fees", "token_cost")
"""Cost blocks, in the order they are reported. Column ``block_<name>``."""

FEE_PER_CALL = 0.002
"""Recorded fee per per-call-only billing item (EDA ``fee.per_call_modal_amount``)."""


def block_column(block: str) -> str:
    return f"block_{block}"


class CacheGuardLike(Protocol):
    """What a version needs from ``cache_guard.CacheGuard`` (written by Pipeline B)."""

    def allows(self, key: str, bot: str) -> bool: ...


@dataclass(frozen=True, eq=False)
class ReplayContext:
    """Injected, plain data for a replay. Analysis cannot import ``settings``.

    ``period_bounds`` maps a period name (``tune``, ``report``) to inclusive naive
    ``(start, end)`` timestamps (Q-06: logged times carry no timezone).
    ``price_table`` holds a ``version`` key (``build_manifest`` records it).
    """

    period_bounds: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]]
    price_table: Mapping[str, object] | pd.DataFrame
    catalogue: Mapping[str, object] | pd.DataFrame
    seed: int
    min_n: int | None = None
    guard: CacheGuardLike | None = None


@runtime_checkable
class StepVersion(Protocol):
    """One competing version of one step.

    ``apply`` returns a copy with the same index. Cache versions set
    ``served_from_cache`` and zero every cost block on hit rows; context versions
    lower ``input_tokens`` and the input cost; routing versions set
    ``routed_model`` and reprice.
    """

    name: str
    step: Step

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame: ...


def with_blocks(req: pd.DataFrame, fee_per_call: float = FEE_PER_CALL) -> pd.DataFrame:
    """Add ``block_fees`` and ``block_token_cost`` from the recorded cost.

    Fee: ``fee_per_call`` x per-call items (none means 0). Token cost: recorded
    total minus the fee, never negative (the EDA's ``routing_finance`` proxy).
    A row without a recorded total is unknown in both blocks.
    """
    out = req.copy()
    total = out["a_bill_totalCost"]
    fees = (out["a_n_per_call_only_items"].fillna(0) * fee_per_call).where(
        total.notna()
    )
    out[block_column("fees")] = fees
    out[block_column("token_cost")] = (total - fees).clip(lower=0)
    return out


def _llm_mask(req: pd.DataFrame) -> pd.Series:
    if "llm_request" not in req:
        raise ValueError("llm_request is missing; run the scope step (S-3) first")
    if req["llm_request"].isna().any():
        raise ValueError("llm_request has unknown rows; unknown is not False")
    return req["llm_request"].astype(bool)


def _overlay(old: pd.Series, new: pd.Series, active: pd.Series) -> pd.Series:
    """``new`` on the active rows, ``old`` elsewhere, in ``old``'s order."""
    if not active.any():
        return old
    if active.all():
        return new.reindex(old.index)
    return pd.concat([old[~active], new]).reindex(old.index)


def _apply_on_rows(
    frame: pd.DataFrame, version: StepVersion, active: pd.Series, ctx: ReplayContext
) -> pd.DataFrame:
    sub = frame.loc[active]
    result = version.apply(sub, ctx)
    if not result.index.equals(sub.index):
        raise ValueError(f"{version.name}: apply must keep the index it was given")
    out = frame.copy()
    for col in result.columns:
        if col in out:
            out[col] = _overlay(out[col], result[col], active)
        else:
            out[col] = result[col].reindex(out.index)
    return out


def combine(
    req: pd.DataFrame,
    cache: StepVersion | None,
    context: StepVersion | None,
    routing: StepVersion | None,
    ctx: ReplayContext,
) -> pd.DataFrame:
    """Apply cache, then context, then routing. ``None`` skips a step.

    Versions only ever see LLM rows. Context and routing also skip rows served
    from cache, so a hit keeps exactly the cost the cache left (zero blocks) and
    no later saving is counted on it. Workflow rows (``llm_request`` False)
    change nothing. Returns a copy with ``req``'s index and order, plus
    ``served_from_cache`` and any column a version adds (NaN for rows it skipped).
    """
    llm = _llm_mask(req)
    out = req.copy()
    if "served_from_cache" not in out:
        out["served_from_cache"] = False
    for version, step in ((cache, "cache"), (context, "context"), (routing, "routing")):
        if version is None:
            continue
        if version.step != step:
            raise ValueError(f"{version.name} is a {version.step} version, not {step}")
        active = llm & ~out["served_from_cache"].astype(bool)
        out = _apply_on_rows(out, version, active, ctx)
        out["served_from_cache"] = out["served_from_cache"].fillna(False).astype(bool)
    return out


def _decimal(value: float) -> Decimal:
    """Fixed nine-decimal Decimal (and no negative zero), so JSON is stable."""
    return Decimal(f"{value + 0.0:.9f}")


def _slice(
    before: pd.DataFrame, after: pd.DataFrame, in_slice: pd.Series, hits: pd.Series
) -> dict[str, Decimal]:
    llm = _llm_mask(before)
    cols = [block_column(b) for b in BLOCKS]
    known = in_slice & llm & before[cols].notna().all(axis=1)
    if after.loc[known, cols].isna().any().any():
        raise ValueError("a version made a known cost unknown; unknown is not zero")
    out: dict[str, Decimal] = {
        "n_requests": Decimal(int(in_slice.sum())),
        "n_cost_known": Decimal(int(known.sum())),
        "n_cache_hits": Decimal(int((in_slice & llm & hits).sum())),
    }
    if out["n_requests"]:
        out["cache_hit_rate"] = _decimal(
            float(out["n_cache_hits"]) / float(out["n_requests"])
        )
    base_total = after_total = 0.0
    for block, col in zip(BLOCKS, cols, strict=True):
        b = math.fsum(before.loc[known, col].to_numpy(dtype=float))
        a = math.fsum(after.loc[known, col].to_numpy(dtype=float))
        out[f"baseline:{block}"], out[f"saving:{block}"] = _decimal(b), _decimal(b - a)
        base_total, after_total = base_total + b, after_total + a
    out["baseline:total"] = _decimal(base_total)
    out["saving:total"] = _decimal(base_total - after_total)
    if base_total > 0:
        out["saving_share"] = _decimal((base_total - after_total) / base_total)
    return out


def summarise_slices(
    before: pd.DataFrame, after: pd.DataFrame
) -> dict[str, dict[str, Decimal]]:
    """The ``all`` and ``llm_only`` slices of a lever result (every rate twice).

    ``all`` counts every row in ``n_requests`` (the denominator of rates over all
    requests); ``llm_only`` counts LLM rows only. Both sum cost, savings and hits
    over LLM rows with a known cost, so workflow rows add nothing to either and are
    never zero-filled. ``n_cost_known`` shows how many rows had a known cost.
    """
    if not before.index.equals(after.index):
        raise ValueError("before and after must share an index")
    hits = (
        after["served_from_cache"].astype(bool)
        if "served_from_cache" in after
        else pd.Series(False, index=after.index)
    )
    everyone = pd.Series(True, index=before.index)
    return {
        "all": _slice(before, after, everyone, hits),
        "llm_only": _slice(before, after, _llm_mask(before), hits),
    }
