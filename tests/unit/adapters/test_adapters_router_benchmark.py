"""The router latency benchmark (ADR-XXXX (system-one-decision-router) point 4; R5) on
the fake backend: synthetic states cover languages, lengths and history; slice states
skip what the gate decides; the report holds counts and timings only. SYNTHETIC text."""

from __future__ import annotations

import json

from fixtures.synthetic.router_off_cases import requests as synthetic_requests

from metis_auto.adapters.routers import FakeDecisionBackend
from metis_auto.adapters.system import SystemClock
from metis_auto.contracts import Language, QuestionLanguage
from metis_auto.domain.features import FeatureConfig
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.settings import load_settings
from metis_auto.wiring import router_benchmark as rb

QUESTIONS = load_settings(
    environ={}, dotenv=None, runtime=None
).reference.router_questions.get("routing_qs_v1", QuestionLanguage.ENGLISH)


def test_synthetic_states_vary_and_respect_the_length_limit():
    states = rb.synthetic_states(48, max_message_chars=300)
    assert {s.language for s in states} == {Language.PERSIAN, Language.ENGLISH}
    assert {s.turn_depth for s in states} == {0, 1}
    assert max(len(s.message) for s in states) <= 300
    assert any(s.message_truncated for s in states)
    assert not any(s.dataset_derived for s in states)


def test_slice_states_skip_what_the_gate_decides():
    config = DecisionRouterConfig()
    states, skipped = rb.slice_states(
        synthetic_requests(),
        features=FeatureConfig(),
        gate=config.gate,
        state=config.state,
    )
    assert skipped["gate.code"] == 1 and skipped["gate.attachment"] == 1
    assert len(states) + sum(skipped.values()) == len(synthetic_requests())
    assert all(s.dataset_derived for s in states)


def test_the_report_has_counts_and_timings_only():
    backend = FakeDecisionBackend(SystemClock(), script={"intent": "chitchat"})
    states = rb.synthetic_states(20)
    out = rb.run(backend, states, QUESTIONS, warmup=2, min_confidence=0.6)
    assert out["answered"] == 20 and out["errors"] == {}
    assert out["latency_ms"]["n"] == 20 and out["meets_budget_p95"] is True
    assert set(out["latency_ms"]) >= {"p50", "p90", "p95", "p99", "max"}
    assert out["below_confidence_gate_share"] == 0.0
    text = json.dumps(out, ensure_ascii=False)
    assert "[SYNTHETIC]" not in text and "سلام" not in text
    assert set(rb.machine()) == {"platform", "python", "cpu_count", "peak_rss_mb"}
