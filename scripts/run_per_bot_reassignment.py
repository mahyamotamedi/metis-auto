"""Run R-A3 per-bot reassignment (exp-route-001) on the full data.

Commands:

- ``run``: fit ``PerBotReassignment`` on the **tune** rows (``split_by_session``
  tune and ``period`` tune, as R-C3) with R-0 eligibility, apply it once to the
  **report** split through ``levers.combine``, and write one ``LeverResult`` per
  baseline for two candidate sets (ADR-0046 point 4):
  ``reports/levers/route.per_bot.<baseline>.json`` (the primary result: the
  ``[routing] candidates`` without those the catalogue marks
  ``hidden_reasoning_billed_as_output``) and
  ``reports/levers/route.per_bot.with_reasoning_models.<baseline>.json`` (all of
  them; "lower bound on candidate cost, hidden reasoning not counted"), plus the
  per-bot tables ``route.per_bot[.with_reasoning_models].bots.csv`` (rank labels,
  never IDs). Each baseline is accounted in its own units with its own model as
  the incumbent (ADR-0046 points 5 and 6); ``as_logged`` prices the target at
  implied recorded rates (``implied_unit_rates.csv``, the ADR-0038 pattern).
- ``eda``: reproduce the full-EDA routing simulation (``scripts/full_eda_analyze.py``
  ``routing_finance``; claims ``route.sim_save.simple_rule`` 14.2% and
  ``route.sim_save.all_billed_requests`` 41.6%) and run the same rule at each
  ``sprint.toml`` routing candidate that has an implied rate. Recorded units,
  all months, no eligibility: a hypothetical upper bound, not a lever result.

Eligibility and candidate cost: R-0, ``analysis.routing_base.eligible_models``
and ``candidate_costs`` (ADR-0045), with ``sprint.toml [routing]`` as ``rules``
(the version drops ``candidates_jev``; J-3 passes its own list).

Traces: FR-ROUTE-01, FR-ROUTE-03, FR-ROUTE-04, FR-ROUTE-05, H-5, X7, ADR-0036,
ADR-0045, ADR-0046. Usage:
``.venv\\Scripts\\python.exe scripts/run_per_bot_reassignment.py {run,eda}``.
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import platform
import sys
import tomllib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis import routing_base
from metis_auto.analysis.baselines_full import (
    best_single_cheap_model,
    cached_reported_separately,
    token_counts,
)
from metis_auto.analysis.lever_result import LeverResult, Manifest, build_manifest
from metis_auto.analysis.levers import ReplayContext, combine, with_blocks
from metis_auto.analysis.replay_scope import (
    cap_tenant_share,
    period_bounds_from_config,
    scope,
    split_by_session,
)
from metis_auto.analysis.stats import cluster_bootstrap_ratio
from metis_auto.settings import StrategySettings, StrategySlot
from metis_auto.wiring.experiments import code_version, load_candidate

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "data" / "derived" / "full_eda" / "requests.parquet"
SPRINT = ROOT / "config" / "evaluation" / "sprint.toml"
RATES = ROOT / "reports" / "full_eda" / "tables" / "implied_unit_rates.csv"
RATES_VERSION = "full-eda-implied-unit-rates"  # as R-A2's and R-C3's as_logged
EXPERIMENT_DIR = ROOT / "experiments" / "routing" / "exp-route-001-per-bot-reassignment"
OUT_DIR = ROOT / "reports" / "levers"

BASELINES = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")
OVER_TOKENS = 8000
TOP_TENANTS = 5
TOP_BOTS = 10
POINT_6 = (
    "Per baseline, the incumbent is that baseline's model for the request (logged "
    "model for todays_models and as_logged, the premium model, the best single "
    "cheap model) and 'cheaper' is tested in that baseline's units.",
    "So each saving is the router's own effect and is >= 0 row by row; follows "
    "ADR-0046 point 6, provisional; owner to confirm (Q-B21).",
)
RUN_ASSUMPTIONS = (
    "Eligibility and candidate cost: R-0 (analysis.routing_base.eligible_models "
    "and candidate_costs, ADR-0045) with sprint.toml [routing] as rules.",
    "Fitted on tune rows (split_by_session tune and period Mar-Jul 2026), applied "
    "once to the report split (sessions starting Aug-Oct 2026); timestamps are "
    "naive (Q-06).",
    "Requests whose cost in a baseline is unknown are left out of both sides "
    "(n_cost_known), never priced at zero; workflow rows have no cost.",
    "Slices: all and llm_only (every rate twice), traffic_weighted (request-"
    "weighted; bot_mean_saving_share is the unweighted mean over bots), over_8k, "
    "lang:<label>, tenant_rank:<n>, bot_rank:<n> (ranks, never IDs), the tenant-"
    "capped rows and eda_simple_rule (the EDA's rule group).",
    *POINT_6,
)
EDA_MIN_ITEMS = 10_000
"""The EDA's high-volume floor for a simulation target (billed items)."""
EDA_FEE_PER_CALL = 0.002
EDA_COLUMNS = [
    "a_billing_state",
    "a_n_token_items",
    "bot_provider_model",
    "a_bill_inputTokens",
    "a_bill_cachedInputTokens",
    "a_bill_outputTokens",
    "a_bill_totalCost",
    "a_n_per_call_only_items",
    "u_n_chars",
    "a_rag_n_chunks",
    "u_att_n",
    "a_tool_n_calls",
    "a_input_n_items",
    "a_is_json",
]


