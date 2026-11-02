"""Run the reranker cut (exp-ctx-003) on the full data: a token-sizing curve (R-A2).

Reads ``data/derived/full_eda/requests.parquet`` and the derived chunk table
``data/derived/full_eda/chunks/`` (no text; local, git-ignored), applies C's
``replay_scope.scope`` and ``levers.with_blocks``, and runs two scorers:

- ``observed_relevancy``: the platform's own ``relevancy``; every eligible
  request of the tune and report periods (no text read);
- ``lexical_overlap``: word overlap of the user message with each chunk
  (*heuristic*), on a seeded sample of eligible requests per period. Chunk text
  (``data/full_data/raw/data/derived/chat_message_rag_chunks-*``) and user text
  (``chat_message-*``) are read **in memory only** and never written or printed.

For each scorer: thresholds are quantiles of the unique-chunk scores of the
**tune** period (``config.toml``); the curve covers every top_k of the grid (and
none) x every threshold (and none), with the floor, on both periods; the
headline point is chosen on the tune period by the rule in ``config.toml`` and
reported on the report period, read once per point. Outputs (content-free):
one ``LeverResult`` per scorer and baseline (``BASELINE_KEYS``), written as
``context.reranker_cut.<scorer>.<baseline>.json``: ``as_logged`` at each model's
implied input rate (recorded units), the three repriced baselines with
``baselines_full.repriced_row_costs`` (price-file units; ADR-0038), and the
curve as ``reports/levers/context.reranker_cut.curve.csv`` (cost at
``todays_models``). S-6 dedup runs first and its
tokens are reported apart, never in the saving.

Traces: H-2, X5, FR-CTX-02, FR-CTX-03, ADR-0031, ADR-0032. Usage:
``.venv\\Scripts\\python.exe scripts/run_reranker_cut.py [--out DIR]
[--scorers observed_relevancy lexical_overlap]``.
"""

from __future__ import annotations

import argparse
import math
import platform
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from metis_auto.analysis.baselines_full import (
    BASELINE_KEYS,
    REPRICED_KEYS,
    best_single_cheap_model,
    cached_reported_separately,
)
from metis_auto.analysis.lever_result import LeverResult, Manifest, build_manifest
from metis_auto.analysis.levers import (
    ReplayContext,
    combine,
    summarise_slices,
    with_blocks,
)
from metis_auto.analysis.replay_scope import period_bounds_from_config, scope
from metis_auto.analysis.stats import cluster_bootstrap_ratio
from metis_auto.settings import StrategySettings, StrategySlot
from metis_auto.wiring.experiments import code_version, load_candidate

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "data" / "derived" / "full_eda" / "requests.parquet"
CHUNKS = ROOT / "data" / "derived" / "full_eda" / "chunks"
RAW = ROOT / "data" / "full_data" / "raw" / "data"
SPRINT = ROOT / "config" / "evaluation" / "sprint.toml"
EXPERIMENT_DIR = ROOT / "experiments" / "context" / "exp-ctx-003-reranker-cut"
CONFIG = EXPERIMENT_DIR / "config.toml"
OUT_DIR = ROOT / "reports" / "levers"
CURVE_NAME = "context.reranker_cut.curve.csv"
RATES = ROOT / "reports" / "full_eda" / "tables" / "implied_unit_rates.csv"
RATES_VERSION = "full-eda-implied-unit-rates"  # as S-6b's as_logged manifests

BASELINE = "todays_models"  # the curve's cost
COST_KEYS = ("fees", "token_cost", "total")
SAVING_UNKNOWN = "rc_saving_unknown"  # set by RerankerCut.baseline_frames
SCORERS = ("observed_relevancy", "lexical_overlap")
CHUNK_COLUMNS = ["message_id", "chunk_id", "h_exact", "n_chars", "relevancy"]
NONE = "none"


# --- loading -----------------------------------------------------------------------


