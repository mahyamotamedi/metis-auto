"""Sprint winners in the live demo, offline (ADR-XXXX (demo-sprint-winners)):
the rules-only decision router as a demo routing choice, within-message
dedup, and the bot-level cache, on the real configuration and pipeline with
the fake model client. No network, no key, no spend; config/local.toml and
.env are not read. All text is SYNTHETIC."""

import tomllib
from pathlib import Path

import pytest

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.settings import load_settings
from metis_auto.wiring.chat import (
    DEMO_ROUTER_MODES,
    ChatSession,
    RoutingMode,
)

CONFIG = Path(__file__).resolve().parents[2] / "config"
RETIRED = {"gpt-4.1-nano", "mimo-v2.5"}
BOT = "[SYNTHETIC] You are a demo shop assistant."


class CountingFake(FakeModelClient):
    calls = 0
    last = None

    def invoke(self, invocation):
        CountingFake.calls += 1
        CountingFake.last = invocation
        return super().invoke(invocation)


@pytest.fixture
def loader(tmp_path):
    def load(overrides):
        return load_settings(
            overrides={
                **overrides,
                "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
                "paths.recorded_dir": str(tmp_path / "recorded"),
            },
            runtime=None,
            dotenv=None,
            environ={},
        )

    return load


def session(loader, **kw) -> ChatSession:
    CountingFake.calls = 0
    return ChatSession(
        live=False,
        instructions=BOT,
        settings_loader=loader,
        client_factory=lambda _l, _r: CountingFake(),
        **kw,
    )


def test_demo_router_toggles_offer_only_the_rules_only_mode():
    assert DEMO_ROUTER_MODES == ("off",)


def test_decision_router_runs_rules_only_by_default(loader):
    chat = session(loader, routing=RoutingMode.DECISION_ROUTER)
    assert chat.router_mode == "off"
    assert chat.pipeline.decision_router is None  # no cascade, no backend
    assert chat.settings()["router"] == "off"
    _, report = chat.ask("[SYNTHETIC] Explain photosynthesis briefly please")
    assert report.status == "ok"
    assert report.routing["policy"].startswith("decision_router@")
    assert CountingFake.calls == 1  # the answer; no router model call


def test_candidates_are_the_sprint_primary_set(loader):
    sprint = tomllib.loads((CONFIG / "evaluation" / "sprint.toml").read_text("utf-8"))
    chosen = sprint["routing"]["candidates"]
    assert not RETIRED & set(chosen)
    catalogue = tomllib.loads(
        (CONFIG / "reference" / "catalogue-metis-test-2026-11-04-v41.toml").read_text(
            "utf-8"
        )
    )
    enabled = {m["model_id"] for m in catalogue["models"] if m["enabled"]}
    assert set(chosen) <= enabled
    chat = session(loader, routing=RoutingMode.DECISION_ROUTER)
    assert tuple(chat.pipeline._config.routing.candidates) == tuple(chosen)


def test_a_retired_model_is_never_chosen_on_any_demo_routing(loader):
    messages = [
        "سلام",
        "hi",
        "[SYNTHETIC] write a python function to add two numbers",
        "[SYNTHETIC] " + "a long question about shipping and returns. " * 30,
        "[SYNTHETIC] What are your opening hours?",
    ]
    for mode in (
        RoutingMode.DECISION_ROUTER,
        RoutingMode.STICKY_V1,
        RoutingMode.PER_REQUEST,
    ):
        chat = session(loader, routing=mode)
        for message in messages:
            _, report = chat.ask(message)
            assert report.model_id not in RETIRED, (mode, message)


def test_the_report_shows_tier_reason_and_the_safe_tier_note(loader):
    chat = session(loader, routing=RoutingMode.DECISION_ROUTER)
    _, greeting = chat.ask("hi")
    assert greeting.routing["tier"] == "0"
    assert greeting.routing["reason_code"] == "decision.gate.greeting"
    assert "safe_tier_note" not in greeting.routing
    _, plain = chat.ask("[SYNTHETIC] Explain photosynthesis briefly please")
    assert plain.routing["reason_code"] == "decision.fallback.safe_tier"
    assert plain.routing["tier"] == "1"
    assert plain.model_id == "gpt-4o-mini"
    note = plain.routing["safe_tier_note"]
    assert "safe tier" in note and "gpt-4o-mini" in note


def test_the_decision_router_is_labelled_provisional_cost_only(loader):
    chat = session(loader, routing=RoutingMode.DECISION_ROUTER)
    _, report = chat.ask("[SYNTHETIC] Explain photosynthesis briefly please")
    assert "provisional: cost only" in report.routing["decision"]


def test_sticky_can_use_the_decision_router_inside(loader):
    chat = session(
        loader, routing=RoutingMode.STICKY_V1, sticky_inner="decision_router"
    )
    assert chat.settings()["sticky_inner"] == "decision_router"
    _, report = chat.ask("[SYNTHETIC] Explain photosynthesis briefly please")
    assert report.routing["policy"].startswith("sticky@")
    assert report.routing["policy"].endswith("+dr-0.1.0")
    plain = session(loader, routing=RoutingMode.STICKY_V1)
    assert plain.settings()["sticky_inner"] == "rule_based"


def test_the_serving_default_is_unchanged(loader):
    fixed = session(loader, model_id="gpt-4o-mini")
    config = fixed.pipeline._config
    assert config.routing.policy == "fixed_model"
    assert config.routing.candidates == ()
    assert config.cache.scope_rule == "fixed"
    assert config.context.strategy == "pass_through"
    base = loader({})
    assert base.settings.pipeline["routing"]["policy"] == "fixed_model"
    assert "candidates" not in base.settings.pipeline["routing"]
