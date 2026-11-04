"""Offline per-request overhead of one step version's ``apply`` (final plan L-1).

    .venv\\Scripts\\python.exe scripts/measure_lever_overhead.py LEVER_ID [LEVER_ID ...]
        [--n 1000] [--seed SEED] [--folder reports/levers] [--dry-run]

Follows the pattern of ``scripts/measure_overhead.py``: loads the version through
the repository loader (``wiring.experiments.load_candidate``), takes a seeded
sample of ``--n`` report-period LLM rows from ``data/derived/full_eda/requests.parquet``
(eligible for the version or not: the rows ``combine`` would hand it; workflow
rows never reach a version), calls ``apply`` once to warm up, then times
``apply`` on **each row as its own one-row frame** (``apply`` takes frames) with
``time.perf_counter_ns``. Per-request time is the batch's time divided by its
rows (one row per batch here). Prints p50, p95 and max in ms, the hardware and
the sample size, compares p95 with the 100 ms target (Q-14), and writes p50 and
p95 into every ``LeverResult`` in ``--folder`` whose ``lever_id`` matches (all
baselines), with the assumption "offline per-request estimate on a local
machine; not a load test (Q-14)". The manifest and every other field stay as
they are: the manifest describes the saving, which is unchanged.

A version that raises, or returns a different index, stops the run before any
file is written: no silent zero. Prints aggregates only. Traces: QA-PERF
(100 ms p95, Q-14), L-1, ADR-0032.
"""

from __future__ import annotations

import argparse
import platform
import re
import statistics
import sys
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from metis_auto.analysis.baselines_full import BASELINE_KEYS
from metis_auto.analysis.cache_guard import CacheGuard
from metis_auto.analysis.lever_result import LeverResult
from metis_auto.analysis.levers import ReplayContext, StepVersion, with_blocks
from metis_auto.analysis.replay_scope import period_bounds_from_config, scope
from metis_auto.settings import StrategySettings, StrategySlot
from metis_auto.wiring.experiments import load_candidate

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "data" / "derived" / "full_eda" / "requests.parquet"
SPRINT = ROOT / "config" / "evaluation" / "sprint.toml"
OUT_DIR = ROOT / "reports" / "levers"

TARGET_P95_MS = 100.0
"""Per-request overhead target, p95 (brief Â§11, Q-14)."""
DEFAULT_N = 1000
OVERHEAD_LABEL = "Overhead:"
CAVEAT_LABEL = "Overhead caveat:"


# --- pure helpers (tested) -----------------------------------------------------------


def sample_rows(req: pd.DataFrame, n: int, *, seed: int) -> pd.DataFrame:
    """Seeded sample of report-period LLM rows; every such row if fewer than ``n``."""
    pool = req[req["period"].eq("report") & req["llm_request"].astype(bool)]
    return pool.sample(n=min(n, len(pool)), random_state=seed)


def time_apply(
    version: StepVersion,
    rows: pd.DataFrame,
    ctx: ReplayContext,
    *,
    batch_size: int = 1,
    clock: Callable[[], int] = time.perf_counter_ns,
) -> list[float]:
    """Milliseconds per request: each batch's ``apply`` time divided by its rows.

    One warm-up call on the first batch is not timed. Any error propagates.
    """
    if rows.empty:
        raise ValueError("no rows to time")
    batches = [rows.iloc[i : i + batch_size] for i in range(0, len(rows), batch_size)]
    version.apply(batches[0], ctx)  # warm-up
    times: list[float] = []
    for batch in batches:
        start = clock()
        out = version.apply(batch, ctx)
        elapsed = clock() - start
        if not out.index.equals(batch.index):
            raise ValueError(f"{version.name}: apply must keep the index it was given")
        times.append(elapsed / 1e6 / len(batch))
    return times