# --- loading -----------------------------------------------------------------------


def _load(directory: Path, file: str, obj: str) -> Any:
    spec = StrategySettings(
        slot=StrategySlot.CANDIDATE_INDEX,  # unused for a file; no lever slot yet
        file=file,
        object=obj,
    )
    return load_candidate(spec, directory, ROOT / "experiments")


def load_constraints() -> tuple[Callable[..., tuple[str, ...]], Callable]:
    """R-0's eligibility and candidate cost (ADR-0045)."""
    return routing_base.eligible_models, routing_base.candidate_costs


def load_version_class() -> type:
    return _load(EXPERIMENT_DIR, "version.py", "PerBotReassignment")


def _version_module(obj: Any) -> Any:
    return sys.modules[(obj if isinstance(obj, type) else type(obj)).__module__]


def load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def make_context(sprint: dict) -> ReplayContext:
    base = sprint["baselines"]
    return ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=load_toml(ROOT / base["price_table"]),
        catalogue=load_toml(ROOT / base["catalogue"]),
        seed=int(sprint["split"]["seed"]),
        min_n=sprint.get("sufficiency", {}).get("min_n"),
    )


def routing_rules(sprint: Mapping[str, Any]) -> dict[str, Any]:
    """``rules`` for R-0: ``sprint.toml [routing]`` as it is (ADR-0045)."""
    return dict(sprint["routing"])


def plain_rules(rules: Mapping[str, Any]) -> dict[str, Any]:
    """The rules a manifest hashes, in plain values only (``sprint.toml`` retiring
    tables carry dates): candidates, retiring IDs with replacements, the flag."""
    retiring = [
        {"model_id": str(r["model_id"]), "replacement": r.get("replacement")}
        if isinstance(r, Mapping)
        else {"model_id": str(r), "replacement": None}
        for r in rules.get("retiring", ())
    ]
    return {
        "candidates": [str(c) for c in rules["candidates"]],
        "retiring": retiring,
        "avoid_long_context_tier": rules.get("avoid_long_context_tier"),
    }


def load_implied_rates(path: Path = RATES) -> dict[str, dict[str, float | None]]:
    """Implied recorded-basis rates per 1M tokens per model (missing = None)."""
    table = pd.read_csv(path)

    def rate(value: Any) -> float | None:
        return None if pd.isna(value) else float(value)

    return {
        str(r["model"]): {
            "input": rate(r["implied_input_per_M"]),
            "output": rate(r["implied_output_per_M"]),
            "cached": rate(r["implied_cached_per_M"]),
        }
        for _, r in table.iterrows()
    }


# --- R-A3 results (tested) -----------------------------------------------------------


