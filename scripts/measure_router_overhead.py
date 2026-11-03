"""Measure a local decision backend's latency against the 60 ms p95 budget (R5).

    python scripts/measure_router_overhead.py                      # THX-01, synthetic
    python scripts/measure_router_overhead.py --from-slice         # the frozen slice
    python scripts/measure_router_overhead.py --threads 2          # thread count
    python scripts/measure_router_overhead.py --max-message-chars 300
    python scripts/measure_router_overhead.py --backend mizan_http # a llama-server

Offline: THX-01 loads only its pinned, sha256-checked files (run
scripts/fetch_router_assets.py first); a local server must already be running
on loopback. No network beyond loopback, no key, no spend. ``--from-slice``
reads the frozen dev slice only after checking it is the committed one; its
text stays in memory. Prints counts, timings (ms), token counts and memory
only: never message text. ADR-XXXX (system-one-decision-router) point 4: if THX-01
misses 60 ms p95, try threads and shorter states, then ONNX int8; else inline routing is
rules only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from metis_auto.adapters.system import SystemClock
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.domain.routing.decision import mapping_question_ids
from metis_auto.evaluation.router_slice.records import to_request
from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring import router_benchmark as rb
from metis_auto.wiring.from_settings import pipeline_config
from metis_auto.wiring.router_slice import DEFAULT_CONFIG, RouterSlice, SliceRefused
from metis_auto.wiring.routers import backend_builder


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--backend", default="thx01", help="a [router.backends] name")
    ap.add_argument("--synthetic", type=int, default=200, help="synthetic states")
    ap.add_argument("--from-slice", action="store_true", help="the frozen dev slice")
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--threads", type=int, help="override the backend's threads")
    ap.add_argument("--max-message-chars", type=int, help="shorter states")
    ap.add_argument("--state-format", choices=["text", "json"])
    ap.add_argument(
        "--profile",
        type=int,
        default=0,
        help="also take N calls apart (sequence building, forward, decoding)",
    )
    ap.add_argument("--out", type=Path, help="also write the JSON here")
    args = ap.parse_args()

    def emit(data: dict) -> None:
        text = json.dumps(data, indent=2)
        print(text)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")

    started = time.perf_counter()
    loaded = load_settings()
    settings = loaded.settings.router.backends.get(args.backend)
    if settings is None:
        print(f"no router backend {args.backend!r}", file=sys.stderr)
        return 2
    update = {}
    if args.threads is not None and hasattr(settings, "threads"):
        update["threads"] = args.threads
    if args.state_format and hasattr(settings, "state_format"):
        update["state_format"] = args.state_format
    settings = settings.model_copy(update=update)
    policy = pipeline_config(loaded).routing.decision_router or DecisionRouterConfig()
    state_config = policy.state
    if args.max_message_chars:
        state_config = state_config.model_copy(
            update={"max_message_chars": args.max_message_chars}
        )
    questions = loaded.reference.router_questions.get(
        loaded.settings.router.question_set, loaded.settings.router.question_language
    )
    backend = backend_builder(
        args.backend,
        settings,
        policy,
        assets=loaded.reference.routers,
        assets_root=loaded.path(loaded.settings.paths.router_assets),
    )(SystemClock())
    availability = backend.available()
    load = getattr(backend, "last_load", None)
    load_info = (
        {
            "ok": load.ok,
            "reason": load.reason.value if load.reason else None,
            "load_ms": round(load.load_ms, 1),
            "sha256_check_ms": round(load.sha_ms, 1),
            "captured_warnings": load.warnings,
            "calibrated": load.calibrated,
            "threads": load.threads,
            "hard_linked_files": load.linked,
            "copied_files": load.copied,
            "work_dir_extra_kb": round(load.copied_bytes / 1024, 1),
            "detail": load.detail,
            "import_ms": None if load.import_ms is None else round(load.import_ms, 1),
            "agent_ms": None if load.agent_ms is None else round(load.agent_ms, 1),
            "param_dtypes": list(load.param_dtypes),
            "cast_to_float32": load.cast_to_float32,
        }
        if load is not None
        else None
    )
    if not availability.available:
        emit(
            {
                "backend": args.backend,
                "available": False,
                "reason": availability.reason.value if availability.reason else None,
                "load": load_info,
            }
        )
        return 2

    skipped: dict[str, int] = {}
    if args.from_slice:
        try:
            records = RouterSlice(
                repo_root(),
                loaded.settings.data.full_data_root,
                repo_root() / Path(DEFAULT_CONFIG),
            ).frozen_records()
        except SliceRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        states, counts = rb.slice_states(
            (to_request(r, profile="pre_retrieval") for r in records),
            features=pipeline_config(loaded).features,
            gate=policy.gate,
            state=state_config,
        )
        skipped = dict(sorted(counts.items()))
        source = {"source": "slice", "records": len(records)}
    else:
        states = rb.synthetic_states(
            args.synthetic, max_message_chars=state_config.max_message_chars
        )
        source = {"source": "synthetic", "records": len(states)}
    result = rb.run(
        backend,
        states,
        questions,
        warmup=args.warmup,
        repeat=args.repeat,
        min_confidence=loaded.settings.router.min_confidence,
        gate_questions=mapping_question_ids(policy.questions)
        if loaded.settings.router.confidence_questions == "mapping"
        else None,
    )
    profiles = []
    profiler = getattr(backend, "profile", None)
    if args.profile and profiler is not None:
        profiles = [profiler(s, questions) for s in states[: args.profile]]
    emit(
        {
            **source,
            "profile": profiles,
            "skipped_by_gate": skipped,
            "state": {
                "format": getattr(settings, "state_format", None),
                "max_message_chars": state_config.max_message_chars,
                "max_previous_turn_chars": state_config.max_previous_turn_chars,
            },
            "threads": getattr(settings, "threads", None),
            "load": load_info,
            **result,
            "machine": rb.machine(),
            "total_s": round(time.perf_counter() - started, 1),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
