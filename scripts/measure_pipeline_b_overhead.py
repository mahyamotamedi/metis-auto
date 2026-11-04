"""Offline per-request overhead of Pipeline B's step versions (final plan L-1).

    python scripts/measure_pipeline_b_overhead.py [LEVER_ID ...] [--n 1000]
        [--seed SEED] [--folder reports/levers] [--dry-run]

One target per B family, built with the helpers of
``scripts/run_pipeline_b_day2.py`` / ``run_pipeline_b_day3.py``: R-B1
``RetrievalResultCache`` with its lookups frame, R-B2 ``CrossTurnChunkPolicy``
with its chunks frame, R-B3 ``KnnRouter`` fitted on the tune split (fitting is
not timed). Without ``LEVER_ID``, every ``rb1.*``, ``rb2.*`` and ``rb3.*``
result in ``--folder`` is measured, one measurement per version.

Sample: ``--n`` seeded LLM rows of the **tune** period with
``split_by_session == "tune"``, ``[sample] tenant_cap`` applied
(``replay_scope.cap_tenant_share``, before and after the draw). The report period
is never read. Method (the pattern of ``scripts/measure_lever_overhead.py`` and
``scripts/measure_overhead.py``): one untimed warm-up, then ``apply`` on **each
row as its own one-row frame**, timed with ``time.perf_counter_ns``; p50
(median), p95 (nearest rank) and max in ms. The data a version needs (lookups,
chunks, fitted router) is built before timing.

Writes ``overhead_ms_p50`` / ``overhead_ms_p95`` and one ``Overhead:`` assumption
into every result of that version (the four baselines get the same figures:
overhead is per version), keeping every other field and the manifest. A version
that cannot be measured keeps None and says so ("not measured", never 0). Also
writes a content-free ``pipeline_b_overhead.json`` in ``--folder``: per version
p50, p95, n, the 100 ms p95 target (Q-14) and pass/fail. ``--dry-run`` prints
the plan and reads and writes nothing.

Why a second script beside Pipeline A's ``measure_lever_overhead.py``: that
script has another owner, has no B targets (it stops with "no known version" on
``rb1``/``rb2``/``rb3``) and samples report-period rows. It can be merged into
A's script later, with A's OK (ADR-0055). Prints
aggregates only: no text, hash, or bot, user, session or chunk ID. No network.
Traces: QA-LAT (100 ms p95, Q-14), FR-ROUTE-04, L-1, ADR-0032.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import re
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from metis_auto.analysis.baselines_full import cached_reported_separately
from metis_auto.analysis.lever_result import LeverResult
from metis_auto.analysis.replay_scope import cap_tenant_share

ROOT = Path(__file__).resolve().parents[1]
LEVERS = ROOT / "reports" / "levers"
SPRINT_CONFIG = ROOT / "config" / "evaluation" / "sprint.toml"
SUMMARY = "pipeline_b_overhead.json"

TARGET_P95_MS = 100.0
"""Per-request overhead target, p95 (brief §11, QA-LAT, Q-14)."""
DEFAULT_N = 1000
OVERHEAD_LABEL = "Overhead:"
CAVEAT_LABEL = "Overhead caveat:"
SAMPLE_LABEL = "Overhead sample:"
SAMPLE_NOTE = (
    "tune-period sample; Pipeline A's R-A3 figure (54.2 ms p95, "
    "route.per_bot) used report-period rows, so the two samples differ"
)
BASELINE = r"(?P<baseline>as_logged|todays_models|premium_gpt_5_5|best_single_cheap)"


# --- versions: lever_id -> what to build ---------------------------------------------


@dataclass(frozen=True)
class Spec:
    family: str
    step: str
    version: str
    params: dict[str, Any]


def _rb1(m: re.Match) -> Spec:
    days = int(m["days"])
    return Spec("rb1", "cache", f"retrieval_result_cache.ttl_{days}d", {"days": days})


def _rb2(m: re.Match) -> Spec:
    window = None if m["window"] == "all" else int(m["window"])
    pointer, ledger = int(m["pointer"]), m["mode"] == "ledger"
    name = f"cross_turn_chunks.ptr{pointer}{'.ledger' if ledger else ''}"
    name += ".all" if window is None else f".k{window}"
    return Spec(
        "rb2", "context", name, {"window": window, "pointer": pointer, "ledger": ledger}
    )


def _rb3(m: re.Match) -> Spec:
    k, wide = int(m["k"]), bool(m["wr"])
    name = "route.knn.with_reasoning_models" if wide else "route.knn"
    return Spec("rb3", "routing", f"{name}.k{k}", {"k": k, "with_reasoning": wide})


PATTERNS = (
    (
        rf"^rb1\.retrieval-cache\.ttl-(?P<days>[0-9]+)d\.user\.(?:tune|report)"
        rf"\.{BASELINE}$",
        _rb1,
    ),
    (
        rf"^rb2\.cross-turn\.k-(?P<window>[0-9]+|all)\.ptr-(?P<pointer>[0-9]+)"
        rf"\.(?P<mode>pointer|ledger)(?:\.report)?\.{BASELINE}$",
        _rb2,
    ),
    (
        rf"^rb3\.knn-router(?P<wr>\.with_reasoning_models)?\.k-(?P<k>[0-9]+)"
        rf"\.(?:tune|report)\.{BASELINE}$",
        _rb3,
    ),
)

CAVEATS = {
    "rb1": "one-row frame: the replay holds only this request's lookups, so this "
    "times keying, eligibility and the guard path, not a hit in a warm store; "
    "building the lookups frame is not timed.",
    "rb2": "one-row frame: only this request's chunks are scanned, so no earlier "
    "turn is in the session state and nothing is dropped; this times the decision "
    "pass, not a session-state lookup; building the chunks frame is not timed.",
    "rb3": "router fitted on the tune split before timing (fit not timed); apply "
    "prices the candidates, checks bot sufficiency and searches the k nearest "
    "training profiles.",
}


def spec_for(lever_id: str) -> Spec:
    """The B version of ``lever_id``; anything else stops the run."""
    for pattern, make in PATTERNS:
        m = re.match(pattern, lever_id)
        if m:
            return make(m)
    raise SystemExit(f"no Pipeline B version for lever_id {lever_id!r}")


def b_results(folder: Path) -> dict[str, list[Path]]:
    """Every ``rb*`` result in ``folder``: lever_id -> path (``LeverResult`` only)."""
    out: dict[str, list[Path]] = {}
    for path in sorted(folder.glob("rb[123].*.json")):
        result = LeverResult.from_json(path.read_text(encoding="utf-8"))
        out.setdefault(result.lever_id, []).append(path)
    return out


def plan(lever_ids: Sequence[str], folder: Path) -> dict[str, tuple[Spec, list[Path]]]:
    """Versions to measure (by version label) and the result files of each, all
    baselines. Without ``lever_ids``: every B version in ``folder``."""
    found = b_results(folder)
    for lever_id in lever_ids:
        spec_for(lever_id)
        if lever_id not in found:
            raise SystemExit(f"no LeverResult with lever_id {lever_id!r} in {folder}")
    wanted = {spec_for(lever_id).version for lever_id in (lever_ids or found)}
    out: dict[str, tuple[Spec, list[Path]]] = {}
    for lever_id, paths in sorted(found.items()):
        spec = spec_for(lever_id)
        if spec.version not in wanted:
            continue
        out.setdefault(spec.version, (spec, []))[1].extend(paths)
        for path in paths:
            r = LeverResult.from_json(path.read_text(encoding="utf-8"))
            if (r.step, r.version) != (spec.step, spec.version):
                raise SystemExit(
                    f"{path.name}: version {r.version} does not match its lever_id"
                )
    return dict(sorted(out.items()))


# --- sample and timing (pure, tested) ------------------------------------------------


def sample_tune_rows(
    req: pd.DataFrame, n: int, *, seed: int, tenant_cap: float
) -> pd.DataFrame:
    """Seeded sample of tune-period, tune-split LLM rows with no tenant above
    ``tenant_cap`` (the cap applied to the pool, then to the draw)."""
    pool = req[
        req["period"].eq("tune")
        & req["split"].eq("tune")
        & req["llm_request"].astype(bool)
    ]
    if pool.empty:
        raise ValueError("no tune-period, tune-split LLM rows to sample")
    pool = cap_tenant_share(pool, tenant_cap, seed=seed)
    drawn = pool.sample(n=min(n, len(pool)), random_state=seed)
    return cap_tenant_share(drawn, tenant_cap, seed=seed)


def time_apply(
    version: Any,
    rows: pd.DataFrame,
    ctx: Any,
    *,
    clock: Callable[[], int] = time.perf_counter_ns,
) -> list[float]:
    """Milliseconds per request, ``apply`` on one-row frames; one untimed
    warm-up on the first row. Any error propagates."""
    if rows.empty:
        raise ValueError("no rows to time")
    version.apply(rows.iloc[:1], ctx)  # warm-up
    times: list[float] = []
    for i in range(len(rows)):
        one = rows.iloc[i : i + 1]
        start = clock()
        out = version.apply(one, ctx)
        elapsed = clock() - start
        if not out.index.equals(one.index):
            raise ValueError(f"{version.name}: apply must keep the index it was given")
        times.append(elapsed / 1e6)
    return times


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest rank (the rule of ``scripts/measure_overhead.py``)."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def summarise(times: Sequence[float]) -> dict[str, float]:
    return {
        "n": len(times),
        "p50_ms": round(statistics.median(times), 4),
        "p95_ms": round(percentile(times, 0.95), 4),
        "max_ms": round(max(times), 4),
    }


def measure_version(
    build: Callable[[], Any],
    rows: pd.DataFrame,
    ctx: Any,
    *,
    clock: Callable[[], int] = time.perf_counter_ns,
) -> tuple[dict[str, float], Any]:
    """Build (untimed: fitting, frames), then time ``apply`` per request."""
    version = build()
    return summarise(time_apply(version, rows, ctx, clock=clock)), version


def built_as_planned(spec: Spec, version: Any, st: dict[str, Any]) -> bool:
    """The built version is the one the label names (R-B2's label adds the
    window; R-B3's the candidate set, checked on the router itself)."""
    if spec.family == "rb3":
        key = (
            "candidates_with_reasoning"
            if spec.params["with_reasoning"]
            else "candidates"
        )
        return version.k == spec.params["k"] and list(version.candidates) == list(
            st[key]
        )
    return spec.version.startswith(version.name)


def verdict(p95_ms: float | None) -> str:
    if p95_ms is None:
        return "not measured"
    return "pass" if p95_ms <= TARGET_P95_MS else "fail"


# --- writing (tested) ----------------------------------------------------------------


def _label(stats: dict[str, float] | None, machine: str, reason: str | None) -> str:
    if stats is None:
        return f"{OVERHEAD_LABEL} not measured ({reason}); fields left empty, never 0"
    return (
        f"{OVERHEAD_LABEL} offline per-request estimate, tune period, one-row apply, "
        f"no load test; machine {machine}. n {stats['n']}, 1 warm-up; p50 "
        f"{stats['p50_ms']} ms, p95 {stats['p95_ms']} ms, max {stats['max_ms']} ms"
    )


def write_overhead(
    paths: Sequence[Path],
    stats: dict[str, float] | None,
    *,
    machine: str,
    caveat: str | None = None,
    reason: str | None = None,
) -> None:
    """Overhead fields and labels into each file (older labels replaced); every
    other field, the manifest included, unchanged. ``stats`` None: not measured."""
    added = (_label(stats, machine, reason),)
    if stats is not None and caveat:
        added += (f"{CAVEAT_LABEL} {caveat}",)
    if stats is not None:
        added += (f"{SAMPLE_LABEL} {SAMPLE_NOTE}",)
    for path in paths:
        old = LeverResult.from_json(path.read_text(encoding="utf-8"))
        kept = tuple(
            a
            for a in old.assumptions
            if not a.startswith((OVERHEAD_LABEL, CAVEAT_LABEL, SAMPLE_LABEL))
        )
        data = old.model_dump() | {
            "overhead_ms_p50": None if stats is None else stats["p50_ms"],
            "overhead_ms_p95": None if stats is None else stats["p95_ms"],
            "assumptions": kept + added,
        }
        path.write_text(LeverResult.model_validate(data).to_json(), encoding="utf-8")


def sample_record(
    rows: pd.DataFrame, *, n: int, seed: int, tenant_cap: float
) -> dict[str, Any]:
    share = rows["user_id"].astype(str).value_counts(normalize=True).max()
    return {
        "period": "tune",
        "split": "tune (split_by_session)",
        "rows": "LLM requests",
        "n_requested": n,
        "n": len(rows),
        "seed": seed,
        "tenant_cap": tenant_cap,
        "max_tenant_share": round(float(share), 4),
    }


def summary_payload(
    measured: Sequence[dict[str, Any]],
    *,
    sample: dict[str, Any],
    machine: str,
    created_at: datetime,
) -> dict[str, Any]:
    """Content-free summary: per version p50, p95, n and the verdict."""
    versions = []
    for m in measured:
        stats = m.get("stats")
        p95 = None if stats is None else stats["p95_ms"]
        versions.append(
            {
                "family": m["family"],
                "step": m["step"],
                "version": m["version"],
                "n": None if stats is None else stats["n"],
                "p50_ms": None if stats is None else stats["p50_ms"],
                "p95_ms": p95,
                "max_ms": None if stats is None else stats["max_ms"],
                "target_p95_ms": TARGET_P95_MS,
                "verdict": verdict(p95),
                "result_files": m["files"],
                "reason": m.get("reason"),
            }
        )
    return {
        "task": "L-1, Pipeline B: offline per-request overhead of each version",
        "method": "apply on one-row frames, 1 untimed warm-up, time.perf_counter_ns; "
        "p50 median, p95 nearest rank; data and fitting built before timing",
        "evidence": "offline per-request estimate; not a load test (Q-14)",
        "target": {"p95_ms": TARGET_P95_MS, "source": "Q-14", "requirement": "QA-LAT"},
        "sample": sample,
        "sample_note": SAMPLE_NOTE,
        "machine": machine,
        "versions": sorted(versions, key=lambda v: (v["family"], v["version"])),
        "created_at": created_at.isoformat(),
    }


def machine_class() -> str:
    """OS, architecture and CPU model; no host name."""
    cpu = platform.processor() or "unknown CPU"
    if platform.system() == "Darwin":
        try:
            cpu = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return (
        f"{platform.system()} {platform.machine()}, {' '.join(cpu.split())}, "
        f"Python {platform.python_version()}"
    )


# --- builders over the real data (B's run helpers) -----------------------------------


def _load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(
        f"{name}_for_b_overhead", ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


D3 = _load_script("run_pipeline_b_day3")
D2 = D3.D2


def rb3_builder(
    st: dict[str, Any],
    train: pd.DataFrame,
    separate: frozenset[str],
    *,
    k: int,
    candidates: Sequence[str] | None = None,
) -> Callable[[], Any]:
    """R-B3 router fitted on ``train`` (the Day 3 factory: shared routing base;
    ``candidates`` default to the primary set)."""
    return lambda: D3._factory(st, separate, candidates)(train, k)


class Data:
    """The frames B's versions need, read once and built for the sample only."""

    def __init__(self, st: dict[str, Any], n: int, seed: int, cap: float) -> None:
        self.st = st
        self.req = D3.requests_frame(st, None)
        self.separate = cached_reported_separately(self.req)
        self.rows = sample_tune_rows(self.req, n, seed=seed, tenant_cap=cap)
        self._rb1: tuple[pd.DataFrame, pd.DataFrame] | None = None
        self._rb2: tuple[pd.DataFrame, pd.DataFrame, float] | None = None
        self._train: pd.DataFrame | None = None

    def rb1(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        if self._rb1 is None:
            rb1 = D3.load(D3.RB1)
            per_call = D2.per_call_items()
            rows = rb1.fee_blocks(self.rows, per_call)
            rag = D2.rag_json(set(rows["ai_message_id"]))
            lookups = rb1.build_lookups(rows, rag, per_call, scope="user")
            self._rb1 = (rows, lookups)
        return self._rb1

    def rb2(self) -> tuple[pd.DataFrame, pd.DataFrame, float]:
        if self._rb2 is None:
            rb1, rb2 = D3.load(D3.RB1), D3.load(D3.RB2)
            rows = rb1.fee_blocks(self.rows, D2.per_call_items())
            items = pd.read_parquet(
                D2.RAW / "derived" / "chat_message_billing.parquet",
                columns=["message_id", "inputTokens", "costBreakdown.input_tokens"],
            )
            rows = rb2.request_inputs(rows, items, self.separate)
            ids = set(rows["ai_message_id"])
            parts = []
            for f in sorted((D2.DERIVED / "chunks").glob("*.parquet")):
                part = pd.read_parquet(
                    f, columns=["message_id", "chunk_id", "n_chars", "h_exact"]
                )
                parts.append(part[part["message_id"].isin(ids)])
            table = pd.concat(parts, ignore_index=True)
            chunks = rb2.build_chunks(rows, table)
            self._rb2 = (rows, chunks, D2._ledger_value("recon.t0rag.coef_rag"))
        return self._rb2

    def train(self) -> pd.DataFrame:
        if self._train is None:
            r = self.req
            fit = r["split"].eq("tune") & r["period"].eq("tune") & r["llm_request"]
            self._train = r[fit].copy()
        return self._train

    def target(self, spec: Spec) -> tuple[Callable[[], Any], pd.DataFrame]:
        """(build, rows to time) for one version."""
        st, p = self.st, spec.params
        if spec.family == "rb1":
            rows, lookups = self.rb1()
            cache = D3.load(D3.RB1).version.RetrievalResultCache
            ttl = pd.Timedelta(days=p["days"])
            return (
                lambda: cache(ttl, lookups=lookups, shadow_rate=st["shadow_rate"]),
                rows,
            )
        if spec.family == "rb2":
            rows, chunks, tpc = self.rb2()
            policy = D3.load(D3.RB2).version.CrossTurnChunkPolicy
            w = p["window"]
            visible = (lambda d: True) if w is None else (lambda d: d <= w)
            return (
                lambda: policy(
                    p["pointer"],
                    visible,
                    p["ledger"],
                    chunks=chunks,
                    tokens_per_char=tpc,
                ),
                rows,
            )
        wide = st["candidates_with_reasoning"] if p["with_reasoning"] else None
        build = rb3_builder(st, self.train(), self.separate, k=p["k"], candidates=wide)
        return build, self.rows


# --- main ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lever_ids", nargs="*", help="default: every rb* result")
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--seed", type=int, help="default: [split] seed in sprint.toml")
    parser.add_argument("--folder", type=Path, default=LEVERS)
    parser.add_argument("--sprint-config", type=Path, default=SPRINT_CONFIG)
    parser.add_argument("--dry-run", action="store_true", help="plan only")
    args = parser.parse_args(argv)

    for lever_id in args.lever_ids:
        spec_for(lever_id)  # an unknown ID stops before anything is read
    todo = plan(args.lever_ids, args.folder)
    st = D3.settings(args.sprint_config)
    sprint = D2._toml(args.sprint_config)
    seed = args.seed if args.seed is not None else int(st["seed"])
    cap = float(sprint["sample"]["tenant_cap"])
    machine = machine_class()
    print(
        f"plan: {len(todo)} versions, {sum(len(p) for _, p in todo.values())} files; "
        f"n={args.n} seed={seed} tenant_cap={cap}; tune period, tune split, LLM "
        f"rows; machine {machine}"
    )
    for spec, paths in todo.values():
        print(f"  {spec.family} {spec.version:40s} files {len(paths)}")
    if args.dry_run:
        print("dry run: nothing read, nothing written")
        return 0

    data = Data(st, args.n, seed, cap)
    measured = []
    for spec, paths in todo.values():
        record: dict[str, Any] = {
            "family": spec.family,
            "step": spec.step,
            "version": spec.version,
            "files": len(paths),
        }
        try:
            build, rows = data.target(spec)
            stats, version = measure_version(build, rows, st["ctx"])
            if not built_as_planned(spec, version, st):
                raise ValueError(f"built {version.name}, expected {spec.version}")
            record["stats"] = stats
        except (OSError, KeyError, ValueError) as exc:
            record["stats"] = None
            record["reason"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        write_overhead(
            paths,
            record["stats"],
            machine=machine,
            caveat=CAVEATS[spec.family],
            reason=record.get("reason"),
        )
        measured.append(record)
        s = record["stats"]
        print(
            f"{spec.version:40s} "
            + (
                f"n={s['n']:<5} p50={s['p50_ms']:.4f} ms  p95={s['p95_ms']:.4f} ms  "
                f"max={s['max_ms']:.4f} ms  target p95 <= {TARGET_P95_MS:.0f} ms: "
                f"{verdict(s['p95_ms'])}"
                if s
                else f"not measured: {record['reason']}"
            )
        )
    payload = summary_payload(
        measured,
        sample=sample_record(data.rows, n=args.n, seed=seed, tenant_cap=cap),
        machine=machine,
        created_at=datetime.now(UTC),
    )
    (args.folder / SUMMARY).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
