"""Run the popular-question cache (exp-cache-002) on the full data (R-A1 phase 2).

Reads ``data/derived/full_eda/requests.parquet`` (local, git-ignored), applies C's
``replay_scope.scope`` and ``levers.with_blocks``, then:

1. a small sensitivity check on the **tune** period only (window 30/90/180,
   min_count 2/3/5; the headline thresholds are fixed by the plan, not tuned);
2. both variants once on the **report** period, with B's ``CacheGuard``
   (no approval step, empty blocklist, key version ``pq-v1``) and the 1% shadow
   sample from ``sprint.toml``; one ``LeverResult`` per variant and baseline in
   ``reports/levers/`` (content-free; ADR-0032);
3. the local K-1 review sheet (30 first-turn hits) at
   ``data/derived/review/k1_popular_question.csv``, refused unless git-ignored.

The terminal shows aggregates only; message text goes to the sheet and nowhere
else. Traces: H-8, X1, FR-XCACHE-02, FR-XCACHE-04, FR-XCACHE-05, ADR-0006,
ADR-0016, ADR-0031, ADR-0032, ADR-0034.

Usage: ``.venv\\Scripts\\python.exe scripts/run_popular_question.py``
(``--ttl-only`` runs only the TTL variants: no sensitivity check, no sheet, and
the untimed results are left as they are; ``--no-sheet`` skips the review sheet;
``--out DIR`` writes the results
elsewhere, e.g. to compare a rerun). Every hit is checked to reuse an entry of its
own bot and instruction fingerprint; a mismatch stops the run.
"""

from __future__ import annotations

import argparse
import math
import platform
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from metis_auto.analysis.baselines_full import (
    BASELINE_KEYS,
    baseline_costs,
    best_single_cheap_model,
    cached_reported_separately,
)
from metis_auto.analysis.cache_guard import CacheGuard
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
RAW_MESSAGES = ROOT / "data" / "full_data" / "raw" / "data"
SPRINT = ROOT / "config" / "evaluation" / "sprint.toml"
EXPERIMENT_DIR = ROOT / "experiments" / "caching" / "exp-cache-002-popular-question"
OUT_DIR = ROOT / "reports" / "levers"
SHEET = ROOT / "data" / "derived" / "review" / "k1_popular_question.csv"

KEY_VERSION = "pq-v1"
DEFAULT_TTL_HOURS = 24
"""Production TTL (owner, 2026-11-02) until ``sprint.toml`` holds ``ttl_hours``."""
VARIANTS = ("first_turn", "all_turns")
AS_LOGGED = "as_logged"
OVER_TOKENS = 8000
TOP_TENANTS = 10
SENSITIVITY_WINDOWS = (30, 90, 180)
SENSITIVITY_MIN_COUNTS = (2, 3, 5)
N_TOP, N_RANDOM = 15, 15

PROXY_FEES = (
    "Fees are a proxy: 0.002 per per-call billing item (ADR-0032); it understates "
    "the recorded fee block by about 5% and overstates token cost by the same."
)
RUN_ASSUMPTIONS = (
    "Report period (Aug-Oct 2026) read once; the window may look back into the tune "
    "period (owner decision 2026-11-02). Period is from a_timestamp, days from "
    "u_timestamp (naive, Q-06).",
    "Guard: no approval step, empty blocklist, no disabled bot, key version pq-v1; "
    "every served key would still need approval before serving.",
    f"Tenant slices: the {TOP_TENANTS} largest tenants by LLM requests (opaque "
    "ranks); traffic_weighted slice not computed.",
)


# --- loading -----------------------------------------------------------------------


def load_cache_class() -> type:
    spec = StrategySettings(
        slot=StrategySlot.CANDIDATE_INDEX,  # unused for a file; no lever slot yet
        file="version.py",
        object="PopularQuestionCache",
    )
    return load_candidate(spec, EXPERIMENT_DIR, ROOT / "experiments")


def load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def make_guard(key_version: str = KEY_VERSION) -> CacheGuard:
    empty: frozenset[str] = frozenset()
    return CacheGuard(
        approved=None, blocked=empty, disabled_bots=empty, key_version=key_version
    )


