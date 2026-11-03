"""R-B1 run helpers: build the lookups frame, the recorded fee block, the
evaluation, the TTL choice and one ``LeverResult`` per baseline (final plan R-B1;
H-3, FR-XCACHE-04, FR-EVAL-08, QA-REPRO; ADR-0036;
ADR-0037). Pure over frames;
``scripts/run_pipeline_b_day2.py`` does the file IO and passes the shared scope
(``analysis.replay_scope``), the baselines (``analysis.baselines_full``) and the
``sprint.toml`` values. Outputs are content-free aggregates: no query, chunk,
hash, bot, user or session value leaves this module except as a count or a rank.

**Fitting vs history** (owner decision 2026-11-02, ADR-0036 decision 1). The
TTL is a fitted threshold, so it is chosen on ``scored`` rows only, which the
script sets to ``split_by_session == "tune"``. The replay itself runs over every
LLM row it is given, so earlier rows of any split or period are cache history.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from metis_auto.analysis.stats import cluster_bootstrap_ratio

HERE = Path(__file__).resolve().parent
TENANT_RANKS = 5
MEASURED_POTENTIAL = (
    "measured potential, conditional on Metis-Auto being able to intercept retrieval"
)


def _sibling(name: str) -> Any:
    key = f"metis_exp_cache_002_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


version = _sibling("version")
REPRICED_NOT_COMPUTED = (
    "saving not computed in price-file units: R-B1 avoids only per-call fees, "
    "and repriced baselines have no fees block (ADR-0036, decision 5)"
)


def _settings(row: Any) -> str:
    """The configuration snapshot (not a history; data dictionary, chat_bot)."""
    return (
        f"top_k={row.bot_rag_top_k};rerank={row.bot_rag_reranking};"
        f"n_corpora={row.bot_n_corpora}"
    )


def build_lookups(
    req: pd.DataFrame,
    rag: pd.DataFrame,
    per_call: pd.DataFrame,
    *,
    scope: str = "user",
) -> pd.DataFrame:
    """One row per logged query lookup, in request order then ``pos``.

    ``rag``: ``message_id``, ``rag`` (raw JSON). ``per_call``: one row per
    per-call billing item, ``message_id`` and ``amount`` (recorded). ``scope``
    ``"user"`` (default, conservative) scopes reuse to the requesting user and
    the bot; ``"bot"`` to the bot owner and the bot (sensitivity). The corpus
    version is always ``None``: the log has no version evidence.
    """
    if scope not in ("user", "bot"):
        raise ValueError("scope must be 'user' or 'bot'")
    raw = dict(zip(rag["message_id"], rag["rag"], strict=True))
    amounts = per_call.groupby("message_id")["amount"].agg(list).to_dict()
    tenant_col = "user_id" if scope == "user" else "bot_user_id"
    rows = []
    for label, row in zip(req.index, req.itertuples(index=False), strict=True):
        parsed = version.lookups_from_rag(raw.get(row.ai_message_id))
        if not parsed:
            continue
        fees = version.attribute_fees(len(parsed), amounts.get(row.ai_message_id, []))
        t_done = row.a_timestamp
        t_arrive = row.u_timestamp if not pd.isna(row.u_timestamp) else t_done
        settings = _settings(row)
        for i, (pos, qkey, chunks) in enumerate(parsed):
            rows.append(
                (
                    label,
                    pos,
                    t_arrive,
                    t_done,
                    getattr(row, tenant_col),
                    row.bot_id,
                    None,
                    settings,
                    qkey,
                    chunks,
                    float("nan") if fees is None else fees[i],
                )
            )
    out = pd.DataFrame(rows, columns=list(version.LOOKUP_COLUMNS))
    out["corpus_version"] = out["corpus_version"].astype(object)
    return out


def fee_blocks(req: pd.DataFrame, per_call: pd.DataFrame) -> pd.DataFrame:
    """``block_fees`` = recorded ``costBreakdown.per_call`` sum of the message
    (0 when it has none), ``block_token_cost`` = recorded total minus that.
    Both unknown when the total is unknown. Replaces the 0.002-per-item proxy of
    ``levers.with_blocks`` so fee avoided and fee block share one source."""
    out = req.copy()
    fee = per_call.groupby("message_id")["amount"].agg(
        lambda s: math.fsum(s.to_numpy(dtype=float))
    )
    total = out["a_bill_totalCost"]
    fees = out["ai_message_id"].map(fee).fillna(0.0).where(total.notna())
    if ((total - fees) < -1e-9).any():
        raise ValueError("per-call fees exceed the recorded total on some rows")
    out["block_fees"] = fees
    out["block_token_cost"] = (total - fees).clip(lower=0.0)
    return out


def _share(num: float, den: float) -> float | None:
    return num / den if den > 0 else None


def evaluate(
    req: pd.DataFrame,
    lookups: pd.DataFrame,
    ttl: pd.Timedelta | None,
    ctx: Any,
    shadow_rate: float,
    *,
    scored: pd.Series | None = None,
) -> dict[str, Any]:
    """Replay one TTL over every LLM row of ``req`` and return content-free
    aggregates plus the ``after`` frame, both over the ``scored`` rows only
    (a boolean mask on ``req.index``; default every row). Unscored rows are
    cache history: they look up and insert, but are not counted."""
    cache = version.RetrievalResultCache(ttl, lookups=lookups, shadow_rate=shadow_rate)
    llm_all = req["llm_request"].astype(bool)
    all_outcomes = cache.replay(ctx, requests=req.index[llm_all.to_numpy()])
    all_after = cache.apply(req, ctx)
    keep = _mask(scored, req.index)
    req, after = req.loc[keep], all_after.loc[keep]
    outcomes = all_outcomes[all_outcomes["req"].isin(req.index)]
    llm = req["llm_request"].astype(bool)
    known = llm & req[["block_fees", "block_token_cost"]].notna().all(axis=1)
    fee_block = math.fsum(req.loc[known, "block_fees"])
    total = fee_block + math.fsum(req.loc[known, "block_token_cost"])
    avoided = math.fsum(after.loc[known, "retrieval_fee_avoided"])
    reused = after["retrieval_reused"] & llm
    den_total = (req["block_fees"] + req["block_token_cost"])[known].to_numpy()
    num = after.loc[known, "retrieval_fee_avoided"].to_numpy()
    sessions = req.loc[known, "session_id"].to_numpy()
    ci_total = cluster_bootstrap_ratio(num, den_total, sessions)
    ci_fees = cluster_bootstrap_ratio(
        num, req.loc[known, "block_fees"].to_numpy(), sessions
    )
    n_lookups_llm = len(outcomes)
    hits = int((outcomes["status"] == "hit").sum())
    return {
        "name": cache.name,
        "summary": version.summarise(outcomes),
        "rates": {
            "n_requests_all": len(req),
            "n_requests_llm": int(llm.sum()),
            "n_requests_reused": int(reused.sum()),
            "requests_reused_all": _share(float(reused.sum()), float(len(req))),
            "requests_reused_llm": _share(float(reused.sum()), float(llm.sum())),
            "n_lookups_llm": n_lookups_llm,
            "lookup_hit_rate_llm": _share(float(hits), float(n_lookups_llm)),
            "requests_with_lookups_llm": int(
                req.index[llm.to_numpy()].isin(lookups["req"]).sum()
            ),
        },
        "fees": {
            "n_cost_known_llm": int(known.sum()),
            "fee_block": fee_block,
            "total_cost": total,
            "fee_avoided": avoided,
            "share_of_fee_block": _share(avoided, fee_block),
            "share_of_fee_block_ci": [ci_fees[1], ci_fees[2]],
            "share_of_total_cost": _share(avoided, total),
            "share_of_total_cost_ci": [ci_total[1], ci_total[2]],
            "fee_block_share_of_total": _share(fee_block, total),
        },
        "tenants": tenant_shares(req.loc[known], after.loc[known]),
        "after": after,
    }


def _mask(scored: pd.Series | None, index: pd.Index) -> pd.Series:
    if scored is None:
        return pd.Series(True, index=index)
    return scored.reindex(index, fill_value=False).astype(bool)


def passes_ttl_rule(summary: dict[str, Any]) -> bool:
    """Declared before the run (README): mean agreement on evaluable hits >= 0.9
    and at least half of the hits evaluable."""
    a = summary["agreement"]
    if not a["n_hits"] or "mean" not in a:
        return False
    return a["mean"] >= 0.9 and a["n_evaluable"] >= 0.5 * a["n_hits"]


def choose_ttl(
    req: pd.DataFrame,
    lookups: pd.DataFrame,
    ttls_days: Sequence[int],
    ctx: Any,
    shadow_rate: float,
    *,
    scored: pd.Series,
) -> dict[str, Any]:
    """The TTL rule on ``scored`` rows only: the longest TTL that passes
    ``passes_ttl_rule`` (``None`` if none does). ``"none"`` (no expiry) is
    reported but never chosen. The replay reads every LLM row of ``req`` as
    history, as ``evaluate`` does."""
    llm = req["llm_request"].astype(bool)
    keep = _mask(scored, req.index)
    counted = req.index[keep.to_numpy()]
    by_ttl: dict[str, Any] = {}
    chosen = None
    for days in (None, *ttls_days):
        ttl = None if days is None else pd.Timedelta(days=days)
        cache = version.RetrievalResultCache(
            ttl, lookups=lookups, shadow_rate=shadow_rate
        )
        outcomes = cache.replay(ctx, requests=req.index[llm.to_numpy()])
        summary = version.summarise(outcomes[outcomes["req"].isin(counted)])
        passed = passes_ttl_rule(summary)
        by_ttl["none" if days is None else f"{days}d"] = {
            "summary": summary,
            "passes_rule": passed,
        }
        if days is not None and passed:
            chosen = days
    return {"by_ttl": by_ttl, "chosen_ttl_days": chosen}


def tenant_shares(
    req: pd.DataFrame, after: pd.DataFrame
) -> dict[str, dict[str, float]]:
    """Per tenant (requesting user), ranked by requests: share of requests and
    of fee avoided. Ranks only; no tenant ID leaves this function."""
    counts = req.groupby("user_id").size().sort_values(ascending=False, kind="stable")
    saved = after.groupby("user_id")["retrieval_fee_avoided"].sum()
    total_saved = float(saved.sum())
    out: dict[str, dict[str, float]] = {}
    for rank, (tenant, n) in enumerate(counts.items(), start=1):
        name = f"tenant_rank:{rank}" if rank <= TENANT_RANKS else "tenant_rank:rest"
        slot = out.setdefault(name, {"requests_share": 0.0, "share": 0.0})
        slot["requests_share"] += n / len(req) if len(req) else 0.0
        if total_saved > 0:
            slot["share"] += float(saved.get(tenant, 0.0)) / total_saved
    return out


def ttl_table(
    lookups: pd.DataFrame,
    windows_days: Sequence[int] = (1, 7, 30, 90),
    scored: pd.Index | None = None,
) -> dict[int, float]:
    """The free check behind the TTL (tune-period lookups only). ``scored``:
    request labels whose lookups form the denominator; all are history."""
    return version.repeat_rates(lookups, windows_days, scored)


def churn_summary(lookups: pd.DataFrame) -> dict[str, Any]:
    """Knowledge-base churn across bots, as counts and shares (no bot IDs)."""
    churn = version.chunk_churn(lookups)
    if churn.empty:
        return {"n_bots": 0}
    changed = churn["n_changed"] > 0
    return {
        "n_bots": len(churn),
        "n_chunk_ids": int(churn["n_chunk_ids"].sum()),
        "n_chunk_ids_changed": int(churn["n_changed"].sum()),
        "share_chunk_ids_changed": float(
            churn["n_changed"].sum() / churn["n_chunk_ids"].sum()
        ),
        "n_bots_with_change": int(changed.sum()),
        "n_chunk_ids_hash_unknown": int(churn["n_hash_unknown"].sum()),
        "bot_share_changed_p50": float(np.percentile(churn["share_changed"], 50)),
        "bot_share_changed_p90": float(np.percentile(churn["share_changed"], 90)),
        "bot_share_changed_max": float(churn["share_changed"].max()),
    }


def _dec(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


TOTAL_SLICES = ("all", "llm_only", "traffic_weighted")
"""Slices that hold the result's own totals."""


