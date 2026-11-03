"""R-B3 kNN router: nearest-profile policy (final plan R-B3, "Routing without
quality labels"; FR-ROUTE-03, FR-ROUTE-05, H-1; Review Focus 2 and 3; ADR-0036).

For one request: take the ``k`` nearest **training** profiles (never the
request's own session or duplicate family), collect the models those requests
ran on, keep the routing candidates that the injected ``eligible_models``
allows for this request, and choose the cheapest of them by the price table.
Keep the incumbent if none is strictly cheaper, if fewer than ``k`` neighbours
exist, or if the request's bot has fewer than ``min_n`` training rows. Never
route upward. No quality label is used: this is a **cost simulation; quality
not proven**.

Profile features (known before the model is chosen; the README says why each
column is in or out): ``NUMERIC`` as ``log1p`` plus a one-hot user language.
Scaling (median fill, mean, standard deviation) comes from the training rows
only. Distance: Euclidean on the scaled profile. Ties: lower training position
first (training rows sorted by index). Neighbours may come from any bot
(``CROSS_BOT``): within one bot every request ran the bot's one model.

**Per-baseline accounting** (``baseline_frames``, outside ``apply``; ADR-0046
points 5 and 6, as R-A3 ``exp-route-001`` and R-C3; owner decision for Pipeline
B, 2026-11-03): ``apply`` is the ``todays_models`` decision and records each
request's target (the cheapest eligible candidate its neighbours ran, cheaper
or not). In each baseline the incumbent is that baseline's model (the logged
model for ``todays_models`` and ``as_logged``, the premium model, the best single
cheap model); a request moves only if the target is another model and strictly
cheaper in that baseline's units, so every saving is the router's own effect and
is >= 0 row by row. ``as_logged`` prices the target at implied recorded rates
(``implied_cost``, the ADR-0038 pattern); a needed rate that is missing makes the
saving unknown (the row leaves both sides), never 0; rows not moved save exactly
0; fees never change. Candidates the catalogue marks
``hidden_reasoning_billed_as_output`` are left out of the primary result
(ADR-0046 point 4, ``primary_candidates``).

Layer: candidate code in ``experiments/``, loaded by file path; pure over
injected frames. ``eligible_models`` is a constructor argument, never imported.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import (
    model_row_costs,
    repriced_row_costs,
    token_counts,
)
from metis_auto.analysis.levers import BLOCKS, block_column
from metis_auto.analysis.replay_scope import bot_sufficiency
from metis_auto.analysis.resumable import cached_blocks

NUMERIC = (
    "n_prior_msgs",
    "prior_chars",
    "a_rag_n_chunks",
    "a_rag_chunk_chars",
    "u_att_n",
    "u_n_chars",
)
LANGS = (
    "fa",
    "fa_en_mixed",
    "short_uncertain",
    "arabic_script_other",
    "en",
    "structured",
    "other",
)
FEATURES = NUMERIC + tuple(f"lang:{x}" for x in LANGS) + ("lang:missing",)
CROSS_BOT = True
"""Neighbours may come from other bots (and from the request's own bot)."""

ASSUMPTIONS = (
    "cost simulation; quality not proven",
    "no quality label: nearest-profile policy over logged models only",
    "token counts assumed model-independent; logged output length unchanged",
    "fees and recorded cost blocks unchanged (lookup fee is not on the price list)",
    "recorded blocks (fees, token_cost) unchanged by apply; each baseline is "
    "accounted in its own units (ADR-0036)",
)
LEVER = "rb3.knn-router"
LEVER_WITH_REASONING = "rb3.knn-router.with_reasoning_models"
VERSION = "route.knn"
VERSION_WITH_REASONING = "route.knn.with_reasoning_models"
REASONING_CAPABILITY = "hidden_reasoning_billed_as_output"
WITH_REASONING_LABEL = "lower bound on candidate cost, hidden reasoning not counted"
BASELINES = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")
CANDIDATE = "route_candidate"
MOVED_B = "route_moved_in_baseline"
SAVING_UNKNOWN = "route_saving_unknown"

BLOCK_QUERIES = 20_000
"""Queries per stored block of the neighbour search (resume granularity)."""

REASONS = (
    "moved",
    "no_cheaper_candidate",
    "no_eligible_candidate",
    "too_few_neighbours",
    "insufficient_bot",
    "incumbent_unpriced",
    "unknown_tokens",
)

EligibleModels = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    tuple[str, ...],
]
"""``eligible_models(row, catalogue, prices, rules)``, the plan's R-0 shape."""