def make_context(sprint: dict, guard: CacheGuard | None) -> ReplayContext:
    base = sprint["baselines"]
    return ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=load_toml(ROOT / base["price_table"]),
        catalogue=load_toml(ROOT / base["catalogue"]),
        seed=int(sprint["split"]["seed"]),
        min_n=sprint.get("sufficiency", {}).get("min_n"),
        guard=guard,
    )


# --- pure helpers (tested) -----------------------------------------------------------


def _dec(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


def rank_labels(values: pd.Series, prefix: str, width: int = 2) -> pd.Series:
    """Opaque rank per row, 1 = most rows; ties by first appearance. NaN stays NaN."""
    counts = values.value_counts(sort=False)
    order = sorted(counts.index, key=lambda v: -counts[v])  # stable: first seen
    rank = {v: f"{prefix}{i:0{width}d}" for i, v in enumerate(order, start=1)}
    return values.map(rank)


def effective_input(req: pd.DataFrame, cached_separately: frozenset[str]) -> pd.Series:
    """Input tokens with cached tokens added back for the models that report them
    outside the input count (Review Focus 3; the rule of ``baselines_full``)."""
    cached = req["a_bill_cachedInputTokens"].fillna(0)
    add = req["bot_provider_model"].isin(cached_separately)
    return req["a_bill_inputTokens"] + cached.where(add, 0)


def _name(label: object) -> str:
    text = "unknown" if label is None or pd.isna(label) else str(label).lower()
    clean = "".join(c if c.isalnum() or c in "_.-" else "_" for c in text)
    return clean if clean and clean[0].isalnum() else f"x{clean}"


def report_slices(
    before: pd.DataFrame, after: pd.DataFrame, *, cached_separately: frozenset[str]
) -> dict[str, dict[str, Decimal]]:
    """``all``, ``llm_only``, ``lang:<label>``, ``tenant_rank:<n>`` (with ``share``,
    the tenant's share of LLM requests) and ``over_8k`` (effective input > 8,000)."""
    out = summarise_slices(before, after)

    def sub(mask: pd.Series) -> dict[str, Decimal]:
        return summarise_slices(before[mask], after[mask])["all"]

    for label in sorted(before["u_lang"].dropna().unique()) + (
        ["unknown"] if before["u_lang"].isna().any() else []
    ):
        mask = (
            before["u_lang"].isna()
            if label == "unknown"
            else before["u_lang"].eq(label)
        )
        out[f"lang:{_name(label)}"] = sub(mask)
    llm = before["llm_request"].astype(bool)
    tenants = rank_labels(before.loc[llm, "user_id"], "", width=1)
    n_llm = int(llm.sum())
    for rank in sorted(tenants.dropna().unique(), key=int)[:TOP_TENANTS]:
        mask = pd.Series(False, index=before.index)
        mask[tenants.index[tenants == rank]] = True
        s = sub(mask)
        s["share"] = _dec(mask.sum() / n_llm) if n_llm else Decimal(0)
        out[f"tenant_rank:{rank}"] = s
    over = effective_input(before, cached_separately) > OVER_TOKENS
    out["over_8k"] = sub(over.fillna(False))
    return out


def _known_costs(before: pd.DataFrame, after: pd.DataFrame):
    cols = ["block_fees", "block_token_cost"]
    known = before["llm_request"].astype(bool) & before[cols].notna().all(axis=1)
    b = before.loc[known, cols].sum(axis=1).to_numpy(float)
    a = after.loc[known, cols].sum(axis=1).to_numpy(float)
    return known, b, a


def saving_ci(
    before: pd.DataFrame, after: pd.DataFrame, *, seed: int
) -> tuple[float, float, float]:
    """Saving share (as-logged) with a session-clustered bootstrap 95% interval."""
    known, b, a = _known_costs(before, after)
    sessions = before.loc[known, "session_id"].astype(str).to_numpy()
    return cluster_bootstrap_ratio(b - a, b, sessions, seed=seed)


def _assumptions(cache, extra: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(cache.assumptions) + (PROXY_FEES,) + RUN_ASSUMPTIONS + extra


def as_logged_result(
    cache,
    before: pd.DataFrame,
    after: pd.DataFrame,
    manifest: Manifest,
    extra: tuple[str, ...],
    *,
    cached_separately: frozenset[str] = frozenset(),
) -> LeverResult:
    slices = report_slices(before, after, cached_separately=cached_separately)
    llm = slices["llm_only"]
    blocks = ("fees", "token_cost", "total")
    _, lo, hi = saving_ci(before, after, seed=manifest.seed)
    return LeverResult(
        lever_id=cache.lever_id,
        step=cache.step,
        version=cache.version,
        n_requests=len(before),
        n_eligible=int((after["pq_eligible"].fillna(False).astype(bool)).sum()),
        baseline=AS_LOGGED,
        baseline_cost={b: llm[f"baseline:{b}"] for b in blocks},
        saving={b: llm[f"saving:{b}"] for b in blocks},
        ci_low=None if math.isnan(lo) else lo,
        ci_high=None if math.isnan(hi) else hi,
        slices=slices,
        evidence_class=cache.evidence_class,
        correctness_state=cache.correctness_state,
        assumptions=_assumptions(cache, extra),
        manifest=manifest,
    )


def _repriced_counts(
    n: int, n_hits: int, base: dict[str, Decimal], save: dict[str, Decimal]
) -> dict[str, Decimal]:
    """Counts and repriced amounts of one slice (no recorded amounts)."""
    d = {
        "n_requests": Decimal(n),
        "n_cost_known": base["n_known"],
        "n_cache_hits": Decimal(n_hits),
        "baseline:total": base["total"],
        "saving:total": save["total"],
    }
    if n:
        d["cache_hit_rate"] = _dec(n_hits / n)
    if base["total"] > 0:
        d["saving_share"] = _dec(float(save["total"] / base["total"]))
    return d


def repriced_results(
    cache,
    before: pd.DataFrame,
    after: pd.DataFrame,
    ctx: ReplayContext,
    manifests: dict[str, Manifest],
    extra: tuple[str, ...],
    *,
    premium_model: str,
    cached_separately: frozenset[str],
) -> tuple[dict[str, LeverResult], dict[str, str]]:
    """The three repriced baselines (price-file units, token cost only).

    Saving = the baseline's cost of the hit rows. ``best_single_cheap`` is
    reported only if the cheapest model over the hit rows is the one chosen over
    all rows (``baseline_costs`` chooses it per frame). Slices hold counts and
    repriced amounts only; no interval is computed (per-row repriced cost is not
    exposed by ``baselines_full``)."""
    hits = after["served_from_cache"].astype(bool)
    llm = before["llm_request"].astype(bool)
    full = baseline_costs(
        before, ctx, premium_model=premium_model, cached_separately=cached_separately
    )
    results: dict[str, LeverResult] = {}
    missing: dict[str, str] = {}
    if not hits.any():
        return results, {k: "no hits" for k in BASELINE_KEYS if k != AS_LOGGED}
    part = baseline_costs(
        before[hits],
        ctx,
        premium_model=premium_model,
        cached_separately=cached_separately,
    )
    same_cheap = best_single_cheap_model(
        before[hits], ctx, cached_separately=cached_separately
    ) == best_single_cheap_model(before, ctx, cached_separately=cached_separately)
    for key in BASELINE_KEYS:
        if key == AS_LOGGED:
            continue
        if key == "best_single_cheap" and not same_cheap:
            missing[key] = "cheapest model over the hits differs from all rows"
            continue
        base, save = full[key], part[key]
        n_hits = int((hits & llm).sum())

        results[key] = LeverResult(
            lever_id=cache.lever_id,
            step=cache.step,
            version=cache.version,
            n_requests=len(before),
            n_eligible=int(after["pq_eligible"].fillna(False).astype(bool).sum()),
            baseline=key,
            baseline_cost={"token_cost": base["token_cost"], "total": base["total"]},
            saving={"token_cost": save["token_cost"], "total": save["total"]},
            slices={
                "all": _repriced_counts(len(before), n_hits, base, save),
                "llm_only": _repriced_counts(int(llm.sum()), n_hits, base, save),
            },
            evidence_class=cache.evidence_class,
            correctness_state=cache.correctness_state,
            assumptions=_assumptions(cache, extra)
            + (
                "Repriced baseline in price-file units, token cost only (fees are "
                "not on the price list); no interval computed.",
            ),
            manifest=manifests[key],
        )
    return results, missing


def diagnostics(
    cache,
    before: pd.DataFrame,
    after: pd.DataFrame,
    keys: pd.Series,
    *,
    shadow_rate: float,
    seed: int,
) -> dict[str, int | float]:
    """Aggregates only: counts, rates, quantiles. No key, hash or text."""
    hits = after["served_from_cache"].astype(bool)
    eligible = after["pq_eligible"].fillna(False).astype(bool)
    llm = before["llm_request"].astype(bool)
    day = before["u_timestamp"].dt.normalize()
    per_day = after["pq_admitted_keys_day"].groupby(day).first().dropna()
    agrees = after.loc[hits, "pq_answer_agrees"].astype(bool)
    shadow = make_guard(cache.key_version).shadow_sample(keys[hits], shadow_rate, seed)
    _, b, a = _known_costs(before, after)
    return {
        "requests": int(len(before)),
        "llm_requests": int(llm.sum()),
        "eligible": int(eligible.sum()),
        "hits": int(hits.sum()),
        "hit_rate_all": float(hits.sum() / len(before)) if len(before) else math.nan,
        "hit_rate_llm": float(hits.sum() / llm.sum()) if llm.any() else math.nan,
        "hit_rate_eligible": float(hits.sum() / eligible.sum())
        if eligible.any()
        else math.nan,
        "cost_share_saved": float((b - a).sum() / b.sum()) if b.sum() else math.nan,
        "admitted_keys_per_day_median": float(per_day.median())
        if len(per_day)
        else math.nan,
        "admitted_keys_per_day_p90": float(per_day.quantile(0.9))
        if len(per_day)
        else math.nan,
        "agreement": float(agrees.mean()) if len(agrees) else math.nan,
        "distinct_served_keys": int(keys[hits].nunique()),
        "shadow_rows": int(shadow.sum()),
        "shadow_keys": int(keys[hits][shadow].nunique()),
        "shadow_agreement": float(agrees[shadow].mean()) if shadow.any() else math.nan,
    }


def sensitivity(
    cache_class,
    req: pd.DataFrame,
    ctx: ReplayContext,
    *,
    windows=SENSITIVITY_WINDOWS,
    min_counts=SENSITIVITY_MIN_COUNTS,
    min_sessions: int = 2,
    variant: str = "first_turn",
) -> pd.DataFrame:
    """Hit rate and saving share on the **tune** period only (report rows are
    never given to the cache here)."""
    tune = req[req["period"].eq("tune")]
    rows = []
    for w in windows:
        for mc in min_counts:
            cache = cache_class(w, mc, min_sessions, variant, KEY_VERSION)
            out = combine(tune, cache, None, None, ctx)
            hits = int(out["served_from_cache"].sum())
            eligible = int(out["pq_eligible"].fillna(False).astype(bool).sum())
            share = summarise_slices(tune, out)["llm_only"].get("saving_share")
            rows.append(
                {
                    "window_days": w,
                    "min_count": mc,
                    "eligible": eligible,
                    "hits": hits,
                    "hit_rate_eligible": hits / eligible if eligible else math.nan,
                    "saving_share": float(share) if share is not None else math.nan,
                }
            )
    return pd.DataFrame(rows)


def review_items(
    hits: pd.Series,
    keys: pd.Series,
    sources: pd.Series,
    *,
    n_top: int = N_TOP,
    n_random: int = N_RANDOM,
    seed: int,
) -> pd.DataFrame:
    """Rows to review: one hit for each of the ``n_top`` keys with the most hits,
    then ``n_random`` other hits, both seeded. Row labels only, no content."""
    rng = np.random.default_rng(seed)
    hit_rows = hits.index[hits.astype(bool)]
    k = keys[hit_rows]
    counts = k.value_counts()
    top_keys = sorted(counts.index, key=lambda x: (-counts[x], x))[:n_top]
    chosen: list[tuple[str, object]] = []
    for key in top_keys:
        options = sorted(k.index[k == key])
        chosen.append(("top_key", options[int(rng.integers(len(options)))]))
    taken = {r for _, r in chosen}
    rest = sorted(r for r in hit_rows if r not in taken)
    pick = rng.choice(len(rest), size=min(n_random, len(rest)), replace=False)
    chosen += [("random", rest[i]) for i in sorted(pick)]
    return pd.DataFrame(
        {
            "item": range(1, len(chosen) + 1),
            "sample": [s for s, _ in chosen],
            "row": [r for _, r in chosen],
            "source_row": [sources[r] for _, r in chosen],
        }
    )


def attach_text(items: pd.DataFrame, raw_dir: Path) -> pd.DataFrame:
    """Join message text by message ID from the raw ``chat_message`` shards."""
    id_cols = ("question_id", "stored_answer_id", "hit_answer_id")
    ids = sorted({str(v) for c in id_cols for v in items[c].dropna()})
    files = sorted(str(p) for p in raw_dir.glob("chat_message-*.parquet"))
    table = ds.dataset(files, format="parquet").to_table(
        columns=["message_id", "content"], filter=ds.field("message_id").isin(ids)
    )
    ids_found, content = table["message_id"].to_pylist(), table["content"].to_pylist()
    text = dict(zip(ids_found, content, strict=True))
    sheet = items[["item", "sample", "bot_rank"]].copy()
    for src, dst in zip(
        id_cols, ("question_text", "stored_answer_text", "hit_answer_text"), strict=True
    ):
        sheet[dst] = items[src].map(lambda m: text.get(str(m)) or "")
    sheet["verdict"] = ""
    sheet["note"] = ""
    return sheet


def is_git_ignored(path: Path) -> bool:
    done = subprocess.run(
        ["git", "check-ignore", "-q", str(path)], cwd=ROOT, capture_output=True
    )
    return done.returncode == 0


def write_sheet(sheet: pd.DataFrame, path: Path) -> None:
    if not is_git_ignored(path):
        raise SystemExit(
            f"refusing to write the review sheet: {path} is not git-ignored"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(path, index=False, encoding="utf-8-sig")


# --- main ----------------------------------------------------------------------------


def ttl_from_config(pq_cfg: dict) -> tuple[float, str]:
    """``ttl_hours`` from ``[cache.popular_question]``, else the script default."""
    if "ttl_hours" in pq_cfg:
        return pq_cfg["ttl_hours"], "sprint.toml"
    return DEFAULT_TTL_HOURS, "script default"


def run_config(cache, shadow_rate: float, sprint: dict) -> dict[str, object]:
    """Settings that change a result (hashed into the manifest). ``ttl_hours`` is
    added only for a TTL run, so an untimed run hashes as in phase 2."""
    config: dict[str, object] = {
        "variant": cache.variant,
        "window_days": cache.window_days,
        "min_count": cache.min_count,
        "min_sessions": cache.min_sessions,
        "key_version": cache.key_version,
        "shadow_rate": shadow_rate,
        "price_table": sprint["baselines"]["price_table"],
        "catalogue": sprint["baselines"]["catalogue"],
    }
    if cache.ttl_hours is not None:
        config["ttl_hours"] = cache.ttl_hours
    return config


def _manifest(config: dict, ctx: ReplayContext, commit: str) -> Manifest:
    return build_manifest(
        config,
        ctx,
        code_commit=commit,
        python_version=platform.python_version(),
        created_at=datetime.now(UTC),
    )


def _print_table(title: str, rows: dict[str, object]) -> None:
    print(f"\n{title}")
    for k, v in rows.items():
        print(f"  {k:32s} {v:.4f}" if isinstance(v, float) else f"  {k:32s} {v}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-sheet", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="result folder")
    parser.add_argument(
        "--ttl-only", action="store_true", help="run only the TTL variants"
    )
    args = parser.parse_args(argv)

    sprint = load_toml(SPRINT)
    pq_cfg = sprint["cache"]["popular_question"]
    shadow_rate = float(sprint["cache_guard"]["shadow_rate"])
    premium = sprint["baselines"]["premium_model"]
    guard = make_guard()
    ctx = make_context(sprint, guard)
    version = code_version(ROOT)
    commit = version.commit or "unknown"
    extra = (
        ("The working tree had uncommitted changes when this ran.",)
        if version.dirty
        else ()
    )

    req = pd.read_parquet(REQUESTS)
    req = with_blocks(scope(req, ctx))
    cached_sep = cached_reported_separately(req)
    cache_class = load_cache_class()
    print(f"requests: {len(req):,}; periods: {req['period'].value_counts().to_dict()}")

    ttl_hours, ttl_source = ttl_from_config(pq_cfg)
    print(f"TTL: {ttl_hours} h ({ttl_source})")
    if not args.ttl_only:
        grid = sensitivity(cache_class, req, ctx)
        print("\nsensitivity, TUNE period only (first_turn, min_sessions 2):")
        print(grid.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    known = req[req["period"].isin(["tune", "report"])]
    report = known["period"].eq("report")
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    first_turn_state = None
    ttls = (ttl_hours,) if args.ttl_only else (None, ttl_hours)
    runs = [(variant, ttl) for ttl in ttls for variant in VARIANTS]
    for variant, ttl in runs:
        cache = cache_class(
            pq_cfg["window_days"],
            pq_cfg["min_count"],
            pq_cfg["min_sessions"],
            variant,
            KEY_VERSION,
            ttl_hours=ttl,
        )
        after_all = combine(known, cache, None, None, ctx)  # report read once here
        before, after = known[report], after_all[report]
        keys = cache.keys(before)
        config = run_config(cache, shadow_rate, sprint)
        manifests = {
            b: _manifest(config | {"baseline": b}, ctx, commit) for b in BASELINE_KEYS
        }
        result = as_logged_result(
            cache,
            before,
            after,
            manifests[AS_LOGGED],
            extra,
            cached_separately=cached_sep,
        )
        (out_dir / f"{cache.lever_id}.json").write_text(
            result.to_json(), encoding="utf-8"
        )
        repriced, missing = repriced_results(
            cache,
            before,
            after,
            ctx,
            manifests,
            extra,
            premium_model=premium,
            cached_separately=cached_sep,
        )
        for key, r in repriced.items():
            (out_dir / f"{cache.lever_id}__{key}.json").write_text(
                r.to_json(), encoding="utf-8"
            )
        funnel = cache.funnel(before)
        print(f"\n=== {cache.lever_id} (report period) ===")
        print(funnel.to_string(index=False))
        _print_table(
            "scope check (same bot, same instruction fingerprint; raises if not)",
            dict(cache.scope_check or {}),
        )
        if cache.stability_check is not None:
            _print_table(
                "stability (TTL: hits whose latest answer is the window's mode)",
                dict(cache.stability_check),
            )
        _print_table(
            "diagnostics (aggregates only)",
            diagnostics(
                cache, before, after, keys, shadow_rate=shadow_rate, seed=ctx.seed
            )
            | {
                "saving_share_ci_low": result.ci_low,
                "saving_share_ci_high": result.ci_high,
            },
        )
        for key, r in repriced.items():
            share = r.slices["llm_only"].get("saving_share")
            print(f"  repriced {key:24s} saving share {share}")
        for key, why in missing.items():
            print(f"  repriced {key:24s} missing: {why}")
        if variant == "first_turn" and ttl is None:
            first_turn_state = (cache, known, after_all, report)

    if not (args.no_sheet or args.ttl_only) and first_turn_state is not None:
        cache, known_rows, after_all, report = first_turn_state
        hits = after_all["served_from_cache"].astype(bool) & report
        sources = cache.served_sources(known_rows[known_rows["llm_request"]], ctx)
        items = review_items(hits, cache.keys(known_rows), sources, seed=ctx.seed)
        bot_rank = rank_labels(req["bot_id"], "bot-")
        items["bot_rank"] = bot_rank[items["row"]].to_numpy()
        items["question_id"] = known_rows.loc[
            items["row"], "user_message_id"
        ].to_numpy()
        items["hit_answer_id"] = known_rows.loc[
            items["row"], "ai_message_id"
        ].to_numpy()
        items["stored_answer_id"] = known_rows.loc[
            items["source_row"], "ai_message_id"
        ].to_numpy()
        sheet = attach_text(items, RAW_MESSAGES)
        write_sheet(sheet, SHEET)
        empty = int(
            (sheet[["question_text", "stored_answer_text", "hit_answer_text"]] == "")
            .sum()
            .sum()
        )
        print(
            f"\nK-1 review sheet: {len(sheet)} items written (local, git-ignored); "
            f"{empty} text cells empty."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
