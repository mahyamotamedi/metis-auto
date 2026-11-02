"""EXP-CTX-004: history budget with a stepped window, a context ``StepVersion``
(final plan R-C2; FR-CTX-02, FR-CTX-03, FR-ACCT-02, H-1, X4; Review Focus 1).

**History tokens** (owner decision 2026-11-02; ADR-XXXX (history-token-measure)).
What reached the provider is unknown (EDA §2), so the history actually sent is
estimated by the excess-over-turn-0 proxy (ledger ``hist.excess_over_t0_all``):
``hist_tokens = max(0, effective input - turn-0 base of the bot - chunk
tokens)``, where chunk tokens = ``a_rag_chunk_chars`` x the ledger coefficient
``recon.t0rag.coef_rag`` and the turn-0 base (``turn0_base``) is the bot's
median of (effective input - chunk tokens) over single-call turn-0 LLM rows of
the **tune** split. A bot with fewer than ``min_n`` such rows has no base, so
its rows are ``unknown`` (NaN), never 0. A multi-call request is ``multi_call``
(its input sums several calls; the ledger proxy covers single calls only).
Evidence: *hypothetical reconstruction*; it also holds the current message's
growth, so it is an **upper bound** on what a budget could remove.

**Per-turn sizes** (hypothetical). ``hist_tokens`` is spread over the
request's earlier turns of the session in proportion to their logged
characters (``u_n_chars + a_n_chars``), assuming the most recent turns are the
ones sent. A request whose earlier turns have no characters has no allocation
basis and is ``unknown``.

**Stepped window.** ``HistoryBudget(budget_tokens, step_turns)`` drops the
OLDEST whole turns, ``step_turns`` at a time, until the remaining history fits
``budget_tokens``; a request already within the budget is untouched.
``HalfOnLong(min_input_tokens, step_turns)`` does the same with a per-request
budget of half its ``hist_tokens``, only where effective input exceeds
``min_input_tokens``. No parameter has a default.

**Excluded, no saving** (``HIST_STATE``): workflow rows, turn 0, memory bots
(``bot_memory_enabled``), summarising bots (``bot_summarizer_mode ==
"AI_SUMMARIZE"``), rows the greeting gate skipped (``memo_status ==
"skipped_phatic"``, if present; ADR-0039), ``multi_call`` and ``unknown``.

**Tokens and cost.** History lies before the current message and may sit in the
provider-cached prefix. Primary rule: removed tokens come out of cached input
first, then uncached (``SAVED``, ``SAVED_CACHED``), capped at the input.
Sensitivity (upper bound on cost): uncached only, the S-6 rule
(``baselines_full.lower_uncached_input``; ``SAVED_UNCACHED_ONLY``). Once per
request. With rates, ``apply`` lowers ``block_token_cost`` by the cached part
at the model's ``implied_cached_per_M`` and the uncached part at its
``implied_input_per_M`` (``as_logged``, recorded units); a missing rate for a
part that is removed makes the saving unknown (``SAVING_KNOWN`` False), never
zero. ``block_fees`` never changes. Repriced baselines lower input and cached
and reprice (ADR-0038 item 5). Dropping old turns may break the cached prefix
for the rest of the conversation: not measured.

Candidate code: loaded by file path only (scripts, tests); ``metis_auto`` never
imports it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal

import numpy as np
import pandas as pd

from metis_auto.analysis.baselines_full import (
    REPRICED_KEYS,
    best_single_cheap_model,
    lower_uncached_input,
    repriced_row_costs,
    token_counts,
)
from metis_auto.analysis.lever_result import LeverResult, Manifest
from metis_auto.analysis.levers import (
    BLOCKS,
    ReplayContext,
    Step,
    block_column,
    summarise_slices,
)

VERSION_PREFIX = "ctx.history_budget"
EVIDENCE = "hypothetical reconstruction"
SUMMARISER_MODE = "AI_SUMMARIZE"
GATED_STATUS = "skipped_phatic"
OVER_8K_TOKENS = 8000

HIST_TOKENS = "hist_tokens"
HIST_STATE = "hist_state"
TURNS_DROPPED = "hist_turns_dropped"
REMOVED = "hist_removed_tokens"
SAVED = "hist_saved_tokens"
SAVED_CACHED = "hist_saved_cached_tokens"
SAVED_UNCACHED_ONLY = "hist_saved_tokens_uncached_only"
CUT_UNCACHED_ONLY = "hist_cut_uncached_only"
SAVING_KNOWN = "hist_saving_known"
SAVING_UNKNOWN = "hist_saving_unknown"
OVER_8K = "hist_over_8k"
STATES = (
    "known",
    "workflow",
    "turn0",
    "memory",
    "summariser",
    "gated",
    "multi_call",
    "unknown",
)


def _chunk_tokens(req: pd.DataFrame, tokens_per_char: float) -> pd.Series:
    """Chunk tokens; no logged chunk (NaN chars) is 0."""
    return req["a_rag_chunk_chars"].fillna(0).astype(float) * tokens_per_char


def turn0_base(
    req: pd.DataFrame,
    *,
    tokens_per_char: float,
    min_n: int | None,
    cached_separately: frozenset[str] = frozenset(),
) -> pd.Series:
    """Per ``bot_id``: median of (effective input - chunk tokens) over single-call
    turn-0 LLM rows with known input. Pass the **tune** split only. Bots with
    fewer than ``min_n`` such rows are left out (their history is unknown)."""
    if min_n is None:
        raise ValueError("min_n is required (sprint.toml [sufficiency] min_n)")
    eff = token_counts(req, cached_separately)["input"]
    rows = (
        req["llm_request"].astype(bool)
        & req["turn"].eq(0)
        & req["a_bill_callCount"].eq(1)
        & eff.notna()
    )
    net = (eff - _chunk_tokens(req, tokens_per_char))[rows]
    by_bot = net.groupby(req.loc[rows, "bot_id"])
    base = by_bot.median()[by_bot.size() >= min_n]
    base.index.name = "bot_id"
    return base.rename("turn0_base").astype(float)


def _check_positive_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise ValueError(f"{name} must be an int (no default), got {value!r}")
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return int(value)


class _SteppedWindow:
    """Shared rule; subclasses give the per-request budget."""

    step: Step = "context"

    def __init__(
        self,
        step_turns: int,
        *,
        turns: pd.DataFrame,
        turn0_base: Mapping[str, float] | pd.Series,
        tokens_per_char: float,
        input_rate_per_m: Mapping[str, float] | None = None,
        cached_rate_per_m: Mapping[str, float] | None = None,
        cached_separately: frozenset[str] = frozenset(),
    ) -> None:
        self.step_turns = _check_positive_int("step_turns", step_turns)
        if (input_rate_per_m is None) != (cached_rate_per_m is None):
            raise ValueError("give both input and cached rates, or neither")
        self._base = dict(turn0_base)
        self._coef = float(tokens_per_char)
        self._in_rates = input_rate_per_m
        self._cached_rates = cached_rate_per_m
        self._sep = cached_separately
        # Every logged turn of every session (all splits), oldest first.
        order = turns.sort_values(["session_id", "turn", "a_order"], kind="stable")
        chars = order["u_n_chars"].fillna(0).astype(float) + order["a_n_chars"].fillna(
            0
        ).astype(float)
        self._cum = np.concatenate([[0.0], np.cumsum(chars.to_numpy())])
        pos = np.arange(len(order))
        first = ~order["session_id"].duplicated().to_numpy()
        start = np.maximum.accumulate(np.where(first, pos, 0))
        self._pos = pd.Series(pos, index=order.index)
        self._start = pd.Series(start, index=order.index)

    def _budget(self, eff_input: pd.Series, hist: pd.Series) -> pd.Series:
        raise NotImplementedError

    def _state(self, req: pd.DataFrame, hist: pd.Series) -> pd.Series:
        state = pd.Series("known", index=req.index, dtype=object)
        rules = [
            ("unknown", hist.isna()),
            ("multi_call", ~req["a_bill_callCount"].eq(1)),
        ]
        if "memo_status" in req:
            rules.append(("gated", req["memo_status"].eq(GATED_STATUS)))
        rules += [
            ("summariser", req["bot_summarizer_mode"].eq(SUMMARISER_MODE)),
            ("memory", req["bot_memory_enabled"].fillna(False).astype(bool)),
            ("turn0", req["turn"].eq(0)),
        ]
        if "llm_request" in req:
            rules.append(("workflow", ~req["llm_request"].astype(bool)))
        for name, mask in rules:  # later rules win
            state[mask.fillna(False).to_numpy()] = name
        return state

    def _window(
        self, req: pd.DataFrame, hist: pd.Series, budget: pd.Series, act: pd.Series
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Tokens removed, whole turns dropped, and rows without an allocation."""
        removed = pd.Series(0.0, index=req.index)
        dropped = pd.Series(0, index=req.index)
        pos = self._pos.reindex(req.index)
        start = self._start.reindex(req.index)
        if pos.isna().any():
            raise ValueError("every request must be among the logged turns")
        pos, start = pos.to_numpy(int), start.to_numpy(int)
        c0 = self._cum[start]
        prior = self._cum[pos] - c0
        h, b = hist.to_numpy(float), budget.to_numpy(float)
        over = act.to_numpy() & (h > b)
        no_basis = over & (prior <= 0)
        cut = over & ~no_basis
        if cut.any():
            # Smallest m with history after dropping m oldest turns <= budget.
            keep_share = np.clip(b[cut] / h[cut], 0.0, 1.0)
            target = c0[cut] + prior[cut] * (1.0 - keep_share) - 1e-9 * prior[cut]
            m = np.searchsorted(self._cum, target, side="left") - start[cut]
            m = np.maximum(m, 1)
            m = np.ceil(m / self.step_turns).astype(int) * self.step_turns
            m = np.minimum(m, pos[cut] - start[cut])
            gone = self._cum[start[cut] + m] - c0[cut]
            removed[cut] = h[cut] * gone / prior[cut]
            dropped[cut] = m
        return removed, dropped, pd.Series(no_basis, index=req.index)

    def apply(self, req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
        out = req.copy()
        tokens = token_counts(req, self._sep)
        eff = tokens["input"]
        base = req["bot_id"].map(self._base).astype(float)
        hist = (eff - base - _chunk_tokens(req, self._coef)).clip(lower=0)
        hist = np.minimum(hist, eff).where(req["a_bill_callCount"].eq(1))
        state = self._state(req, hist)
        budget = self._budget(eff, hist)
        removed, dropped, no_basis = self._window(
            req, hist.fillna(0), budget, state.eq("known")
        )
        state[no_basis] = "unknown"
        out[HIST_TOKENS] = hist
        out[HIST_STATE] = state
        out[TURNS_DROPPED] = dropped.where(~no_basis, 0)
        out[REMOVED] = removed.where(~no_basis, 0.0)
        out[OVER_8K] = eff.gt(OVER_8K_TOKENS)
        want = out[REMOVED]
        from_cached = np.minimum(want, tokens["cached"].fillna(0))
        room = (tokens["input"] - tokens["cached"]).clip(lower=0).fillna(0)
        from_uncached = np.minimum(want - from_cached, room)
        out[SAVED_CACHED] = from_cached
        out[SAVED] = from_cached + from_uncached
        upper = lower_uncached_input(tokens.fillna(0), want)["saved"]
        out[SAVED_UNCACHED_ONLY] = upper.where(want > 0, 0.0)
        if self._in_rates is None:
            return out
        model = req["bot_provider_model"]
        in_rate = model.map(self._in_rates).astype(float)
        cached_rate = model.map(self._cached_rates).astype(float)
        part_in = (from_uncached * in_rate).where(from_uncached > 0, 0.0)
        part_cached = (from_cached * cached_rate).where(from_cached > 0, 0.0)
        cut = np.minimum((part_in + part_cached) / 1e6, out["block_token_cost"])
        out[SAVING_KNOWN] = out[SAVED].eq(0) | cut.notna()
        out["block_token_cost"] = out["block_token_cost"] - cut.where(
            out[SAVED] > 0, 0.0
        ).fillna(0.0)
        upper_cut = (out[SAVED_UNCACHED_ONLY] * in_rate / 1e6).where(
            out[SAVED_UNCACHED_ONLY] > 0, 0.0
        )
        out[CUT_UNCACHED_ONLY] = np.minimum(upper_cut, req["block_token_cost"])
        return out


class HistoryBudget(_SteppedWindow):
    """Drop the oldest whole turns, ``step_turns`` at a time, until the history
    fits ``budget_tokens``."""

    def __init__(self, budget_tokens: int, step_turns: int, **kwargs) -> None:
        self.budget_tokens = _check_positive_int("budget_tokens", budget_tokens)
        super().__init__(step_turns, **kwargs)
        suffix = "" if self.step_turns == 1 else f".s{self.step_turns}"
        self.name = f"{VERSION_PREFIX}.b{self.budget_tokens}{suffix}"

    def _budget(self, eff_input: pd.Series, hist: pd.Series) -> pd.Series:
        return pd.Series(float(self.budget_tokens), index=hist.index)


class HalfOnLong(_SteppedWindow):
    """Budget = half the request's ``hist_tokens`` where effective input exceeds
    ``min_input_tokens``; other requests are untouched."""

    def __init__(self, min_input_tokens: int, step_turns: int, **kwargs) -> None:
        self.min_input_tokens = _check_positive_int(
            "min_input_tokens", min_input_tokens
        )
        super().__init__(step_turns, **kwargs)
        n = self.min_input_tokens
        size = f"{n // 1000}k" if n % 1000 == 0 else str(n)
        suffix = "" if self.step_turns == 1 else f".s{self.step_turns}"
        self.name = f"{VERSION_PREFIX}.half_over_{size}{suffix}"

    def _budget(self, eff_input: pd.Series, hist: pd.Series) -> pd.Series:
        return (hist / 2).where(eff_input.gt(self.min_input_tokens), np.inf)


def baseline_frames(
    req: pd.DataFrame,
    out: pd.DataFrame,
    ctx: ReplayContext,
    *,
    baseline: str,
    premium_model: str,
    cached_separately: frozenset[str] = frozenset(),
    cheap_model: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Before and after cost blocks of one baseline, for ``summarise_slices``.

    As in EXP-CTX-001 (ADR-0038): ``as_logged`` uses the recorded blocks, and a
    row whose saving is unknown leaves both sides. Repriced baselines reprice
    the logged tokens and the tokens less ``SAVED`` (cached less
    ``SAVED_CACHED``), so a tier can change; ``block_fees`` is 0 on both sides
    only so the slices can be summed (``lever_result`` drops the baseline fee).
    """
    llm = req["llm_request"].astype(bool)
    before = req[["llm_request"]].copy()
    after = before.copy()
    cols = [block_column(b) for b in BLOCKS]
    if baseline == "as_logged":
        if SAVING_KNOWN not in out:
            raise ValueError("as_logged needs the rates in the version")
        unknown = ~out[SAVING_KNOWN].fillna(False).astype(bool)
        base_known = req[cols].notna().all(axis=1)
        for col in cols:
            before[col] = req[col].where(~unknown)
            after[col] = out[col].where(~unknown)
    elif baseline in REPRICED_KEYS:
        tokens = token_counts(req, cached_separately)
        if cheap_model is None:
            cheap_model = best_single_cheap_model(
                req, ctx, cached_separately=cached_separately
            )
        lowered = tokens.assign(
            input=tokens["input"] - out[SAVED],
            cached=tokens["cached"] - out[SAVED_CACHED],
        )
        costs = [
            repriced_row_costs(
                req,
                ctx,
                premium_model=premium_model,
                cached_separately=cached_separately,
                tokens=t,
                cheap_model=cheap_model,
            )[baseline]
            for t in (tokens, lowered)
        ]
        base_known = costs[0].notna()
        unknown = costs[1].isna()
        for frame, cost in zip((before, after), costs, strict=True):
            cost = cost.where(~unknown)
            frame[cols[0]] = (cost * 0.0).where(cost.notna())
            frame[cols[1]] = cost
    else:
        raise ValueError(f"unknown baseline {baseline}")
    after[SAVING_UNKNOWN] = llm & base_known & unknown
    return before, after


def _decimal(value: float) -> Decimal:
    """Fixed nine-decimal Decimal (and no negative zero), as in ``levers``."""
    return Decimal(f"{value + 0.0:.9f}")


def _fsum(values: pd.Series) -> Decimal:
    return _decimal(math.fsum(values.fillna(0).to_numpy(dtype=float)))


def concentration(out: pd.DataFrame, rows: pd.Series) -> dict[str, Decimal]:
    """Share of the saved tokens held by the top bot, the top five bots and the
    top tenant (``user_id``), as ranks only (Review Focus 5). Missing when
    nothing is saved or the column is absent."""
    saved = out.loc[rows, SAVED].fillna(0)
    total = math.fsum(saved.to_numpy(dtype=float))
    result: dict[str, Decimal] = {}
    if total <= 0:
        return result
    for column, label, top in (
        ("bot_id", "top_bot", 1),
        ("bot_id", "top5_bots", 5),
        ("user_id", "top_tenant", 1),
    ):
        if column in out:
            by = saved.groupby(out.loc[rows, column]).sum().nlargest(top)
            result[f"saved_share_{label}"] = _decimal(by.sum() / total)
    return result


def lever_result(
    before: pd.DataFrame,
    after: pd.DataFrame,
    out: pd.DataFrame,
    *,
    version_id: str,
    baseline: str,
    manifest: Manifest,
    assumptions: Sequence[str] = (),
) -> LeverResult:
    """One ``LeverResult``: slices ``all``, ``llm_only``, ``over_8k`` (LLM rows
    with effective input above 8,000) and ``history_budget`` (counts per state,
    tokens removed under both rules). Top-level blocks from ``llm_only``; the
    fee saving is always 0."""
    slices = summarise_slices(before, after)
    over = out[OVER_8K].fillna(False).astype(bool)
    slices["over_8k"] = summarise_slices(before[over], after[over])["llm_only"]
    llm = before["llm_request"].astype(bool)
    known = before[[block_column(b) for b in BLOCKS]].notna().all(axis=1) & llm
    counted = known & ~after[SAVING_UNKNOWN]
    repriced = baseline in REPRICED_KEYS
    for name, rows in (
        ("all", pd.Series(True, index=llm.index)),
        ("llm_only", llm),
        ("over_8k", llm & over),
    ):
        s = slices[name]
        s["n_saving_unknown"] = Decimal(int((rows & after[SAVING_UNKNOWN]).sum()))
        s["saved_input_tokens"] = _fsum(out.loc[rows & counted, SAVED])
        if repriced:
            del s["baseline:fees"]
    state = out[HIST_STATE].where(llm)
    hist = out[HIST_TOKENS].where(llm & state.eq("known"))
    hb: dict[str, Decimal] = {
        f"n_{s}": Decimal(int(state.eq(s).sum())) for s in STATES if s != "workflow"
    }
    hb |= {
        "n_reduced": Decimal(int((llm & out[SAVED].gt(0)).sum())),
        "hist_tokens_known": _fsum(hist),
        "removed_tokens": _fsum(out.loc[llm, REMOVED]),
        "saved_tokens": _fsum(out.loc[llm, SAVED]),
        "saved_tokens_from_cached": _fsum(out.loc[llm, SAVED_CACHED]),
        "saved_tokens_uncached_only": _fsum(out.loc[llm, SAVED_UNCACHED_ONLY]),
    }
    hb |= concentration(out, llm)
    if baseline == "as_logged" and CUT_UNCACHED_ONLY in out:
        hb["saving_token_cost_uncached_only"] = _fsum(
            out.loc[llm & counted, CUT_UNCACHED_ONLY]
        )
    slices["history_budget"] = hb
    top = slices["llm_only"]
    names = (*BLOCKS, "total")
    baseline_cost = {b: top[f"baseline:{b}"] for b in names if f"baseline:{b}" in top}
    saving = {b: top[f"saving:{b}"] for b in names}
    return LeverResult(
        lever_id=f"{version_id}.{baseline}",
        step="context",
        version=version_id,
        n_requests=len(before),
        n_eligible=int((llm & state.eq("known")).sum()),
        baseline=baseline,
        baseline_cost=baseline_cost,
        saving=saving,
        slices=slices,
        evidence_class=EVIDENCE,
        correctness_state="unmeasured",
        assumptions=tuple(assumptions),
        manifest=manifest,
    )
