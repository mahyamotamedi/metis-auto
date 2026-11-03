"""R-A3 per-bot reassignment + rules (final plan R-A3, "Routing without quality
labels"; FR-ROUTE-01, FR-ROUTE-03, FR-ROUTE-05, H-5, X7; Review Focus 1 and 3;
ADR-0036, ADR-0045, ADR-0046).

**Fit** (tune rows): per bot, the *target* is the cheapest candidate that R-0
allows for **every** priced tune request of the bot (cost summed over those
requests, price-file units). The bot's decision is then made separately in each
baseline (ADR-0046 point 6, provisional): the bot is reassigned in a baseline
only if the target's cost over its tune requests is strictly lower than that
baseline's own model there (``todays_models``: the logged model; the premium
model; the best single cheap model; ``as_logged``: the recorded token cost
against the target at its implied recorded rates). ``bots`` keeps one
``gate:<baseline>`` column per baseline. A bot below ``ctx.min_n`` tune requests
(``replay_scope.bot_sufficiency``), a bot whose incumbent has no price and a bot
without an eligible candidate get no target. No quality label exists: a **cost
simulation; quality not proven**, and no bot is declared moved.

**Apply** (LLM rows only, through ``levers.combine``) is the ``todays_models``
decision: a request of a reassigned bot is switched only if the target is
eligible for it and strictly cheaper on it (never upward, row by row). Columns
added: ``routed_model``, ``route_reason`` (``ROW_REASONS``), ``route_target``,
``route_target_cost`` (the target's cost where eligible), ``route_cost_incumbent``
and ``route_cost_routed`` (price-file units). The recorded blocks are never
changed (ADR-0036).

**Accounting** (``baseline_frames``, outside ``apply``): before and after blocks of
one baseline. A request moves in a baseline if its bot is reassigned there, the
target is eligible and strictly cheaper than that baseline's model on that
request, in that baseline's units. So each saving is the router's own effect and
is >= 0 row by row. ``as_logged`` prices the target at implied recorded rates
(``implied_cost``, the ADR-0038 pattern); a needed rate that is missing makes the
saving unknown (the row leaves both sides), never 0; rows not moved save exactly
0; fees never change.

Eligibility and candidate cost come from R-0 (``routing_base.eligible_models`` as
``constraints``, ``routing_base.candidate_costs`` as ``costs``), injected; without
``costs`` the version asks ``constraints`` row by row and prices with
``baselines_full``. Repricing adds cached tokens back for the logged models that
report them separately (``token_counts``). Token counts are assumed
model-independent. Unknown is never zero.

Layer: candidate code in ``experiments/``, loaded by file path; pure over
injected frames.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
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

LEVER = "route.per_bot"
LEVER_WITH_REASONING = "route.per_bot.with_reasoning_models"
VERSION = "route.per_bot.v2"
REASONING_CAPABILITY = "hidden_reasoning_billed_as_output"

ASSUMPTIONS = (
    "quality not proven; cost simulation only",
    "no quality label: per bot, the cheapest candidate eligible for all of its "
    "tune traffic, chosen by repriced cost only; no bot is declared moved",
    "token counts assumed model-independent (tokenizers differ); logged output "
    "length unchanged",
    "recorded blocks (fees, token_cost) unchanged by apply; each baseline is "
    "accounted in its own units (ADR-0036)",
)
WITH_REASONING_LABEL = "lower bound on candidate cost, hidden reasoning not counted"

BASELINES = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")
BOT_REASONS = (
    "chosen",
    "no_cheaper_candidate",
    "no_eligible_candidate",
    "insufficient_bot",
    "incumbent_unpriced",
)
ROW_REASONS = (
    "simulated_switch",
    "no_cheaper_candidate",
    "no_eligible_candidate",
    "insufficient_bot",
    "incumbent_unpriced",
    "unknown_tokens",
    "unseen_bot",
    "row_not_eligible",
    "row_not_cheaper",
)
WHY = (
    "attachment",
    "functions",
    "attachment_and_functions",
    "context_or_output_limit",
    "no_callable_candidate",
)
"""Why a request has no eligible candidate (``no_eligible_why``)."""

CANDIDATE = "route_candidate"
MOVED_B = "route_moved_in_baseline"
SAVING_UNKNOWN = "route_saving_unknown"

Constraints = Callable[
    [Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    tuple[str, ...],
]
"""``eligible_models(row, catalogue, prices, rules)``, the plan's R-0 shape."""
Costs = Callable[..., pd.DataFrame]
"""``candidate_costs(req, ctx, candidates, *, rules, cached_separately)`` (R-0)."""

_TOKENS = ("input", "cached", "output")


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