def _load(obj: str):
    spec = StrategySettings(
        slot=StrategySlot.CANDIDATE_INDEX,  # unused for a file; no lever slot yet
        file="version.py",
        object=obj,
    )
    return load_candidate(spec, EXPERIMENT_DIR, ROOT / "experiments")


def load_version_class() -> type:
    return _load("RerankerCut")


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


def rag_candidates(req: pd.DataFrame) -> pd.Series:
    """LLM requests with RAG state ``ok`` and chunks: the version's eligibility
    before the chunk join (it checks the join itself)."""
    return (
        req["llm_request"].astype(bool)
        & req["a_rag_state"].eq("ok")
        & req["a_rag_n_chunks"].fillna(0).gt(0)
    )


def read_chunks(message_ids, *, with_text: bool = False) -> pd.DataFrame:
    """Derived chunk rows of these AI messages, in logged order; with
    ``with_text`` the raw ``content`` is attached (in memory only)."""
    ids = sorted({str(m) for m in message_ids})
    files = sorted(str(p) for p in CHUNKS.glob("*.parquet"))
    derived = (
        ds.dataset(files, format="parquet")
        .to_table(columns=CHUNK_COLUMNS, filter=ds.field("message_id").isin(ids))
        .to_pandas()
    )
    if not with_text:
        return derived
    raw_files = sorted(
        str(p) for p in (RAW / "derived").glob("chat_message_rag_chunks-*.parquet")
    )
    raw = (
        ds.dataset(raw_files, format="parquet")
        .to_table(
            columns=["message_id", "chunk_id", "content"],
            filter=ds.field("message_id").isin(ids),
        )
        .to_pandas(ignore_metadata=True)
    )
    return attach_content(derived, raw)


def read_queries(req: pd.DataFrame) -> dict[str, str]:
    """User message text by ``ai_message_id`` (in memory only)."""
    ids = sorted({str(m) for m in req["user_message_id"].dropna()})
    files = sorted(str(p) for p in RAW.glob("chat_message-*.parquet"))
    table = ds.dataset(files, format="parquet").to_table(
        columns=["message_id", "content"], filter=ds.field("message_id").isin(ids)
    )
    text = dict(
        zip(table["message_id"].to_pylist(), table["content"].to_pylist(), strict=True)
    )
    pairs = zip(req["ai_message_id"], req["user_message_id"], strict=True)
    return {
        str(a): text[str(u)]
        for a, u in pairs
        if pd.notna(u) and isinstance(text.get(str(u)), str)
    }


# --- pure helpers (tested) -----------------------------------------------------------


def implied_input_rates(table: pd.DataFrame) -> dict[str, float]:
    """``implied_input_per_M`` by model (recorded units); a model without one is
    left out, so its as_logged saving is unknown (ADR-0038)."""
    rates = table.dropna(subset=["implied_input_per_M"]).set_index("model")
    return rates["implied_input_per_M"].astype(float).to_dict()


