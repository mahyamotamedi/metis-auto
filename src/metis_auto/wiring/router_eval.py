"""R8 shadow evaluation of the decision router on the frozen dev slice
(exp-route-013; ADR-XXXX (system-one-decision-router) point 12).

Each slice record goes through two pipelines with the fake answering client:
**rules only** (``decision_router`` policy with ``router.mode = "off"``: the
policy falls back to the rules) and **with the router** (a local chain:
``thx01`` from settings on the owner's machine, or the ``fake`` backend in
tests and CI). Per record we keep the routed model's catalogue tier, the
router's path, the decision status, the lowest confidence over the gate's
questions (Q-61) and the decision step's duration: ``ShadowRow``. The rows
are summarised by ``evaluation.router_eval.summarise`` (per split, balanced
and traffic-weighted, Persian first). Labels do not exist yet: agreement here
is agreement with the rules, not accuracy.

Two modes: the **inline settings** (the configured deadline, cache and gate:
what serving would see) and **offline** (``OFFLINE``: 60 s per request, no
cache, gate off; the evaluation mode, owner 2026-11-03), which also returns
each question's confidence and probability distribution and the provisional
gate proposal (``evaluation.router_eval.propose_gate``).

Local only: the slice's text stays in memory and never reaches a hosted
backend (no hosted backend is in either chain; ``real_data_approved`` stays
false). Output: counts, shares and timings only. Called by
scripts/evaluate_router_slice.py and tests.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from metis_auto.adapters.system import SystemClock
from metis_auto.contracts import DecisionStatus
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.domain.routing.decision import (
    answer_strength,
    mapping_question_ids,
    result_confidence,
)
from metis_auto.evaluation.router_eval import (
    ShadowRow,
    against_labels,
    answer_distributions,
    propose_gate,
    summarise,
)
from metis_auto.evaluation.router_slice.records import to_request
from metis_auto.ports import Clock
from metis_auto.settings import LoadedSettings

from .from_settings import pipeline_config
from .router_replay import replay_pipeline
from .routers import router_spec

Loader = Callable[[dict[str, Any]], LoadedSettings]
BACKENDS = ("thx01", "fake")
FAKE = "fake_local"


OFFLINE_TIMEOUT_MS = 60_000
OFFLINE = {
    "router.deadline_ms": OFFLINE_TIMEOUT_MS,
    "router.cache.enabled": False,
    "router.min_confidence": 0.0,
    "router.circuit.failure_threshold": 1_000_000,
}
"""Offline evaluation (owner, 2026-11-03): no inline deadline (60 s per
request), no router cache, the confidence gate off (every answer is used; the
gate is studied afterwards from the recorded strengths) and a breaker that
never opens, so the rows hold THX-01's real answers, never a fallback caused
by the inline budget."""


def _overrides(
    backend: str | None, profile: str, offline: bool = False
) -> dict[str, Any]:
    over: dict[str, Any] = {"pipeline.routing.policy": "decision_router"}
    if backend == "thx01":
        over.update(
            {
                "router.mode": "local",
                "router.backends.thx01.enabled": True,
                "router.chains.local": ["thx01"],
            }
        )
        if offline:
            over["router.backends.thx01.timeout_ms"] = OFFLINE_TIMEOUT_MS
    elif backend == "fake":
        over.update(
            {
                "router.mode": "local",
                f"router.backends.{FAKE}": {
                    "type": "fake",
                    "enabled": True,
                    "profile": profile,
                },
                "router.chains.local": [FAKE],
            }
        )
        if offline:
            over[f"router.backends.{FAKE}"]["timeout_ms"] = OFFLINE_TIMEOUT_MS
    if offline and backend is not None:
        over.update(OFFLINE)
    return over


def shadow_rows(
    load: Loader,
    records: Sequence[dict[str, Any]],
    *,
    backend: str = "thx01",
    profile: str = "cheap",
    clock: Clock | None = None,
    offline: bool = False,
) -> list[ShadowRow]:
    """One ``ShadowRow`` per record (content-free). ``offline``: the
    evaluation settings in ``OFFLINE`` (no inline deadline, no cache, gate off)."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}")
    clock = clock or SystemClock()
    rules_loaded = load(_overrides(None, profile))
    router_loaded = load(_overrides(backend, profile, offline))
    tier = {
        e.model_id: e.tier
        for e in router_loaded.reference.catalogue.entries
        if getattr(e, "tier", None) is not None
    }
    policy = (
        pipeline_config(router_loaded).routing.decision_router or DecisionRouterConfig()
    )
    gate_ids = (
        mapping_question_ids(policy.questions)
        if router_loaded.settings.router.confidence_questions == "mapping"
        else None
    )
    settings = router_loaded.settings.router
    min_confidence = settings.min_confidence
    statistic = settings.confidence_statistic
    mapping = mapping_question_ids(policy.questions)
    rules_pipe, rules_sink = replay_pipeline(
        rules_loaded, None, run_id="run-shadow-rules", clock=clock
    )
    spec = router_spec(router_loaded, policy, states_dataset_derived=True)
    router_pipe, router_sink = replay_pipeline(
        router_loaded, spec, run_id="run-shadow-router", clock=clock
    )
    rows: list[ShadowRow] = []
    for record in records:
        request = to_request(record, profile="pre_retrieval")
        rules_sink.events.clear()
        router_sink.events.clear()
        rules_pipe.handle(request)
        router_pipe.handle(request)
        rules_target = _target(rules_sink.events)
        router_target = _target(router_sink.events)
        path, status, confidence, ms = "none", "off", None, None
        strengths: tuple = ()
        gate_reported = gate_probability = None
        for e in router_sink.events:
            p = e.payload
            if p.event_type == "routing_decided" and p.decision.router_summary:
                path = p.decision.router_summary.path.value
            elif p.event_type == "decision_measured":
                status = p.outcome.status.value
                ms = e.duration_ms
                result = p.outcome.result
                if result is not None:
                    confidence = result_confidence(result, gate_ids, statistic)
                    strengths = tuple(
                        (
                            a.question_id,
                            answer_strength(a, "reported"),
                            answer_strength(a, "probability"),
                        )
                        for a in result.answers
                    )
                    gate_reported = result_confidence(result, mapping, "reported")
                    gate_probability = result_confidence(result, mapping, "probability")
        rows.append(
            ShadowRow(
                record_id=str(record["slice_record_id"]),
                split=str(record.get("split", "unknown")),
                language_group=str(record.get("language_group", "unknown")),
                weight=_float(record.get("traffic_weight")),
                rules_tier=tier.get(rules_target) if rules_target else None,
                router_tier=tier.get(router_target) if router_target else None,
                router_path=path,
                decision_status=status,
                confidence=confidence,
                below_gate=status == DecisionStatus.ANSWERED.value
                and confidence is not None
                and confidence < min_confidence,
                decide_ms=ms,
                strengths=strengths,
                gate_reported=gate_reported,
                gate_probability=gate_probability,
            )
        )
    return rows


def _target(events) -> str | None:
    for e in events:
        if e.payload.event_type == "routing_decided":
            return e.payload.decision.target_model_id
    return None


def _float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def evaluate(
    load: Loader,
    records: Sequence[dict[str, Any]],
    *,
    backend: str = "thx01",
    profile: str = "cheap",
    labels: dict[str, int] | None = None,
    offline: bool = False,
) -> dict[str, Any]:
    """The R8 summary. ``offline`` adds the per-question confidence and
    probability distributions and the provisional gate proposal (threshold
    from the tune split, effect on the check split)."""
    rows = shadow_rows(load, records, backend=backend, profile=profile, offline=offline)
    out: dict[str, Any] = {
        "backend": backend,
        "mode": "offline" if offline else "inline_settings",
        **summarise(rows),
    }
    if offline:
        answered = [r for r in rows if r.strengths]
        out["answer_strengths"] = {
            "all": answer_distributions(answered),
            "tune": answer_distributions(r for r in answered if r.split == "tune"),
        }
        out["gate_proposal"] = propose_gate(rows)
    if labels is not None:
        out["labels"] = against_labels(rows, labels)
    return out