def percentile(values: list[float], q: float) -> float:
    """Nearest rank, as in ``scripts/measure_overhead.py``."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def summarise(times: list[float]) -> dict[str, float]:
    return {
        "n": len(times),
        "p50_ms": round(statistics.median(times), 4),
        "p95_ms": round(percentile(times, 0.95), 4),
        "max_ms": round(max(times), 4),
    }


def verdict(p95_ms: float) -> str:
    return "pass" if p95_ms <= TARGET_P95_MS else "fail"


def with_overhead(
    result: LeverResult,
    *,
    p50: float,
    p95: float,
    note: str,
    caveat: str | None = None,
) -> LeverResult:
    """A copy with the overhead fields and one overhead label (replacing an older
    one); every other field is unchanged, the manifest included."""
    kept = tuple(
        a
        for a in result.assumptions
        if not a.startswith((OVERHEAD_LABEL, CAVEAT_LABEL))
    )
    label = (
        f"{OVERHEAD_LABEL} offline per-request estimate on a local machine; not a "
        f"load test (Q-14). {note}"
    )
    added = (label,) + ((f"{CAVEAT_LABEL} {caveat}",) if caveat else ())
    data = result.model_dump() | {
        "overhead_ms_p50": p50,
        "overhead_ms_p95": p95,
        "assumptions": kept + added,
    }
    return LeverResult.model_validate(data)


def result_files(
    lever_id: str, folder: Path, *, per_baseline: bool = False
) -> list[Path]:
    """Every result in ``folder`` whose ``lever_id`` field matches (all baselines).

    With ``per_baseline`` (Pipeline C's results, whose ``lever_id`` is
    ``<version id>.<baseline>``) a result matches when its ``lever_id`` is the
    version id plus one of the four baseline keys."""
    wanted = {lever_id}
    if per_baseline:
        wanted = {f"{lever_id}.{key}" for key in BASELINE_KEYS}
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            result = LeverResult.from_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue  # not a LeverResult (e.g. a curve file)
        if result.lever_id in wanted:
            found.append(path)
    return found


def measure(
    lever_id: str,
    version: StepVersion,
    req: pd.DataFrame,
    ctx: ReplayContext,
    *,
    folder: Path,
    n: int,
    seed: int,
    note: Callable[[dict[str, float]], str],
    caveat: str | None = None,
    batch_size: int = 1,
    clock: Callable[[], int] = time.perf_counter_ns,
    write: bool = True,
    per_baseline: bool = False,
) -> dict[str, float]:
    """Time ``version`` and write p50 and p95 into its result files.

    Files are found first (none is an error) and written only after every row
    was timed, so a failing version leaves them untouched."""
    paths = result_files(lever_id, folder, per_baseline=per_baseline)
    if not paths:
        raise FileNotFoundError(f"no LeverResult with lever_id {lever_id} in {folder}")
    rows = sample_rows(req, n, seed=seed)
    summary = summarise(
        time_apply(version, rows, ctx, batch_size=batch_size, clock=clock)
    )
    if write:
        for path in paths:
            old = LeverResult.from_json(path.read_text(encoding="utf-8"))
            new = with_overhead(
                old,
                p50=summary["p50_ms"],
                p95=summary["p95_ms"],
                note=note(summary),
                caveat=caveat,
            )
            path.write_text(new.to_json(), encoding="utf-8")
    summary["files"] = len(paths)
    return summary


# --- hardware -----------------------------------------------------------------------


def cpu_name() -> str:
    """CPU model name (Windows registry, macOS sysctl), else ``platform``."""
    if platform.system() == "Windows":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    if platform.system() == "Darwin":
        import subprocess

        try:
            return subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return platform.processor() or "unknown"


def hardware() -> dict[str, str]:
    return {
        "cpu": " ".join(cpu_name().split()),
        "system": f"{platform.system()} {platform.release()}",
        "python": f"{platform.python_implementation()} {platform.python_version()}",
    }


# --- versions this script knows how to build ----------------------------------------


Loader = Callable[[str], Any]
"""Loads one object from the target's ``version.py`` (the repository loader)."""


@dataclass(frozen=True)
class Target:
    """How to build one family of versions from its ``lever_id``.

    ``build(load, match, sprint, req, rows)`` gets the full scoped frame and the
    sampled rows, for versions that need data of those rows (chunks, text)."""

    pattern: str
    experiment: Path
    build: Callable[[Loader, re.Match, dict, pd.DataFrame, pd.DataFrame], StepVersion]
    caveat: str | None = None
    guard_key_version: str | None = None
    per_baseline: bool = False
    """Results carry the baseline in ``lever_id`` (Pipeline C)."""
    version_name: Callable[[re.Match], str] | None = None
    """The built version's ``name`` when it differs from the lever id."""
    prepare: Callable[[pd.DataFrame], pd.DataFrame] | None = None
    """Columns the version reads from its rows, added to the frame before the
    sample is drawn (not timed)."""


def _popular_question(load: Loader, m: re.Match, sprint: dict, req, rows):
    pq = sprint["cache"]["popular_question"]
    ttl = float(m["ttl"]) if m["ttl"] else None
    return load("PopularQuestionCache")(
        pq["window_days"],
        pq["min_count"],
        pq["min_sessions"],
        m["variant"],
        "pq-v1",
        ttl_hours=ttl,
    )


