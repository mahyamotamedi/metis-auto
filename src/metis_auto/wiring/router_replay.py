"""Replay the frozen routing dev slice through the pipeline
(ADR-XXXX (system-one-decision-router), R4).

Each of the 150 records becomes a ``Request`` (``pre_retrieval`` profile:
routing happens before retrieval) and goes through the real pipeline with the
**fake** answering client and **fake** decision backends: no network, no
weights, no keys, no spend. What this shows on real Persian text: the gate,
the state builder, the router cache and the policy's paths, the overhead of
the decision step, and the approval check (a dataset-derived state never
reaches a hosted backend). It says nothing about answer quality or about a
real router's accuracy or latency (R5).

Scenarios:
- ``off``: ``router.mode = "off"``; the decision_router policy falls back to
  the rules, then the safe tier. No decision event.
- ``local``: a fake local backend (``profile``), two passes: the second shows
  the router cache.
- ``thx01`` (R5): the **real** THX-01 local backend from settings (pinned,
  sha256-checked files under ``paths.router_assets``; extra ``router-local``),
  still with the fake answering client; two passes. It shows THX-01's own
  answers, tiers and latency on the slice, never answer quality. Without the
  extra or the files the backend reports itself unavailable and every
  decision fails over to the rules (counted, not hidden).
- ``hosted_refused``: ``hybrid_hosted_first`` with a fake hosted backend
  first (over an in-memory ledger; the real ledger is never touched) and the
  fake local backend second. ``real_data_approved`` stays false, so every
  state goes to the local fake and the hosted fake is never called.

Returns counts, timings and peak memory only: never text (QA-PRIV). Called by:
scripts/replay_router_slice.py, tests.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.routers import FakeDecisionBackend
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.adapters.system import (
    InMemorySpendLedger,
    SequentialIdSource,
    SystemClock,
)
from metis_auto.adapters.system.resources import peak_rss_mb
from metis_auto.contracts import (
    DecisionFailureReason,
    Money,
    RunMode,
    SpanName,
)
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.evaluation.router_slice.records import to_request
from metis_auto.ports import Clock
from metis_auto.settings import LoadedSettings

from .from_settings import model_templates, pipeline_config
from .pipeline import build_pipeline
from .routers import fake_profiles, router_spec
from .tokenizers import build_tokenizers

SCENARIOS = ("off", "local", "hosted_refused", "thx01")
OFFLINE_SCENARIOS = ("off", "local", "hosted_refused")
"""The scenarios ``all`` runs: fakes only, no weights needed."""
FAKE = "fake_local"
HOSTED_FAKE = "fake_hosted"


def _percentiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, max(0, round(0.95 * len(ordered)) - 1))]
    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 3),
        "p95": round(p95, 3),
        "max": round(ordered[-1], 3),
    }


Loader = Callable[[dict[str, Any]], LoadedSettings]
"""``overrides → LoadedSettings``: the script loads the owner's layers
(``config/local.toml`` and the environment) plus the scenario's overrides."""


def _settings(load: Loader, scenario: str, profile: str) -> LoadedSettings:
    """The settings with this scenario's router overrides; runtime approvals
    stay as configured (``real_data_approved`` false, owner decision)."""
    overrides: dict[str, Any] = {"pipeline.routing.policy": "decision_router"}
    if scenario == "thx01":
        overrides.update(
            {
                "router.mode": "local",
                "router.backends.thx01.enabled": True,
                "router.chains.local": ["thx01"],
            }
        )
    elif scenario != "off":
        overrides.update(
            {
                "router.mode": "local" if scenario == "local" else "hybrid_local_first",
                f"router.backends.{FAKE}": {
                    "type": "fake",
                    "enabled": True,
                    "profile": profile,
                },
                "router.chains.local": [FAKE],
                "router.chains.hybrid_local_first": [FAKE],
            }
        )
    return load(overrides)


def run_scenario(
    load: Loader,
    records: Sequence[dict[str, Any]],
    scenario: str,
    *,
    profile: str = "cheap",
    passes: int = 2,
    clock: Clock | None = None,
) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    loaded = _settings(load, scenario, profile)
    clock = clock or SystemClock()
    config = pipeline_config(loaded)
    policy = config.routing.decision_router or DecisionRouterConfig()
    built: list[FakeDecisionBackend] = []
    spec = router_spec(loaded, policy)
    if spec is not None and scenario == "hosted_refused":
        script = fake_profiles(policy.questions)[profile]

        def backends(c: Clock):
            hosted = FakeDecisionBackend(
                c, name=HOSTED_FAKE, kind="hosted", script=script
            )
            built.append(hosted)
            return {
                HOSTED_FAKE: hosted,
                FAKE: FakeDecisionBackend(c, name=FAKE, script=script),
            }

        chain = (HOSTED_FAKE, FAKE)
        spec = type(spec)(
            config=spec.config.model_copy(
                update={
                    "mode": "hybrid_hosted_first",
                    "chain": chain,
                    "timeouts_ms": {n: spec.config.timeouts_ms[FAKE] for n in chain},
                }
            ),
            backends=backends,
            questions=spec.questions,
            spend_ledger=InMemorySpendLedger(
                Money(amount=Decimal("0.01"), currency="USD")
            ),
        )
    run_id = f"run-slice-replay-{scenario}"
    pipeline, sink = replay_pipeline(loaded, spec, run_id=run_id, clock=clock)
    requests = [to_request(r, profile="pre_retrieval") for r in records]
    out: dict[str, Any] = {"scenario": scenario, "records": len(records), "passes": []}
    started = time.perf_counter()
    for number in range(1, (passes if spec is not None else 1) + 1):
        sink.events.clear()
        pass_started = time.perf_counter()
        statuses: Counter[str] = Counter()
        for request in requests:
            statuses[pipeline.handle(request).status.value] += 1
        out["passes"].append(
            _summary(sink.events, statuses, number, time.perf_counter() - pass_started)
        )
    cascade = pipeline.decision_router
    out["router"] = {
        "built": cascade is not None,
        "mode": cascade.mode if cascade else "off",
        "cache_entries": len(cascade.cache) if cascade else 0,
        "revision_changes": len(cascade.cache.revision_changes) if cascade else 0,
        "hosted_calls": sum(b.calls for b in built),
        "spend_guard_stopped": bool(cascade and cascade.guard_stopped),
    }
    out["duration_s"] = round(time.perf_counter() - started, 3)
    out["peak_rss_mb"] = peak_rss_mb()
    return out


