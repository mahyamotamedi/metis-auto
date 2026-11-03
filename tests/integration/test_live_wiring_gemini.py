"""Gemini wiring over a FAKE transport (ADR-0043).

The real configuration keeps the Gemini endpoint deferred and has no Gemini
model; these tests enable both in SYNTHETIC copies under ``tmp_path`` to check
the route. No network, no real key, no spend.
"""

import json

import pytest

pytest.importorskip("openai")

from metis_auto.adapters.providers import gemini_native  # noqa: E402
from metis_auto.adapters.providers.gemini_native import HttpResponse  # noqa: E402
from metis_auto.adapters.providers.openai_compat import (  # noqa: E402
    OpenAICompatibleClient,
)
from metis_auto.contracts import (  # noqa: E402
    ComponentName,
    InputPart,
    ModelInvocation,
    ModelResponse,
    PartRole,
)
from metis_auto.settings import SettingsError, load_settings, repo_root  # noqa: E402
from metis_auto.wiring.live import (  # noqa: E402
    build_live_client,
    live_overrides,
    request_options,
    thinking_budgets,
)

SYNTHETIC_KEY = "sk-SYNTHETIC-not-a-key"
REFERENCE = repo_root() / "config" / "reference"
GEMINI_ROW = """
[[models]]
# SYNTHETIC test row: not a real catalogue entry.
model_id = "gem-synth"
provider = "gemini"
provider_model_name = "gem-synth-wire"
tier = 0
equivalence_group = "synthetic"
context_window = {}
max_output_tokens = {}
enabled = false
"""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the default urllib transport was reached")

    monkeypatch.setattr(gemini_native.urllib.request, "urlopen", refuse)


@pytest.fixture
def reference(tmp_path):
    """SYNTHETIC copies: Gemini endpoint enabled, one disabled Gemini model."""
    endpoints = (REFERENCE / "endpoints-metis.toml").read_text(encoding="utf-8")
    assert endpoints.count('status = "deferred"') == 1
    (tmp_path / "endpoints.toml").write_text(
        endpoints.replace('status = "deferred"', 'status = "enabled"'),
        encoding="utf-8",
    )
    catalogue = (REFERENCE / "catalogue-metis-test.toml").read_text(encoding="utf-8")
    (tmp_path / "catalogue.toml").write_text(catalogue + GEMINI_ROW, encoding="utf-8")
    return {
        "reference.endpoints": str(tmp_path / "endpoints.toml"),
        "reference.catalogue": str(tmp_path / "catalogue.toml"),
        "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
        "paths.recorded_dir": str(tmp_path / "recorded"),
    }


def _load(extra, **overrides):
    return load_settings(
        overrides={**live_overrides(), **extra, "live.enabled": True, **overrides},
        environ={"METIS_API_KEY": SYNTHETIC_KEY},
        dotenv=None,
        runtime=None,
    )


class FakeTransport:
    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        body = {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "[SYNTHETIC]"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 9,
                "candidatesTokenCount": 2,
                "totalTokenCount": 11,
            },
        }
        return HttpResponse(200, {}, json.dumps(body).encode())


def _invocation(model_id):
    return ModelInvocation(
        request_id="req-1",
        attempt_id="att-1",
        attempt_kind="primary",
        model_id=model_id,
        parts=(
            InputPart(
                role=PartRole.USER,
                text="[SYNTHETIC] hi",
                component=ComponentName.MESSAGE,
            ),
        ),
        max_output_tokens=16,
    )


def test_thinking_budgets_come_from_model_options(reference):
    loaded = _load(reference, **{"model_options.gem-synth.thinking_budget": 256})
    assert thinking_budgets(loaded) == {"gem-synth": 256}
    assert request_options(loaded) == {}  # not an OpenAI-style body field


def test_a_thinking_budget_for_another_family_is_refused(reference):
    loaded = _load(
        reference, **{"model_options.deepseek-v4-flash.thinking_budget": 256}
    )
    with pytest.raises(SettingsError, match="not supported"):
        request_options(loaded)


def test_the_real_configuration_builds_no_gemini_route(tmp_path):
    loaded = _load(
        {
            "paths.spend_ledger": str(tmp_path / "ledger.jsonl"),
            "paths.recorded_dir": str(tmp_path / "recorded"),
        }
    )
    transport = FakeTransport()
    client = build_live_client(loaded, "run-g0", gemini_transport=transport)
    assert isinstance(client._inner, OpenAICompatibleClient)  # unchanged stack
    assert thinking_budgets(loaded) == {}


def test_an_enabled_gemini_endpoint_routes_its_models_to_the_native_adapter(
    reference,
):
    loaded = _load(reference, **{"model_options.gem-synth.thinking_budget": 0})
    transport = FakeTransport()
    client = build_live_client(loaded, "run-g1", gemini_transport=transport)

    result = client.invoke(_invocation("gem-synth"))

    assert isinstance(result, ModelResponse)
    assert result.usage.input.tokens == 9
    (sent,) = transport.requests
    assert sent.url == (
        "https://api.metisai.ir/v1beta/models/gem-synth-wire:generateContent"
    )
    assert sent.headers["x-goog-api-key"] == SYNTHETIC_KEY
    body = json.loads(sent.body)
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    recorded = list((tmp := loaded.path(loaded.settings.paths.recorded_dir)).iterdir())
    assert [p.name for p in recorded] == ["live-run-g1.jsonl"], tmp


def test_an_enabled_gemini_model_without_a_budget_is_refused(reference):
    transport = FakeTransport()
    client = build_live_client(_load(reference), "run-g2", gemini_transport=transport)
    with pytest.raises(ValueError, match="thinking budget"):
        client.invoke(_invocation("gem-synth"))
    assert transport.requests == []
