"""Replay scope, time split, bot sufficiency and tenant cap (final plan S-3;
FR-EVAL-06, FR-EVAL-07, FR-EVAL-08, FR-REQ-04, FR-REQ-05; Review Focus 2 and 5).

Columns are the real names in ``requests.parquet`` (``a_timestamp``,
``bot_provider_name``, ``session_id``, ``bot_id``, ``u_h_norm``, ``user_id``,
``a_order``).

- ``scope`` adds ``period`` and ``llm_request``. ``period`` is ``tune``,
  ``report`` or ``unknown`` from the answer time ``a_timestamp`` and the
  inclusive bounds in ``ReplayContext.period_bounds``. A missing time, or one
  outside every period, is ``unknown``, never silently tune. Times are naive
  (Q-06): every time-based result says so. ``llm_request`` is False only for
  ``bot_provider_name == "workflow"`` (no billing; ledger
  ``model.workflow_share``). A missing provider is unknown, not False, and is
  refused, because ``levers.combine`` needs a complete column.
- ``split_by_session`` is the split for **fitting** data (thresholds,
  classifiers). Owner decision 2026-11-02: caches may look back across the
  boundary, so a cache's time window uses ``period``, not this split.
  1. A whole session takes the period of its earliest timed request
     (``a_timestamp``, then ``a_order``); a session with no time is ``unknown``.
  2. A duplicate family is ``(bot_id, u_h_norm)`` over rows with user text. A
     family with rows on both sides keeps its ``report`` rows; its ``tune``
     rows become ``excluded`` (owner decision 2026-11-02, report side keeps).
     Step 2 never relabels a ``report`` row, so the report side is exactly the
     report sessions of step 1. ``seed`` does not change the result (no ties,
     no held-out split).
  So no session and no family is on both sides. ``excluded`` rows are in
  neither side of the fit; all of them come from tune sessions, and callers
  report their count (FR-EVAL-08). Decision record:
  ADR-0036,
  ``docs/adr/0036-replay-scope-split-and-baselines.md``.
- ``bot_sufficiency``: a bot with fewer than ``min_n`` requests is
  ``insufficient``; a bot with one request always is.
- ``cap_tenant_share`` downsamples the largest tenants (``user_id``; a missing
  one is its own tenant) so that none holds more than ``max_share`` of the
  rows. Other tenants keep every row. Inside a capped tenant, whole sessions are
  kept in a seeded order, so at most one session per tenant is cut.

Layer: pure pandas over injected data. No settings, no files.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

import numpy as np
import pandas as pd

from metis_auto.analysis.levers import ReplayContext

WORKFLOW_PROVIDER = "workflow"
UNKNOWN = "unknown"
EXCLUDED = "excluded"
SIDES = ("tune", "report")
_END_OF_DAY = pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)


def period_bounds_from_config(
    periods: Mapping[str, Mapping[str, object]],
) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """``{name: {start, end}}`` with dates → inclusive naive bounds.

    A date end covers its whole day (to the last microsecond, the resolution of
    ``a_timestamp``). Overlapping periods are refused, so each time falls in at
    most one period.
    """
    bounds: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for name, p in periods.items():
        start = pd.Timestamp(str(p["start"]))
        end = pd.Timestamp(str(p["end"]))
        if end == end.normalize():
            end = end + _END_OF_DAY
        if start > end:
            raise ValueError(f"period {name}: start is after end")
        bounds[name] = (start, end)
    _check_no_overlap(bounds)
    return bounds


def _check_no_overlap(bounds: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]]):
    ordered = sorted(bounds.items(), key=lambda kv: kv[1][0])
    for (a, (_, a_end)), (b, (b_start, _)) in zip(ordered, ordered[1:], strict=False):
        if b_start <= a_end:
            raise ValueError(f"periods {a} and {b} overlap")


def scope(req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
    """A copy of ``req`` with ``period`` and ``llm_request`` added."""
    _check_no_overlap(ctx.period_bounds)
    provider = req["bot_provider_name"]
    if provider.isna().any():
        raise ValueError("bot_provider_name has unknown rows; unknown is not False")
    out = req.copy()
    ts = out["a_timestamp"]
    period = pd.Series(UNKNOWN, index=out.index, dtype=object)
    for name, (start, end) in ctx.period_bounds.items():
        period[(ts >= start) & (ts <= end)] = name
    out["period"] = period
    out["llm_request"] = (provider != WORKFLOW_PROVIDER).astype(bool)
    return out


def split_by_session(req: pd.DataFrame, *, seed: int) -> pd.Series:
    """Split label per row: ``tune``, ``report``, ``unknown`` or ``excluded``.

    Needs ``period`` (from ``scope``). See the module docstring for the rules: a
    duplicate family with rows on both sides keeps its ``report`` rows, and its
    ``tune`` rows become ``excluded``; no ``report`` row is relabelled.
    ``seed`` is checked but does not change the result (the rule has no ties);
    it stays for the plan's shared interface.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed must be an int")
    if "period" not in req:
        raise ValueError("period is missing; run scope first")
    timed = req[req["a_timestamp"].notna()]
    first = timed.sort_values(["a_timestamp", "a_order"], kind="stable")
    session_period = first.groupby("session_id", sort=False)["period"].first()
    split = req["session_id"].map(session_period).fillna(UNKNOWN).astype(object)

    on_side = split.isin(SIDES) & req["u_h_norm"].notna()
    family = _family(req.loc[on_side])
    in_report = set(family[split[on_side] == "report"])
    lose = (split[on_side] == "tune") & family.isin(in_report)
    split[lose[lose].index] = EXCLUDED
    return split.rename("split")


