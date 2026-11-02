"""The golden-answer request over MOCKED HTTP: the body carries the effort and the
output limit, the messages follow the parts, nothing else is added. SYNTHETIC text,
a SYNTHETIC key, a mock transport: no network, no real key, no spend."""

import json

import pytest

pytest.importorskip("openai")
import httpx2  # noqa: E402

from metis_auto.contracts import (  # noqa: E402
    AttemptKind,
    ComponentName,
    InputPart,
    ModelInvocation,
    ModelResponse,
    PartRole,
)
from metis_auto.settings import SettingsError, load_settings  # noqa: E402
from metis_auto.wiring.golden_answers import GoldenAnswers  # noqa: E402
from metis_auto.wiring.live import (  # noqa: E402
    build_live_client,
    live_overrides,
    request_options,
)

KEY = "sk-SYNTHETIC-not-a-key"


def _loaded(tmp_path, **extra):
    return load_settings(
        overrides={
            **live_overrides(),
            "paths.spend_ledger": str(tmp_path / "ledger.jsonl"),
            "paths.recorded_dir": str(tmp_path / "recorded"),
            "live.enabled": True,
            **extra,
        },
        environ={"METIS_API_KEY": KEY},
        dotenv=None,
        runtime=None,
    )


def _completion(sent):
    return httpx2.Response(
        200,
        json={
            "id": "synthetic",
            "object": "chat.completion",
            "created": 0,
            "model": sent["model"] + "-snapshot",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "[SYNTHETIC] OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 40,
                "total_tokens": 70,
                "prompt_tokens_details": {"cached_tokens": 0},
                "completion_tokens_details": {"reasoning_tokens": 25},
            },
        },
    )


def test_the_request_carries_effort_limit_and_only_the_records_parts(tmp_path):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return _completion(bodies[-1])

    loaded = _loaded(tmp_path)
    answers = GoldenAnswers(engine=object(), loaded=loaded, log=lambda _m: None)
    entry = answers._entry(loaded)
    client = build_live_client(
        loaded,
        "run-mock",
        http_client_factory=lambda: httpx2.Client(
            transport=httpx2.MockTransport(handler)
        ),
        model_options=answers._model_options(loaded, entry),
    )
    parts = (
        InputPart(
            role=PartRole.INSTRUCTIONS,
            text="[SYNTHETIC] rules",
            component=ComponentName.INSTRUCTIONS,
        ),
        InputPart(
            role=PartRole.USER, text="[SYNTHETIC] hi", component=ComponentName.MESSAGE
        ),
    )
    result = client.invoke(
        ModelInvocation(
            request_id="req-1",
            attempt_id="att-1",
            attempt_kind=AttemptKind.PRIMARY,
            model_id="gpt-5.5",
            parts=parts,
            max_output_tokens=8192,
            effort="medium",
        )
    )
    assert isinstance(result, ModelResponse)
    body = bodies[0]
    assert body["model"] == "gpt-5.5"
    assert body["reasoning_effort"] == "medium"
    assert body["max_completion_tokens"] == 8192
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert set(body) == {
        "model",
        "messages",
        "max_completion_tokens",
        "reasoning_effort",
    }
    assert result.usage.reasoning.tokens == 25
    assert result.provider_model_version == "gpt-5.5-snapshot"


def test_effort_is_refused_for_a_family_that_does_not_document_it(tmp_path):
    loaded = _loaded(
        tmp_path, **{"model_options.deepseek-v4-flash.reasoning_effort": "low"}
    )
    with pytest.raises(SettingsError, match="not supported"):
        request_options(loaded)


def test_the_general_settings_send_no_effort_by_default(tmp_path):
    assert request_options(_loaded(tmp_path)) == {}