RERANKER_DIR = ROOT / "experiments" / "context" / "exp-ctx-003-reranker-cut"
CURVE = OUT_DIR / "context.reranker_cut.curve.csv"


def headline_point(
    curve: pd.DataFrame, scorer: str
) -> tuple[int, float | None, int | None]:
    """``(floor, threshold, top_k)`` of the scorer's headline row (report period)."""
    rows = curve[
        curve["scorer"].eq(scorer)
        & curve["period"].eq("report")
        & curve["headline"].astype(bool)
    ]
    if len(rows) != 1:
        raise SystemExit(f"curve has {len(rows)} headline rows for {scorer}")
    row = rows.iloc[0]

    def opt(value, kind):
        return None if value is None or pd.isna(value) else kind(value)

    return int(row["floor"]), opt(row["threshold"], float), opt(row["top_k"], int)


def _run_reranker_cut():
    """``scripts/run_reranker_cut.py`` by path (its chunk and text readers)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_reranker_cut_for_overhead", ROOT / "scripts" / "run_reranker_cut.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _reranker_cut(load: Loader, m: re.Match, sprint: dict, req, rows):
    """The headline point of the run, with the sampled rows' chunks (and, for a
    text scorer, their chunk and question text, in memory only)."""
    from metis_auto.analysis.baselines_full import cached_reported_separately

    rc = _run_reranker_cut()
    cfg = load_toml(RERANKER_DIR / "config.toml")["reranker_cut"]
    floor, threshold, top_k = headline_point(pd.read_csv(CURVE), m["scorer"])
    text = m["scorer"] != "observed_relevancy"
    ids = rows["ai_message_id"]
    return load("RerankerCut")(
        load(m["scorer"]) if text else None,
        floor,
        threshold,
        top_k,
        chunks=rc.read_chunks(ids, with_text=text),
        tokens_per_char=float(cfg["tokens_per_char"]),
        queries=rc.read_queries(rows) if text else None,
        cached_separately=cached_reported_separately(req),
    )


def _per_bot_reassignment(load: Loader, m: re.Match, sprint: dict, req, rows):
    """R-A3 fitted on the tune rows by ``scripts/run_per_bot_reassignment.py``
    (its loader and R-0 eligibility); the fit is not timed. ``apply`` makes the
    ``todays_models`` decision, so the other baselines' gates are not needed."""
    import importlib.util

    from metis_auto.analysis.baselines_full import cached_reported_separately

    spec = importlib.util.spec_from_file_location(
        "run_per_bot_reassignment_for_overhead",
        ROOT / "scripts" / "run_per_bot_reassignment.py",
    )
    rp = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = rp
    spec.loader.exec_module(rp)
    ctx = make_context(sprint, None)
    return rp.fit_version(
        sprint,
        rp.tune_rows(req, ctx),
        ctx,
        cached_reported_separately(req),
        with_reasoning=m["set"] is not None,
    )


# --- Pipeline C versions (sprint final Stage 1): built as their own runners do ----

C_TABLES = ROOT / "reports" / "full_eda" / "tables"
C_CHUNKS = ROOT / "data" / "derived" / "full_eda" / "chunks"
C_LEDGER_ROW = "recon.t0rag.coef_rag"