def priced_models(ctx: Any) -> frozenset[str]:
    """Catalogue models whose ``price_ref`` is in the price table."""
    refs = {str(p["price_ref"]) for p in _records(ctx.price_table, "prices")}
    return frozenset(
        str(m["model_id"])
        for m in _records(ctx.catalogue, "models")
        if str(m["price_ref"]) in refs
    )


def cost_at(req: pd.DataFrame, tokens: pd.DataFrame, model: str, ctx: Any) -> pd.Series:
    """Token cost of every row at ``model`` (price-file units, the tier chosen by
    the effective input); NaN for an unpriced model, a workflow row or unknown
    tokens. ``baselines_full.model_row_costs``: the rule of ``repriced_row_costs``
    for one model (tested equal)."""
    if model not in priced_models(ctx):
        return pd.Series(np.nan, index=req.index)
    return model_row_costs(
        req, ctx, model, cached_separately=frozenset(), tokens=tokens
    )


def incumbent_cost(req: pd.DataFrame, tokens: pd.DataFrame, ctx: Any) -> pd.Series:
    """Token cost of every row at its logged model (``todays_models``)."""
    out = pd.Series(np.nan, index=req.index)
    model = req["bot_provider_model"].astype(str)
    for m, rows in req.groupby(model, sort=True).groups.items():
        out[rows] = cost_at(req.loc[rows], tokens.loc[rows], m, ctx)
    return out


def implied_cost(
    tokens: pd.DataFrame, model: pd.Series, rates: Mapping[str, Mapping[str, float]]
) -> pd.Series:
    """Recorded-unit cost of each row on ``model`` at its implied rates per 1M
    tokens (``input``, ``cached``, ``output``). A rate is needed only for a token
    part above 0; a needed rate that is missing gives NaN (unknown)."""
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


def _row(req: pd.DataFrame, tokens: pd.DataFrame, i: int) -> dict[str, Any]:
    """The ``row`` mapping ``constraints`` receives (R-0's keys)."""
    r = req.iloc[i]
    return {
        "input_tokens": float(tokens["input"].iloc[i]),
        "output_tokens": float(tokens["output"].iloc[i]),
        "u_att_n": r.get("u_att_n"),
        "bot_n_functions": r.get("bot_n_functions"),
        "bot_provider_model": str(r["bot_provider_model"]),
    }


def no_eligible_why(
    req: pd.DataFrame,
    ctx: Any,
    constraints: Constraints,
    rules: Mapping[str, Any],
    cached_separately: frozenset[str] = frozenset(),
) -> pd.Series:
    """Per row, why ``constraints`` allow no candidate (``WHY``), found by asking
    ``constraints`` again with one cause removed (no rule is copied here); NaN
    where a candidate is allowed or the tokens are unknown. Checked in order:
    attachment, functions, both, then the context or output limit (tokens 0);
    what remains is a catalogue cause (disabled, unpriced, retiring or an
    unknown limit)."""
    tokens = token_counts(req, cached_separately)
    known = tokens[list(_TOKENS)].notna().all(axis=1).to_numpy()
    out = pd.Series(np.nan, index=req.index, dtype=object)

    def allows(row: Mapping[str, Any]) -> bool:
        return bool(constraints(row, ctx.catalogue, ctx.price_table, rules))

    for i in np.flatnonzero(known):
        row = _row(req, tokens, i)
        if allows(row):
            continue
        clear = dict(row, u_att_n=0.0, bot_n_functions=0.0)
        if allows(dict(row, u_att_n=0.0)):
            why = "attachment"
        elif allows(dict(row, bot_n_functions=0.0)):
            why = "functions"
        elif allows(clear):
            why = "attachment_and_functions"
        elif allows(dict(clear, input_tokens=0.0, output_tokens=0.0)):
            why = "context_or_output_limit"
        else:
            why = "no_callable_candidate"
        out.iloc[i] = why
    return out


