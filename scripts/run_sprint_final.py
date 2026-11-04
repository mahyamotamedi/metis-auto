"""I-1: the final combined run of the sprint's pipelines (plan I-1; ADR-0031,
ADR-0036; ADR-0061).

    .venv/bin/python scripts/run_sprint_final.py experiments/pipelines/sprint-final.toml
        [--only winners pipeline_a ...] [--sample 0.05 --out-root /scratch/dir]

Applies the frozen versions named in ``sprint-final.toml`` to the **report
split** (the one population, 73,063 requests) for A, B, C, Parham's routing-only
run and the provisional winners, against all four baselines. No setting is tuned
here. Each version is built the way its own runner builds it (their helpers are
loaded by path), and the engine in ``experiments/pipelines/sprint-final/run.py``
runs the steps alone and combined: recorded and repriced units are never added,
routing is priced on the post-context tokens (``PostContextRouting``), and the
sum rule must hold. Writes the content-free ``reports/pipelines/sprint-final/
summary.json``; it is not a ``LeverResult`` (a combined pipeline has no single
step). No network, no model call, no key, no spend: the run refuses unless the
router is off and live calls are disabled.

``--sample`` and ``--out-root`` are for smoke runs on a seeded share of sessions
into a scratch folder; they skip the population check.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import math
import platform
import sys
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from metis_auto.analysis.baselines_full import (
    best_single_cheap_model,
    cached_reported_separately,
    repriced_row_costs,
)
from metis_auto.analysis.replay_scope import scope, split_by_session
from metis_auto.settings import load_settings
from metis_auto.wiring.experiments import code_version

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments"
CONFIG = EXP / "pipelines" / "sprint-final.toml"
OUT = Path("reports/pipelines/sprint-final/summary.json")
TABLES = ROOT / "reports/full_eda/tables"
BASE = ("premium_gpt_5_5", "as_logged", "todays_models", "best_single_cheap")
ALL_PIPELINES = ("winners", "parham", "pipeline_c", "pipeline_a", "pipeline_b")
FRAME_COLS = ("block_fees", "block_token_cost")
ROUTING_NOTE = (
    "PostContextRouting: routing prices the input lowered by the context "
    "version's net saved tokens (stated assumption; the shared combine is not "
    "changed)"
)


def load(path: Path, name: str) -> Any:
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def script(name: str) -> Any:
    return load(ROOT / "scripts" / f"{name}.py", f"sprint_final_{name}")


SF = load(EXP / "pipelines/sprint-final/run.py", "sprint_final_engine")
Member = SF.Member


def decimal(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


def frames_saving(before: pd.DataFrame, after: pd.DataFrame, rows: pd.Series):
    """Saving of a before/after pair over the scored LLM rows with a known cost on
    both sides (a row unknown on either side leaves both: unknown is not 0)."""
    cols = list(FRAME_COLS)
    known = (
        rows.reindex(before.index, fill_value=False)
        & before["llm_request"].astype(bool)
        & before[cols].notna().all(axis=1)
        & after[cols].notna().all(axis=1)
    )
    diff = before.loc[known, cols].sum(axis=1) - after.loc[known, cols].sum(axis=1)
    return decimal(math.fsum(diff.to_numpy(dtype=float)))


class Prep:
    """Shared data, built lazily once (the report split is read once)."""

    def __init__(self, sample: float | None) -> None:
        self.sample = sample
        self.d3 = script("run_pipeline_b_day3")
        self.d2 = self.d3.D2
        self.st = self.d3.settings(self.d3.SPRINT_CONFIG)
        self.ctx = self.st["ctx"]
        self.sprint = tomllib.loads(self.d3.SPRINT_CONFIG.read_text(encoding="utf-8"))
        self._frame: pd.DataFrame | None = None
        self._cheap: str | None = None
        self._costs: pd.DataFrame | None = None

    # -- the frame ----------------------------------------------------------------

    @property
    def frame(self) -> pd.DataFrame:
        if self._frame is None:
            req = pd.read_parquet(self.d2.DERIVED / "requests.parquet")
            if self.sample is not None:  # smoke runs only: a seeded share of sessions
                share = 256 * self.sample
                keep = req["session_id"].map(
                    lambda s: (
                        hashlib.blake2b(str(s).encode(), digest_size=4).digest()[0]
                        < share
                    )
                )
                req = req[keep]
            req = scope(req, self.ctx)
            req["split"] = split_by_session(req, seed=self.st["seed"])
            keep = req["period"].isin(["tune", "report"]) | req["split"].eq("report")
            req = req[keep]
            rb1 = self.d3.load(self.d3.RB1)
            self._frame = rb1.fee_blocks(req, self.per_call)
        return self._frame

    @property
    def scored(self) -> pd.Series:
        return self.frame["split"].eq("report")

    @property
    def llm(self) -> pd.DataFrame:
        return self.frame[self.frame["llm_request"].astype(bool)]

    @property
    def per_call(self) -> pd.DataFrame:
        if not hasattr(self, "_per_call"):
            self._per_call = self.d2.per_call_items()
        return self._per_call

    @property
    def sep(self) -> frozenset[str]:
        if not hasattr(self, "_sep"):
            self._sep = cached_reported_separately(self.frame)
        return self._sep

    @property
    def cheap(self) -> str:
        if self._cheap is None:
            self._cheap = best_single_cheap_model(
                self.frame[self.scored], self.ctx, cached_separately=self.sep
            )
        return self._cheap

    @property
    def row_costs(self) -> pd.DataFrame:
        """Per-row repriced cost of each repriced baseline on the logged tokens."""
        if self._costs is None:
            self._costs = repriced_row_costs(
                self.frame,
                self.ctx,
                premium_model=self.st["premium_model"],
                cached_separately=self.sep,
                cheap_model=self.cheap,
            )
        return self._costs

    # -- ledger values ------------------------------------------------------------

    @property
    def coef(self) -> float:
        ledger = pd.read_csv(TABLES / "claims_ledger.csv").set_index("claim_id")
        return float(ledger.loc["recon.t0rag.coef_rag", "value"])

    def implied(self, column: str = "implied_input_per_M") -> dict[str, float]:
        rates = pd.read_csv(TABLES / "implied_unit_rates.csv").set_index("model")
        return rates[column].dropna().astype(float).to_dict()

    def chunks(self, columns: list[str], ids: set[str] | None = None) -> pd.DataFrame:
        wanted = set(self.llm["ai_message_id"]) if ids is None else ids
        parts = []
        for f in sorted((self.d2.DERIVED / "chunks").glob("*.parquet")):
            part = pd.read_parquet(f, columns=columns)
            parts.append(part[part["message_id"].isin(wanted)])
        return pd.concat(parts, ignore_index=True)


# --- one builder per version --------------------------------------------------------


def block_diff(before, after, baseline, rows):
    return frames_saving(before, after, rows)


def build_pq(p: Prep) -> Any:
    rp = script("run_popular_question")
    pq = p.sprint["cache"]["popular_question"]
    cache = rp.load_cache_class()(
        pq["window_days"],
        pq["min_count"],
        pq["min_sessions"],
        "first_turn",
        rp.KEY_VERSION,
        ttl_hours=None,
    )

    def part(before, after, baseline, rows):
        if baseline == "as_logged":
            return frames_saving(before, after, rows)
        hits = after["served_from_cache"].fillna(False).astype(bool)
        if "served_from_cache" in before:
            hits &= ~before["served_from_cache"].fillna(False).astype(bool)
        cost = p.row_costs[baseline]
        known = rows & before["llm_request"].astype(bool) & hits & cost.notna()
        return decimal(math.fsum(cost[known].to_numpy(dtype=float)))

    return Member(
        "cache",
        "cache.popular_question.first_turn",
        cache,
        part,
        kind="answer_cache",
        extra={"guard": rp.make_guard()},
    )


def build_rb1(p: Prep) -> Any:
    rb1 = p.d3.load(p.d3.RB1)
    llm = p.llm
    lookups = rb1.build_lookups(
        llm, p.d2.rag_json(set(llm["ai_message_id"])), p.per_call, scope="user"
    )
    cache = rb1.version.RetrievalResultCache(
        pd.Timedelta(days=1), lookups=lookups, shadow_rate=p.st["shadow_rate"]
    )
    return Member(
        "cache",
        "retrieval_result_cache.ttl_1d",
        cache,
        lambda b, a, base, rows: frames_saving(b, a, rows),
        units=("as_logged",),
        kind="retrieval_cache",
        touched=lambda out: out["retrieval_reused"].astype("boolean").fillna(False),
        extra={"guard": p.ctx.guard},
    )


def build_memo(p: Prep) -> Any:
    sm = script("session_memo_levers")
    v = sm._version()
    summary = json.loads(
        (ROOT / "reports/caching/exp-cache-004/summary.json").read_text()
    )
    threshold = summary["chosen_threshold"]
    ids = set(p.llm["ai_message_id"])
    fps = pd.read_parquet(sm.QUERY_FPS)
    lookups = v.build_lookups(
        p.frame,
        fps[fps["message_id"].isin(ids)],
        p.chunks(["message_id", "chunk_id", "h_exact", "n_chars"], ids),
        p.per_call,
    )
    memo = v.SessionMemo(
        threshold,
        frozenset(p.sprint["phatic"]["words"]),
        lookups=lookups,
        tokens_per_char=p.coef,
        input_rate_per_m=p.implied(),
        cached_separately=p.sep,
    )

    def part(before, after, baseline, rows):
        b, a = v.baseline_frames(
            before,
            after,
            p.ctx,
            baseline=baseline,
            premium_model=p.st["premium_model"],
            cached_separately=p.sep,
            cheap_model=p.cheap,
        )
        return frames_saving(b, a, rows)

    from metis_auto.analysis.cache_guard import CacheGuard

    guard = CacheGuard(
        approved=None,
        blocked=frozenset(),
        disabled_bots=frozenset(),
        key_version=sm.GUARD_KEY_VERSION,
    )
    return Member(
        "cache",
        "cache.session_memo_gate",
        memo,
        part,
        units=("as_logged",),
        kind="retrieval_cache",
        touched=lambda out: out["memo_status"].isin(["reused", "skipped_phatic"]),
        extra={"guard": guard},
    )


def build_dedup(p: Prep) -> Any:
    mod = load(
        EXP / "context/exp-ctx-001-within-message-dedup/version.py",
        "sprint_final_exp_ctx_001",
    )
    dedup = mod.WithinMessageDedup(
        p.chunks(["message_id", "h_exact", "n_chars"]),
        tokens_per_char=p.coef,
        input_rate_per_m=p.implied(),
        cached_separately=p.sep,
    )

    def part(before, after, baseline, rows):
        b, a = mod.baseline_frames(
            before,
            after,
            p.ctx,
            baseline=baseline,
            premium_model=p.st["premium_model"],
            cached_separately=p.sep,
            cheap_model=p.cheap,
        )
        return frames_saving(b, a, rows)

    return Member(
        "context",
        "ctx.within_message_dedup",
        dedup,
        part,
        saved_column=mod.SAVED_TOKENS,
    )


def build_rc(p: Prep) -> Any:
    rc = script("run_reranker_cut")
    mo = script("measure_lever_overhead")
    cfg = tomllib.loads(
        (EXP / "context/exp-ctx-003-reranker-cut/config.toml").read_text()
    )["reranker_cut"]
    floor, threshold, top_k = mo.headline_point(
        pd.read_csv(mo.CURVE), "observed_relevancy"
    )
    cut = rc.load_version_class()(
        None,
        floor,
        threshold,
        top_k,
        chunks=rc.read_chunks(p.llm["ai_message_id"], with_text=False),
        tokens_per_char=float(cfg["tokens_per_char"]),
        queries=None,
        cached_separately=p.sep,
    )
    rates = p.implied()

    def part(before, after, baseline, rows):
        b, a = cut.baseline_frames(
            before,
            after,
            p.ctx,
            baseline=baseline,
            premium_model=p.st["premium_model"],
            cheap_model=p.cheap,
            input_rate_per_m=rates,
            cached_separately=p.sep,
        )
        return frames_saving(b, a, rows)

    return Member(
        "context",
        "context.reranker_cut.observed_relevancy",
        cut,
        part,
        saved_column="rc_saved_tokens",
        recorded_rates=rates,  # rc prices its recorded saving outside apply
    )


def build_rb2(p: Prep) -> Any:
    rb2 = p.d3.load(p.d3.RB2)
    items = pd.read_parquet(
        p.d2.RAW / "derived" / "chat_message_billing.parquet",
        columns=["message_id", "inputTokens", "costBreakdown.input_tokens"],
    )
    llm = p.llm
    chunks = rb2.build_chunks(
        llm, p.chunks(["message_id", "chunk_id", "n_chars", "h_exact"])
    )
    policy = rb2.version.CrossTurnChunkPolicy(
        8, lambda d: d <= 1, False, chunks=chunks, tokens_per_char=p.coef
    )

    def part(before, after, baseline, rows):
        if baseline == "as_logged":
            return frames_saving(before, after, rows)
        logged = before[rows.reindex(before.index, fill_value=False)].assign(
            ctx_tokens_saved=after["ctx_tokens_saved"]
        )
        saved = rb2.repriced_savings(
            logged,
            p.ctx,
            premium_model=p.st["premium_model"],
            cached_separately=p.sep,
        )
        return saved["saving"][baseline]["token_cost"]

    return Member(
        "context",
        "cross_turn_chunks.ptr8.k1",
        policy,
        part,
        saved_column="ctx_tokens_saved",
        extra={
            "prep": lambda frame: rb2.request_inputs(frame, items, p.sep),
        },
    )


def routing_member(p: Prep, name: str, version: Any, frames_fn: Callable) -> Any:
    def part(before, after, baseline, rows):
        b, a = frames_fn(before, after, baseline)
        return frames_saving(b, a, rows)

    return Member("routing", name, version, part)


def build_per_bot(p: Prep) -> Any:
    rp = script("run_per_bot_reassignment")
    tune = p.frame[p.frame["split"].eq("tune") & p.frame["period"].eq("tune")]
    rates = rp.load_implied_rates()
    fitted = rp.fit_version(
        p.sprint,
        tune,
        p.ctx,
        p.sep,
        premium_model=p.st["premium_model"],
        cheap_model=p.cheap,
        rates=rates,
    )
    module = rp._version_module(fitted)

    def frames(before, after, baseline):
        return module.baseline_frames(
            before,
            after,
            p.ctx,
            fitted,
            baseline=baseline,
            premium_model=p.st["premium_model"],
            cheap_model=p.cheap,
            cached_separately=p.sep,
            rates=rates,
        )

    return routing_member(p, "route.per_bot", fitted, frames)


def build_knn(p: Prep) -> Any:
    rb3 = p.d3.load(p.d3.RB3)
    train = p.frame[p.frame["split"].eq("tune") & p.frame["llm_request"].astype(bool)]
    train = train[train["period"].eq("tune")]
    router = p.d3._factory(p.st, p.sep)(train, 5)
    rates = p.d3.load_implied_rates()

    def frames(before, after, baseline):
        merged = before.copy()
        for c in after.columns:
            if c not in merged.columns:
                merged[c] = after[c]
        return rb3.version.baseline_frames(
            merged,
            merged,
            p.ctx,
            baseline=baseline,
            premium_model=p.st["premium_model"],
            cheap_model=p.cheap,
            cached_separately=p.sep,
            rates=rates,
        )

    return routing_member(p, "route.knn.k5", router, frames)


def build_classifier(p: Prep) -> Any:
    sc = script("small_classifier_levers")
    c12 = sc._version()
    version = sc.make_versions(
        p.sprint["routing"],
        p.ctx.catalogue,
        max_u_chars=sc.MAX_U_CHARS,
        max_input_tokens=sc.MAX_INPUT_TOKENS,
        cached_separately=p.sep,
    )["primary"]
    rates = sc.load_rates(TABLES / "implied_unit_rates.csv")

    def frames(before, after, baseline):
        return c12.baseline_frames(
            before,
            after,
            p.ctx,
            baseline=baseline,
            premium_model=p.st["premium_model"],
            cached_separately=p.sep,
            cheap_model=p.cheap,
            rates=rates,
        )

    return routing_member(p, "route.small_classifier.rules", version, frames)


def build_router(p: Prep) -> Any:
    from metis_auto.wiring.from_settings import pipeline_config

    dr = script("decision_router_levers")
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    dr.rules_only.require_offline(loaded.settings)
    tiers = dr.rules_only.rules_only_tiers(
        p.frame, pd.read_parquet(dr.FLAGS), pipeline_config(loaded)
    )
    c12, v13 = dr._classifier(), dr._router()
    cat = p.ctx.catalogue
    primary = c12.candidate_sets(p.sprint["routing"], cat)["primary"]
    version = v13.DecisionRouterRouting(
        tiers=tiers,
        tier_of={
            str(m["model_id"]): int(m["tier"])
            for m in cat.get("models", [])
            if m.get("tier") is not None
        },
        rules={
            **p.sprint["routing"],
            "candidates": list(primary),
            "candidates_jev": [],
        },
        cached_separately=p.sep,
        name=dr.VERSION_ID,
    )
    rates = dr.load_rates(TABLES / "implied_unit_rates.csv")

    def frames(before, after, baseline):
        return c12.baseline_frames(
            before,
            dr._accounting_frame(after, c12),
            p.ctx,
            baseline=baseline,
            premium_model=p.st["premium_model"],
            cached_separately=p.sep,
            cheap_model=p.cheap,
            rates=rates,
        )

    return routing_member(p, "route.decision_router.rules_only", version, frames)


BUILDERS: dict[str, Callable[[Prep], Any]] = {
    "cache.popular_question.first_turn": build_pq,
    "retrieval_result_cache.ttl_1d": build_rb1,
    "cache.session_memo_gate": build_memo,
    "context.reranker_cut.observed_relevancy": build_rc,
    "cross_turn_chunks.ptr8.k1": build_rb2,
    "ctx.within_message_dedup": build_dedup,
    "route.per_bot": build_per_bot,
    "route.knn.k5": build_knn,
    "route.small_classifier.rules": build_classifier,
    "route.decision_router.rules_only": build_router,
}


# --- the run ------------------------------------------------------------------------


def run_one(p: Prep, name: str, spec: dict[str, str]) -> dict[str, Any]:
    members = [
        BUILDERS[spec[s]](p) for s in ("cache", "context", "routing") if s in spec
    ]
    frame = p.frame
    for m in members:
        prep = m.extra.get("prep")
        if prep is not None:
            frame = prep(frame)
    ctx = p.ctx
    for m in members:
        if m.step == "cache" and "guard" in m.extra:
            ctx = dataclasses.replace(ctx, guard=m.extra["guard"])
    scored = frame["split"].eq("report")
    out = SF.run_pipeline(name, frame, scored, members, ctx, BASE)
    SF.require_sum_rule(
        {b: r["sum_rule"] for b, r in out["baselines"].items() if r["sum_rule"]}
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("config", type=Path, nargs="?", default=CONFIG)
    ap.add_argument("--only", nargs="+", choices=ALL_PIPELINES)
    ap.add_argument("--sample", type=float)
    ap.add_argument("--out-root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    loaded = load_settings(environ={}, dotenv=None, runtime=None)  # no .env read
    script("decision_router_levers").rules_only.require_offline(loaded.settings)
    config = tomllib.loads(args.config.read_text(encoding="utf-8"))
    p = Prep(args.sample)
    expected = int(config["population"]["expected_requests"])
    if args.sample is None:
        n = SF.check_population(p.scored, expected=expected)
    else:
        n = int(p.scored.sum())
    summary: dict[str, Any] = {
        "task": "I-1: the pipelines' combined run on the report split",
        "status": config["status"],
        "note": config["note"],
        "population": {
            "split": config["population"]["split"],
            "scored_requests": n,
            "llm_requests": int((p.scored & p.frame["llm_request"].astype(bool)).sum()),
            "history_rows": len(p.frame),
            "sample": args.sample,
            "timestamps": "naive (Q-06)",
        },
        "baselines": list(BASE),
        "best_single_cheap": p.cheap,
        "routing_after_context": ROUTING_NOTE,
        "units": "recorded (as_logged) and price-file units are never added; a step "
        "without a figure in a baseline's units is 'not computed', never 0",
        "pipelines": {},
        "skipped": {},
        "not_run": config.get("not_run", {}),
        "runners_up": config.get("runners_up", {}),
        "code_commit": code_version(ROOT).commit or "unknown",
        "python": platform.python_version(),
        "created_at": datetime.now(UTC).isoformat(),
    }
    out_path = args.out_root / OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if args.only and out_path.exists():  # keep the pipelines already run
        previous = json.loads(out_path.read_text(encoding="utf-8"))
        if previous.get("population", {}).get("sample") == args.sample:
            summary["pipelines"] = dict(previous.get("pipelines", {}))
    for name in args.only or ALL_PIPELINES:
        spec = {
            k: v
            for k, v in config[name].items()
            if k in ("cache", "context", "routing")
        }
        started = datetime.now(UTC)
        try:
            summary["pipelines"][name] = run_one(p, name, spec)
            print(f"{name}: done in {(datetime.now(UTC) - started).seconds} s")
        except Exception as exc:  # noqa: BLE001 - recorded, never silent
            summary["skipped"][name] = f"{type(exc).__name__}: {str(exc)[:200]}"
            print(f"{name}: SKIPPED {summary['skipped'][name]}")
        out_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    return 1 if summary["skipped"] and not summary["pipelines"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