def _script(name: str) -> Any:
    """``scripts/<name>.py`` by path (its loaders and frozen settings)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"{name}_for_overhead", ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _coef() -> float:
    ledger = pd.read_csv(C_TABLES / "claims_ledger.csv").set_index("claim_id")
    return float(ledger.loc[C_LEDGER_ROW, "value"])


def _implied(column: str) -> dict[str, float]:
    rates = pd.read_csv(C_TABLES / "implied_unit_rates.csv").set_index("model")
    return rates[column].dropna().astype(float).to_dict()


def _chunks_of(ids: pd.Series, columns: list[str]) -> pd.DataFrame:
    wanted = set(ids)
    parts = [
        pd.read_parquet(f, columns=columns) for f in sorted(C_CHUNKS.glob("*.parquet"))
    ]
    chunks = pd.concat(parts)
    return chunks[chunks["message_id"].isin(wanted)].reset_index(drop=True)


def _within_message_dedup(load: Loader, m: re.Match, sprint: dict, req, rows):
    from metis_auto.analysis.baselines_full import cached_reported_separately

    return load("WithinMessageDedup")(
        _chunks_of(rows["ai_message_id"], ["message_id", "h_exact", "n_chars"]),
        tokens_per_char=_coef(),
        input_rate_per_m=_implied("implied_input_per_M"),
        cached_separately=cached_reported_separately(req),
    )


def _history_budget(load: Loader, m: re.Match, sprint: dict, req, rows):
    """The frozen variant with the bot's turn-0 base fitted on the tune split
    (not timed); every turn of the scoped table is the session history."""
    from metis_auto.analysis.baselines_full import cached_reported_separately
    from metis_auto.analysis.replay_scope import split_by_session

    hb = _script("history_budget_levers")
    ctx = make_context(sprint, None)
    sep = cached_reported_separately(req)
    turns = req.assign(split=split_by_session(req, seed=ctx.seed))
    coef = _coef()
    t0 = hb._version().turn0_base(
        turns[turns["split"] == "tune"],
        tokens_per_char=coef,
        min_n=ctx.min_n,
        cached_separately=sep,
    )
    return hb.make_version(
        hb.VARIANTS[m["variant"]],
        turns=turns,
        turn0_base=t0,
        tokens_per_char=coef,
        input_rate_per_m=_implied("implied_input_per_M"),
        cached_rate_per_m=_implied("implied_cached_per_M"),
        cached_separately=sep,
    )


def _session_memo_prepare(req: pd.DataFrame) -> pd.DataFrame:
    """Recorded per-call fee blocks (ADR-0037 item 2), as the runner does."""
    sm = _script("session_memo_levers")
    return sm._version().fee_blocks(req, _per_call(sm, req))


def _per_call(sm: Any, req: pd.DataFrame) -> pd.DataFrame:
    bt = pd.read_parquet(sm.BILLING, columns=["message_id", "costBreakdown.per_call"])
    per_call = bt[bt["costBreakdown.per_call"].notna()].rename(
        columns={"costBreakdown.per_call": "amount"}
    )
    return per_call[per_call["message_id"].isin(set(req["ai_message_id"]))]


def _session_memo(load: Loader, m: re.Match, sprint: dict, req, rows):
    """The chosen threshold (``reports/caching/exp-cache-004/summary.json``) with
    the sampled rows' lookups (query fingerprints, chunks, per-call items)."""
    import json

    from metis_auto.analysis.baselines_full import cached_reported_separately

    sm = _script("session_memo_levers")
    v = sm._version()
    threshold = json.loads(sm.SUMMARY.read_text(encoding="utf-8"))["chosen_threshold"]
    ids = rows["ai_message_id"]
    query_fps = pd.read_parquet(sm.QUERY_FPS)
    lookups = v.build_lookups(
        rows,
        query_fps[query_fps["message_id"].isin(set(ids))],
        _chunks_of(ids, ["message_id", "chunk_id", "h_exact", "n_chars"]),
        _per_call(sm, rows),
    )
    return v.SessionMemo(
        threshold,
        frozenset(sprint["phatic"]["words"]),
        lookups=lookups,
        tokens_per_char=_coef(),
        input_rate_per_m=_implied("implied_input_per_M"),
        cached_separately=cached_reported_separately(req),
    )


def _small_classifier_prepare(req: pd.DataFrame) -> pd.DataFrame:
    """The strict modes read the intent columns of the whole table (ADR-0046
    Amendment 1); the rules mode ignores them."""
    sc = _script("small_classifier_levers")
    if not sc.FLAGS.exists():
        raise SystemExit(f"{sc.FLAGS} missing: run scripts/derive_turn_intent_flags.py")
    return sc._version().intent_columns(req, pd.read_parquet(sc.FLAGS))


def _small_classifier(load: Loader, m: re.Match, sprint: dict, req, rows):
    from metis_auto.analysis.baselines_full import cached_reported_separately

    sc = _script("small_classifier_levers")
    strict = m["mode"] != "rules"
    versions = sc.make_versions(
        sprint["routing"],
        make_context(sprint, None).catalogue,
        max_u_chars=sc.MAX_U_CHARS,
        max_input_tokens=sc.MAX_INPUT_TOKENS,
        cached_separately=cached_reported_separately(req),
        strict=strict,
    )
    key = m["mode"] if strict else ("with_reasoning_models" if m["set"] else "primary")
    return versions[key]