def _family(req: pd.DataFrame) -> pd.Series:
    return req["bot_id"].astype(str) + "\x1f" + req["u_h_norm"].astype(str)


def _unit(seed: int, key: str) -> float:
    """A uniform number in [0, 1) from (seed, key); stable across runs."""
    digest = hashlib.blake2b(f"{seed}\x1f{key}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def bot_sufficiency(req: pd.DataFrame, min_n: int | None) -> pd.Series:
    """``sufficient`` / ``insufficient`` per ``bot_id``."""
    floor = max(min_n or 0, 2)
    counts = req["bot_id"].value_counts(sort=False)
    status = counts.map(lambda n: "sufficient" if n >= floor else "insufficient")
    return status.rename("sufficiency").rename_axis("bot_id")


def cap_tenant_share(req: pd.DataFrame, max_share: float, *, seed: int) -> pd.DataFrame:
    """Rows of ``req`` such that no tenant holds more than ``max_share`` of them."""
    if not 0 < max_share <= 1:
        raise ValueError("max_share must be in (0, 1]")
    tenant = req["user_id"].astype(object).where(req["user_id"].notna(), UNKNOWN)
    counts = tenant.value_counts()
    cap = _cap(counts.to_numpy(), max_share)
    if cap == 0:
        raise ValueError(
            f"cannot cap {len(counts)} tenants at {max_share}: too few tenants"
        )
    over = counts[counts > cap].index
    if over.empty:
        return req.copy()
    keep = ~tenant.isin(over)
    for t in over:
        rows = req[tenant == t]
        session = rows["session_id"].astype(str)
        rank = {s: _unit(seed, s) for s in session.unique()}
        order = pd.DataFrame(
            {
                "s": session.map(rank),
                "o": rows["a_order"] if "a_order" in rows else 0,
            },
            index=rows.index,
        ).sort_values(["s", "o"], kind="stable")
        keep[order.index[:cap]] = True
    return req[keep].copy()


def _cap(counts: np.ndarray, max_share: float) -> int:
    """Largest per-tenant row count ``T`` with ``T <= max_share * sum(min(c, T))``.

    That condition is concave in ``T`` and holds at 0, so the feasible ``T``
    form an interval from 0 and a binary search finds its end.
    """
    lo, hi = 0, int(counts.max())
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if mid <= max_share * np.minimum(counts, mid).sum():
            lo = mid
        else:
            hi = mid - 1
    return lo
