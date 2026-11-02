"""R-B3 run helpers: session- and family-grouped folds, nested cross-validation
of ``k`` inside the tune split, repricing through ``baselines_full`` and one
``LeverResult`` per baseline (final plan R-B3; FR-ROUTE-03, QA-REPRO;
ADR-0032, ADR-0036). Pure over frames; ``scripts/run_pipeline_b_day3.py`` does
the file IO and passes the ``sprint.toml`` settings.

Units (ADR-0036 decisions 5 to 7): the routed cost is in price-file units, so
the saving is computed against the three repriced baselines only. Against
``as_logged`` (recorded units) it is **not computed**: ``saving`` is empty and
recorded and price-file figures are never subtracted.
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
REPRICED_KEYS = ("premium_gpt_5_5", "todays_models", "best_single_cheap")
OUT_OF_SCOPE = ("incumbent_unpriced", "unknown_tokens")


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


def _scope(after: pd.DataFrame) -> pd.Series:
    return after["llm_request"].astype(bool) & ~after["route_reason"].isin(OUT_OF_SCOPE)


def routed_baselines(
    after: pd.DataFrame,
    ctx: Any,
    *,
    premium_model: str,
    cached_separately: frozenset[str],
) -> dict[str, Any]:
    """The four baselines and the routed cost over the rows the router can
    price (``baselines_full.baseline_costs`` both times).

    Routed cost: a copy with each row's ``bot_provider_model`` set to the
    routed model and the input already effective (cached tokens added back
    for the **logged** model), priced as ``todays_models``.
    """
    from metis_auto.analysis.baselines_full import baseline_costs

    scope = _scope(after)
    sub = after[scope]
    kw = {"premium_model": premium_model}
    before = baseline_costs(sub, ctx, cached_separately=cached_separately, **kw)
    priced = sub.copy()
    priced["a_bill_inputTokens"] = version.effective_tokens(sub, cached_separately)[
        "input"
    ]
    priced["bot_provider_model"] = sub["routed_model"]
    routed = baseline_costs(priced, ctx, cached_separately=frozenset(), **kw)[
        "todays_models"
    ]
    if routed["n_known"] != before["todays_models"]["n_known"]:
        raise ValueError("a routed model has no price; the difference is void")
    saving = {
        key: {
            "token_cost": before[key]["token_cost"] - routed["token_cost"],
            "total": before[key]["total"] - routed["total"],
        }
        for key in REPRICED_KEYS
    }
    return {
        "before": before,
        "routed": routed,
        "saving": saving,
        "n_scope": int(scope.sum()),
        "n_left_out": int((~scope).sum()),
    }


def _dec(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


def row_baseline(
    after: pd.DataFrame,
    key: str,
    ctx: Any,
    *,
    premium_model: str,
    cached_separately: frozenset[str],
) -> pd.Series:
    """Per-row cost of baseline ``key`` (price-file units), for intervals and
    slices; its sum equals ``baseline_costs`` (tested)."""
    from metis_auto.analysis.baselines_full import best_single_cheap_model

    if key == "todays_models":
        return after["route_cost_incumbent"]
    if key == "premium_gpt_5_5":
        model = premium_model
    else:
        model = best_single_cheap_model(after, ctx, cached_separately=cached_separately)
    return version.candidate_costs(after, [model], ctx, cached_separately)[model]


def _label(value: object) -> str:
    text = "missing" if value is None or pd.isna(value) else str(value).lower()
    return "".join(c if c.isalnum() or c in "_.-" else "_" for c in text)


def _share_slices(
    sub: pd.DataFrame, base: pd.Series, saving: pd.Series, n_all: int
) -> dict[str, dict[str, Decimal]]:
    def block(mask: pd.Series, n: int) -> dict[str, Decimal]:
        b = math.fsum(base[mask].to_numpy(dtype=float))
        s = math.fsum(saving[mask].to_numpy(dtype=float))
        out = {
            "n_requests": Decimal(int(n)),
            "n_cost_known": Decimal(int(mask.sum())),
            "baseline:token_cost": _dec(b),
            "saving:token_cost": _dec(s),
        }
        if b > 0:
            out["saving_share"] = _dec(s / b)
        return out

    every = pd.Series(True, index=sub.index)
    slices = {"all": block(every, n_all), "llm_only": block(every, len(sub))}
    slices["traffic_weighted"] = dict(slices["all"])
    for lang, rows in sub.groupby(sub["u_lang"].map(_label), sort=True):
        slices[f"lang:{lang}"] = block(sub.index.isin(rows.index), len(rows))
    tok = version.effective_tokens(sub, frozenset())
    long = tok["input"] > 8000
    slices["over_8k"] = block(long, int(long.sum()))
    total = math.fsum(saving.to_numpy(dtype=float))
    by_tenant = saving.groupby(sub["user_id"].astype(str)).sum()
    by_tenant = by_tenant.sort_values(ascending=False, kind="stable")
    for rank, (_, value) in enumerate(by_tenant.head(5).items(), start=1):
        if total > 0:
            slices[f"tenant_rank:{rank}"] = {"share": _dec(value / total)}
    return slices


def _routing_slice(after: pd.DataFrame) -> dict[str, Decimal]:
    n = len(after)
    moved = after["route_reason"] == "moved"
    out = {
        "n_requests_routed": Decimal(n),
        "n_moved": Decimal(int(moved.sum())),
    }
    if n:
        out["moved_share"] = _dec(moved.sum() / n)
    for r, c in after["route_reason"].value_counts().sort_index().items():
        out[f"reason:{r}"] = Decimal(int(c))
    for m, c in after.loc[moved, "routed_model"].value_counts().sort_index().items():
        out[f"moved_to:{_label(m)}"] = Decimal(int(c))
    if moved.any():
        out["support_median"] = _dec(float(after.loc[moved, "route_support"].median()))
    return out


def lever_results_json(
    after: pd.DataFrame,
    req_all: pd.DataFrame,
    *,
    k: int,
    ctx: Any,
    premium_model: str,
    cached_separately: frozenset[str],
    code_commit: str,
    python_version: str,
    created_at: datetime,
    extra_assumptions: Sequence[str] = (),
    config_extra: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """``LeverResult`` JSON per baseline key for the decisions in ``after``
    (LLM rows of the scored split); ``req_all`` is every scored row (its
    length is the ``all`` denominator)."""
    from metis_auto.analysis.lever_result import LeverResult, build_manifest
    from metis_auto.analysis.stats import cluster_bootstrap_ratio

    rb = routed_baselines(
        after, ctx, premium_model=premium_model, cached_separately=cached_separately
    )
    scope = _scope(after)
    sub = after[scope]
    routing = _routing_slice(after)
    config = {
        "lever": "rb3-knn-router",
        "k": k,
        "features": list(version.FEATURES),
        "cross_bot": version.CROSS_BOT,
        "criterion": CRITERION,
        "rows": "split_by_session tune",
        **(config_extra or {}),
    }
    manifest = build_manifest(
        config,
        ctx,
        code_commit=code_commit,
        python_version=python_version,
        created_at=created_at,
    )
    common = (
        *version.ASSUMPTIONS,
        "rows: split_by_session tune, LLM; fitted on the same rows, own session "
        "and duplicate family never a neighbour",
        "baselines over the rows whose incumbent and tokens are priced; the "
        "others keep their model and are counted in the routing slice",
        "timestamps are naive (Q-06)",
        *extra_assumptions,
    )
    texts: dict[str, str] = {}
    for key in ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap"):
        before = rb["before"][key]
        if key == "as_logged":
            baseline_cost = {b: before[b] for b in ("fees", "token_cost", "total")}
            saving: dict[str, Decimal] = {}
            note = (
                "saving not computed in recorded units: the routed cost is in "
                "price-file units and units are never subtracted across"
            )
            n_all, n_llm = Decimal(len(req_all)), Decimal(len(after))
            known = Decimal(rb["n_scope"])
            base_slice = {"n_requests": n_all, "n_cost_known": known}
            slices: dict[str, dict[str, Decimal]] = {
                "all": base_slice,
                "llm_only": {"n_requests": n_llm, "n_cost_known": known},
                "traffic_weighted": dict(base_slice),
            }
            ci = (None, None)
        else:
            baseline_cost = {
                "token_cost": before["token_cost"],
                "total": before["total"],
            }
            saving = dict(rb["saving"][key])
            note = (
                "saving = baseline minus routed cost, both from baseline_costs "
                "(price-file units, token cost only)"
            )
            base = row_baseline(
                sub,
                key,
                ctx,
                premium_model=premium_model,
                cached_separately=cached_separately,
            )
            per_row = base - sub["route_cost_routed"]
            slices = _share_slices(sub, base, per_row, len(req_all))
            _, lo, hi = cluster_bootstrap_ratio(
                per_row.to_numpy(),
                base.to_numpy(),
                sub["session_id"].to_numpy(),
                seed=ctx.seed,
            )
            ci = (None, None) if math.isnan(lo) else (lo, hi)
        slices["routing"] = routing
        result = LeverResult(
            lever_id=f"rb3.knn-router.k-{k}.tune.{key}",
            step="routing",
            version=f"route.knn.k{k}",
            n_requests=len(req_all),
            n_eligible=rb["n_scope"],
            baseline=key,
            baseline_cost=baseline_cost,
            saving=saving,
            ci_low=ci[0],
            ci_high=ci[1],
            slices=slices,
            evidence_class="simulation",
            correctness_state="unmeasured",
            assumptions=(common[0], note, *common[1:]),
            manifest=manifest,
        )
        texts[key] = result.to_json()
    return texts