def _records(table: Any, key: str) -> list[Mapping[str, Any]]:
    if isinstance(table, pd.DataFrame):
        return table.to_dict("records")
    return list(table.get(key, []))


def reasoning_billed(catalogue: Any) -> frozenset[str]:
    """Models whose catalogue entry has ``REASONING_CAPABILITY`` (ADR-0046 point 4)."""
    out = set()
    for m in _records(catalogue, "models"):
        names = {str(c.get("name")) for c in m.get("capabilities") or []}
        if REASONING_CAPABILITY in names:
            out.add(str(m["model_id"]))
    return frozenset(out)


def primary_candidates(candidates: Sequence[str], catalogue: Any) -> tuple[str, ...]:
    """``candidates`` without the reasoning-billed ones, in order."""
    hidden = reasoning_billed(catalogue)
    return tuple(c for c in candidates if c not in hidden)


def implied_cost(
    tokens: pd.DataFrame, model: pd.Series, rates: Mapping[str, Mapping[str, float]]
) -> pd.Series:
    """Recorded-unit cost of each row on ``model`` at its implied rates per 1M
    tokens (``input``, ``cached``, ``output``). A rate is needed only for a token
    part above 0; a needed rate that is missing gives NaN (unknown). The rule of
    R-A3's ``implied_cost`` (ADR-0038 pattern, ADR-0046 point 5)."""
    out = pd.Series(np.nan, index=tokens.index)
    uncached = tokens["input"] - tokens["cached"]
    for m in pd.unique(model.dropna()):
        rows = model.eq(m)
        r = rates.get(str(m), {})
        total = pd.Series(0.0, index=tokens.index)[rows]
        parts = (
            (uncached, "input"),
            (tokens["cached"], "cached"),
            (tokens["output"], "output"),
        )
        for part, key in parts:
            rate = r.get(key)
            rate = np.nan if rate is None else float(rate)
            value = part[rows]
            total = total + (value * rate).where(value.ne(0), 0.0).where(value.notna())
        out[rows] = total / 1e6
    return out


