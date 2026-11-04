"""Pipeline B, sprint Day 3: R-B3 kNN router and the B-only combined dry run.

    python scripts/run_pipeline_b_day3.py rb3              # tune split; freezes k
    python scripts/run_pipeline_b_day3.py rb3-report --k K # once, report split
    python scripts/run_pipeline_b_day3.py i1               # after rb3 (frozen k)

Reads the local, git-ignored derived tables and the read-only raw export, loads
candidate code from ``experiments/`` by file path, and writes content-free
aggregates: R-B3 ``LeverResult`` files to ``reports/levers/<lever_id>.json``
(primary ``rb3.knn-router.k-<k>.<split>.<baseline>`` and secondary
``rb3.knn-router.with_reasoning_models.k-<k>.<split>.<baseline>``) and summaries
to ``reports/routing/exp-route-011/summary.json`` (tune, with the frozen ``k``),
``reports/routing/exp-route-011/report.json`` (the one report run) and
``reports/pipelines/b-only-dry-run/summary.json``. Prints aggregates only: no
text, hash, or bot, user, session or chunk ID (bots and tenants as ranks).

Scope, split and baselines are the shared S-3 code (ADR-0036); every setting
comes from ``config/evaluation/sprint.toml`` (``--sprint-config``). ``rb3`` fits
and scores ``split_by_session == "tune"`` rows inside the tune period and chooses
``k`` by the predeclared least-aggressive criterion in nested CV; that ``k`` is
frozen in the summary. ``rb3-report`` (owner approval, 2026-11-03: one report
run, as R-A3 and R-C3) fits on those tune rows and applies the frozen version
once to the report split (sessions starting Aug-Oct 2026); it refuses a ``k``
other than the frozen one. ``--out-root`` and ``--sample-sessions`` are for a
smoke run into a scratch folder. No network, no model call, no key.

Eligibility is the shared routing base (R-0, ADR-0045):
``analysis.routing_base.eligible_models`` is injected into the router with
``sprint.toml [routing]`` as its rules (``candidates_jev`` handled as R-A3:
dropped, the constructor's candidates used). Accounting per baseline follows
ADR-0046 points 4 to 6 (as R-A3 and R-C3; owner decision for Pipeline B,
2026-11-03): the primary result leaves out candidates the catalogue marks
``hidden_reasoning_billed_as_output``, the secondary keeps them; each baseline's
incumbent is that baseline's model; ``as_logged`` prices the target at implied
recorded rates. L-1 (overhead) is not run here:
``scripts/measure_pipeline_b_overhead.py`` fills it into the written files.
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
    best_single_cheap_model,
    cached_reported_separately,
)
from metis_auto.analysis.levers import combine, summarise_slices, with_blocks
from metis_auto.analysis.replay_scope import scope, split_by_session
from metis_auto.analysis.routing_base import eligible_models

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ROOT / "experiments"
SPRINT_CONFIG = ROOT / "config" / "evaluation" / "sprint.toml"
RATES = ROOT / "reports" / "full_eda" / "tables" / "implied_unit_rates.csv"
RATES_VERSION = "full-eda-implied-unit-rates"  # as R-A3's and R-C3's as_logged
GRID = (5, 15, 50)
OUTER, INNER = 5, 3
RB3_SUMMARY = Path("reports") / "routing" / "exp-route-011" / "summary.json"
RB3_REPORT = Path("reports") / "routing" / "exp-route-011" / "report.json"
I1_SUMMARY = Path("reports") / "pipelines" / "b-only-dry-run" / "summary.json"
REPRICED = ("premium_gpt_5_5", "todays_models", "best_single_cheap")
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
I1 = "pipelines/b-only-dry-run/run.py"
ELIGIBILITY = "shared routing base (R-0, ADR-0045): analysis.routing_base"


def settings(path: Path) -> dict[str, Any]:
    """``sprint.toml`` values, the routing rules and the two candidate sets:
    ``candidates`` (primary, without reasoning-billed models, ADR-0046 point 4)
    and ``candidates_with_reasoning`` (all of ``[routing] candidates``)."""
    st = D2.sprint_settings(path)
    sprint = tomllib.loads(path.read_text(encoding="utf-8"))
    routing = sprint["routing"]
    version = load(RB3).version
    every = [str(c) for c in routing["candidates"]]
    st["routing"] = routing
    st["candidates_with_reasoning"] = every
    st["candidates"] = list(version.primary_candidates(every, st["ctx"].catalogue))
    st["reasoning_billed"] = sorted(
        version.reasoning_billed(st["ctx"].catalogue) & set(every)
    )
    st["retiring"] = [r["model_id"] for r in routing.get("retiring", [])]
    st["tenant_cap"] = float(sprint["sample"]["tenant_cap"])
    return st


def load_implied_rates(path: Path = RATES) -> dict[str, dict[str, float | None]]:
    """Implied recorded-basis rates per 1M tokens per model (missing = None);
    the table R-A3 and R-C3 read."""
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


def _factory(st: dict[str, Any], separate: frozenset[str], candidates=None):
    """Router factory: shared eligibility, ``sprint.toml [routing]`` as rules;
    ``candidates`` default to the primary set."""
    run = load(RB3)
    chosen = list(st["candidates"] if candidates is None else candidates)

    def factory(train: pd.DataFrame, k: int) -> Any:
        return run.version.KnnRouter(
            k=k,
            train=train,
            candidates=chosen,
            eligible_models=eligible_models,
            rules=st["routing"],
            cached_separately=separate,
        )

    return factory


def rb3_assumptions(
    k: int, role: str, *, split: str = "tune", hidden: tuple[str, ...] = ()
) -> tuple[str, ...]:
    """The run-level assumptions of one R-B3 result."""
    rows = (
        "rows: split_by_session tune inside the tune period, LLM; fitted on the "
        "same rows, own session and duplicate family never a neighbour"
        if split == "tune"
        else "fitted on tune rows (split_by_session tune and period Mar-Jul 2026), "
        "applied once to the report split (sessions starting Aug-Oct 2026)"
    )
    out = (
        f"eligibility: {ELIGIBILITY}",
        rows,
        f"k={k} is the {role}; grid {list(GRID)}; default chosen by "
        f"session/family-grouped nested CV, {OUTER} outer x {INNER} inner folds, "
        "inside the tune split",
        "timestamps are naive (Q-06)",
    )
    if hidden:
        out += (
            "Candidates the catalogue marks hidden_reasoning_billed_as_output are "
            f"excluded (ADR-0046 point 4): {', '.join(hidden)}.",
        )
    return out


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


def _result_record(texts: dict[str, str]) -> dict[str, Any]:
    """Per baseline: saving share with CI, rows moved, cost or saving unknown."""
    out = {}
    for key, text in texts.items():
        r = json.loads(text)
        llm, routing = r["slices"]["llm_only"], r["slices"]["routing"]
        out[key] = {
            "lever_id": r["lever_id"],
            "saving": r["saving"],
            "baseline_cost": r["baseline_cost"],
            "saving_share": llm.get("saving_share"),
            "ci": [r["ci_low"], r["ci_high"]],
            "n_llm": llm["n_requests"],
            "n_cost_known": llm["n_cost_known"],
            "n_switched_in_baseline": routing["n_switched_in_baseline"],
            "switched_share_llm": routing.get("switched_share_llm"),
            "n_saving_unknown": routing["n_saving_unknown"],
        }
    return out


def _requests(st: dict[str, Any], sample: float | None):
    """Scoped requests with the recorded blocks (``levers.with_blocks``, as R-A3),
    the cached-token convention and the implied rates."""
    req = with_blocks(requests_frame(st, sample))
    return req, cached_reported_separately(req), load_implied_rates()


def cmd_rb3(st: dict[str, Any], out_root: Path, sample: float | None) -> dict[str, Any]:
    run = load(RB3)
    ctx = st["ctx"]
    req, separate, rates = _requests(st, sample)
    scored = (req["split"] == "tune") & (req["period"] == "tune")
    tune_all = req[scored]
    t = tune_all[tune_all["llm_request"]].copy()
    cheap = best_single_cheap_model(tune_all, ctx, cached_separately=separate)
    nested = run.nested_cv(
        t, GRID, ctx, _factory(st, separate), outer=OUTER, inner=INNER, seed=st["seed"]
    )
    default_k = _default_k(nested["chosen_k"])
    created = datetime.now(UTC)
    kw = {
        "ctx": ctx,
        "premium_model": st["premium_model"],
        "cheap_model": cheap,
        "cached_separately": separate,
        "rates": rates,
    }
    written: list[str] = []
    variants: dict[str, Any] = {}
    bots: list[dict[str, Any]] = []
    for with_reasoning in (False, True):
        cands = st["candidates_with_reasoning" if with_reasoning else "candidates"]
        router = _factory(st, separate, cands)(t, max(GRID))
        decided = router.apply_many(t, ctx, GRID)
        grid: dict[str, Any] = {}
        for k in GRID:
            role = "declared default" if k == default_k else "grid point"
            texts = run.lever_results_json(
                decided[k],
                tune_all,
                k=k,
                split="tune",
                with_reasoning=with_reasoning,
                code_commit=D2.code_commit(),
                python_version=platform.python_version(),
                created_at=created,
                extra_assumptions=rb3_assumptions(
                    k,
                    role,
                    hidden=() if with_reasoning else tuple(st["reasoning_billed"]),
                ),
                config_extra={"grid": list(GRID), "default_k": default_k},
                tenant_cap=st["tenant_cap"],
                rates_version=RATES_VERSION,
                **kw,
            )
            written += write_levers(texts, out_root)
            grid[str(k)] = {
                "role": role,
                "routing": json.loads(texts["todays_models"])["slices"]["routing"],
                "by_baseline": _result_record(texts),
            }
            if not with_reasoning:
                oof = nested["oof"][k].dropna(subset=["route_reason"])
                grid[str(k)]["out_of_fold_todays_models"] = run.baseline_saving(
                    oof, "todays_models", **kw
                ) | {"moved_share": float(oof["route_reason"].eq("moved").mean())}
        name = "with_reasoning_models" if with_reasoning else "primary"
        variants[name] = {"candidates": cands, "by_k": grid}
        if not with_reasoning:
            bots = _bot_table(decided[default_k], ctx)
    payload = _plain(
        {
            "lever": "R-B3 kNN router, nearest-profile policy (exp-route-011)",
            "period": "tune (2026-03-01..2026-07-31, naive timestamps, Q-06)",
            "scope": "split_by_session tune rows inside the tune period, LLM rows "
            "(ADR-0036); report period not read by this command",
            "evidence": "simulation; cost simulation; quality not proven",
            "eligibility": ELIGIBILITY,
            "saving_definition": " ".join(run.POINT_6),
            "units": "each baseline in its own units: repriced in price-file units, "
            "as_logged in recorded units at implied rates (ADR-0046 point 5)",
            "overhead": "filled into the lever files by "
            "scripts/measure_pipeline_b_overhead.py",
            "settings": D2._settings_record(st)
            | {
                "candidates": st["candidates"],
                "candidates_with_reasoning": st["candidates_with_reasoning"],
                "reasoning_billed_excluded": st["reasoning_billed"],
                "retiring": st["retiring"],
                "best_single_cheap": cheap,
                "implied_rates": RATES.relative_to(ROOT).as_posix(),
            },
            "criterion": run.CRITERION,
            "grid": list(GRID),
            "nested_cv": {
                "candidates": "primary",
                "outer": OUTER,
                "inner": INNER,
                "fold_sizes": nested["fold_sizes"],
                "chosen_k_per_outer_fold": nested["chosen_k"],
                "inner_moved_share": nested["inner_moved_share"],
            },
            "default_k": default_k,
            "frozen_k": default_k,
            "frozen": "k chosen on the tune split by the predeclared criterion and "
            f"frozen on {created.date().isoformat()} before the report run",
            "variants": variants,
            "bots_default_k": bots,
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


def frozen_k(out_root: Path) -> int:
    summary = json.loads((out_root / RB3_SUMMARY).read_text(encoding="utf-8"))
    return int(summary["frozen_k"])


def cmd_rb3_report(
    st: dict[str, Any], out_root: Path, sample: float | None, k: int
) -> dict[str, Any]:
    """The frozen version, fitted on tune rows, applied once to the report split."""
    frozen = frozen_k(out_root)
    if k != frozen:
        raise SystemExit(f"--k {k} is not the frozen k {frozen} (summary.json)")
    run = load(RB3)
    ctx = st["ctx"]
    req, separate, rates = _requests(st, sample)
    fit = (req["split"] == "tune") & (req["period"] == "tune") & req["llm_request"]
    t = req[fit].copy()
    report = req[req["split"] == "report"]
    report_llm = report[report["llm_request"]].copy()
    cheap = best_single_cheap_model(report, ctx, cached_separately=separate)
    created = datetime.now(UTC)
    written: list[str] = []
    variants: dict[str, Any] = {}
    for with_reasoning in (False, True):
        cands = st["candidates_with_reasoning" if with_reasoning else "candidates"]
        after = _factory(st, separate, cands)(t, k).apply(report_llm, ctx)
        texts = run.lever_results_json(
            after,
            report,
            k=k,
            split="report",
            with_reasoning=with_reasoning,
            ctx=ctx,
            premium_model=st["premium_model"],
            cheap_model=cheap,
            cached_separately=separate,
            rates=rates,
            code_commit=D2.code_commit(),
            python_version=platform.python_version(),
            created_at=created,
            extra_assumptions=rb3_assumptions(
                k,
                "frozen default",
                split="report",
                hidden=() if with_reasoning else tuple(st["reasoning_billed"]),
            ),
            config_extra={"frozen_k": k, "fit_rows": "tune split, tune period"},
            tenant_cap=st["tenant_cap"],
            rates_version=RATES_VERSION,
        )
        written += write_levers(texts, out_root)
        name = "with_reasoning_models" if with_reasoning else "primary"
        variants[name] = {
            "candidates": cands,
            "routing": json.loads(texts["todays_models"])["slices"]["routing"],
            "by_baseline": _result_record(texts),
        }
    payload = _plain(
        {
            "lever": "R-B3 kNN router (exp-route-011), report split, one run",
            "approval": "owner (Kimia, Pipeline B), 2026-11-03: one report-period "
            "run for R-B3, like R-A3 and R-C3",
            "fit_rows": "split_by_session tune and period tune, LLM",
            "eval_rows": "split_by_session report (sessions starting Aug-Oct 2026), "
            "LLM",
            "frozen_k": k,
            "best_single_cheap": cheap,
            "variants": variants,
            "data_facts": {
                "n_fit_llm": len(t),
                "n_report": len(report),
                "n_report_llm": len(report_llm),
                "sample_sessions": sample,
            },
            "lever_results": sorted(written),
            "created_at": created.isoformat(),
        }
    )
    _write(payload, out_root / RB3_REPORT)
    return payload


def cmd_i1(st: dict[str, Any], out_root: Path, sample: float | None) -> dict[str, Any]:
    rb1, rb2, rb3, i1 = load(RB1), load(RB2), load(RB3), load(I1)
    ctx = st["ctx"]
    k = frozen_k(out_root)
    req = requests_frame(st, sample)
    separate = cached_reported_separately(req)
    rates = load_implied_rates()
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

    rows = scored & frame["llm_request"]
    before = frame[scored]
    cheap = best_single_cheap_model(before, ctx, cached_separately=separate)
    kw = {
        "ctx": ctx,
        "premium_model": st["premium_model"],
        "cheap_model": cheap,
        "cached_separately": separate,
        "rates": rates,
    }

    def routing_part(after: pd.DataFrame, key: str) -> Decimal:
        """R-B3's own effect in ``key`` on the frame the router saw (``combine``
        keeps the tokens the router was given)."""
        return rb3.baseline_saving(after[rows], key, **kw)["saving:total"]

    def context_part(after: pd.DataFrame, key: str) -> Decimal:
        """R-B2's own effect in a repriced ``key``: logged tokens before, tokens
        lowered by the net tokens saved after (``repriced_savings``)."""
        logged = frame[rows].assign(
            ctx_tokens_saved=after.loc[rows, "ctx_tokens_saved"]
        )
        saved = rb2.repriced_savings(
            logged,
            ctx,
            premium_model=st["premium_model"],
            cached_separately=separate,
        )
        return saved["saving"][key]["token_cost"]

    out: dict[str, Any] = {"recorded": {}, "repriced": {}, "overlaps": {}, "checks": {}}
    for name, after in runs.items():
        sl = summarise_slices(before, after[scored])["llm_only"]
        rec = {
            key: sl[key] for key in ("saving:fees", "saving:token_cost", "saving:total")
        } | {"baseline:total": sl["baseline:total"]}
        if "route_reason" in after:
            routed = routing_part(after, "as_logged")
            rec["saving:routing_as_logged"] = routed
            rec["saving:total_with_routing"] = sl["saving:total"] + routed
            rec["steps"] = (
                "blocks lowered by cache and context; routing's as_logged saving at "
                "implied recorded rates added (its unknown rows out of its sum)"
            )
        out["recorded"][name] = rec
        if {"retrieval_reused", "route_reason", "ctx_tokens_saved"} <= set(after):
            out["overlaps"][name] = i1.overlaps(after[rows])
        if "retrieval_reused" in after:
            out["checks"][f"{name}.retrieval_rows_not_served"] = (
                i1.retrieval_rows_not_served(after)
            )
        repriced: dict[str, Any] = {}
        for key in REPRICED:
            parts: dict[str, Decimal] = {}
            if "ctx_tokens_saved" in after:
                parts["context"] = context_part(after, key)
            if "route_reason" in after:
                parts["routing"] = routing_part(after, key)
            if parts:
                repriced[key] = parts | {"total": sum(parts.values(), Decimal(0))}
            else:
                repriced[key] = i1.REASONS["cache"]
        out["repriced"][name] = repriced
    rules: dict[str, Any] = {}
    for label in RB2_SCENARIOS:
        rec = out["recorded"]
        rules[f"as_logged.{label}"] = i1.sum_rule(
            rec[f"combined.{label}"]["saving:total_with_routing"],
            [
                rec["cache_alone"]["saving:total"],
                rec[f"context_alone.{label}"]["saving:total"],
                rec["routing_alone"]["saving:routing_as_logged"],
            ],
        )
        for key in REPRICED:
            rep = out["repriced"]
            rules[f"{key}.{label}"] = i1.sum_rule(
                rep[f"combined.{label}"][key]["total"],
                [
                    rep[f"context_alone.{label}"][key]["total"],
                    rep["routing_alone"][key]["total"],
                ],
            )
    out["repriced_note"] = (
        "each step's own effect at each baseline's prices (ADR-0046 point 6 for "
        "routing, before minus after for context), so per-baseline savings add; "
        "in combined.* routing is priced on the post-context tokens it saw"
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
                "routing": f"R-B3 route.knn.k{k} (frozen default, primary "
                f"candidates), eligibility: {ELIGIBILITY}",
            },
            "units": i1.unit_cells(),
            "routing_after_context": "combined.*: PostContextRouting (input lowered by "
            "R-B2's net tokens saved); combined_today.*: combine as it is (routing "
            "reprices the logged input)",
            "best_single_cheap": cheap,
            **out,
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    _write(payload, out_root / I1_SUMMARY)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("task", choices=["rb3", "rb3-report", "i1"])
    parser.add_argument("--k", type=int, help="rb3-report: the frozen k")
    parser.add_argument("--sprint-config", type=Path, default=SPRINT_CONFIG)
    parser.add_argument("--out-root", type=Path, default=ROOT, help="smoke runs only")
    parser.add_argument(
        "--sample-sessions", type=float, default=None, help="smoke only"
    )
    args = parser.parse_args()
    st = settings(args.sprint_config)
    if args.task == "rb3":
        payload = cmd_rb3(st, args.out_root, args.sample_sessions)
    elif args.task == "rb3-report":
        if args.k is None:
            parser.error("rb3-report needs --k (the frozen k)")
        payload = cmd_rb3_report(st, args.out_root, args.sample_sessions, args.k)
    else:
        payload = cmd_i1(st, args.out_root, args.sample_sessions)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
