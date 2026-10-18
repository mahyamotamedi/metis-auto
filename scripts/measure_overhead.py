"""Measure the pipeline's own overhead on the walking skeleton (brief §11).

    python scripts/measure_overhead.py [--requests 2000] [--hit-ratio 0.5]
        [--tokenizer openai-o200k-base] [--instructions-chars 0]
        [--out reports/cost/overhead.json]

Runs N SYNTHETIC requests through the real pipeline (fake model client,
in-memory cache, no network, no keys) and reports p50 / p95 / max per span,
the overhead total (the spans the contracts classify as overhead,
``SPAN_CATEGORY``), the hit/miss mix, and the hardware. The synthetic
catalogue's models are counted with the chosen tokenizer from the tokenizer
table (``--tokenizer``; exact backends need scripts/fetch_tokenizer_assets.py),
so the tokenizer's cost is part of the measurement. ``--instructions-chars``
adds SYNTHETIC instructions of that size, to see how counting scales.
Indicative only (A-22): a local machine, synthetic requests, a fake model.
Prints content-free numbers only. Thin wrapper over wiring.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.contracts import (
    SPAN_CATEGORY,
    Component,
    LatencyCategory,
    Request,
    RunMode,
    ServedBy,
)
from metis_auto.wiring.from_settings import fingerprint_key, pipeline_config
from metis_auto.wiring.pipeline import build_pipeline
from metis_auto.wiring.tokenizers import build_tokenizers
from metis_auto.wiring.walking_skeleton import SYNTHETIC, skeleton_settings

FILLER = (
    f"{SYNTHETIC} You are a support assistant for an online shop. "
    "به پرسش‌های مشتریان درباره سفارش، ارسال و بازگشت کالا پاسخ بده. "
    "Answer briefly and politely; do not invent order details. "
)


def hardware() -> dict[str, str]:
    info = {
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "python": f"{platform.python_implementation()} {platform.python_version()}",
    }
    if platform.system() == "Darwin":
        try:
            info["cpu"] = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    info.setdefault("cpu", platform.processor() or "unknown")
    return info


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def requests(n: int, hit_ratio: float, instructions_chars: int) -> list[Request]:
    """Every request is either new (a miss) or repeats the previous new one in
    the same session (an exact hit); deterministic, no randomness."""
    instructions = (FILLER * (instructions_chars // len(FILLER) + 1))[
        : max(instructions_chars, 0)
    ]
    out: list[Request] = []
    last: Request | None = None
    hits_due = 0.0
    for i in range(n):
        hits_due += hit_ratio
        if last is not None and hits_due >= 1:
            hits_due -= 1
            out.append(last)
            continue
        last = Request(
            message=f"{SYNTHETIC} سفارش شماره {i} کی می‌رسد؟ order {i}",
            history=Component.absent(),
            instructions=Component.present(instructions)
            if instructions.strip()
            else Component.absent(),
            retrieved=Component.absent(),
            attachments=Component.absent(),
            structured_input=Component.absent(),
            session_ref=f"sess-bench-{i // 50}",
        )
        out.append(last)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--hit-ratio", type=float, default=0.5)
    parser.add_argument("--tokenizer", default="openai-o200k-base")
    parser.add_argument("--instructions-chars", type=int, default=0)
    parser.add_argument("--out", type=Path, help="also write the JSON here")
    args = parser.parse_args()

    loaded = skeleton_settings(hermetic=False)
    tokens = build_tokenizers(loaded)
    if args.tokenizer not in tokens.tokenizers:
        print(f"unknown tokenizer ref {args.tokenizer!r}", file=sys.stderr)
        return 2
    status = next(s for s in tokens.status if s.ref == args.tokenizer)
    config = pipeline_config(loaded)
    entries = tuple(
        e.model_copy(update={"tokenizer_ref": args.tokenizer})
        for e in config.catalogue.entries
    )
    config = config.model_copy(
        update={"catalogue": config.catalogue.model_copy(update={"entries": entries})}
    )
    pipeline = build_pipeline(
        config,
        model_client=FakeModelClient(),
        cache_store=InMemoryCacheStore(),
        sink=InMemoryEventSink(),
        fingerprint_key=fingerprint_key(loaded),
        run_id="run-measure-overhead",
        run_mode=RunMode.SIMULATED,
        tokenizers=tokens.tokenizers,
        templates=tokens.templates,
        config_hash=loaded.config_hash,
    )

    batch = requests(args.requests, args.hit_ratio, args.instructions_chars)
    spans: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    served: dict[str, int] = defaultdict(int)
    for request in batch:
        meta = pipeline.handle(request).metadata
        kind = "hit" if meta.served_by == ServedBy.CACHE else "miss"
        served[kind] += 1
        overhead = 0.0
        for span in meta.spans:
            spans[kind][span.span.value].append(span.duration_ms)
            if SPAN_CATEGORY[span.span] == LatencyCategory.OVERHEAD:
                overhead += span.duration_ms
        spans[kind]["overhead_total"].append(overhead)

    def summary(values: list[float]) -> dict[str, float]:
        return {
            "n": len(values),
            "p50_ms": round(statistics.median(values), 4),
            "p95_ms": round(percentile(values, 0.95), 4),
            "max_ms": round(max(values), 4),
        }

    result = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "script": "scripts/measure_overhead.py",
        "requests": args.requests,
        "hit_ratio_requested": args.hit_ratio,
        "served": dict(served),
        "instructions_chars": args.instructions_chars,
        "tokenizer": {
            "ref": status.ref,
            "loaded": status.loaded,
            "fidelity": status.fidelity,
            "fallback_reason": status.reason,
        },
        "config_hash": loaded.config_hash,
        "hardware": hardware(),
        "spans": {
            kind: {name: summary(v) for name, v in sorted(by_span.items())}
            for kind, by_span in sorted(spans.items())
        },
        "note": "Indicative only (A-22): synthetic requests, fake model, one machine.",
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