def baseline_frames(
    req: pd.DataFrame,
    out: pd.DataFrame,
    ctx: Any,
    *,
    baseline: str,
    premium_model: str,
    cheap_model: str,
    cached_separately: frozenset[str],
    rates: Mapping[str, Mapping[str, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Before and after cost blocks of one baseline (ADR-0046 points 5 and 6).

    ``out`` is ``apply``'s frame. A request is a candidate (``CANDIDATE``) if it
    has a priced target; it moves (``MOVED_B``) only if the target is another
    model than the baseline's and strictly cheaper in this baseline's units.
    ``as_logged``: recorded blocks, the target at ``implied_cost``; an unknown
    target cost removes the row from both sides (``SAVING_UNKNOWN``). Repriced:
    list prices; ``block_fees`` is 0 on both sides only so the blocks sum (the
    result drops the fee key)."""
    llm = req["llm_request"].astype(bool)
    before = req[["llm_request"]].copy()
    after = before.copy()
    fee_col, tok_col = (block_column(b) for b in BLOCKS)
    target = out["route_target"].reindex(req.index)
    tcost = out["route_target_cost"].reindex(req.index)
    candidate = (llm & target.notna() & tcost.notna()).astype(bool)
    if baseline == "as_logged":
        tokens = token_counts(req, cached_separately)
        cost = implied_cost(tokens, target.where(candidate), rates)
        recorded = req[tok_col]
        unknown = candidate & cost.isna() & recorded.notna()
        moved = (
            candidate & cost.lt(recorded) & target.ne(req["bot_provider_model"])
        ).astype(bool)
        before[fee_col] = req[fee_col].where(~unknown)
        after[fee_col] = req[fee_col].where(~unknown)
        before[tok_col] = recorded.where(~unknown)
        after[tok_col] = recorded.where(~moved, cost).where(~unknown)
    elif baseline in ("premium_gpt_5_5", "todays_models", "best_single_cheap"):
        inc = repriced_row_costs(
            req,
            ctx,
            premium_model=premium_model,
            cached_separately=cached_separately,
            cheap_model=cheap_model,
        )[baseline]
        inc_model = {
            "todays_models": req["bot_provider_model"],
            "premium_gpt_5_5": pd.Series(premium_model, index=req.index),
            "best_single_cheap": pd.Series(cheap_model, index=req.index),
        }[baseline]
        moved = (candidate & tcost.lt(inc) & target.ne(inc_model)).astype(bool)
        unknown = pd.Series(False, index=req.index)
        zero = (inc * 0.0).where(inc.notna())
        before[fee_col], after[fee_col] = zero, zero
        before[tok_col] = inc
        after[tok_col] = inc.where(~moved, tcost)
    else:
        raise ValueError(f"unknown baseline {baseline}")
    after[CANDIDATE] = candidate & llm
    after[MOVED_B] = moved & llm
    after[SAVING_UNKNOWN] = unknown & llm
    return before, after


def family_key(req: pd.DataFrame) -> pd.Series:
    """Duplicate family ``(bot_id, u_h_norm)`` as in ``replay_scope``; None
    without user text (such a row has no family)."""
    key = req["bot_id"].astype(str) + "\x1f" + req["u_h_norm"].astype(str)
    return key.where(req["u_h_norm"].notna(), None)


def profile_matrix(req: pd.DataFrame) -> np.ndarray:
    """Raw profile per row (``FEATURES`` order). Numbers are ``log1p`` of the
    logged value; missing stays NaN, except chunk characters on a row without
    chunks, which are 0."""
    cols = []
    for name in NUMERIC:
        x = req[name].astype(float)
        if name == "a_rag_chunk_chars":
            x = x.where(~(req["a_rag_n_chunks"].fillna(0).eq(0) & x.isna()), 0.0)
        cols.append(np.log1p(x.clip(lower=0).to_numpy()))
    lang = req["u_lang"]
    for value in LANGS:
        cols.append(lang.eq(value).fillna(False).to_numpy(dtype=float))
    cols.append((~lang.isin(LANGS)).to_numpy(dtype=float))
    return np.column_stack(cols)


@dataclass(frozen=True, eq=False)
class Scaler:
    """Median fill, then ``(x - center) / scale``; fitted on training rows."""

    median: np.ndarray
    center: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, raw: np.ndarray) -> Scaler:
        median = np.array(
            [np.nanmedian(c) if np.isfinite(c).any() else 0.0 for c in raw.T]
        )
        filled = np.where(np.isnan(raw), median, raw)
        center = filled.mean(axis=0)
        scale = filled.std(axis=0)
        return cls(median, center, np.where(scale > 0, scale, 1.0))

    def fill(self, raw: np.ndarray) -> np.ndarray:
        return np.where(np.isnan(raw), self.median, raw)

    def transform(self, raw: np.ndarray) -> np.ndarray:
        return (self.fill(raw) - self.center) / self.scale


def nearest(
    train_x: np.ndarray,
    query_x: np.ndarray,
    *,
    k: int,
    train_groups: tuple[np.ndarray, np.ndarray],
    query_groups: tuple[np.ndarray, np.ndarray],
    chunk: int = 128,
) -> np.ndarray:
    """Indices of the ``k`` nearest training rows per query, nearest first.

    ``*_groups`` are (session code, family code); a training row with the
    query's session, or with its family (code >= 0), is never a neighbour.
    Ties go to the lower training position. Missing slots are -1. Distances
    are float32 (speed on 200k training rows): two neighbours closer than
    float32 rounding are ordered by that rounding, the same way every run.
    """
    n_train = len(train_x)
    out = np.full((len(query_x), k), -1, dtype=np.int64)
    kk = min(k, n_train)
    if kk == 0:
        return out
    banned_rows = _rows_by_code(*train_groups)
    train_x = np.ascontiguousarray(train_x, dtype=np.float32)
    query_x = np.asarray(query_x, dtype=np.float32)
    tn = (train_x**2).sum(axis=1)
    for start in range(0, len(query_x), chunk):
        q = query_x[start : start + chunk]
        d = q @ train_x.T
        d *= -2.0
        d += tn[None, :]
        d += (q**2).sum(axis=1)[:, None]
        np.maximum(d, 0.0, out=d)
        for r in range(len(q)):
            sess = query_groups[0][start + r]
            fam = query_groups[1][start + r]
            d[r, banned_rows[0].get(sess, _EMPTY)] = np.inf
            if fam >= 0:
                d[r, banned_rows[1].get(fam, _EMPTY)] = np.inf
        threshold = np.partition(d, kk - 1, axis=1)[:, kk - 1]
        rows_b, cols_b = np.nonzero(d < threshold[:, None])
        tied = d == threshold[:, None]
        tied[~np.isfinite(threshold)] = False
        rows_t, cols_t = np.nonzero(tied)
        need = kk - np.bincount(rows_b, minlength=len(q))
        rank = np.arange(len(rows_t)) - np.searchsorted(rows_t, rows_t, side="left")
        keep = rank < need[rows_t]
        rows = np.concatenate([rows_b, rows_t[keep]])
        cols = np.concatenate([cols_b, cols_t[keep]])
        order = np.lexsort((cols, d[rows, cols], rows))
        rows, cols = rows[order], cols[order]
        slot = np.arange(len(rows)) - np.searchsorted(rows, rows, side="left")
        out[start + rows, slot] = cols
    return out


_EMPTY = np.empty(0, dtype=np.int64)


def _rows_by_code(*codes: np.ndarray) -> tuple[dict[int, np.ndarray], ...]:
    """Training positions per session code and per family code (code >= 0)."""
    out = []
    for c in codes:
        c = np.asarray(c)
        valid = np.flatnonzero(c >= 0)
        order = valid[np.argsort(c[valid], kind="stable")]
        keys, first = np.unique(c[order], return_index=True)
        parts = np.split(order, first[1:]) if len(keys) else []
        out.append(dict(zip(keys.tolist(), parts, strict=True)))
    return tuple(out)


def effective_tokens(
    req: pd.DataFrame, cached_separately: frozenset[str]
) -> pd.DataFrame:
    """Effective input, cached (capped at input) and output tokens:
    ``baselines_full.token_counts`` (cached tokens added back for the logged
    models that report them outside the input count), as floats."""
    return token_counts(req, cached_separately).astype(float)


def candidate_costs(
    req: pd.DataFrame,
    models: Sequence[str],
    ctx: Any,
    cached_separately: frozenset[str],
) -> pd.DataFrame:
    """Per-row cost of each model in price-file units (NaN: unpriced model or one
    the catalogue does not describe, unknown tokens or a workflow row):
    ``baselines_full.model_row_costs``, before eligibility (the router applies
    the injected ``eligible_models``). Used to *order* models; reported totals
    go through ``baselines_full.baseline_costs`` (tested equal)."""
    known = {str(m["model_id"]) for m in ctx.catalogue["models"]}
    tokens = token_counts(req, cached_separately)
    out = pd.DataFrame(index=req.index)
    for model in models:
        out[model] = (
            model_row_costs(
                req, ctx, model, cached_separately=cached_separately, tokens=tokens
            )
            if model in known
            else np.nan
        )
    return out


class KnnRouter:
    """Nearest-profile routing version (``StepVersion``-shaped, step ``routing``).

    ``train`` is the fitting frame (``split_by_session == "tune"`` rows). The
    columns it adds: ``routed_model``, ``route_reason`` (one of ``REASONS``),
    ``route_support`` (share of the ``k`` neighbours that ran the routed
    model), ``route_target`` and ``route_target_cost`` (the cheapest eligible
    candidate the neighbours ran, cheaper than the incumbent or not, for
    ``baseline_frames``), ``route_cost_incumbent`` and ``route_cost_routed``
    (price-file units). Recorded cost blocks are left as they are.
    """

    step = "routing"

    def __init__(
        self,
        *,
        k: int,
        train: pd.DataFrame,
        candidates: Sequence[str],
        eligible_models: EligibleModels,
        rules: Mapping[str, Any],
        cached_separately: frozenset[str] = frozenset(),
        label_source: str | None = None,
        chunk: int = 128,
        neighbours: Any = None,
        progress: Callable[[int], Any] | None = None,
    ) -> None:
        """``neighbours``: an optional ``analysis.resumable.NeighbourCache``;
        the nearest-neighbour search is then done in blocks of queries that are
        stored and reused (resume, and the second candidate list of one run).
        ``progress(n_queries)`` returns a ``Progress`` for one search. Neither
        changes a result."""
        if label_source is not None:
            raise ValueError(
                f"supervised use blocked: label source {label_source!r} is not a "
                "benchmark label with provenance and a disjoint evaluation set"
            )
        if k < 1:
            raise ValueError("k must be at least 1")
        self.name = f"route.knn.k{k}"
        self.k = k
        self.label_source = label_source
        self.candidates = tuple(candidates)
        self.eligible_models = eligible_models
        # As R-A3: the constructor's candidates replace rules["candidates"] and
        # rules["candidates_jev"] is dropped, so R-0 sees exactly this list.
        self.rules = {k: v for k, v in rules.items() if k != "candidates_jev"} | {
            "candidates": list(self.candidates)
        }
        self.cached_separately = cached_separately
        self.chunk = chunk
        self.neighbours = neighbours
        self.progress = progress
        train = train.sort_index(kind="stable")
        raw = profile_matrix(train)
        self.scaler = Scaler.fit(raw)
        self._x = self.scaler.transform(raw)
        self._models = train["bot_provider_model"].astype(str).to_numpy()
        self._session = train["session_id"].astype(str).to_numpy()
        self._family = family_key(train).to_numpy(dtype=object)
        self._train = train[["bot_id"]]

    def _codes(self, q_session: np.ndarray, q_family: np.ndarray):
        sess, _ = pd.factorize(np.concatenate([self._session, q_session]))
        fam_all = pd.Series(np.concatenate([self._family, q_family]), dtype=object)
        fam, _ = pd.factorize(fam_all, use_na_sentinel=True)
        n = len(self._session)
        return (sess[:n], fam[:n]), (sess[n:], fam[n:])

    def apply(self, req: pd.DataFrame, ctx: Any) -> pd.DataFrame:
        return self.apply_many(req, ctx, (self.k,))[self.k]

    def apply_many(
        self, req: pd.DataFrame, ctx: Any, ks: Sequence[int]
    ) -> dict[int, pd.DataFrame]:
        """``apply`` for every ``k`` in ``ks`` (each at most ``self.k``) from one
        neighbour search: the nearest ``k`` are a prefix of the nearest
        ``self.k`` under the same tie rule."""
        if any(k < 1 or k > self.k for k in ks):
            raise ValueError(f"every k must be in 1..{self.k}")
        incumbent = req["bot_provider_model"].astype(str)
        models = sorted(set(self.candidates) | set(incumbent))
        costs = candidate_costs(req, models, ctx, self.cached_separately)
        cost_arr = costs.to_numpy()
        col = {m: i for i, m in enumerate(costs.columns)}
        inc_cost = cost_arr[np.arange(len(req)), [col[m] for m in incumbent]]
        tok = effective_tokens(req, self.cached_separately)

        base = np.full(len(req), "", dtype=object)
        base[(tok["input"].isna() | tok["output"].isna()).to_numpy()] = "unknown_tokens"
        base[(base == "") & np.isnan(inc_cost)] = "incumbent_unpriced"
        if ctx.min_n is not None:
            status = bot_sufficiency(self._train, ctx.min_n)
            ok = req["bot_id"].map(status).eq("sufficient").to_numpy()
            base[(base == "") & ~ok] = "insufficient_bot"
        active = np.flatnonzero(base == "")
        idx = np.empty((0, self.k), dtype=np.int64)
        allowed: dict[int, set[str]] = {}
        if len(active):
            q = req.iloc[active]
            tgroups, qgroups = self._codes(
                q["session_id"].astype(str).to_numpy(),
                family_key(q).to_numpy(dtype=object),
            )
            qx = self.scaler.transform(profile_matrix(q))
            if self.neighbours is None:
                idx = nearest(
                    self._x,
                    qx,
                    k=self.k,
                    train_groups=tgroups,
                    query_groups=qgroups,
                    chunk=self.chunk,
                )
            else:
                idx = self._cached_nearest(qx, tgroups, qgroups)
        cand = set(self.candidates)
        out: dict[int, pd.DataFrame] = {}
        for k in ks:
            reason = base.copy()
            routed = incumbent.to_numpy(dtype=object).copy()
            routed_cost = np.where(reason == "unknown_tokens", np.nan, inc_cost)
            support = np.full(len(req), np.nan)
            target = np.full(len(req), None, dtype=object)
            target_cost = np.full(len(req), np.nan)
            for j, i in enumerate(active):
                neigh = idx[j, :k]
                if (neigh < 0).any():
                    reason[i] = "too_few_neighbours"
                    continue
                ran = self._models[neigh]
                seen = sorted(set(ran) & cand)
                if seen:
                    if i not in allowed:
                        allowed[i] = set(self._eligible(req, tok, incumbent, i, ctx))
                    seen = [m for m in seen if m in allowed[i]]
                priced = [(cost_arr[i, col[m]], m) for m in seen]
                priced = [(c, m) for c, m in priced if not np.isnan(c)]
                if not priced:
                    reason[i] = "no_eligible_candidate"
                    continue
                best_cost, best = min(priced)
                target[i], target_cost[i] = best, best_cost
                if best_cost < inc_cost[i]:
                    reason[i] = "moved"
                    routed[i] = best
                    routed_cost[i] = best_cost
                    support[i] = float(np.mean(ran == best))
                else:
                    reason[i] = "no_cheaper_candidate"
            frame = req.copy()
            frame["routed_model"] = routed
            frame["route_reason"] = reason
            frame["route_support"] = support
            frame["route_target"] = target
            frame["route_target_cost"] = target_cost
            frame["route_cost_incumbent"] = inc_cost
            frame["route_cost_routed"] = routed_cost
            out[k] = frame
        return out

    def _cached_nearest(self, qx, tgroups, qgroups) -> np.ndarray:
        """``nearest`` in blocks of queries through the neighbour cache. The
        cache key hashes the training matrix and groups, the whole query set
        and ``k``, so only an identical search is ever reused."""
        digest = hashlib.sha256()
        for part in (self._x, *tgroups, qx, *qgroups):
            digest.update(np.ascontiguousarray(part).tobytes())
        key = digest.hexdigest()

        def compute(a: int, b: int) -> np.ndarray:
            return nearest(
                self._x,
                qx[a:b],
                k=self.k,
                train_groups=tgroups,
                query_groups=(qgroups[0][a:b], qgroups[1][a:b]),
                chunk=self.chunk,
            )

        return cached_blocks(
            self.neighbours,
            key,
            len(qx),
            BLOCK_QUERIES,
            compute,
            k=self.k,
            progress=self.progress(len(qx)) if self.progress else None,
        )

    def _eligible(self, req, tok, incumbent, i, ctx) -> tuple[str, ...]:
        row = req.iloc[i]
        return self.eligible_models(
            {
                "input_tokens": float(tok["input"].iloc[i]),
                "output_tokens": float(tok["output"].iloc[i]),
                "u_att_n": row.get("u_att_n"),
                "bot_n_functions": row.get("bot_n_functions"),
                "bot_provider_model": incumbent.iloc[i],
            },
            ctx.catalogue,
            ctx.price_table,
            self.rules,
        )