class PerBotReassignment:
    """Per-bot reassignment (``StepVersion``-shaped, step ``routing``).

    ``candidates`` stay a constructor argument (J-3 passes the JEV list); they
    replace ``rules["candidates"]``, and ``rules["candidates_jev"]`` is dropped, so
    R-0's ``candidate_list`` sees exactly this list. ``fit`` returns a fitted
    copy; ``bots`` is its per-bot table (index ``bot_id``, never written out):
    ``n_tune``, ``n_priced``, ``incumbent`` (most common logged model), ``reason``
    (``BOT_REASONS``, the ``todays_models`` decision), ``target``, ``chosen``
    (the target where reassigned in ``todays_models``), ``cost_incumbent`` and
    ``cost_chosen`` (tune sums of the logged model and the target, price-file
    units) and one ``gate:<baseline>`` per baseline fitted.
    """

    step = "routing"
    evidence_class = "simulation"

    def __init__(
        self,
        candidates: Sequence[str],
        *,
        constraints: Constraints,
        rules: Mapping[str, Any],
        cached_separately: frozenset[str] = frozenset(),
        costs: Costs | None = None,
        name: str = LEVER,
    ) -> None:
        self.candidates = tuple(candidates)
        self.constraints = constraints
        self.costs = costs
        self.rules = {k: v for k, v in rules.items() if k != "candidates_jev"} | {
            "candidates": list(self.candidates)
        }
        self.cached_separately = frozenset(cached_separately)
        self.name = name
        self.version = VERSION
        self.bots: pd.DataFrame | None = None

    def _copy(self) -> PerBotReassignment:
        return PerBotReassignment(
            self.candidates,
            constraints=self.constraints,
            rules=self.rules,
            cached_separately=self.cached_separately,
            costs=self.costs,
            name=self.name,
        )

    def candidate_costs(
        self,
        req: pd.DataFrame,
        tokens: pd.DataFrame,
        ctx: Any,
        models: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """Per-row price-file cost of each of ``models`` (default: every
        candidate), NaN where not eligible."""
        models = list(self.candidates if models is None else models)
        if self.costs is not None:
            return self.costs(
                req,
                ctx,
                models,
                rules=self.rules,
                cached_separately=self.cached_separately,
            )[models]
        out = pd.DataFrame({m: cost_at(req, tokens, m, ctx) for m in models})
        known = tokens[list(_TOKENS)].notna().all(axis=1).to_numpy()
        for i in np.flatnonzero(known):
            allowed = set(
                self.constraints(
                    _row(req, tokens, i), ctx.catalogue, ctx.price_table, self.rules
                )
            )
            for m in models:
                if m not in allowed:
                    out.iat[i, out.columns.get_loc(m)] = np.nan
        return out

    def fit(
        self,
        tune: pd.DataFrame,
        ctx: Any,
        *,
        premium_model: str | None = None,
        cheap_model: str | None = None,
        rates: Mapping[str, Mapping[str, float]] | None = None,
    ) -> PerBotReassignment:
        """A copy fitted on ``tune`` (LLM rows). ``premium_model``,
        ``cheap_model`` and ``rates`` add the gates of the other baselines."""
        rows = tune[tune["llm_request"].astype(bool)]
        tokens = token_counts(rows, self.cached_separately)
        inc = incumbent_cost(rows, tokens, ctx).to_numpy()
        priced = tokens[list(_TOKENS)].notna().all(axis=1).to_numpy() & ~np.isnan(inc)
        cand = self.candidate_costs(rows, tokens, ctx)
        cand_arr = {m: cand[m].to_numpy(dtype=float) for m in self.candidates}
        base = {
            key: cost_at(rows, tokens, model, ctx).to_numpy()
            for key, model in (
                ("premium_gpt_5_5", premium_model),
                ("best_single_cheap", cheap_model),
            )
            if model is not None
        }
        recorded = (
            rows[block_column("token_cost")].to_numpy(dtype=float)
            if rates is not None
            else None
        )
        status = bot_sufficiency(rows, ctx.min_n)
        positions = pd.Series(np.arange(len(rows))).groupby(
            rows["bot_id"].astype(str).to_numpy(), sort=True
        )
        records = []
        for bot, pos in positions:
            pos = pos.to_numpy()
            p = pos[priced[pos]]
            logged = rows["bot_provider_model"].iloc[pos].astype(str)
            rec: dict[str, Any] = {
                "bot_id": bot,
                "n_tune": len(pos),
                "n_priced": len(p),
                "incumbent": logged.mode().sort_values().iloc[0],
                "reason": None,
                "target": None,
                "chosen": None,
                "cost_incumbent": math.fsum(inc[p]) if len(p) else math.nan,
                "cost_chosen": math.nan,
            }
            if status.get(bot) != "sufficient":
                rec["reason"] = "insufficient_bot"
            elif not len(p):
                rec["reason"] = "incumbent_unpriced"
            else:
                costs = {
                    m: math.fsum(cand_arr[m][p])
                    for m in sorted(self.candidates)
                    if not np.isnan(cand_arr[m][p]).any()
                }
                if not costs:
                    rec["reason"] = "no_eligible_candidate"
                else:
                    target = min(costs, key=lambda m: (costs[m], m))
                    cost = costs[target]
                    rec |= {"target": target, "cost_chosen": cost}
                    gate = cost < rec["cost_incumbent"]
                    rec["reason"] = "chosen" if gate else "no_cheaper_candidate"
                    rec["chosen"] = target if gate else None
                    rec["gate:todays_models"] = gate
                    for key, arr in base.items():
                        rec[f"gate:{key}"] = cost < math.fsum(arr[p])
                    if recorded is not None:
                        rec["gate:as_logged"] = self._recorded_gate(
                            tokens.iloc[p], target, recorded[p], rates
                        )
            records.append(rec)
        out = self._copy()
        table = pd.DataFrame.from_records(records).set_index("bot_id")
        fitted_for = {"todays_models", *base} | (
            {"as_logged"} if rates is not None else set()
        )
        for key in BASELINES:
            col = f"gate:{key}"
            if key in fitted_for:  # bots without a target are never reassigned
                table[col] = (
                    table[col].fillna(False).astype(bool) if col in table else False
                )
        out.bots = table
        return out

    @staticmethod
    def _recorded_gate(tokens, target, recorded, rates) -> bool:
        """Target at implied rates below the recorded token cost, summed over the
        rows where both are known (none known: not reassigned)."""
        implied = implied_cost(
            tokens, pd.Series(target, index=tokens.index), rates
        ).to_numpy()
        known = ~np.isnan(implied) & ~np.isnan(recorded)
        if not known.any():
            return False
        return math.fsum(implied[known]) < math.fsum(recorded[known])

    def apply(self, req: pd.DataFrame, ctx: Any) -> pd.DataFrame:
        if self.bots is None:
            raise ValueError("fit the version on the tune split before apply")
        out = req.copy()
        tokens = token_counts(req, self.cached_separately)
        known = tokens[list(_TOKENS)].notna().all(axis=1)
        inc = incumbent_cost(req, tokens, ctx)
        bot = req["bot_id"].astype(str)
        bot_reason = bot.map(self.bots["reason"])
        target = bot.map(self.bots["target"])
        needed = sorted(set(target.dropna()))  # price only the targets present
        target_cost = pd.Series(np.nan, index=req.index)
        if needed:
            cand = self.candidate_costs(req, tokens, ctx, needed)
            for m, rows in target.dropna().groupby(target.dropna()).groups.items():
                target_cost[rows] = cand.loc[rows, m]

        reason = pd.Series("", index=req.index, dtype=object)
        reason[~known] = "unknown_tokens"
        reason[reason.eq("") & inc.isna()] = "incumbent_unpriced"
        reason[reason.eq("") & bot_reason.isna()] = "unseen_bot"
        keep = reason.eq("") & bot_reason.ne("chosen")
        reason[keep] = bot_reason[keep]
        open_ = reason.eq("")
        reason[open_ & target_cost.isna()] = "row_not_eligible"
        reason[open_ & target_cost.notna() & ~target_cost.lt(inc)] = "row_not_cheaper"
        switch = open_ & target_cost.lt(inc)
        reason[switch] = "simulated_switch"
        out["routed_model"] = (
            req["bot_provider_model"].astype(object).where(~switch, target)
        )
        out["route_reason"] = reason
        out["route_target"] = target.astype(object)
        out["route_target_cost"] = target_cost
        out["route_cost_incumbent"] = inc
        out["route_cost_routed"] = inc.where(~switch, target_cost)
        return out


def baseline_frames(
    req: pd.DataFrame,
    out: pd.DataFrame,
    ctx: Any,
    fitted: PerBotReassignment,
    *,
    baseline: str,
    premium_model: str,
    cheap_model: str,
    cached_separately: frozenset[str],
    rates: Mapping[str, Mapping[str, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Before and after cost blocks of one baseline (ADR-0046 points 5 and 6).

    The incumbent is the baseline's model for the row. A request moves
    (``MOVED_B``) only if it is a candidate (``CANDIDATE``: its bot is reassigned
    in this baseline and the target is eligible for it), the target is another
    model, and it is strictly cheaper in this baseline's units. ``as_logged``:
    recorded blocks, the target at ``implied_cost``; an unknown target cost
    removes the row from both sides (``SAVING_UNKNOWN``). Repriced: list prices;
    ``block_fees`` is 0 on both sides only so the blocks sum (the result drops the
    fee key)."""
    gate_col = f"gate:{baseline}"
    if fitted.bots is None or gate_col not in fitted.bots:
        raise ValueError(f"the version was not fitted for {baseline}")
    llm = req["llm_request"].astype(bool)
    before = req[["llm_request"]].copy()
    after = before.copy()
    fee_col, tok_col = (block_column(b) for b in BLOCKS)
    target = out["route_target"].reindex(req.index)
    tcost = out["route_target_cost"].reindex(req.index)
    gate = (
        req["bot_id"].astype(str).map(fitted.bots[gate_col]).fillna(False).astype(bool)
    )
    candidate = (llm & target.notna() & tcost.notna() & gate).astype(bool)
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
