"""R-B3 run helpers: session- and family-grouped folds, nested cross-validation
of ``k`` inside the tune split, and one ``LeverResult`` per baseline from the
version's ``baseline_frames`` (final plan R-B3; FR-ROUTE-03, QA-REPRO;
ADR-0032, ADR-0036, ADR-0046 points 4 to 6 as R-A3 and R-C3). Pure over frames;
``scripts/run_pipeline_b_day3.py`` does the file IO and passes the ``sprint.toml``
settings.

Units (ADR-0036): each baseline is accounted in its own units with its own model
as the incumbent. Repriced baselines in price-file units (``baseline_cost`` has no
fees key); ``as_logged`` in recorded units, the target at implied recorded rates.
Every slice of a result is in that result's units.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CRITERION = (
    "least aggressive: the grid k with the lowest share of requests moved in "
    "the inner folds (ties: smaller k); saving is never the criterion"
)
OVER_TOKENS = 8000
TOP_TENANTS = 5
TOP_BOTS = 10
POINT_6 = (
    "Per baseline, the incumbent is that baseline's model for the request (logged "
    "model for todays_models and as_logged, the premium model, the best single "
    "cheap model) and 'cheaper' is tested in that baseline's units.",
    "So each saving is the router's own effect and is >= 0 row by row; follows "
    "ADR-0046 point 6, confirmed for Pipeline B by the owner 2026-11-03 (Q-B21).",
)


def _sibling(name: str) -> Any:
    key = f"metis_exp_route_011_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


version = _sibling("version")
family_key = version.family_key


def component_folds(req: pd.DataFrame, *, n_folds: int, seed: int) -> pd.Series:
    """Fold per row. Sessions joined by a shared duplicate family form one
    component, and a component never spans two folds, so no fold shares a
    session or a family with another. Seeded per component (order-free)."""
    sess, _ = pd.factorize(req["session_id"].astype(str))
    fam, _ = pd.factorize(family_key(req), use_na_sentinel=True)
    has = fam >= 0
    comp = sess.copy()
    while True:
        new = comp.copy()
        new[has] = pd.Series(comp[has]).groupby(fam[has]).transform("min").to_numpy()
        new = pd.Series(new).groupby(sess).transform("min").to_numpy()
        if np.array_equal(new, comp):
            break
        comp = new
    rep = (
        pd.Series(req["session_id"].astype(str).to_numpy())
        .groupby(comp)
        .transform("min")
    )
    fold = {
        r: int.from_bytes(
            hashlib.blake2b(f"{seed}\x1f{r}".encode(), digest_size=8).digest(), "big"
        )
        % n_folds
        for r in rep.unique()
    }
    return pd.Series(rep.map(fold).to_numpy(), index=req.index, name="fold")


def least_aggressive(moved_share: Mapping[int, float]) -> int:
    """The declared criterion (``CRITERION``)."""
    return min(moved_share, key=lambda k: (moved_share[k], k))


def nested_cv(
    req: pd.DataFrame,
    grid: Sequence[int],
    ctx: Any,
    factory: Callable[[pd.DataFrame, int], Any],
    *,
    outer: int,
    inner: int,
    seed: int,
) -> dict[str, Any]:
    """Session/family-grouped nested CV inside ``req`` (the tune split).

    Inner folds of each outer training part choose ``k`` by ``CRITERION``; the
    outer fold is then decided by a router fitted on the outer training part
    for every grid ``k`` (out-of-fold decisions, ``oof``). ``factory(train, k)``
    builds a router fitted (scaling included) on ``train`` only.
    """
    kmax = max(grid)
    folds = component_folds(req, n_folds=outer, seed=seed)
    oof_parts: dict[int, list[pd.DataFrame]] = {k: [] for k in grid}
    fits: list[dict[str, Any]] = []
    chosen: dict[int, int] = {}
    inner_share: dict[int, dict[int, float]] = {}
    for f in range(outer):
        train, test = req[folds != f], req[folds == f]
        ifolds = component_folds(train, n_folds=inner, seed=seed + 1 + f)
        moved = dict.fromkeys(grid, 0)
        scored = 0
        for g in range(inner):
            itrain, itest = train[ifolds != g], train[ifolds == g]
            if itrain.empty or itest.empty:
                continue
            res = factory(itrain, kmax).apply_many(itest, ctx, grid)
            fits.append(
                {
                    "level": "inner",
                    "outer": f,
                    "fit": itrain.index,
                    "scored": itest.index,
                }
            )
            scored += len(itest)
            for k in grid:
                moved[k] += int((res[k]["route_reason"] == "moved").sum())
        inner_share[f] = {k: moved[k] / scored if scored else 0.0 for k in grid}
        chosen[f] = least_aggressive(inner_share[f])
        if train.empty or test.empty:
            continue
        res = factory(train, kmax).apply_many(test, ctx, grid)
        fits.append(
            {"level": "outer", "outer": f, "fit": train.index, "scored": test.index}
        )
        for k in grid:
            oof_parts[k].append(res[k])
    oof = {
        k: pd.concat(parts).reindex(req.index)
        if parts
        else req.iloc[:0].reindex(req.index)
        for k, parts in oof_parts.items()
    }
    return {
        "oof": oof,
        "chosen_k": chosen,
        "inner_moved_share": inner_share,
        "fold_sizes": {
            int(f): int(n) for f, n in folds.value_counts().sort_index().items()
        },
        "fits": fits,
    }


def _dec(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


def _label(value: object) -> str:
    text = "missing" if value is None or pd.isna(value) else str(value).lower()
    return "".join(c if c.isalnum() or c in "_.-" else "_" for c in text)


def bot_ranks(after: pd.DataFrame) -> pd.Series:
    """Rank per ``bot_id`` (1 = largest ``todays_models`` cost over the routed LLM
    rows; unknown cost last; ties by more requests, then a stable order). R-A3's
    rule."""
    rows = after[after["route_reason"].notna()]
    g = rows.groupby(rows["bot_id"].astype(str), sort=True)
    stats = pd.DataFrame(
        {"cost": g["route_cost_incumbent"].sum(min_count=1), "n": g.size()}
    )
    stats = stats.sort_values(
        ["cost", "n"], ascending=[False, False], na_position="last", kind="stable"
    )
    return pd.Series(np.arange(1, len(stats) + 1), index=stats.index)


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
    after: pd.DataFrame, b_after: pd.DataFrame, saving: pd.Series
) -> dict[str, Decimal]:
    """Counts only: the apply reasons and moves (the ``todays_models`` decision),
    the requests moved and unknown in this baseline, saving by target model."""
    llm = after["llm_request"].astype(bool)
    n = int(llm.sum())
    reason = after.loc[llm, "route_reason"]
    moved = reason.eq("moved")
    switched = b_after["route_moved_in_baseline"].astype(bool)
    out = {
        "n_requests_routed": Decimal(n),
        "n_moved": Decimal(int(moved.sum())),
        "n_candidates_in_baseline": Decimal(int(b_after["route_candidate"].sum())),
        "n_switched_in_baseline": Decimal(int(switched.sum())),
        "n_saving_unknown": Decimal(int(b_after["route_saving_unknown"].sum())),
    }
    if n:
        out["moved_share"] = _dec(moved.sum() / n)
        out["switched_share_llm"] = _dec(switched.sum() / n)
    for r, c in reason.value_counts().sort_index().items():
        out[f"reason:{r}"] = Decimal(int(c))
    routed = after.loc[llm, "routed_model"]
    for m, c in routed[moved].value_counts().sort_index().items():
        out[f"moved_to:{_label(m)}"] = Decimal(int(c))
    if moved.any():
        support = after.loc[llm, "route_support"][moved]
        out["support_median"] = _dec(float(support.median()))
    by_target = saving[switched].groupby(after.loc[switched, "route_target"]).sum()
    for m, value in by_target.sort_index().items():
        out[f"saving_by_target:{_label(m)}"] = _dec(float(value))
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
        "scored rows (cost only)",
    }[key]
    return (
        f"Unit: price-file units ({key}). Fees are not priced, so baseline_cost has "
        f"no fees key (ADR-0036). Incumbent: {model}.",
    )


def baseline_saving(
    after: pd.DataFrame,
    key: str,
    ctx: Any,
    *,
    premium_model: str,
    cheap_model: str,
    cached_separately: frozenset[str],
    rates: Mapping[str, Mapping[str, float | None]],
) -> dict[str, Any]:
    """Totals of one baseline over the LLM rows of ``after`` (``apply`` output):
    baseline, saving, share, cost-known rows, rows moved in this baseline."""
    before, b_after = version.baseline_frames(
        after,
        after,
        ctx,
        baseline=key,
        premium_model=premium_model,
        cheap_model=cheap_model,
        cached_separately=cached_separately,
        rates=rates,
    )
    cols = ["block_fees", "block_token_cost"]
    base = before[cols].sum(axis=1, min_count=2)
    saving = base - b_after[cols].sum(axis=1, min_count=2)
    known = after["llm_request"].astype(bool) & base.notna()
    out = _block(base, saving, known, int(after["llm_request"].astype(bool).sum()))
    out["n_switched_in_baseline"] = Decimal(int(b_after[version.MOVED_B].sum()))
    return out


def lever_results_json(
    after: pd.DataFrame,
    req_all: pd.DataFrame,
    *,
    k: int,
    split: str,
    with_reasoning: bool,
    ctx: Any,
    premium_model: str,
    cheap_model: str,
    cached_separately: frozenset[str],
    rates: Mapping[str, Mapping[str, float | None]],
    code_commit: str,
    python_version: str,
    created_at: datetime,
    extra_assumptions: Sequence[str] = (),
    config_extra: Mapping[str, object] | None = None,
    tenant_cap: float = 0.35,
    rates_version: str = "full-eda-implied-unit-rates",
) -> dict[str, str]:
    """``LeverResult`` JSON per baseline key for the decisions in ``after`` (LLM
    rows of the scored split, with the recorded blocks); ``req_all`` is every
    scored row (its length is the ``all`` denominator). The slices of R-A3's
    results, each baseline in its own units (ADR-0046 points 5 and 6)."""
    import dataclasses

    from metis_auto.analysis.lever_result import LeverResult, build_manifest
    from metis_auto.analysis.replay_scope import cap_tenant_share
    from metis_auto.analysis.stats import cluster_bootstrap_ratio

    lever = version.LEVER_WITH_REASONING if with_reasoning else version.LEVER
    label = version.VERSION_WITH_REASONING if with_reasoning else version.VERSION
    llm = after["llm_request"].astype(bool)
    effective = version.effective_tokens(after, cached_separately)["input"]
    over = effective.gt(OVER_TOKENS) & llm
    ranks = bot_ranks(after)
    bot_rank = after["bot_id"].astype(str).map(ranks)
    users = after.loc[llm, "user_id"].astype(object).fillna("unknown")
    tenant_order = users.value_counts(sort=True).index[:TOP_TENANTS]
    all_users = after["user_id"].astype(object).fillna("unknown")
    lang = after["u_lang"].map(_label)
    config = {
        "lever": lever,
        "k": k,
        "split": split,
        "features": list(version.FEATURES),
        "cross_bot": version.CROSS_BOT,
        "criterion": CRITERION,
        "premium_model": premium_model,
        "best_single_cheap": cheap_model,
        "tenant_cap": tenant_cap,
        **(config_extra or {}),
    }
    texts: dict[str, str] = {}
    for key in version.BASELINES:
        before, b_after = version.baseline_frames(
            after,
            after,
            ctx,
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
        slices = {
            "all": _block(base, saving, known, len(req_all)),
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
        slices["over_8k"] = _block(base, saving, known & over, int(over.sum()))
        for name in sorted(lang[llm].unique()):
            mask = lang.eq(name)
            slices[f"lang:{name}"] = _block(
                base, saving, known & mask, int((llm & mask).sum())
            )
        for rank, user in enumerate(tenant_order, start=1):
            mask = all_users.eq(user)
            n = int((llm & mask).sum())
            block = _block(base, saving, known & mask, n)
            block["share"] = _dec(n / llm.sum())
            slices[f"tenant_rank:{rank}"] = block
        for rank in range(1, min(TOP_BOTS, len(ranks)) + 1):
            mask = bot_rank.eq(rank)
            slices[f"bot_rank:{rank}"] = _block(
                base, saving, known & mask, int((llm & mask).sum())
            )
        try:
            capped = cap_tenant_share(after[known], tenant_cap, seed=ctx.seed).index
        except ValueError:  # too few tenants to cap: the slice is left out
            capped = None
        if capped is not None:
            slices[f"tenant_capped_{tenant_cap}"] = _block(
                base, saving, known & after.index.isin(capped), len(capped)
            )
        slices["routing"] = routing_slice(after, b_after, saving)
        top = slices["llm_only"]
        _, lo, hi = cluster_bootstrap_ratio(
            saving[known].to_numpy(float),
            base[known].to_numpy(float),
            after.loc[known, "session_id"].astype(str).to_numpy(),
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
            run_ctx = dataclasses.replace(ctx, price_table={"version": rates_version})
        else:
            baseline_cost = {
                "token_cost": top["baseline:total"],
                "total": top["baseline:total"],
            }
            saving_cost = {
                "token_cost": top["saving:total"],
                "total": top["saving:total"],
            }
            run_ctx = ctx
        manifest = build_manifest(
            config | {"baseline": key},
            run_ctx,
            code_commit=code_commit,
            python_version=python_version,
            created_at=created_at,
        )
        extra: tuple[str, ...] = ()
        if with_reasoning:
            extra = (
                f"{version.WITH_REASONING_LABEL} (ADR-0046 point 4): includes the "
                "candidates the catalogue marks hidden_reasoning_billed_as_output.",
            )
        result = LeverResult(
            lever_id=f"{lever}.k-{k}.{split}.{key}",
            step="routing",
            version=f"{label}.k{k}",
            n_requests=len(req_all),
            n_eligible=int(b_after[version.CANDIDATE].sum()),
            baseline=key,
            baseline_cost=baseline_cost,
            saving=saving_cost,
            ci_low=None if math.isnan(lo) else lo,
            ci_high=None if math.isnan(hi) else hi,
            slices=slices,
            evidence_class="simulation",
            correctness_state="unmeasured",
            assumptions=(
                *version.ASSUMPTIONS,
                *_baseline_note(key, premium_model, cheap_model),
                "Requests whose cost in a baseline is unknown are left out of both "
                "sides (n_cost_known), never priced at zero; workflow rows have no "
                "cost.",
                *POINT_6,
                *extra,
                *extra_assumptions,
            ),
            manifest=manifest,
        )
        texts[key] = result.to_json()
    return texts