def price_file_slices(
    slices: Mapping[str, Mapping[str, Decimal]],
    *,
    baseline_cost: Mapping[str, Decimal],
    saving: Mapping[str, Decimal],
    n_cost_known: Decimal,
) -> dict[str, dict[str, Decimal]]:
    """The slices of a repriced result, every money figure in price-file units
    (ADR-0036, ADR-0050). The total slices take the result's own token cost and
    saving (none when not computed) and the repriced baseline's known rows;
    recorded-unit keys (``baseline:*``, ``saving:*``, ``saving_share`` and the
    share of a recorded saving) are dropped everywhere else. Counts stay."""
    recorded = ("baseline:", "saving:")
    out: dict[str, dict[str, Decimal]] = {}
    for name, values in slices.items():
        kept = {
            k: v
            for k, v in values.items()
            if not k.startswith(recorded) and k not in ("saving_share", "share")
        }
        if name in TOTAL_SLICES:
            kept["n_cost_known"] = n_cost_known
            kept["baseline:token_cost"] = baseline_cost["token_cost"]
            kept["baseline:total"] = baseline_cost["total"]
            if saving:
                kept["saving:token_cost"] = saving["token_cost"]
                kept["saving:total"] = saving["total"]
                if baseline_cost["token_cost"] > 0:
                    kept["saving_share"] = _dec(
                        float(saving["token_cost"] / baseline_cost["token_cost"])
                    )
        out[name] = kept
    return out


