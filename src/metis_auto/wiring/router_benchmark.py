"""Latency benchmark of a local decision backend (ADR-0047
point 4; R5).

Measures one backend in isolation (``decide`` with a generous timeout, so the
real duration is recorded) on decision states built exactly as the cascade
builds them, and reports against the local router's budget, **60 ms p95**
(owner). States come from:

- ``synthetic``: SYNTHETIC Persian, English and mixed messages at four lengths,
  with and without a previous user turn (no dataset text);
- ``slice``: the frozen 150-record dev slice (``pre_retrieval`` requests →
  features → gate → state). Gated records are counted and skipped: the
  cascade would not ask the model for them.

Output is counts, timings (ms), token counts and memory only, never text:
load time and sha256 check time, latency p50/p90/p95/p99/max overall and by
message length, the share over budget, model input tokens per call, errors
by kind, and the share of answers below the confidence gate (A-105).
If THX-01 misses the budget, the next steps are fewer threads or more, a
shorter state (``--max-message-chars``), then ONNX int8; else inline routing
is rules only and THX-01 runs in shadow (ADR-0047 point 4).
"""

from __future__ import annotations

import os
import platform
import statistics
import time
from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from typing import Any

from metis_auto.adapters.system import SystemClock
from metis_auto.adapters.system.resources import peak_rss_mb
from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.contracts import (
    Component,
    ComponentState,
    DecisionError,
    DecisionQuestionSet,
    DecisionState,
    Language,
    LastAssistantTurnKind,
    Request,
)
from metis_auto.domain.features import FeatureConfig, extract_features
from metis_auto.domain.routing.decision import (
    GateConfig,
    StateConfig,
    build_state,
    needs_decision,
    result_confidence,
)
from metis_auto.ports import BaseRouter

BUDGET_MS = 60.0
LENGTH_BUCKETS = ((0, 40, "<=40"), (41, 200, "41-200"), (201, 600, "201-600"))
SYNTHETIC = "[SYNTHETIC]"

_FA = (
    "سلام",
    "ساعت کاری فروشگاه در روزهای تعطیل چیست؟",
    "لطفاً این متن را خلاصه کن و نکات اصلی را در سه بند بنویس.",
    "برای سفارشم که هفته پیش ثبت شده هنوز پیامکی نیامده، پیگیری کنید.",
)
_EN = (
    "Thanks!",
    "What is the refund policy for damaged items?",
    "Compare these two plans and tell me which is cheaper over a year.",
    "Explain step by step why the integral of 1/x is ln|x|.",
)


def _bucket(chars: int) -> str:
    for low, high, name in LENGTH_BUCKETS:
        if low <= chars <= high:
            return name
    return ">600"


def synthetic_states(n: int, *, max_message_chars: int = 1000) -> list[DecisionState]:
    """``n`` SYNTHETIC states cycling language, length and history."""
    states = []
    for i in range(n):
        persian = i % 3 != 1
        base = (_FA if persian else _EN)[i % 4]
        repeat = (1, 3, 8, 20)[(i // 4) % 4]
        message = f"{SYNTHETIC} " + " ".join([base] * repeat)
        message = message[:max_message_chars]
        previous = (
            Component.present(f"{SYNTHETIC} {(_FA if persian else _EN)[(i + 1) % 4]}")
            if i % 2
            else Component[str].absent()
        )
        states.append(
            DecisionState(
                message=message,
                message_truncated=len(message) >= max_message_chars,
                previous_user_turn=previous,
                last_assistant_turn_kind=LastAssistantTurnKind.ANSWER
                if i % 2
                else LastAssistantTurnKind.NONE,
                retrieved_state=ComponentState.UNKNOWN,
                language=Language.PERSIAN if persian else Language.ENGLISH,
                turn_depth=1 if i % 2 else 0,
                dataset_derived=False,
            )
        )
    return states


def slice_states(
    requests: Iterable[Request],
    *,
    features: FeatureConfig,
    gate: GateConfig,
    state: StateConfig,
) -> tuple[list[DecisionState], Counter[str]]:
    """States the cascade would send for these requests, and why the others
    were skipped (gate rule IDs, ``ineligible_state``)."""
    measurement = MeasurementService(
        Fingerprinter(os.urandom(32)), SystemClock(), ApproxCharsTokenizer()
    )
    states, skipped = [], Counter()
    for request in requests:
        feats = extract_features(request, measurement.measure(request), features)
        decided = needs_decision(feats, gate)
        if decided is not None:
            skipped[decided.rule_id] += 1
            continue
        built = build_state(request, feats, state, dataset_derived=True)
        if built is None:
            skipped["ineligible_state"] += 1
            continue
        states.append(built)
    return states, skipped


def _pct(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)

    def at(q: float) -> float:
        return round(
            ordered[min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))], 2
        )

    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 2),
        "p90": at(0.90),
        "p95": at(0.95),
        "p99": at(0.99),
        "max": round(ordered[-1], 2),
        "mean": round(statistics.fmean(ordered), 2),
    }