def _decision_router(load: Loader, m: re.Match, sprint: dict, req, rows):
    """The rules-only decision router: tiers for the whole frame (flags joined
    before timing); ``apply`` times the R-0 candidate costs and the choice."""
    from metis_auto.analysis.baselines_full import cached_reported_separately
    from metis_auto.settings import load_settings
    from metis_auto.wiring.from_settings import pipeline_config

    dr = _script("decision_router_levers")
    loaded = load_settings(environ={}, dotenv=None, runtime=None)  # no .env
    dr.rules_only.require_offline(loaded.settings)
    if not dr.FLAGS.exists():
        raise SystemExit(f"{dr.FLAGS} missing: run decision_router_levers.py derive")
    tiers = dr.rules_only.rules_only_tiers(
        req, pd.read_parquet(dr.FLAGS), pipeline_config(loaded)
    )
    c12, v13 = dr._classifier(), dr._router()
    catalogue = make_context(sprint, None).catalogue
    primary = c12.candidate_sets(sprint["routing"], catalogue)["primary"]
    return v13.DecisionRouterRouting(
        tiers=tiers,
        tier_of={
            str(e["model_id"]): int(e["tier"])
            for e in catalogue.get("models", [])
            if e.get("tier") is not None
        },
        rules={**sprint["routing"], "candidates": list(primary), "candidates_jev": []},
        cached_separately=cached_reported_separately(req),
        name=dr.VERSION_ID,
    )


TARGETS = (
    Target(
        pattern=r"^cache\.popular_question\.(?P<variant>first_turn|all_turns)"
        r"(?:\.ttl(?P<ttl>[0-9.]+)h)?$",
        experiment=ROOT / "experiments" / "caching" / "exp-cache-003-popular-question",
        build=_popular_question,
        caveat=(
            "on a one-row frame the nightly window is empty, so this times "
            "eligibility, keying and the guard path, not the nightly build "
            "(batch work) or a lookup in a built set."
        ),
        guard_key_version="pq-v1",
    ),
    Target(
        pattern=r"^context\.reranker_cut\.(?P<scorer>observed_relevancy|lexical_overlap)$",
        experiment=RERANKER_DIR,
        build=_reranker_cut,
        caveat=(
            "the headline point; chunks (and text) of the sampled rows are loaded "
            "before timing, so reading data is not timed; scoring and the cut are. "
            "Not a reranker model's latency."
        ),
    ),
    Target(
        pattern=r"^route\.per_bot(?P<set>\.with_reasoning_models)?$",
        experiment=ROOT
        / "experiments"
        / "routing"
        / "exp-route-001-per-bot-reassignment",
        build=_per_bot_reassignment,
        caveat=(
            "the per-bot choice is fitted on the tune split before timing (batch "
            "work); apply times the repricing and the eligibility check of the "
            "bot's choice (R-0 candidate_costs)."
        ),
    ),
    Target(
        pattern=r"^ctx\.within_message_dedup$",
        experiment=ROOT
        / "experiments"
        / "context"
        / "exp-ctx-001-within-message-dedup",
        build=_within_message_dedup,
        caveat=(
            "chunk rows of the sampled requests are loaded before timing, so "
            "reading data is not timed; the dedup and the token conversion are."
        ),
        per_baseline=True,
        version_name=lambda m: "exp-ctx-001-within-message-dedup",
    ),
    Target(
        pattern=r"^ctx\.history_budget\.(?P<variant>b2000|b4000|b8000|half_over_8k)$",
        experiment=ROOT / "experiments" / "context" / "exp-ctx-004-history-budget",
        build=_history_budget,
        caveat=(
            "the bots' turn-0 bases are fitted on the tune split before timing "
            "(batch work); apply times the history measure and the budget cut."
        ),
        per_baseline=True,
    ),
    Target(
        pattern=r"^cache\.session_memo_gate$",
        experiment=ROOT / "experiments" / "caching" / "exp-cache-004-session-memo-gate",
        build=_session_memo,
        caveat=(
            "a one-row frame holds no earlier turn of its session, so this times "
            "the gate and the memo's decision path, not a reuse; lookups of the "
            "sampled rows are built before timing."
        ),
        guard_key_version="session-memo-v1",
        per_baseline=True,
        version_name=lambda m: "exp-cache-004-session-memo-gate.t0.8",
        prepare=_session_memo_prepare,
    ),
    Target(
        pattern=r"^route\.small_classifier\.(?P<mode>rules|strict|strict_unknown_blocked)"
        r"(?P<set>\.with_reasoning_models)?$",
        experiment=ROOT / "experiments" / "routing" / "exp-route-012-small-classifier",
        build=_small_classifier,
        caveat=(
            "thresholds are frozen (MAX_INPUT_TOKENS) and the intent columns are "
            "joined before timing; apply times the rule, R-0 eligibility and the "
            "candidate costs."
        ),
        per_baseline=True,
        prepare=_small_classifier_prepare,
    ),
    Target(
        pattern=r"^route\.decision_router\.rules_only$",
        experiment=ROOT / "experiments" / "routing" / "exp-route-013-decision-router",
        build=_decision_router,
        caveat=(
            "tiers (gate, rules, safe tier) and the flags are computed for the "
            "whole frame before timing; apply times the R-0 candidate costs and "
            "the choice. No decision backend exists in this mode."
        ),
        per_baseline=True,
    ),
)


