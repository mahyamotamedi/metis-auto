"""Measure the pipeline's own overhead on the walking skeleton (brief §11).

    python scripts/measure_overhead.py [--requests 2000] [--hit-ratio 0.5]
        [--tokenizer openai-o200k-base] [--instructions-chars 0]
        [--sizes-from-sample] [--compression off|llmlingua2|fake]
        [--compress-rate 0.5] [--out reports/cost/overhead.json]

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

``--sizes-from-sample`` (Stage 8, brief §11): one request per sample replay
case, rebuilt from **sizes only**: the message, instructions, each history
turn (with its role), and each retrieved item get SYNTHETIC filler of the
same character length, and attachments stay present where the case had
them. No sample text is kept or written; only size aggregates are printed.
Every message is unique, so every request is an exact-cache miss (the worst
case for counting). The synthetic models' context windows are raised to
1,000,000 placeholder tokens so large sample instructions do not overflow
(``--requests`` and ``--hit-ratio`` are then ignored).

``--compression`` (Demo milestone, brief §9 and §11): run the EXPERIMENTAL
context compressor on every miss (history turns and retrieved items of at
least ``min_chars``; never instructions or the message). Its time is the
``context.compress`` span, part of the overhead total. The JSON adds the
compressor's token totals (its own tokens) and the input tokens actually
sent per miss (the target tokenizer), so the saving can be compared with the
run without compression. ``llmlingua2`` needs the extra ``compress`` and the
model files (scripts/fetch_compressor_assets.py); ``fake`` is the SYNTHETIC
word-dropper (mechanics only). With ``--sizes-from-sample`` the texts are
repeated SYNTHETIC filler: times reflect the lengths, compression rates do not
reflect real text.
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

from metis_auto.adapters.compressors import FakeCompressor
from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.application.measurement import Fingerprinter
from metis_auto.contracts import (
    SPAN_CATEGORY,
    AttachmentRef,
    Component,
    LatencyCategory,
    Modality,
    Request,
    RetrievedContext,
    RetrievedItem,
    RunMode,
    ServedBy,
    Turn,
)
from metis_auto.contracts.events import ContextBuilt, ContextCompressed
from metis_auto.settings import load_settings
from metis_auto.wiring.compression import build_compressor
from metis_auto.wiring.experiments import sample_cases
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


def filler(n: int, salt: str = "") -> str:
    text = salt + FILLER * (n // len(FILLER) + 1)
    return text[:n] if n > len(salt) else (salt + "x")[: max(n, 1)]


def sample_sized_requests() -> tuple[list[Request], dict[str, dict[str, int]]]:
    """SYNTHETIC requests with the sample cases' component sizes."""
    import secrets

    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    fp = Fingerprinter(secrets.token_bytes(32))  # IDs only; never written
    cases = sample_cases(loaded, fp).cases
    out: list[Request] = []
    sizes: dict[str, list[int]] = defaultdict(list)
    for i, case in enumerate(cases):
        r = case.request
        sizes["message"].append(len(r.message))
        instr = r.instructions.value
        hist = r.history.value or ()
        items = r.retrieved.value.items if r.retrieved.value else ()
        if instr:
            sizes["instructions"].append(len(instr))
        sizes["history_chars"].append(sum(len(t.text) for t in hist))
        sizes["history_turns"].append(len(hist))
        if items:
            sizes["retrieved_chars"].append(sum(len(x.text) for x in items))

        def state(c, value):
            return (
                Component.present(value)
                if value
                else (
                    Component.absent()
                    if c.state.value != "unknown"
                    else Component.unknown()
                )
            )

        out.append(
            Request(
                message=filler(len(r.message), f"{SYNTHETIC} {i} "),
                instructions=state(
                    r.instructions, filler(len(instr)) if instr else None
                ),
                history=state(
                    r.history,
                    tuple(
                        Turn(role=t.role, text=filler(len(t.text), SYNTHETIC))
                        for t in hist
                    )
                    or None,
                ),
                retrieved=state(
                    r.retrieved,
                    RetrievedContext(
                        items=tuple(
                            RetrievedItem(text=filler(len(x.text), SYNTHETIC))
                            for x in items
                        )
                    )
                    if items
                    else None,
                ),
                attachments=Component.present((AttachmentRef(modality=Modality.IMAGE),))
                if r.attachments.value
                else Component.absent(),
                structured_input=Component.absent(),
                session_ref=f"sess-bench-{case.session_ref[-8:]}",
            )
        )
    agg = {
        k: {
            "n": len(v),
            "p50": int(statistics.median(v)),
            "p95": int(percentile(v, 0.95)),
            "max": max(v),
        }
        for k, v in sorted(sizes.items())
        if v
    }
    return out, agg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--hit-ratio", type=float, default=0.5)
    parser.add_argument("--tokenizer", default="openai-o200k-base")
    parser.add_argument("--instructions-chars", type=int, default=0)
    parser.add_argument("--sizes-from-sample", action="store_true")
    parser.add_argument(
        "--compression", choices=["off", "llmlingua2", "fake"], default="off"
    )
    parser.add_argument("--compress-rate", type=float, default=0.5)
    parser.add_argument("--out", type=Path, help="also write the JSON here")
    args = parser.parse_args()

    loaded = skeleton_settings(hermetic=False)
    tokens = build_tokenizers(loaded)
    if args.tokenizer not in tokens.tokenizers:
        print(f"unknown tokenizer ref {args.tokenizer!r}", file=sys.stderr)
        return 2
    status = next(s for s in tokens.status if s.ref == args.tokenizer)
    config = pipeline_config(loaded)

    def patched(e):
        update = {"tokenizer_ref": args.tokenizer}
        if args.sizes_from_sample:  # SYNTHETIC placeholder window, see docstring
            update["context_window"] = e.context_window.model_copy(
                update={"value": 1_000_000}
            )
        return e.model_copy(update=update)

    entries = tuple(patched(e) for e in config.catalogue.entries)
    config = config.model_copy(
        update={"catalogue": config.catalogue.model_copy(update={"entries": entries})}
    )
    compressor = None
    if args.compression != "off":
        settings = pipeline_config(load_settings(environ={}, dotenv=None, runtime=None))
        compression = settings.context.compression.model_copy(
            update={"enabled": True, "rate": args.compress_rate}
        )
        context = config.context.model_copy(update={"compression": compression})
        config = config.model_copy(update={"context": context})
        compressor = (
            FakeCompressor()
            if args.compression == "fake"
            else build_compressor(loaded, compression.compressor)
        )
    sink = InMemoryEventSink()
    pipeline = build_pipeline(
        config,
        model_client=FakeModelClient(),
        cache_store=InMemoryCacheStore(),
        sink=sink,
        fingerprint_key=fingerprint_key(loaded),
        run_id="run-measure-overhead",
        run_mode=RunMode.SIMULATED,
        tokenizers=tokens.tokenizers,
        templates=tokens.templates,
        config_hash=loaded.config_hash,
        compressor=compressor,
    )

    size_summary = None
    if args.sizes_from_sample:
        batch, size_summary = sample_sized_requests()
    else:
        batch = requests(args.requests, args.hit_ratio, args.instructions_chars)
    spans: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    served: dict[str, int] = defaultdict(int)
    sent_tokens: list[int] = []
    squeezed = defaultdict(int)
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
        for event in sink.events:
            payload = event.payload
            if isinstance(payload, ContextBuilt) and payload.record.input_tokens:
                sent_tokens.append(payload.record.input_tokens.tokens)
            elif isinstance(payload, ContextCompressed):
                for c in payload.components:
                    squeezed["items_compressed"] += c.items_compressed
                    squeezed["items_skipped"] += c.items_skipped
                    squeezed["chars_before"] += c.chars_before
                    squeezed["chars_after"] += c.chars_after
                    squeezed["compressor_tokens_before"] += c.tokens_before
                    squeezed["compressor_tokens_after"] += c.tokens_after
        sink.events.clear()

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
        "requests": len(batch),
        "sizes_from_sample": size_summary,
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
        "compression": {
            "mode": args.compression,
            "compressor": f"{compressor.ref.name}@{compressor.ref.version}"
            if compressor
            else None,
            "rate": args.compress_rate if compressor else None,
            "token_method": compressor.token_method if compressor else None,
            **dict(squeezed),
        },
        "sent_input_tokens_per_context": {
            "n": len(sent_tokens),
            "sum": sum(sent_tokens),
            "p50": int(statistics.median(sent_tokens)) if sent_tokens else None,
        },
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