def attach_content(derived: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """Join raw ``content`` to derived rows by message and position (the derived
    table keeps the raw order, checked 2026-11-02); ``chunk_id`` must agree."""
    d = derived.reset_index(drop=True)
    r = raw.reset_index(drop=True)
    d["_pos"] = d.groupby("message_id", sort=False).cumcount()
    r["_pos"] = r.groupby("message_id", sort=False).cumcount()
    m = d.merge(
        r.rename(columns={"chunk_id": "_raw_chunk_id"}),
        on=["message_id", "_pos"],
        how="left",
        validate="one_to_one",
    )
    bad = int((m["_raw_chunk_id"].astype(str) != m["chunk_id"].astype(str)).sum())
    if bad:
        raise RuntimeError(f"{bad} chunk rows: raw and derived chunk_id differ")
    return m.drop(columns=["_pos", "_raw_chunk_id"])


def sample_requests(
    req: pd.DataFrame, mask: pd.Series, n: int, *, seed: int
) -> pd.DataFrame:
    pool = req[mask.reindex(req.index).fillna(False).astype(bool)]
    return pool.sample(n=min(n, len(pool)), random_state=seed).sort_index()


def threshold_grid(scores: pd.Series, quantiles) -> dict[str, float]:
    known = scores.dropna().astype(float)
    return {
        f"q{round(q * 100):02d}": round(float(known.quantile(q)), 6) for q in quantiles
    }


def grid_points(top_ks, thresholds: dict[str, float]) -> list[tuple]:
    rules = [(NONE, None), *thresholds.items()]
    return [(k, rule, value) for k in (*top_ks, None) for rule, value in rules]


@dataclass(frozen=True)
class Pricing:
    """What ``RerankerCut.baseline_frames`` needs besides the frames."""

    ctx: ReplayContext
    premium_model: str
    cheap_model: str
    cached_separately: frozenset[str] = frozenset()
    rates: Mapping[str, float] | None = None
    """Implied input rate per 1M tokens by model (recorded units), for as_logged."""

    def frames(self, version, req: pd.DataFrame, out: pd.DataFrame, baseline: str):
        return version.baseline_frames(
            req,
            out,
            self.ctx,
            baseline=baseline,
            premium_model=self.premium_model,
            cheap_model=self.cheap_model,
            input_rate_per_m=self.rates,
            cached_separately=self.cached_separately,
        )


def _row_saving(before: pd.DataFrame, after: pd.DataFrame):
    """Rows with a known cost on both sides: (known, saving, baseline total)."""
    cols = ["block_fees", "block_token_cost"]
    known = before["llm_request"].astype(bool) & before[cols].notna().all(axis=1)
    base = before.loc[known, cols].sum(axis=1)
    return known, base - after.loc[known, cols].sum(axis=1), base


def _ratio(num: float, den: float) -> float:
    return num / den if den else math.nan


def point_metrics(
    version, req: pd.DataFrame, out: pd.DataFrame, *, seed: int, pricing: Pricing
) -> dict:
    """Aggregates of one curve point; cost at ``todays_models`` (LLM rows with a
    known repriced cost)."""
    ok = out["rc_eligible"].fillna(False).astype(bool)
    e = out[ok]
    unique_chars = float((e["rc_raw_chars"] - e["rc_dup_chars"]).sum())
    known, row_saving, row_base = _row_saving(
        *pricing.frames(version, req, out, BASELINE)
    )
    saving, base = row_saving.to_numpy(float), row_base.to_numpy(float)
    sessions = req.loc[known, "session_id"].astype(str).to_numpy()
    est, lo, hi = cluster_bootstrap_ratio(saving, base, sessions, seed=seed)
    return {
        "eligible_requests": int(ok.sum()),
        "eligible_cost_known": int((ok & known).sum()),
        "unscored_chunks": int(e["rc_n_unscored"].sum()),
        "raw_chunk_tokens": float(e["rc_raw_chunk_tokens"].sum()),
        "dedup_tokens_s6_not_counted": float(e["rc_dedup_tokens"].sum()),
        "saved_input_tokens": float(e["rc_saved_tokens"].sum()),
        "chunk_share_removed": _ratio(float(e["rc_cut_chars"].sum()), unique_chars),
        "score_mass_kept": _ratio(
            float(e["rc_score_kept"].sum()), float(e["rc_score_total"].sum())
        ),
        "cost_share_saved": est,
        "ci_low": lo,
        "ci_high": hi,
    }


def curve(
    version,
    req: pd.DataFrame,
    ctx: ReplayContext,
    thresholds: dict[str, float],
    *,
    top_ks,
    floor: int,
    seed: int,
    pricing: Pricing,
) -> pd.DataFrame:
    rows = []
    for top_k, rule, value in grid_points(top_ks, thresholds):
        v = version.with_params(floor=floor, threshold=value, top_k=top_k)
        out = combine(req, None, v, None, ctx)
        rows.append(
            {"top_k": top_k, "threshold_rule": rule, "threshold": value, "floor": floor}
            | point_metrics(v, req, out, seed=seed, pricing=pricing)
        )
    return pd.DataFrame(rows).astype({"top_k": object, "threshold": object})


def choose_headline(tune: pd.DataFrame, *, min_mass: float) -> tuple[pd.Series, bool]:
    """Most tokens saved with score mass kept >= ``min_mass``; ties: larger top_k
    (none = largest), then lower threshold (none = lowest). Else the gentlest."""
    t = tune.assign(
        _k=tune["top_k"].map(lambda k: math.inf if k is None or pd.isna(k) else k),
        _thr=tune["threshold"].map(
            lambda x: -math.inf if x is None or pd.isna(x) else x
        ),
    )
    ok = t[t["score_mass_kept"] >= min_mass]
    if ok.empty:
        gentle = t[t["_k"] != math.inf].sort_values(
            ["_k", "_thr"], ascending=[False, True]
        )
        return gentle.iloc[0].drop(["_k", "_thr"]), False
    best = ok.sort_values(
        ["saved_input_tokens", "_k", "_thr"], ascending=[False, False, True]
    )
    return best.iloc[0].drop(["_k", "_thr"]), True


def _dec(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


def headline_result(
    version,
    req: pd.DataFrame,
    out: pd.DataFrame,
    manifest: Manifest,
    *,
    pricing: Pricing,
    extra: tuple[str, ...],
    baseline: str = BASELINE,
) -> LeverResult:
    """The scorer's ``LeverResult`` against one baseline. ``as_logged`` is in
    recorded units with ``fees``; a repriced baseline is in price-file units and
    its ``baseline_cost`` has no ``fees`` key (ADR-0036). ``saving.fees`` is 0."""
    before, after = pricing.frames(version, req, out, baseline)
    slices = summarise_slices(before, after)
    llm = req["llm_request"].astype(bool)
    known, row_saving, row_base = _row_saving(before, after)
    ok = out["rc_eligible"].fillna(False).astype(bool)
    unknown = after[SAVING_UNKNOWN]
    drop = ("n_cache_hits", "cache_hit_rate")
    if baseline in REPRICED_KEYS:
        drop += ("baseline:fees",)
    for name, rows in (("all", pd.Series(True, index=req.index)), ("llm_only", llm)):
        s = slices[name]
        for key in drop:
            s.pop(key, None)
        s["n_saving_unknown"] = Decimal(int((rows & unknown).sum()))
        e = out[rows & ok]  # tokens need no price: every eligible row
        s["n_eligible"] = Decimal(int((rows & ok).sum()))
        s["n_eligible_cost_known"] = Decimal(int((rows & ok & known).sum()))
        s["raw_chunk_tokens"] = _dec(float(e["rc_raw_chunk_tokens"].sum()))
        s["dedup_tokens_s6_not_counted"] = _dec(float(e["rc_dedup_tokens"].sum()))
        s["saved_input_tokens"] = _dec(float(e["rc_saved_tokens"].sum()))
        s["unscored_chunks"] = Decimal(int(out.loc[rows & ok, "rc_n_unscored"].sum()))
    top = slices["llm_only"]
    sessions = req.loc[known, "session_id"].astype(str).to_numpy()
    _, lo, hi = cluster_bootstrap_ratio(
        row_saving.to_numpy(float),
        row_base.to_numpy(float),
        sessions,
        seed=manifest.seed,
    )
    return LeverResult(
        lever_id=version.lever_id,
        step="context",
        version=version.version,
        n_requests=len(req),
        n_eligible=int(ok.sum()),
        baseline=baseline,
        baseline_cost={
            b: top[f"baseline:{b}"] for b in COST_KEYS if f"baseline:{b}" in top
        },
        saving={b: top[f"saving:{b}"] for b in COST_KEYS},
        ci_low=None if math.isnan(lo) else lo,
        ci_high=None if math.isnan(hi) else hi,
        slices=slices,
        evidence_class=version.evidence_class,
        correctness_state="unmeasured",
        assumptions=tuple(version.assumptions)
        + baseline_assumptions(baseline, pricing)
        + extra,
        manifest=manifest,
    )


def baseline_assumptions(baseline: str, pricing: Pricing) -> tuple[str, ...]:
    """The ``Unit:`` line of one baseline and how the cut is priced in it."""
    if baseline == "as_logged":
        return (
            "Unit: recorded units (as_logged). Fees never change (ADR-0038).",
            "as_logged saving = the cut's tokens x the logged model's "
            "implied_input_per_M / 1e6 (reports/full_eda/tables/implied_unit_rates.csv)"
            ", off the recorded token block after S-6's share.",
            "A model without an implied rate makes the saving unknown: the row leaves "
            "both sides (n_saving_unknown), never zero.",
        )
    priced_at = {
        "premium_gpt_5_5": f"{pricing.premium_model}'s price: an estimate only, the "
        "model is never called (ADR-0026).",
        "todays_models": "its logged model's price. Only sprint-catalogue models are "
        "priced (n_eligible_cost_known); gemini-2.5-flash is not, so the cost share "
        "is of a small, unrepresentative subset.",
        "best_single_cheap": f"{pricing.cheap_model}, the cheapest callable model "
        "over the report period (cost only; capability and quality not checked).",
    }[baseline]
    return (
        f"Unit: price-file units ({baseline}). Fees are not priced, so baseline_cost "
        "has no fees key (ADR-0036).",
        "Logged tokens less the removed tokens are repriced with the price table's "
        f"tiers (tier chosen again); every request at {priced_at}",
    )


def write_results(
    version,
    req: pd.DataFrame,
    out: pd.DataFrame,
    manifest_for: Callable[[str], Manifest],
    *,
    pricing: Pricing,
    extra: tuple[str, ...],
    out_dir: Path,
) -> list[Path]:
    """One ``LeverResult`` per baseline, written as
    ``<lever_id>.<baseline>.json`` (the file naming of S-6b's results)."""
    paths = []
    for baseline in BASELINE_KEYS:
        result = headline_result(
            version,
            req,
            out,
            manifest_for(baseline),
            pricing=pricing,
            extra=extra,
            baseline=baseline,
        )
        path = out_dir / f"{result.lever_id}.{baseline}.json"
        path.write_text(result.to_json(), encoding="utf-8")
        paths.append(path)
    return paths


def run_assumptions(
    rule: str, *, mass: float, min_mass: float, passed: bool, sample: int | None
) -> tuple[str, ...]:
    """Run-level assumptions of a headline result (short authored statements)."""
    notes = (
        f"Headline chosen on the tune period (Mar-Jul 2026): {rule}; most tokens "
        f"saved with score mass kept >= {min_mass} (tune {mass:.3f}); rule met: "
        f"{passed}. Reported on Aug-Oct 2026.",
        "Slices all and llm_only; workflow rows have no cost. Tokens cover every "
        "eligible request; cost only those with a known cost (n_eligible_cost_known).",
        "Cached tokens: the saving uses characters, not a_bill_inputTokens; the "
        "repriced baselines add cached tokens back for the five models (Review "
        "Focus 3).",
        "Removed tokens are priced as uncached input (chunks assumed after the "
        "cached prefix); the saving is capped at input minus cached tokens.",
    )
    if sample is not None:
        notes += (
            f"Lexical: seeded sample of {sample:,} eligible report-period requests; "
            "slices all and llm_only are that sample, so the cost share is of RAG "
            "requests only (observed: of all LLM requests).",
        )
    return notes


# --- main ----------------------------------------------------------------------------


def _rule_text(point: pd.Series) -> str:
    k = (
        "none"
        if point["top_k"] is None or pd.isna(point["top_k"])
        else int(point["top_k"])
    )
    thr = point["threshold_rule"]
    value = "" if thr == NONE else f" ({float(point['threshold']):.4f})"
    return f"top_k {k}, threshold {thr}{value}, floor {int(point['floor'])}"


def _shown(path: Path) -> Path:
    """Path relative to the repository when inside it (``--out`` may be outside)."""
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="result folder")
    parser.add_argument("--scorers", nargs="+", choices=SCORERS, default=list(SCORERS))
    args = parser.parse_args(argv)

    sprint = load_toml(SPRINT)
    cfg = load_toml(CONFIG)["reranker_cut"]
    ctx = make_context(sprint)
    version = code_version(ROOT)
    commit = version.commit or "unknown"
    dirty = (
        ("The working tree had uncommitted changes when this ran.",)
        if version.dirty
        else ()
    )
    cls = load_version_class()
    lexical = _load("lexical_overlap")

    req = with_blocks(scope(pd.read_parquet(REQUESTS), ctx))
    cached_sep = cached_reported_separately(req)
    periods = {p: req[req["period"].eq(p)] for p in ("tune", "report")}
    for p, f in periods.items():
        print(
            f"{p}: {len(f):,} requests, {int(f['llm_request'].sum()):,} LLM, "
            f"{int(rag_candidates(f).sum()):,} RAG candidates"
        )
    premium = sprint["baselines"]["premium_model"]
    cheap = best_single_cheap_model(
        periods["report"], ctx, cached_separately=cached_sep
    )
    rates = implied_input_rates(pd.read_csv(RATES))
    pricing = Pricing(ctx, premium, cheap, cached_sep, rates)
    print(
        f"premium model {premium}; best single cheap (report period) {cheap}; "
        f"implied input rates for {len(rates)} models"
    )
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    curves = []

    for scorer_name in args.scorers:
        frames = dict(periods)
        if scorer_name == "lexical_overlap":
            frames = {
                p: sample_requests(
                    f, rag_candidates(f), int(cfg["lexical_sample"]), seed=ctx.seed
                )
                for p, f in periods.items()
            }
            both = pd.concat(frames.values())
            chunks = read_chunks(both["ai_message_id"], with_text=True)
            mismatch = int((chunks["content"].str.len() != chunks["n_chars"]).sum())
            print(f"\nlexical: text attached; length != n_chars on {mismatch:,} rows")
            base = cls(
                lexical,
                int(cfg["floor"]),
                None,
                None,
                chunks=chunks,
                tokens_per_char=float(cfg["tokens_per_char"]),
                queries=read_queries(both),
                cached_separately=cached_sep,
            )
            del chunks
        else:
            cand = pd.concat(f[rag_candidates(f)] for f in periods.values())
            base = cls(
                None,
                int(cfg["floor"]),
                None,
                None,
                chunks=read_chunks(cand["ai_message_id"]),
                tokens_per_char=float(cfg["tokens_per_char"]),
                cached_separately=cached_sep,
            )
        tune, report = frames["tune"], frames["report"]
        thresholds = threshold_grid(
            base.unique_scores(tune), cfg["threshold_quantiles"]
        )
        print(f"\n=== {base.lever_id} ===\nthresholds (tune quantiles): {thresholds}")
        grids = {}
        for p, f in (("tune", tune), ("report", report)):
            c = curve(
                base,
                f,
                ctx,
                thresholds,
                top_ks=tuple(cfg["top_k_grid"]),
                floor=int(cfg["floor"]),
                seed=ctx.seed,
                pricing=pricing,
            )
            c.insert(0, "period", p)
            c.insert(0, "scorer", scorer_name)
            grids[p] = c
        pick, passed = choose_headline(
            grids["tune"], min_mass=cfg["min_score_mass_kept"]
        )
        rule = _rule_text(pick)
        print(f"headline (chosen on tune): {rule}; rule met: {passed}")
        for p in ("tune", "report"):
            c = grids[p]
            c["headline"] = c["top_k"].map(str).eq(str(pick["top_k"])) & c[
                "threshold_rule"
            ].eq(pick["threshold_rule"])
            curves.append(c)

        point = base.with_params(
            floor=int(cfg["floor"]),
            threshold=None
            if pick["threshold_rule"] == NONE
            else float(pick["threshold"]),
            top_k=None
            if pick["top_k"] is None or pd.isna(pick["top_k"])
            else int(pick["top_k"]),
        )
        after = combine(report, None, point, None, ctx)
        config = {
            "scorer": scorer_name,
            "tokens_per_char": cfg["tokens_per_char"],
            "floor": point.floor,
            "top_k": point.top_k,
            "threshold": point.threshold,
            "threshold_rule": pick["threshold_rule"],
            "threshold_quantiles": cfg["threshold_quantiles"],
            "top_k_grid": cfg["top_k_grid"],
            "min_score_mass_kept": cfg["min_score_mass_kept"],
            "sample": cfg["lexical_sample"]
            if scorer_name == "lexical_overlap"
            else None,
            "price_table": sprint["baselines"]["price_table"],
            "catalogue": sprint["baselines"]["catalogue"],
            "premium_model": premium,
            "best_single_cheap": cheap,
            "implied_rates": str(RATES.relative_to(ROOT).as_posix()),
        }
        created = datetime.now(UTC)

        def manifest_for(baseline: str, config=config, created=created) -> Manifest:
            # as_logged is priced with the implied rates, not the price table
            run_ctx = (
                replace(ctx, price_table={"version": RATES_VERSION})
                if baseline == "as_logged"
                else ctx
            )
            return build_manifest(
                config | {"baseline": baseline},
                run_ctx,
                code_commit=commit,
                python_version=platform.python_version(),
                created_at=created,
            )

        extra = run_assumptions(
            rule,
            mass=float(pick["score_mass_kept"]),
            min_mass=cfg["min_score_mass_kept"],
            passed=passed,
            sample=len(report) if scorer_name == "lexical_overlap" else None,
        )
        paths = write_results(
            point,
            report,
            after,
            manifest_for,
            pricing=pricing,
            extra=extra + dirty,
            out_dir=out_dir,
        )
        m = grids["report"][grids["report"]["headline"]].iloc[0]
        print(
            f"report headline: eligible {int(m['eligible_requests']):,}; raw chunk "
            f"tokens {m['raw_chunk_tokens']:,.0f}; dedup (S-6, not counted) "
            f"{m['dedup_tokens_s6_not_counted']:,.0f}; saved "
            f"{m['saved_input_tokens']:,.0f}; chunk share removed "
            f"{m['chunk_share_removed']:.4f}; cost share saved "
            f"{m['cost_share_saved']:.4f} ({m['ci_low']:.4f} to {m['ci_high']:.4f})"
        )
        for path in paths:
            r = LeverResult.from_json(path.read_text(encoding="utf-8"))
            llm = r.slices["llm_only"]
            print(
                f"  {r.baseline:18s} eligible cost known "
                f"{int(llm['n_eligible_cost_known']):,}/{int(llm['n_eligible']):,}; "
                f"saving unknown {int(llm['n_saving_unknown']):,}; baseline total "
                f"{r.baseline_cost['total']}; saving token_cost "
                f"{r.saving['token_cost']}; share {llm.get('saving_share')}; CI "
                f"{r.ci_low} to {r.ci_high}"
            )
            print(f"wrote {_shown(path)}")

    table = pd.concat(curves, ignore_index=True)
    curve_path = out_dir / CURVE_NAME
    if curve_path.exists() and set(args.scorers) != set(SCORERS):
        old = pd.read_csv(curve_path)
        table = pd.concat(
            [old[~old["scorer"].isin(args.scorers)], table], ignore_index=True
        )
    table.to_csv(curve_path, index=False, float_format="%.10g")
    show = table[table["period"].eq("report")][
        [
            "scorer",
            "top_k",
            "threshold_rule",
            "eligible_requests",
            "chunk_share_removed",
            "saved_input_tokens",
            "cost_share_saved",
            "ci_low",
            "ci_high",
            "headline",
        ]
    ]
    print("\ncurve, REPORT period:")
    print(show.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"wrote {_shown(curve_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