def target_for(lever_id: str) -> tuple[Target, re.Match]:
    for target in TARGETS:
        m = re.match(target.pattern, lever_id)
        if m:
            return target, m
    raise SystemExit(f"no known version for lever_id {lever_id!r}")


def load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def make_context(sprint: dict, key_version: str | None) -> ReplayContext:
    base = sprint["baselines"]
    empty: frozenset[str] = frozenset()
    guard = (
        CacheGuard(
            approved=None, blocked=empty, disabled_bots=empty, key_version=key_version
        )
        if key_version
        else None
    )
    return ReplayContext(
        period_bounds=period_bounds_from_config(sprint["periods"]),
        price_table=load_toml(ROOT / base["price_table"]),
        catalogue=load_toml(ROOT / base["catalogue"]),
        seed=int(sprint["split"]["seed"]),
        min_n=sprint.get("sufficiency", {}).get("min_n"),
        guard=guard,
    )


def load_version(
    target: Target, m: re.Match, sprint: dict, req: pd.DataFrame, rows: pd.DataFrame
) -> StepVersion:
    def load(obj: str) -> Any:
        spec = StrategySettings(
            slot=StrategySlot.CANDIDATE_INDEX,  # unused for a file; no lever slot yet
            file="version.py",
            object=obj,
        )
        return load_candidate(spec, target.experiment, ROOT / "experiments")

    return target.build(load, m, sprint, req, rows)


# --- main ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lever_ids", nargs="+")
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--seed", type=int, help="default: [split] seed in sprint.toml")
    parser.add_argument("--folder", type=Path, default=OUT_DIR)
    parser.add_argument("--dry-run", action="store_true", help="time, write nothing")
    args = parser.parse_args(argv)

    sprint = load_toml(SPRINT)
    seed = args.seed if args.seed is not None else int(sprint["split"]["seed"])
    hw = hardware()
    day = datetime.now(UTC).date().isoformat()
    targets = [(lid, *target_for(lid)) for lid in args.lever_ids]
    print(f"hardware: {hw}")

    req = None
    for lever_id, target, m in targets:
        ctx = make_context(sprint, target.guard_key_version)
        if req is None:
            req = with_blocks(scope(pd.read_parquet(REQUESTS), ctx))
        frame = target.prepare(req) if target.prepare else req
        rows = sample_rows(frame, args.n, seed=seed)  # the rows measure() times
        version = load_version(target, m, sprint, frame, rows)
        expected = target.version_name(m) if target.version_name else lever_id
        if version.name != expected:
            raise SystemExit(f"built {version.name}, expected {expected}")

        def note(s: dict[str, float]) -> str:
            return (
                f"apply on one-row frames, {s['n']} seeded report-period LLM rows, "
                f"1 warm-up; p50 {s['p50_ms']} ms, p95 {s['p95_ms']} ms, max "
                f"{s['max_ms']} ms; {day}, {hw['cpu']}, {hw['python']}."
            )

        summary = measure(
            lever_id,
            version,
            frame,
            ctx,
            folder=args.folder,
            n=args.n,
            seed=seed,
            note=note,
            caveat=target.caveat,
            write=not args.dry_run,
            per_baseline=target.per_baseline,
        )
        print(
            f"{lever_id:42s} n={summary['n']:<5} p50={summary['p50_ms']:.4f} ms  "
            f"p95={summary['p95_ms']:.4f} ms  max={summary['max_ms']:.4f} ms  "
            f"target p95 <= {TARGET_P95_MS:.0f} ms: {verdict(summary['p95_ms'])}  "
            f"files {'(dry run) ' if args.dry_run else ''}{summary['files']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