def _dec(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


def _name(label: object) -> str:
    text = "unknown" if label is None or pd.isna(label) else str(label).lower()
    clean = "".join(c if c.isalnum() or c in "_.-" else "_" for c in text)
    return clean if clean and clean[0].isalnum() else f"x{clean}"


def eda_simple_rule(req: pd.DataFrame) -> pd.Series:
    """The EDA's "short, no RAG, no attachments, no tools, no JSON" screen."""
    return (
        (req["u_n_chars"].fillna(0) <= 200)
        & (req["a_rag_n_chunks"].fillna(0) == 0)
        & (req["u_att_n"].fillna(0) == 0)
        & (req["a_tool_n_calls"].fillna(0) == 0)
        & (req["a_input_n_items"].fillna(0) == 0)
        & (~req["a_is_json"].fillna(False).astype(bool))
    )


def bot_ranks(after: pd.DataFrame) -> pd.Series:
    """Rank per ``bot_id`` (1 = largest ``todays_models`` cost over the routed LLM
    rows; unknown cost last; ties by more requests, then a stable order)."""
    rows = after[after["route_reason"].notna()]
    g = rows.groupby(rows["bot_id"].astype(str), sort=True)
    stats = pd.DataFrame(
        {"cost": g["route_cost_incumbent"].sum(min_count=1), "n": g.size()}
    )
    stats = stats.sort_values(
        ["cost", "n"], ascending=[False, False], na_position="last", kind="stable"
    )
    return pd.Series(np.arange(1, len(stats) + 1), index=stats.index)


def bot_table(after: pd.DataFrame, fitted: Any, *, top: int = TOP_BOTS) -> pd.DataFrame:
    """The per-bot candidate table: ``bot-NN`` rank labels (by ``todays_models``
    cost on the report split), incumbent, target candidate, the decision per
    baseline, ``todays_models`` cost per request before and after (price-file
    units, rows with a known cost), share of cost. No bot ID is kept."""
    ranks = bot_ranks(after)
    rows = after[after["route_reason"].notna()]
    bot = rows["bot_id"].astype(str)
    known = rows["route_cost_routed"].notna()
    g = rows.groupby(bot, sort=True)
    gk = rows[known].groupby(bot[known], sort=True)
    total = math.fsum(rows.loc[known, "route_cost_incumbent"].to_numpy(float))
    table = pd.DataFrame(
        {
            "rank": ranks,
            "n_requests": g.size(),
            "n_cost_known": gk.size(),
            "n_switched": g["route_reason"].agg(
                lambda r: int(r.eq("simulated_switch").sum())
            ),
            "cost_before": gk["route_cost_incumbent"].sum(),
            "cost_after": gk["route_cost_routed"].sum(),
        }
    ).fillna({"n_cost_known": 0})
    fit = fitted.bots.reindex(table.index)
    table["incumbent"] = fit["incumbent"].fillna(
        g["bot_provider_model"].agg(lambda m: m.astype(str).mode().iloc[0])
    )
    table["fit_reason"] = fit["reason"].fillna("unseen_bot")
    table["candidate"] = fit["target"].fillna("none")
    gates = [c for c in fitted.bots.columns if c.startswith("gate:")]
    for col in gates:
        table[f"reassigned_in:{col[5:]}"] = fit[col].fillna(False).astype(bool)
    n = table["n_cost_known"].replace(0, np.nan)
    table["cost_per_request_before"] = table["cost_before"] / n
    table["cost_per_request_after"] = table["cost_after"] / n
    table["share_of_cost"] = table["cost_before"] / total if total else np.nan
    table["quality"] = "not proven"
    table = table.sort_values("rank").head(top)
    table.insert(0, "bot_rank", [f"bot-{r:02d}" for r in table["rank"]])
    cols = [
        "bot_rank",
        "incumbent",
        "candidate",
        "fit_reason",
        *[f"reassigned_in:{c[5:]}" for c in gates],
        "n_requests",
        "n_cost_known",
        "n_switched",
        "cost_per_request_before",
        "cost_per_request_after",
        "share_of_cost",
        "quality",
    ]
    return table[cols].reset_index(drop=True)


def _block(base: pd.Series, saving: pd.Series, mask: pd.Series, n: int) -> dict:
    b = math.fsum(base[mask].to_numpy(float))
    s = math.fsum(saving[mask].to_numpy(float))
    out = {
        "n_requests": Decimal(int(n)),
        "n_cost_known": Decimal(int(mask.sum())),
        "baseline:total": _dec(b),
        "saving:total": _dec(s),
    }
    if b > 0:
        out["saving_share"] = _dec(s / b)
    return out


def routing_slice(
    after: pd.DataFrame,
    b_after: pd.DataFrame,
    saving: pd.Series,
    fitted: Any,
    baseline: str,
    why: pd.Series | None,
) -> dict[str, Decimal]:
    """Counts only: the apply reasons (``todays_models`` decision), the requests
    moved and unknown in this baseline, saving by target model, why no candidate
    is eligible (with the ``todays_models`` cost share), and the fitted bots."""
    llm = after["llm_request"].astype(bool)
    reason = after.loc[llm, "route_reason"].fillna("served_from_cache")
    switched = int(reason.eq("simulated_switch").sum())
    moved = b_after["route_moved_in_baseline"].astype(bool)
    out = {
        "n_llm_requests": Decimal(int(llm.sum())),
        "n_simulated_switch": Decimal(switched),
        "n_candidates_in_baseline": Decimal(int(b_after["route_candidate"].sum())),
        "n_switched_in_baseline": Decimal(int(moved.sum())),
        "switched_share_llm": _dec(moved.sum() / llm.sum())
        if llm.any()
        else Decimal(0),
        "switched_share_all": _dec(moved.sum() / len(after))
        if len(after)
        else Decimal(0),
        "n_saving_unknown": Decimal(int(b_after["route_saving_unknown"].sum())),
    }
    for r, c in reason.value_counts().sort_index().items():
        out[f"reason:{r}"] = Decimal(int(c))
    by_target = saving[moved].groupby(after.loc[moved, "route_target"]).sum()
    for m, s in by_target.sort_index().items():
        out[f"saving_by_target:{_name(m)}"] = _dec(float(s))
    if why is not None:
        w = why.reindex(after.index)[llm]
        cost = after.loc[llm, "route_cost_incumbent"]
        total = math.fsum(cost.dropna().to_numpy(float))
        for k, c in w.value_counts().sort_index().items():
            out[f"no_eligible:{k}"] = Decimal(int(c))
            share = math.fsum(cost[w.eq(k)].dropna().to_numpy(float))
            out[f"no_eligible_cost_share:{k}"] = (
                _dec(share / total) if total else Decimal(0)
            )
    bots = fitted.bots
    for r, c in bots["reason"].value_counts().sort_index().items():
        out[f"bots:{r}"] = Decimal(int(c))
    out["bots:fitted"] = Decimal(len(bots))
    gate = f"gate:{baseline}"
    if gate in bots:
        out["bots:reassigned_in_baseline"] = Decimal(int(bots[gate].sum()))
    return out


def _baseline_note(key: str, premium_model: str, cheap_model: str) -> tuple[str, ...]:
    if key == "as_logged":
        return (
            "Unit: recorded units (as_logged). Incumbent: the recorded token cost; "
            "the target at its implied recorded rates (reports/full_eda/tables/"
            "implied_unit_rates.csv, the ADR-0038 pattern).",
            "A needed implied rate that is missing makes the request's saving "
            "unknown (n_saving_unknown, out of both sides), never 0; requests not "
            "moved save exactly 0; fees never change.",
        )
    model = {
        "premium_gpt_5_5": f"{premium_model} (estimate only, never called, ADR-0026)",
        "todays_models": "each request's logged model",
        "best_single_cheap": f"{cheap_model}, the cheapest callable model over the "
        "report split (cost only)",
    }[key]
    return (
        f"Unit: price-file units ({key}). Fees are not priced, so baseline_cost has "
        f"no fees key (ADR-0036). Incumbent: {model}.",
    )


def lever_results(
    req: pd.DataFrame,
    after: pd.DataFrame,
    ctx: ReplayContext,
    *,
    fitted: Any,
    premium_model: str,
    cheap_model: str,
    cached_separately: frozenset[str],
    rates: Mapping[str, Mapping[str, float | None]],
    manifests: Mapping[str, Manifest],
    extra: tuple[str, ...],
    why: pd.Series | None = None,
    tenant_cap: float = 0.35,
) -> dict[str, LeverResult]:
    """One ``LeverResult`` per ``BASELINES`` key for ``after`` (``combine`` output
    on ``req``, every report row), each from the version's ``baseline_frames``."""
    module = _version_module(fitted)
    llm = after["llm_request"].astype(bool)
    effective = token_counts(after[llm], cached_separately)["input"]
    over = effective.gt(OVER_TOKENS).reindex(after.index, fill_value=False)
    ranks = bot_ranks(after)
    routed = after["route_reason"].notna()
    bot_rank = after["bot_id"].astype(str).map(ranks).where(routed)
    users = after.loc[llm, "user_id"].astype(object).fillna("unknown")
    tenant_order = users.value_counts(sort=True).index[:TOP_TENANTS]
    all_users = after["user_id"].astype(object).fillna("unknown")
    lang = after["u_lang"].map(_name)
    simple = eda_simple_rule(after) & llm
    results: dict[str, LeverResult] = {}
    for key in BASELINES:
        before, b_after = module.baseline_frames(
            req,
            after,
            ctx,
            fitted,
            baseline=key,
            premium_model=premium_model,
            cheap_model=cheap_model,
            cached_separately=cached_separately,
            rates=rates,
        )
        cols = ["block_fees", "block_token_cost"]
        base = before[cols].sum(axis=1, min_count=2)
        saving = base - b_after[cols].sum(axis=1, min_count=2)
        known = llm & base.notna()
        try:
            capped = cap_tenant_share(after[known], tenant_cap, seed=ctx.seed).index
        except ValueError:  # too few tenants to cap: the slice is left out
            capped = None
        every = pd.Series(True, index=after.index)
        slices = {
            "all": _block(base, saving, known & every, len(after)),
            "llm_only": _block(base, saving, known, int(llm.sum())),
        }
        tw = dict(slices["llm_only"])
        sums = pd.DataFrame({"b": base[known], "s": saving[known]}).groupby(
            after.loc[known, "bot_id"].astype(str)
        )
        sums = sums.sum()
        sums = sums[sums["b"] > 0]
        if len(sums):
            tw["bot_mean_saving_share"] = _dec(float((sums["s"] / sums["b"]).mean()))
        slices["traffic_weighted"] = tw
        slices["over_8k"] = _block(base, saving, known & over, int((llm & over).sum()))
        for label in sorted(lang[llm].unique()):
            mask = lang.eq(label)
            slices[f"lang:{label}"] = _block(
                base, saving, known & mask, int((llm & mask).sum())
            )
        for rank, user in enumerate(tenant_order, start=1):
            mask = all_users.eq(user)
            n = int((llm & mask).sum())
            s = _block(base, saving, known & mask, n)
            s["share"] = _dec(n / llm.sum())
            slices[f"tenant_rank:{rank}"] = s
        for rank in range(1, min(TOP_BOTS, len(ranks)) + 1):
            mask = bot_rank.eq(rank)
            slices[f"bot_rank:{rank}"] = _block(
                base, saving, known & mask, int(mask.sum())
            )
        if capped is not None:
            slices[f"tenant_capped_{tenant_cap}"] = _block(
                base, saving, known & after.index.isin(capped), len(capped)
            )
        rule = _block(base, saving, known & simple, int(simple.sum()))
        total = float(slices["llm_only"]["baseline:total"])
        if total > 0:
            rule["saving_share_of_all"] = _dec(float(rule["saving:total"]) / total)
        slices["eda_simple_rule"] = rule
        slices["routing"] = routing_slice(after, b_after, saving, fitted, key, why)
        top = slices["llm_only"]
        sessions = after.loc[known, "session_id"].astype(str).to_numpy()
        _, lo, hi = cluster_bootstrap_ratio(
            saving[known].to_numpy(float),
            base[known].to_numpy(float),
            sessions,
            seed=ctx.seed,
        )
        if key == "as_logged":
            fees = math.fsum(before.loc[known, "block_fees"].to_numpy(float))
            token = math.fsum(before.loc[known, "block_token_cost"].to_numpy(float))
            baseline_cost = {
                "fees": _dec(fees),
                "token_cost": _dec(token),
                "total": top["baseline:total"],
            }
            saving_cost = {
                "fees": Decimal(0),
                "token_cost": top["saving:total"],
                "total": top["saving:total"],
            }
        else:
            baseline_cost = {
                "token_cost": top["baseline:total"],
                "total": top["baseline:total"],
            }
            saving_cost = {
                "token_cost": top["saving:total"],
                "total": top["saving:total"],
            }
        results[key] = LeverResult(
            lever_id=fitted.name,
            step="routing",
            version=fitted.version,
            n_requests=len(after),
            n_eligible=int(b_after["route_candidate"].sum()),
            baseline=key,
            baseline_cost=baseline_cost,
            saving=saving_cost,
            ci_low=None if math.isnan(lo) else lo,
            ci_high=None if math.isnan(hi) else hi,
            slices=slices,
            evidence_class="simulation",
            correctness_state="unmeasured",
            assumptions=tuple(module.ASSUMPTIONS)
            + _baseline_note(key, premium_model, cheap_model)
            + RUN_ASSUMPTIONS
            + extra,
            manifest=manifests[key],
        )
    return results


# --- EDA reproduction (tested) -------------------------------------------------------


def eda_target(rates: pd.DataFrame) -> pd.Series:
    """The EDA's target: among models with at least ``EDA_MIN_ITEMS`` billed items,
    the lowest nominal 90/10 input/output blend of implied rates."""
    big = rates[rates["items"] >= EDA_MIN_ITEMS].copy()
    big["blend"] = big["implied_input_per_M"] * 0.9 + big["implied_output_per_M"] * 0.1
    return big.sort_values("blend", kind="stable").iloc[0]


def eda_simulation(
    req: pd.DataFrame,
    rates: pd.DataFrame,
    *,
    target: pd.Series | None = None,
    cached_separately: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """The EDA's same-basis routing simulation, re-implemented (not imported).

    Population: billed requests (``a_billing_state == "items"`` and at least one
    token item), all months. Input is the EDA frame's effective input: cached
    tokens added back for ``cached_separately`` (``full_eda_analyze``
    ``_cached_convention``, the rule of ``baselines_full.cached_reported_separately``).
    Every request at ``target``'s implied recorded rates (cached tokens capped at
    that input; no cached rate means the input rate); saving per row = recorded
    token cost (total less 0.002 per per-call item) less that, clipped at 0;
    shares are of the recorded total cost (fees included)."""
    if target is None:
        target = eda_target(rates)
    model = str(target["model"]) if "model" in target else str(target.name)
    b = req[(req["a_billing_state"] == "items") & (req["a_n_token_items"] >= 1)]
    recorded = float(b["a_bill_totalCost"].sum())
    add = b["bot_provider_model"].isin(cached_separately)
    inp = (
        b["a_bill_inputTokens"] + b["a_bill_cachedInputTokens"].fillna(0).where(add, 0)
    ).fillna(0)
    cached = np.minimum(b["a_bill_cachedInputTokens"].fillna(0), inp)
    cached_rate = (
        target["implied_cached_per_M"]
        if pd.notna(target["implied_cached_per_M"])
        else target["implied_input_per_M"]
    )
    new = (
        (inp - cached) * target["implied_input_per_M"]
        + cached * cached_rate
        + b["a_bill_outputTokens"].fillna(0) * target["implied_output_per_M"]
    ) / 1e6
    token_cost = (
        b["a_bill_totalCost"]
        - EDA_FEE_PER_CALL * b["a_n_per_call_only_items"].fillna(0)
    ).clip(lower=0)
    save = (token_cost - new).clip(lower=0)
    simple = eda_simple_rule(b)
    n_simple = int(simple.sum())
    on_target = int((b.loc[simple, "bot_provider_model"] == model).sum())
    return {
        "target": model,
        "n_billed": len(b),
        "recorded_cost": recorded,
        "n_simple_rule": n_simple,
        "simple_rule_share": n_simple / len(b) if len(b) else float("nan"),
        "save_simple_rule": float(save[simple].sum()),
        "share_simple_rule": float(save[simple].sum()) / recorded,
        "save_all_billed": float(save.sum()),
        "share_all_billed": float(save.sum()) / recorded,
        "simple_rule_already_on_target": on_target / n_simple if n_simple else 0.0,
    }


def run_eda(sprint: Mapping[str, Any]) -> pd.DataFrame:
    req = pd.read_parquet(REQUESTS, columns=EDA_COLUMNS)
    rates = pd.read_csv(RATES)
    sep = cached_reported_separately(req)
    rows = [
        eda_simulation(req, rates, cached_separately=sep)
        | {"run": "EDA target (reproduction)"}
    ]
    by_model = rates.set_index("model")
    for model in sprint["routing"]["candidates"]:
        if model in by_model.index:
            target = by_model.loc[model].rename(model)
            rows.append(
                eda_simulation(req, rates, target=target, cached_separately=sep)
                | {"run": "sprint candidate, same EDA rule"}
            )
        else:
            rows.append({"run": "sprint candidate, no implied rate", "target": model})
    return pd.DataFrame(rows)


# --- main ----------------------------------------------------------------------------


def tune_rows(req: pd.DataFrame, ctx: ReplayContext) -> pd.DataFrame:
    """Fit rows: tune split and tune period (as R-C3)."""
    split = split_by_session(req, seed=ctx.seed)
    return req[split.eq("tune") & req["period"].eq("tune")]


def fit_version(
    sprint: Mapping[str, Any],
    tune: pd.DataFrame,
    ctx: ReplayContext,
    cached_separately: frozenset[str],
    *,
    with_reasoning: bool = False,
    premium_model: str | None = None,
    cheap_model: str | None = None,
    rates: Mapping[str, Mapping[str, float | None]] | None = None,
) -> Any:
    """``PerBotReassignment`` with R-0, fitted on ``tune``. Primary candidates:
    ``[routing] candidates`` without the reasoning-billed ones (ADR-0046 point 4);
    ``with_reasoning`` keeps them (lever ``route.per_bot.with_reasoning_models``)."""
    cls = load_version_class()
    module = _version_module(cls)
    constraints, costs = load_constraints()
    rules = routing_rules(sprint)
    candidates = list(rules["candidates"])
    if not with_reasoning:
        candidates = list(module.primary_candidates(candidates, ctx.catalogue))
    version = cls(
        candidates,
        constraints=constraints,
        rules=rules,
        cached_separately=cached_separately,
        costs=costs,
        name=module.LEVER_WITH_REASONING if with_reasoning else module.LEVER,
    )
    return version.fit(
        tune, ctx, premium_model=premium_model, cheap_model=cheap_model, rates=rates
    )


def candidate_status(ctx: ReplayContext, rules: Mapping[str, Any]) -> pd.DataFrame:
    """Catalogue facts per candidate (enabled, priced, limits known)."""
    refs = {str(p["price_ref"]) for p in ctx.price_table["prices"]}
    entries = {str(m["model_id"]): m for m in ctx.catalogue["models"]}
    rows = []
    for model in rules["candidates"]:
        m = entries.get(model, {})
        rows.append(
            {
                "candidate": model,
                "in_catalogue": bool(m),
                "enabled": bool(m.get("enabled", False)),
                "priced": str(m.get("price_ref")) in refs,
                "limits_known": m.get("context_window") is not None
                and m.get("max_output_tokens") is not None,
            }
        )
    return pd.DataFrame(rows)


def run(sprint: Mapping[str, Any], out_dir: Path) -> None:
    ctx = make_context(sprint)
    commit_info = code_version(ROOT)
    commit = commit_info.commit or "unknown"
    req = with_blocks(scope(pd.read_parquet(REQUESTS), ctx))
    split = split_by_session(req, seed=ctx.seed)
    tune = tune_rows(req, ctx)
    report = req[split.eq("report")]
    llm = report["llm_request"].astype(bool)
    print(f"tune rows (split and period): {len(tune):,}")
    print(f"report split: {len(report):,} requests, {int(llm.sum()):,} LLM")
    cached_sep = cached_reported_separately(req)
    premium = sprint["baselines"]["premium_model"]
    cheap = best_single_cheap_model(report, ctx, cached_separately=cached_sep)
    rates = load_implied_rates()
    rules = routing_rules(sprint)
    print(candidate_status(ctx, rules).to_string(index=False))
    out_dir.mkdir(parents=True, exist_ok=True)
    tenant_cap = float(sprint["sample"]["tenant_cap"])
    for with_reasoning in (False, True):
        fitted = fit_version(
            sprint,
            tune,
            ctx,
            cached_sep,
            with_reasoning=with_reasoning,
            premium_model=premium,
            cheap_model=cheap,
            rates=rates,
        )
        module = _version_module(fitted)
        print(f"\n=== {fitted.name}: candidates {list(fitted.candidates)} ===")
        print(fitted.bots["reason"].value_counts().to_string())
        after = combine(report, None, None, fitted, ctx)  # report split, read once
        why = module.no_eligible_why(
            report[llm], ctx, fitted.constraints, fitted.rules, cached_sep
        )
        created = datetime.now(UTC)
        config = {
            "lever": fitted.name,
            "version": fitted.version,
            "candidates": list(fitted.candidates),
            "rules": plain_rules(fitted.rules),
            "constraints": "analysis.routing_base (R-0, ADR-0045)",
            "fit_rows": "split_by_session tune and period tune, LLM",
            "eval_rows": "split_by_session report, LLM",
            "min_n": ctx.min_n,
            "premium_model": premium,
            "best_single_cheap": cheap,
            "price_table": sprint["baselines"]["price_table"],
            "catalogue": sprint["baselines"]["catalogue"],
            "implied_rates": str(RATES.relative_to(ROOT).as_posix()),
            "tenant_cap": tenant_cap,
        }
        manifests = {}
        for key in BASELINES:
            run_ctx = (
                dataclasses.replace(ctx, price_table={"version": RATES_VERSION})
                if key == "as_logged"
                else ctx
            )
            manifests[key] = build_manifest(
                config | {"baseline": key},
                run_ctx,
                code_commit=commit,
                python_version=platform.python_version(),
                created_at=created,
            )
        extra: tuple[str, ...] = ()
        if with_reasoning:
            extra += (
                f"{module.WITH_REASONING_LABEL} (ADR-0046 point 4): includes the "
                "candidates the catalogue marks hidden_reasoning_billed_as_output.",
            )
        else:
            hidden = sorted(
                module.reasoning_billed(ctx.catalogue) & set(rules["candidates"])
            )
            extra += (
                "Candidates the catalogue marks hidden_reasoning_billed_as_output are "
                f"excluded (ADR-0046 point 4): {', '.join(hidden)}.",
            )
        if commit_info.dirty:
            extra += ("The working tree had uncommitted changes when this ran.",)
        results = lever_results(
            report,
            after,
            ctx,
            fitted=fitted,
            premium_model=premium,
            cheap_model=cheap,
            cached_separately=cached_sep,
            rates=rates,
            manifests=manifests,
            extra=extra,
            why=why,
            tenant_cap=tenant_cap,
        )
        for key, r in results.items():
            path = out_dir / f"{r.lever_id}.{key}.json"
            path.write_text(r.to_json(), encoding="utf-8")
            s = r.slices["llm_only"]
            routing = r.slices["routing"]
            print(
                f"  {key:18s} cost known {int(s['n_cost_known']):,}/"
                f"{int(s['n_requests']):,}; unknown {routing['n_saving_unknown']}; "
                f"switched {routing['n_switched_in_baseline']}; baseline "
                f"{r.baseline_cost['total']}; saving {r.saving['total']}; share "
                f"{s.get('saving_share')}; CI {r.ci_low} to {r.ci_high}"
            )
        table = bot_table(after, fitted)
        table.to_csv(
            out_dir / f"{fitted.name}.bots.csv", index=False, float_format="%.9g"
        )
        print(f"\nper-bot table (top {TOP_BOTS} by todays_models cost):")
        with pd.option_context("display.width", 260, "display.max_columns", 30):
            print(table.to_string(index=False))
        print("\nrouting slice, todays_models (counts):")
        for k, val in results["todays_models"].slices["routing"].items():
            print(f"  {k:48s} {val}")
        print(f"cheap model {cheap}; premium {premium}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["run", "eda"])
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="result folder")
    args = parser.parse_args(argv)
    sprint = load_toml(SPRINT)
    if args.command == "run":
        run(sprint, args.out)
    elif args.command == "eda":
        table = run_eda(sprint)
        cols = [
            "run",
            "target",
            "n_billed",
            "recorded_cost",
            "simple_rule_share",
            "share_simple_rule",
            "share_all_billed",
            "simple_rule_already_on_target",
        ]
        with pd.option_context("display.width", 200):
            print(table[[c for c in cols if c in table]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
