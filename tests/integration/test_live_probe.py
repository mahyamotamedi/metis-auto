"""The Stage 7.5 follow-up probe and model request options, over MOCKED HTTP:
real configuration and pipeline, SYNTHETIC key, a mock wrapper that simulates
a provider prefix cache. No network, no real key, no spend."""

import json
from decimal import Decimal

import pytest

pytest.importorskip("openai")
import httpx2  # noqa: E402

from metis_auto.settings import SettingsError, load_settings  # noqa: E402
from metis_auto.wiring import wrapper_check  # noqa: E402
from metis_auto.wiring.live import (  # noqa: E402
    build_live_client,
    live_overrides,
    request_options,
)

KEY = "sk-SYNTHETIC-not-a-key"


class CachingWrapper:
    """Reports 1,024 cached tokens when a long system prompt is seen again."""

    def __init__(self):
        self.requests: list[dict] = []
        self.seen: set[str] = set()

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        sent = json.loads(request.content)
        self.requests.append(sent)
        system = sent["messages"][0]["content"]
        prompt = 4 * sum(len(m["content"]) for m in sent["messages"]) // 3
        cached = 1024 if (system in self.seen and prompt > 1024) else 0
        self.seen.add(system)
        usage = {
            "prompt_tokens": prompt,
            "completion_tokens": 3,
            "total_tokens": prompt + 3,
            "prompt_tokens_details": {"cached_tokens": cached},
        }
        body = {
            "id": "synthetic",
            "object": "chat.completion",
            "created": 0,
            "model": sent["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "[SYNTHETIC] OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        }
        return httpx2.Response(200, json=body)

    def factory(self):
        return lambda loaded, run_id: build_live_client(
            loaded,
            run_id,
            http_client_factory=lambda: httpx2.Client(
                transport=httpx2.MockTransport(self.handler)
            ),
        )


@pytest.fixture
def loader(tmp_path):
    def load(overrides):
        return load_settings(
            overrides={
                **overrides,
                "live.enabled": True,
                "paths.spend_ledger": str(tmp_path / "ledger.jsonl"),
                "paths.recorded_dir": str(tmp_path / "recorded"),
            },
            environ={"METIS_API_KEY": KEY},
            dotenv=None,
            runtime=None,
        )

    return load


def test_probe_plan_is_under_the_owners_limit(loader):
    steps, total = wrapper_check.probe_plan(loader)
    assert [s.calls_per_model for s in steps] == [2, 1, 1]
    assert total is not None and total < wrapper_check.PROBE_MAX_TOTAL
    # The cache prompt exceeds 1,024 tokens for every test model.
    assert all(r.input_tokens > 1024 for r in steps[0].rows)


def test_mocked_probe_run(loader, tmp_path):
    wrapper = CachingWrapper()
    results = wrapper_check.probe_run(
        loader, client_factory=wrapper.factory(), run_id="run-probe-test"
    )
    assert len(wrapper.requests) == 12
    cache = results["provider_cache"]
    assert [r["call"] for r in cache] == [1, 2] * 5
    second = [r for r in cache if r["call"] == 2]
    assert all(r["reported"]["cached_input"]["tokens"] == 1024 for r in second)
    assert all(r["provider_cache_saving"].endswith("USD") for r in second)
    assert any(Decimal(r["provider_cache_saving"].split()[0]) > 0 for r in second)
    assert results["mimo_tiny_check"][0]["model_id"] == "mimo-v2.5"
    # Q-34: only the last request carries the thinking switch.
    assert wrapper.requests[-1]["thinking"] == {"type": "disabled"}
    assert all("thinking" not in r for r in wrapper.requests[:-1])
    assert "[SYNTHETIC] OK" not in json.dumps(results)  # no answer text kept
    lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 12


def test_thinking_option_is_refused_for_an_undocumented_family(loader):
    loaded = loader(
        {**live_overrides(), "model_options.gpt-4o-mini.thinking": "disabled"}
    )
    with pytest.raises(SettingsError, match="not supported"):
        request_options(loaded)
    loaded = loader({"model_options.no-such-model.thinking": "enabled"})
    with pytest.raises(SettingsError, match="unknown model"):
        request_options(loaded)
