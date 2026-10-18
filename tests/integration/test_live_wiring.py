"""Live wiring end to end over MOCKED HTTP: real configuration, the real
pipeline, spend guard, persistent ledger, and recording decorator, with a
SYNTHETIC key and a mock transport. No network, no real key, no spend."""

import json
from decimal import Decimal

import pytest

pytest.importorskip("openai")
import httpx2  # noqa: E402

from metis_auto.adapters.providers.recording import read_records  # noqa: E402
from metis_auto.settings import SettingsError, load_settings  # noqa: E402
from metis_auto.wiring import wrapper_check  # noqa: E402
from metis_auto.wiring.chat import ChatSession  # noqa: E402
from metis_auto.wiring.live import build_live_client, live_overrides  # noqa: E402

SYNTHETIC_KEY = "sk-SYNTHETIC-not-a-key"


class Wrapper:
    """Mock Metis wrapper: scripted status, synthetic bodies, request log."""

    def __init__(self, status=200):
        self.status = status
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx2.Response(
                self.status, json={"error": {"message": "[SYNTHETIC]", "code": None}}
            )
        sent = json.loads(request.content)
        prompt = 20 * len(sent["messages"])
        usage = {
            "prompt_tokens": prompt,
            "completion_tokens": 7,
            "total_tokens": prompt + 7,
            "prompt_tokens_details": {"cached_tokens": 0},
        }
        return httpx2.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": sent["model"] + "-reported",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "[SYNTHETIC] OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            },
        )

    def factory(self):
        return lambda: httpx2.Client(transport=httpx2.MockTransport(self.handler))


@pytest.fixture
def paths(tmp_path):
    return {
        "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
        "paths.recorded_dir": str(tmp_path / "recorded"),
    }


def _loader(paths, enabled=True, key=SYNTHETIC_KEY):
    def load(overrides):
        return load_settings(
            overrides={**overrides, **paths, "live.enabled": enabled},
            environ={"METIS_API_KEY": key} if key else {},
            dotenv=None,
            runtime=None,
        )

    return load


def _factory(wrapper):
    return lambda loaded, run_id: build_live_client(
        loaded, run_id, http_client_factory=wrapper.factory()
    )


def _ledger_lines(paths):
    with open(paths["paths.spend_ledger"]) as handle:
        return [json.loads(line) for line in handle]


def test_live_client_is_refused_with_every_reason(paths):
    loaded = _loader(paths, enabled=False, key=None)(live_overrides())
    with pytest.raises(SettingsError) as info:
        build_live_client(loaded, "run-x")
    assert "live.enabled is false" in str(info.value)
    assert "METIS_API_KEY is not set" in str(info.value)


def test_live_chat_charges_the_ledger_records_and_sends_history(paths):
    wrapper = Wrapper()
    session = ChatSession(
        "gpt-4o-mini",
        live=True,
        instructions="[SYNTHETIC] be brief",
        settings_loader=_loader(paths),
        client_factory=_factory(wrapper),
        run_id="run-chat-test",
    )
    _, first = session.ask("[SYNTHETIC] hello")
    _, second = session.ask("[SYNTHETIC] again")

    roles = [m["role"] for m in json.loads(wrapper.requests[1].content)["messages"]]
    assert roles == ["system", "user", "assistant", "user"]  # history resent
    assert str(wrapper.requests[0].url) == (
        "https://api.metisai.ir/openai/v1/chat/completions"
    )
    assert json.loads(wrapper.requests[0].content)["max_completion_tokens"] == 4096

    assert first.provider_model == "gpt-4o-mini-reported"
    assert "provider_reported" in first.tokens["input"]
    assert first.tokens["cached_input"] == "0 (provider_reported)"
    assert first.cost.endswith("USD")
    assert dict(first.decomposition)["actually_paid"] == first.cost
    assert len(second.session_decomposition) == 7

    charges = _ledger_lines(paths)
    assert len(charges) == 2 and {c["run_id"] for c in charges} == {"run-chat-test"}
    # gpt-4o-mini: 40 input × 0.165 + 7 output × 0.66 per 1M tokens.
    assert Decimal(charges[0]["amount"]) == Decimal("0.00001122")
    records = read_records(
        session.loaded.path(session.loaded.settings.paths.recorded_dir)
        / "live-run-chat-test.jsonl"
    )
    assert len(records) == 2
    assert session.budget()["run_spent"] == str(
        sum(Decimal(c["amount"]) for c in charges)
    )


def test_an_uncomputable_cost_charges_the_estimate_and_stops(paths):
    wrapper = Wrapper(status=500)
    session = ChatSession(
        "gpt-4o-mini",
        live=True,
        settings_loader=_loader(paths),
        client_factory=_factory(wrapper),
        run_id="run-error-test",
    )
    response, report = session.ask("[SYNTHETIC] hello")
    assert response.answer is None
    assert len(wrapper.requests) == 1  # the retry was blocked by the guard
    assert report.live_stopped and "estimate" in report.live_stopped
    (charge,) = _ledger_lines(paths)
    assert Decimal(charge["amount"]) > 0  # the pre-call estimate, never zero


def test_wrapper_check_plan_and_mocked_run(paths):
    rows, total = wrapper_check.plan(_loader(paths)(live_overrides()))
    assert [r.model_id for r in rows] == list(wrapper_check.CHECK_MODELS)
    assert total is not None and total < wrapper_check.MAX_TOTAL_ESTIMATE

    wrapper = Wrapper()
    results = wrapper_check.run(
        _loader(paths), client_factory=_factory(wrapper), run_id="run-check-test"
    )
    assert len(wrapper.requests) == 5  # one call per model, grok included
    by_model = {r["model_id"]: r for r in results["results"]}
    assert set(by_model) == set(wrapper_check.CHECK_MODELS)
    row = by_model["deepseek-v4-flash"]
    assert row["provider_model"] == "deepseek-v4-flash-reported"
    assert row["reported"]["cached_input"]["tokens"] == 0
    assert "comparison" in row
    assert "[SYNTHETIC] OK" not in json.dumps(results)  # no answer text kept
    assert len(_ledger_lines(paths)) == 5