def lever_results_json(
    res: dict[str, Any],
    req: pd.DataFrame,
    *,
    baselines: Mapping[str, Mapping[str, Decimal]],
    split_counts: Mapping[str, int],
    ttl: pd.Timedelta | None,
    ctx: Any,
    code_commit: str,
    python_version: str,
    created_at: datetime,
    extra_assumptions: Sequence[str] = (),
    shadow_rate: float = 0.0,
    scope: str = "user",
    period: str = "tune",
) -> dict[str, str]:
    """One ``LeverResult`` JSON text per baseline key (``BASELINE_KEYS``).

    ``req`` and ``res`` cover the scored rows; ``baselines`` is
    ``baselines_full.baseline_costs`` over the same rows. ``ctx`` is the
    ``ReplayContext`` (period bounds, price table, catalogue, seed, ``min_n``)
    that goes into the manifest.

    - ``as_logged`` (recorded units): baseline and saving per block. The blocks
      are R-B1's recorded per-call split (``fee_blocks``); their sum must equal
      the shared ``as_logged`` total.
    - repriced baselines (price-file units): ``baseline_cost`` holds
      ``token_cost`` and ``total`` only; ``saving`` is empty, the way a missing
      value is represented (``compare`` shows "saving unknown"), never 0.
    """
    from metis_auto.analysis.baselines_full import BASELINE_KEYS
    from metis_auto.analysis.lever_result import LeverResult, build_manifest
    from metis_auto.analysis.levers import BLOCKS, summarise_slices

    after = res["after"]
    slices = summarise_slices(req, after)
    slices["traffic_weighted"] = dict(slices["all"])  # full traffic, unsampled
    for name, values in res["tenants"].items():
        slices[name] = {k: _dec(v) for k, v in values.items()}
    s, r = res["summary"], res["rates"]
    retrieval = {
        "n_lookups_llm": r["n_lookups_llm"],
        "n_hits": s["status"].get("hit", 0),
        "n_guard_blocks": s["status"].get("guard_block", 0),
        "n_ineligible": s["status"].get("ineligible", 0),
        "n_requests_reused": r["n_requests_reused"],
        "n_agreement_evaluable": s["agreement"]["n_evaluable"],
        "n_agreement_unknown": s["agreement"]["n_unknown"],
        "n_shadow_sampled": s["shadow"]["sampled"],
        "n_shadow_agree": s["shadow"]["agree"],
        "n_shadow_unknown": s["shadow"]["unknown"],
    }
    slices["retrieval"] = {k: Decimal(int(v)) for k, v in retrieval.items()}
    if "mean" in s["agreement"]:
        slices["retrieval"]["agreement_mean"] = _dec(s["agreement"]["mean"])
    slices["split"] = {k: Decimal(int(v)) for k, v in split_counts.items()}
    known = slices["llm_only"]
    recorded = {b: known[f"baseline:{b}"] for b in BLOCKS}
    recorded_total = sum(recorded.values(), Decimal(0))
    if abs(recorded_total - baselines["as_logged"]["total"]) > Decimal("0.000001"):
        raise ValueError("recorded blocks do not sum to the as_logged baseline total")
    days = "none" if ttl is None else f"{ttl / pd.Timedelta(days=1):g}d"
    config = {
        "lever": "rb1-retrieval-result-cache",
        "ttl": days,
        "scope": scope,
        "shadow_rate": shadow_rate,
        "period": period,
        "split": "split_by_session tune rows (ADR-0036)",
    }
    manifest = build_manifest(
        config,
        ctx,
        code_commit=code_commit,
        python_version=python_version,
        created_at=created_at,
    )
    ci = res["fees"]["share_of_total_cost_ci"]
    ci_ok = all(isinstance(v, float) and math.isfinite(v) for v in ci)
    common = (
        MEASURED_POTENTIAL,
        "candidate reuse; agreement with the later real lookup is in slice "
        "'retrieval'; production correctness not measured",
        "TTL chosen on split_by_session tune rows only; earlier rows of any "
        "split are cache history (owner decision 2026-11-02)",
        "frequency bias: the tune split drops a family's tune rows if it recurs "
        "in the report period, so repeat rates are understated (ADR-0036)",
        "no corpus-version evidence: every hit is ttl_only",
        "retrieval settings are a configuration snapshot, not a history",
        "timestamps are naive (Q-06)",
    )
    if period == "report":
        common += (
            "report split (split_by_session report) scored once; tune-period rows "
            "may warm the cache (the history looks back into the tune period, as "
            "R-A1's window; owner decision 2026-11-02); TTL frozen on the tune split",
        )
    out: dict[str, str] = {}
    for key in BASELINE_KEYS:
        if key == "as_logged":
            fields: dict[str, Any] = {
                "slices": slices,
                "baseline_cost": recorded | {"total": recorded_total},
                "saving": {b: known[f"saving:{b}"] for b in BLOCKS},
                "ci_low": ci[0] if ci_ok else None,
                "ci_high": ci[1] if ci_ok else None,
                "assumptions": (
                    "fees avoided are recorded per-call amounts of skipped lookups "
                    "(recorded units); token cost unchanged",
                    "fee block from recorded costBreakdown.per_call, not the 0.002 "
                    "proxy; the total equals the shared as_logged total",
                    "ci is session-clustered, share of total recorded cost",
                ),
            }
        else:
            base = baselines[key]
            cost = {"token_cost": base["token_cost"], "total": base["total"]}
            fields = {
                "baseline_cost": cost,
                "saving": {},
                "slices": price_file_slices(
                    slices, baseline_cost=cost, saving={}, n_cost_known=base["n_known"]
                ),
                "ci_low": None,
                "ci_high": None,
                "assumptions": (
                    REPRICED_NOT_COMPUTED,
                    "baseline in price-file units; never added to recorded units",
                ),
            }
        result = LeverResult(
            lever_id=f"rb1.retrieval-cache.ttl-{days}.{scope}.{period}.{key}",
            step="cache",
            version=res["name"],
            n_requests=len(req),
            n_eligible=int(r["n_requests_llm"]),
            baseline=key,
            evidence_class="simulation",
            correctness_state="unmeasured",
            manifest=manifest,
            **fields
            | {
                "assumptions": (
                    common[0],
                    *fields["assumptions"],
                    *common[1:],
                    *extra_assumptions,
                )
            },
        )
        out[key] = result.to_json()
    return out
