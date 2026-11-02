"""Pipeline B, sprint Day 3: R-B3 kNN router and the B-only combined dry run.

    python scripts/run_pipeline_b_day3.py rb3
    python scripts/run_pipeline_b_day3.py i1     # after rb3 (reads its default k)

Reads the local, git-ignored derived tables and the read-only raw export, loads
candidate code from ``experiments/`` by file path, and writes content-free
aggregates: R-B3 ``LeverResult`` files to ``reports/levers/<lever_id>.json``
(one per ``k`` per baseline) and summaries to
``reports/routing/exp-route-011/summary.json`` and
``reports/pipelines/b-only-dry-run/summary.json``. Prints aggregates only: no
text, hash, or bot, user, session or chunk ID (bots and tenants as ranks).

Scope, split and baselines are the shared S-3 code (ADR-0036); every setting
comes from ``config/evaluation/sprint.toml`` (``--sprint-config``). Fitting and
results use ``split_by_session == "tune"`` rows inside the tune period. The
report period is not read. ``--out-root`` and ``--sample-sessions`` are for a
smoke run into a scratch folder. No network, no model call, no key.

L-1 (overhead) is not run here: ``scripts/measure_lever_overhead.py``
(Pipeline A) exists on no branch, so overhead stays "not measured".
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import sys
import tomllib
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from metis_auto.analysis.baselines_full import (
    baseline_costs,
    cached_reported_separately,
)
from metis_auto.analysis.levers import combine, summarise_slices
from metis_auto.analysis.replay_scope import scope, split_by_session

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"
SPRINT_CONFIG = ROOT / "config" / "evaluation" / "sprint.toml"
GRID = (5, 15, 50)
OUTER, INNER = 5, 3
RB3_SUMMARY = Path("reports") / "routing" / "exp-route-011" / "summary.json"
I1_SUMMARY = Path("reports") / "pipelines" / "b-only-dry-run" / "summary.json"
EXTRA_COLUMNS = [
    "u_lang",
    "n_prior_msgs",
    "prior_chars",
    "a_rag_chunk_chars",
    "u_att_n",
    "u_n_chars",
    "bot_n_functions",
]
RB2_SCENARIOS = {  # (visible window, pointer tokens, ledger); hypothetical
    "conservative-default": (0, 8, False),
    "stated-scenario-k1": (1, 8, False),
}


def load(relative: str) -> Any:
    path = (
        (EXPERIMENTS / relative)
        if not relative.startswith("scripts/")
        else ROOT / relative
    )
    name = "metis_day3_" + relative.replace("/", "_").replace("-", "_")[:-3]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D2 = load("scripts/run_pipeline_b_day2.py")
RB1 = "caching/exp-cache-002-retrieval-result-cache/run.py"
RB2 = "context/exp-ctx-002-cross-turn-chunk-policy/run.py"
RB3 = "routing/exp-route-011-knn-router/run.py"
ELIG = "routing/exp-route-011-knn-router/eligibility_interim.py"
I1 = "pipelines/b-only-dry-run/run.py"


def settings(path: Path) -> dict[str, Any]:
    st = D2.sprint_settings(path)
    routing = tomllib.loads(path.read_text(encoding="utf-8"))["routing"]
    st["candidates"] = [*routing["candidates"], *routing.get("candidates_jev", [])]
    st["retiring"] = [r["model_id"] for r in routing.get("retiring", [])]
    return st


def requests_frame(st: dict[str, Any], sample: float | None) -> pd.DataFrame:
    cols = list(dict.fromkeys(D2.REQ_COLUMNS + EXTRA_COLUMNS))
    req = pd.read_parquet(D2.DERIVED / "requests.parquet", columns=cols)
    if sample is not None:  # smoke runs only: a seeded share of sessions
        keep = req["session_id"].map(
            lambda s: (
                hashlib.blake2b(str(s).encode(), digest_size=4).digest()[0]
                < 256 * sample
            )
        )
        req = req[keep]
    req = scope(req, st["ctx"])
    req["split"] = split_by_session(req, seed=st["seed"])
    return req


def write_levers(texts: dict[str, str], out_root: Path) -> list[str]:
    folder = out_root / "reports" / "levers"
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for text in texts.values():
        name = json.loads(text)["lever_id"]
        (folder / f"{name}.json").write_text(text, encoding="utf-8")
        names.append(name)
    return names


def _write(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _plain(obj: Any) -> Any:
    return D2._plain(D2._clean(obj))


def _factory(st: dict[str, Any], separate: frozenset[str]):
    run, elig = load(RB3), load(ELIG)
    rules = {"candidates": st["candidates"], "retiring": st["retiring"]}

    def factory(train: pd.DataFrame, k: int) -> Any:
        return run.version.KnnRouter(
            k=k,
            train=train,
            candidates=st["candidates"],
            eligible_models=elig.interim_eligible_models,
            rules=rules,
            cached_separately=separate,
        )

    return factory


def _default_k(chosen: dict[int, int]) -> int:
    """The k chosen by most outer folds (ties: the smaller k)."""
    counts = Counter(chosen.values())
    return min(counts, key=lambda k: (-counts[k], k))


def _bot_table(after: pd.DataFrame, ctx: Any) -> list[dict[str, Any]]:
    """Per bot, ranked by requests (``bot-01`` is the largest): no IDs."""
    from metis_auto.analysis.replay_scope import bot_sufficiency

    status = bot_sufficiency(after, ctx.min_n)
    rows = []
    sizes = after["bot_id"].value_counts(sort=False)
    order = sorted(sizes.index, key=lambda b: (-sizes[b], str(b)))
    for rank, bot in enumerate(order[:20], start=1):
        sub = after[after["bot_id"] == bot]
        base = sub["route_cost_incumbent"].sum(min_count=1)
        routed = sub["route_cost_routed"].sum(min_count=1)
        rows.append(
            {
                "bot": f"bot-{rank:02d}",
                "n_requests": len(sub),
                "sufficiency": status.get(bot, "insufficient"),
                "incumbent_priced": bool(pd.notna(base)),
                "moved_share": float((sub["route_reason"] == "moved").mean()),
                "saving_share_todays_models": (
                    float((base - routed) / base)
                    if pd.notna(base) and base > 0
                    else None
                ),
            }
        )
    return rows


def cmd_rb3(st: dict[str, Any], out_root: Path, sample: float | None) -> dict[str, Any]:
    run = load(RB3)
    ctx = st["ctx"]
    req = requests_frame(st, sample)
    separate = cached_reported_separately(req)
    scored = (req["split"] == "tune") & (req["period"] == "tune")
    tune_all = req[scored]
    t = tune_all[tune_all["llm_request"]].copy()
    factory = _factory(st, separate)
    nested = run.nested_cv(
        t, GRID, ctx, factory, outer=OUTER, inner=INNER, seed=st["seed"]
    )
    default_k = _default_k(nested["chosen_k"])
    router = factory(t, max(GRID))
    decided = router.apply_many(t, ctx, GRID)
    created = datetime.now(UTC)
    label = load(ELIG).LABEL
    kw = {"premium_model": st["premium_model"], "cached_separately": separate}
    written: list[str] = []
    grid: dict[str, Any] = {}
    for k in GRID:
        role = "declared default" if k == default_k else "grid point, not the default"
        texts = run.lever_results_json(
            decided[k],
            tune_all,
            k=k,
            ctx=ctx,
            code_commit=D2.code_commit(),
            python_version=platform.python_version(),
            created_at=created,
            extra_assumptions=(
                label,
                f"k={k} is the {role}; grid {list(GRID)} reported in full",
                f"default chosen by session/family-grouped nested CV, {OUTER} outer "
                f"x {INNER} inner folds, inside the tune split",
            ),
            config_extra={"grid": list(GRID), "default_k": default_k},
            **kw,
        )
        written += write_levers(texts, out_root)
        res = {key: json.loads(text) for key, text in texts.items()}
        oof = run.routed_baselines(
            nested["oof"][k].dropna(subset=["route_reason"]), ctx, **kw
        )
        grid[str(k)] = {
            "role": role,
            "routing": res["todays_models"]["slices"]["routing"],
            "saving": {key: r["saving"] for key, r in res.items()},
            "baseline_cost": {key: r["baseline_cost"] for key, r in res.items()},
            "saving_share": {
                key: r["slices"]["all"].get("saving_share") for key, r in res.items()
            },
            "ci": {key: [r["ci_low"], r["ci_high"]] for key, r in res.items()},
            "out_of_fold": {
                "moved_share": float(
                    (nested["oof"][k]["route_reason"] == "moved").mean()
                ),
                "saving": oof["saving"],
                "n_scope": oof["n_scope"],
            },
        }
    payload = _plain(
        {
            "lever": "R-B3 kNN router, nearest-profile policy (exp-route-011)",
            "period": "tune (2026-03-01..2026-07-31, naive timestamps, Q-06)",
            "scope": "split_by_session tune rows inside the tune period, LLM rows "
            "(ADR-0036); report period not read",
            "evidence": "simulation; cost simulation; quality not proven",
            "eligibility": label,
            "units": "routed cost in price-file units; as_logged saving not computed",
            "overhead": "not measured (script missing: "
            "scripts/measure_lever_overhead.py is on no branch)",
            "settings": D2._settings_record(st)
            | {"candidates": st["candidates"], "retiring": st["retiring"]},
            "criterion": run.CRITERION,
            "grid": list(GRID),
            "nested_cv": {
                "outer": OUTER,
                "inner": INNER,
                "fold_sizes": nested["fold_sizes"],
                "chosen_k_per_outer_fold": nested["chosen_k"],
                "inner_moved_share": nested["inner_moved_share"],
            },
            "default_k": default_k,
            "by_k": grid,
            "bots_default_k": _bot_table(decided[default_k], ctx),
            "data_facts": {
                "n_requests": len(req),
                "n_scored": len(tune_all),
                "n_scored_llm": len(t),
                "incumbent_in_catalogue": int(
                    t["bot_provider_model"]
                    .isin({m["model_id"] for m in ctx.catalogue["models"]})
                    .sum()
                ),
                "separate_cached_models": len(separate),
                "sample_sessions": sample,
            },
            "lever_results": sorted(written),
            "created_at": created.isoformat(),
        }
    )
    _write(payload, out_root / RB3_SUMMARY)
    return payload


def _repriced_on(rows: pd.DataFrame, ctx: Any, st: dict[str, Any], separate) -> dict:
    return baseline_costs(
        rows, ctx, premium_model=st["premium_model"], cached_separately=separate
    )


def cmd_i1(st: dict[str, Any], out_root: Path, sample: float | None) -> dict[str, Any]:
    rb1, rb2, rb3, i1 = load(RB1), load(RB2), load(RB3), load(I1)
    ctx = st["ctx"]
    rb3_summary = json.loads((out_root / RB3_SUMMARY).read_text(encoding="utf-8"))
    k = int(rb3_summary["default_k"])
    req = requests_frame(st, sample)
    separate = cached_reported_separately(req)
    frame = req[req["period"] == "tune"].copy()
    per_call = D2.per_call_items()
    frame = rb1.fee_blocks(frame, per_call)
    items = pd.read_parquet(
        D2.RAW / "derived" / "chat_message_billing.parquet",
        columns=["message_id", "inputTokens", "costBreakdown.input_tokens"],
    )
    frame = rb2.request_inputs(frame, items, separate)
    scored = frame["split"].eq("tune")
    llm = frame[frame["llm_request"]]
    lookups = rb1.build_lookups(
        llm, D2.rag_json(set(llm["ai_message_id"])), per_call, scope="user"
    )
    table = pd.concat(
        [
            pd.read_parquet(f, columns=["message_id", "chunk_id", "n_chars", "h_exact"])
            for f in sorted((D2.DERIVED / "chunks").glob("*.parquet"))
        ],
        ignore_index=True,
    )
    chunks = rb2.build_chunks(llm, table)
    tpc = D2._ledger_value("recon.t0rag.coef_rag")
    cache = rb1.version.RetrievalResultCache(
        pd.Timedelta(days=1), lookups=lookups, shadow_rate=st["shadow_rate"]
    )
    train = frame[scored & frame["llm_request"]]
    router = _factory(st, separate)(train, k)
    post = i1.PostContextRouting(router, cached_separately=separate)

    def policy(window: int, pointer: int, ledger: bool) -> Any:
        visible = (lambda d: True) if window is None else (lambda d: d <= window)
        return rb2.version.CrossTurnChunkPolicy(
            pointer, visible, ledger, chunks=chunks, tokens_per_char=tpc
        )

    runs: dict[str, pd.DataFrame] = {
        "cache_alone": combine(frame, cache, None, None, ctx),
        "routing_alone": combine(frame, None, None, router, ctx),
    }
    for label, sc in RB2_SCENARIOS.items():
        ctx_v = policy(*sc)
        runs[f"context_alone.{label}"] = combine(frame, None, ctx_v, None, ctx)
        runs[f"combined.{label}"] = combine(frame, cache, ctx_v, post, ctx)
    label = "stated-scenario-k1"
    runs[f"combined_today.{label}"] = combine(
        frame, cache, policy(*RB2_SCENARIOS[label]), router, ctx
    )

    before = frame[scored]
    out: dict[str, Any] = {"recorded": {}, "repriced": {}, "overlaps": {}, "checks": {}}
    for name, after in runs.items():
        sl = summarise_slices(before, after[scored])["llm_only"]
        if name == "routing_alone":
            out["recorded"][name] = i1.REASONS["routing"]
        else:
            out["recorded"][name] = {
                key: sl[key]
                for key in ("saving:fees", "saving:token_cost", "saving:total")
            } | {"baseline:total": sl["baseline:total"]}
            if name.startswith("combined"):
                out["recorded"][name]["steps"] = "cache + context; routing not computed"
        if (
            "retrieval_reused" in after
            and "route_reason" in after
            and "ctx_tokens_saved" in after
        ):
            out["overlaps"][name] = i1.overlaps(after[scored & frame["llm_request"]])
        if "retrieval_reused" in after:
            out["checks"][f"{name}.retrieval_rows_not_served"] = (
                i1.retrieval_rows_not_served(after)
            )
    # Repriced: one row set for every run (the rows routing can price) and one
    # definition: saving vs a baseline = baseline cost minus the pipeline's own
    # cost (price-file units, today's pricing of the models each row ends on).
    routed = runs["routing_alone"][scored & frame["llm_request"]]
    s_rows = routed.index[~routed["route_reason"].isin(rb3.OUT_OF_SCOPE)]
    base = _repriced_on(frame.loc[s_rows], ctx, st, separate)
    kw = {"premium_model": st["premium_model"], "cached_separately": separate}
    pipeline_cost: dict[str, Decimal] = {}
    for name, after in runs.items():
        a = after.loc[s_rows]
        if "route_reason" in a:
            cost = rb3.routed_baselines(a, ctx, **kw)
            if cost["n_scope"] != len(s_rows):
                raise ValueError(f"{name}: routing scope differs from the shared rows")
            pipeline_cost[name] = cost["routed"]["token_cost"]
        elif "ctx_tokens_saved" in a:
            lowered = rb2.after_tokens(a, separate)
            pipeline_cost[name] = _repriced_on(lowered, ctx, st, separate)[
                "todays_models"
            ]["token_cost"]
        else:
            out["repriced"][name] = i1.REASONS["cache"]
            continue
        out["repriced"][name] = {
            key: base[key]["token_cost"] - pipeline_cost[name]
            for key in i1.STEP_UNITS["routing"]
        }
    today = base["todays_models"]["token_cost"]
    rules: dict[str, Any] = {}
    for label in RB2_SCENARIOS:
        rec = out["recorded"]
        rules[f"as_logged.{label}"] = i1.sum_rule(
            rec[f"combined.{label}"]["saving:total"],
            [
                rec["cache_alone"]["saving:total"],
                rec[f"context_alone.{label}"]["saving:total"],
            ],
        )
        rules[f"repriced_increment_over_todays_models.{label}"] = i1.sum_rule(
            today - pipeline_cost[f"combined.{label}"],
            [
                today - pipeline_cost[f"context_alone.{label}"],
                today - pipeline_cost["routing_alone"],
            ],
        )
    out["repriced_note"] = (
        "per-baseline savings share the term (baseline - today's models), so they "
        "are not additive across runs; the sum rule is checked on the increment "
        "over today's models, which is the same for the three repriced baselines"
    )
    out["sum_rule"] = rules
    payload = _plain(
        {
            "task": "I-1, Pipeline B only: dry-run combine of R-B1 + R-B2 + R-B3 "
            "(handoff; no winner picked)",
            "why_not_lever_result": "LeverResult.step is one of cache/context/routing; "
            "a combined pipeline has no step, so a content-free summary is written",
            "period": "tune (naive timestamps, Q-06); scored rows "
            "split_by_session tune; every tune-period row is R-B1 cache history",
            "versions": {
                "cache": "R-B1 retrieval_result_cache.ttl_1d (TTL chosen on Day 2)",
                "context": {k: list(v) for k, v in RB2_SCENARIOS.items()},
                "routing": f"R-B3 route.knn.k{k} (declared default), "
                f"{load(ELIG).LABEL}",
            },
            "units": i1.unit_cells(),
            "routing_after_context": "combined.*: PostContextRouting (input lowered by "
            "R-B2's net tokens saved); combined_today.*: combine as it is (routing "
            "reprices the logged input)",
            "repriced_rows": {
                "n": len(s_rows),
                "note": "rows whose incumbent and "
                "tokens routing can price; same rows for every run",
            },
            **out,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    _write(payload, out_root / I1_SUMMARY)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("task", choices=["rb3", "i1"])
    parser.add_argument("--sprint-config", type=Path, default=SPRINT_CONFIG)
    parser.add_argument("--out-root", type=Path, default=ROOT, help="smoke runs only")
    parser.add_argument(
        "--sample-sessions", type=float, default=None, help="smoke only"
    )
    args = parser.parse_args()
    st = settings(args.sprint_config)
    if args.task == "rb3":
        payload = cmd_rb3(st, args.out_root, args.sample_sessions)
    else:
        payload = cmd_i1(st, args.out_root, args.sample_sessions)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