def replay_pipeline(loaded: LoadedSettings, spec, *, run_id: str, clock: Clock):
    """The replay's pipeline: the fake answering client, an in-memory cache and
    event sink, an ephemeral fingerprint key, and the given router spec (None:
    no decision router). Also used by the R8 shadow evaluation."""
    tokens = build_tokenizers(loaded)
    sink = InMemoryEventSink()
    pipeline = build_pipeline(
        pipeline_config(loaded),
        model_client=FakeModelClient(),
        cache_store=InMemoryCacheStore(),
        sink=sink,
        fingerprint_key=b"slice-replay-ephemeral-key-not-a-secret-0001",
        run_id=run_id,
        run_mode=RunMode.REPLAYED,
        clock=clock,
        ids=SequentialIdSource(run_id),
        tokenizers=tokens.tokenizers,
        templates=model_templates(loaded, tokens),
        router=spec,
    )
    return pipeline, sink


def _summary(events, statuses: Counter[str], number: int, seconds: float) -> dict:
    status: Counter[str] = Counter()
    skip: Counter[str] = Counter()
    failure: Counter[str] = Counter()
    refused: Counter[str] = Counter()
    paths: Counter[str] = Counter()
    tiers: Counter[str] = Counter()
    models: Counter[str] = Counter()
    decide_ms: list[float] = []
    request_ms: list[float] = []
    cache_hits = 0
    overhead = Decimal(0)
    no_target: Counter[str] = Counter()
    modalities = {
        e.request_id: ",".join(
            sorted(m.value for m in e.payload.features.attachment_modalities)
        )
        or "none"
        for e in events
        if e.payload.event_type == "features_extracted"
    }
    for e in events:
        p = e.payload
        if p.event_type == "decision_measured":
            o = p.outcome
            status[o.status.value] += 1
            if o.skip_reason is not None:
                skip[o.rule_id or o.skip_reason.value] += 1
            if o.failure_reason is not None:
                failure[o.failure_reason.value] += 1
            if o.result is not None and o.result.cache_hit:
                cache_hits += 1
            for a in o.attempts:
                if a.failure_reason == DecisionFailureReason.REAL_DATA_NOT_APPROVED:
                    refused[a.backend.name] += 1
            if e.duration_ms is not None:
                decide_ms.append(e.duration_ms)
        elif p.event_type == "routing_decided":
            s = p.decision.router_summary
            paths[s.path.value if s else "none"] += 1
            if s is not None and s.mapped_tier is not None:
                tiers[str(s.mapped_tier)] += 1
            models[p.decision.target_model_id or "none"] += 1
            if p.decision.target_model_id is None:
                no_target[_no_target_key(p.decision, modalities.get(e.request_id))] += 1
        elif p.event_type == "response_returned":
            cost = p.metadata.overhead_cost
            if cost.amount is not None:
                overhead += cost.amount.amount
            if e.span == SpanName.REQUEST and e.duration_ms is not None:
                request_ms.append(e.duration_ms)
    return {
        "pass": number,
        "responses": dict(sorted(statuses.items())),
        "decision_status": dict(sorted(status.items())),
        "decision_skipped_by": dict(sorted(skip.items())),
        "decision_failed_by": dict(sorted(failure.items())),
        "router_cache_hits": cache_hits,
        "hosted_refused_not_approved": dict(sorted(refused.items())),
        "router_paths": dict(sorted(paths.items())),
        "mapped_tiers": dict(sorted(tiers.items())),
        "target_models": dict(sorted(models.items())),
        "no_target_by_reason": dict(sorted(no_target.items())),
        "decision_step_ms": _percentiles(decide_ms),
        "request_ms": _percentiles(request_ms),
        "overhead_cost_usd": str(overhead),
        "seconds": round(seconds, 3),
    }


def _no_target_key(decision, modalities: str | None) -> str:
    """Content-free: the reason code, how many models stayed eligible, the
    exclusion reasons with their model counts, and the attachment modalities.
    e.g. ``no_eligible_model|eligible=0|modality_unsupported:5|attachments=image``."""
    reasons = Counter(x.reason.value for x in decision.exclusions)
    excluded = ",".join(f"{r}:{n}" for r, n in sorted(reasons.items())) or "none"
    return (
        f"{decision.reason_code}|eligible={len(decision.eligible)}|{excluded}"
        f"|attachments={modalities or 'unknown'}"
    )