def run(
    backend: BaseRouter,
    states: Sequence[DecisionState],
    questions: DecisionQuestionSet,
    *,
    warmup: int = 5,
    repeat: int = 1,
    budget_ms: float = BUDGET_MS,
    min_confidence: float = 0.6,
    timeout_ms: float = 30_000,
    gate_questions: Collection[str] | None = None,
) -> dict[str, Any]:
    """Times every ``decide`` (wall clock around the call and the backend's
    own measurement); returns counts and timings only."""
    for s in states[: max(0, warmup)]:
        backend.decide(s, questions, timeout_ms=timeout_ms)
    wall: list[float] = []
    reported: list[float] = []
    by_length: dict[str, list[float]] = {}
    tokens: list[int] = []
    errors: Counter[str] = Counter()
    low = low_all = answered = 0
    started = time.perf_counter()
    for _ in range(max(1, repeat)):
        for s in states:
            t0 = time.perf_counter()
            out = backend.decide(s, questions, timeout_ms=timeout_ms)
            ms = (time.perf_counter() - t0) * 1000.0
            if isinstance(out, DecisionError):
                kind = (
                    "invalid_response"
                    if out.invalid_response
                    else out.error_class.value
                    if out.error_class
                    else "error"
                )
                errors[kind] += 1
                continue
            answered += 1
            wall.append(ms)
            reported.append(out.latency_ms)
            by_length.setdefault(_bucket(len(s.message)), []).append(ms)
            if out.usage is not None:
                tokens.append(out.usage.input.tokens)
            confidence = result_confidence(out, gate_questions)
            if confidence is not None and confidence < min_confidence:
                low += 1
            every = result_confidence(out)
            if every is not None and every < min_confidence:
                low_all += 1
    overall = _pct(wall)
    p95 = overall.get("p95")
    return {
        "backend": f"{backend.ref.name}@{backend.ref.version}",
        "states": len(states),
        "calls": len(states) * max(1, repeat),
        "answered": answered,
        "errors": dict(sorted(errors.items())),
        "latency_ms": overall,
        "backend_reported_ms": _pct(reported),
        "latency_ms_by_message_chars": {
            k: _pct(v) for k, v in sorted(by_length.items())
        },
        "over_budget_share": round(sum(m > budget_ms for m in wall) / len(wall), 3)
        if wall
        else None,
        "budget_ms": budget_ms,
        "meets_budget_p95": None if p95 is None else bool(p95 <= budget_ms),
        "model_input_tokens_per_call": _pct([float(t) for t in tokens]),
        "below_confidence_gate_share": round(low / answered, 3) if answered else None,
        "gate_questions": "all" if gate_questions is None else sorted(gate_questions),
        "below_gate_share_all_questions": round(low_all / answered, 3)
        if answered
        else None,
        "min_confidence": min_confidence,
        "seconds": round(time.perf_counter() - started, 1),
    }


def machine() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "peak_rss_mb": peak_rss_mb(),
    }
