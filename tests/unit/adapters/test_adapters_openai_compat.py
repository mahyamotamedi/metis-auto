"""The OpenAI-compatible live adapter, over MOCKED HTTP only (no network, no key).

Every response body below is SYNTHETIC, shaped like the documented formats:
OpenAI chat completions (openai SDK 3.24.0 types), DeepSeek
(``prompt_cache_hit_tokens``, api-docs.deepseek.com), and a provider that
reports reasoning outside ``completion_tokens``.
"""

import json

import pytest

pytest.importorskip("openai")
import httpx2  # noqa: E402

from metis_auto.adapters.providers.openai_compat import (  # noqa: E402
    EndpointRoute,
    OpenAICompatibleClient,
    parse_usage,
)
from metis_auto.contracts import (  # noqa: E402
    AnswerSource,
    CatalogueEntry,
    ComponentName,
    ErrorClass,
    Fidelity,
    FinishReason,
    InputPart,
    Limit,
    ModelCatalogue,
    ModelError,
    ModelInvocation,
    ModelResponse,
    PartRole,
)
from metis_auto.ports import ModelClient  # noqa: E402

KEY = "sk-synthetic-test-key"
ROUTES = {
    "openai": EndpointRoute(
        "openai", "https://wrapper.test/openai/v1", "max_completion_tokens"
    ),
    "deepseek": EndpointRoute(
        "deepseek", "https://wrapper.test/deepseek/v1", "max_tokens"
    ),
}


def _entry(model_id: str, provider: str) -> CatalogueEntry:
    return CatalogueEntry(
        model_id=model_id,
        provider=provider,
        provider_model_name=f"{model_id}-wire",
        tier=0,
        equivalence_group="g",
        context_window=Limit(),
        max_output_tokens=Limit(),
        enabled=True,
    )


CATALOGUE = ModelCatalogue(
    version="cat-test",
    entries=(
        _entry("oa-model", "openai"),
        _entry("ds-model", "deepseek"),
        _entry("gem-model", "gemini"),
    ),
)


def _invocation(model_id="oa-model", **kw) -> ModelInvocation:
    parts = (
        InputPart(
            role=PartRole.INSTRUCTIONS,
            text="[SYNTHETIC] be brief",
            component=ComponentName.INSTRUCTIONS,
        ),
        InputPart(
            role=PartRole.RETRIEVED,
            text="[SYNTHETIC] doc",
            component=ComponentName.RETRIEVED,
            item_index=0,
        ),
        InputPart(
            role=PartRole.USER,
            text="[SYNTHETIC] earlier",
            component=ComponentName.HISTORY,
            item_index=0,
        ),
        InputPart(
            role=PartRole.ASSISTANT,
            text="[SYNTHETIC] reply",
            component=ComponentName.HISTORY,
            item_index=1,
        ),
        InputPart(
            role=PartRole.USER, text="[SYNTHETIC] hi", component=ComponentName.MESSAGE
        ),
    )
    return ModelInvocation(
        request_id="req-1",
        attempt_id="att-1",
        attempt_kind="primary",
        model_id=model_id,
        parts=parts,
        max_output_tokens=kw.pop("max_output_tokens", 64),
        **kw,
    )


def _body(
    usage=None, finish="stop", model="oa-model-wire-2026", content="[SYNTHETIC] ok"
):
    body = {
        "id": "chatcmpl-synthetic",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish,
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


class Server:
    """A mock transport that records requests and replays scripted replies."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx2.Response(status, json=body)

    def client(self) -> OpenAICompatibleClient:
        return OpenAICompatibleClient(
            api_key=KEY,
            catalogue=CATALOGUE,
            endpoints=ROUTES,
            http_client_factory=lambda: httpx2.Client(
                transport=httpx2.MockTransport(self.handler)
            ),
        )


def _usage(prompt=40, completion=12, total=None, **extra):
    usage = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total if total is not None else prompt + completion,
    }
    usage.update(extra)
    return usage


def test_conforms_to_the_port_and_is_live():
    client = Server((200, _body())).client()
    assert isinstance(client, ModelClient)
    assert client.source == AnswerSource.LIVE


def test_request_shape_route_auth_layout_and_generation_limit():
    server = Server((200, _body(_usage())))
    server.client().invoke(_invocation())
    (request,) = server.requests
    assert str(request.url) == "https://wrapper.test/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    sent = json.loads(request.content)
    assert sent["model"] == "oa-model-wire"
    # A-55: one message per part; retrieved context is its own system message.
    assert [m["role"] for m in sent["messages"]] == [
        "system",
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert sent["max_completion_tokens"] == 64 and "max_tokens" not in sent


def test_deepseek_route_uses_its_base_url_and_max_tokens():
    server = Server((200, _body(_usage())))
    server.client().invoke(_invocation("ds-model"))
    (request,) = server.requests
    assert str(request.url).startswith("https://wrapper.test/deepseek/v1/")
    sent = json.loads(request.content)
    assert sent["max_tokens"] == 64 and "max_completion_tokens" not in sent


def test_openai_usage_with_cached_and_reasoning_tokens():
    usage = _usage(
        prompt=1200,
        completion=300,
        prompt_tokens_details={"cached_tokens": 1024},
        completion_tokens_details={"reasoning_tokens": 256},
    )
    result = Server((200, _body(usage))).client().invoke(_invocation())
    assert isinstance(result, ModelResponse)
    u = result.usage
    assert (u.input.tokens, u.output.tokens, u.total.tokens) == (1200, 300, 1500)
    assert u.cached_input.tokens == 1024
    assert u.cached_input.method == "provider:prompt_tokens_details.cached_tokens"
    assert u.reasoning.tokens == 256
    assert u.output.method == "provider:completion_tokens"  # reasoning inside
    assert u.input.fidelity == Fidelity.PROVIDER_REPORTED
    assert result.provider_model_version == "oa-model-wire-2026"
    assert result.finish_reason == FinishReason.COMPLETE
    assert result.source == AnswerSource.LIVE
    assert result.provider_latency_ms is not None


def test_cached_zero_is_reported_and_missing_is_none():
    zero = parse_usage(_usage(prompt_tokens_details={"cached_tokens": 0}), "m")
    assert zero.cached_input.tokens == 0
    missing = parse_usage(_usage(), "m")
    assert missing.cached_input is None and missing.reasoning is None


def test_deepseek_cache_hit_field():
    u = parse_usage(
        _usage(prompt=100, prompt_cache_hit_tokens=64, prompt_cache_miss_tokens=36),
        "ds-model",
    )
    assert u.cached_input.tokens == 64
    assert u.cached_input.method == "provider:prompt_cache_hit_tokens"


def test_reasoning_reported_outside_completion_is_added_to_output():
    # total = prompt + completion + reasoning: reasoning is not inside
    # completion_tokens, so output (billed) = completion + reasoning.
    u = parse_usage(
        _usage(
            prompt=30,
            completion=5,
            total=30 + 5 + 120,
            completion_tokens_details={"reasoning_tokens": 120},
        ),
        "m",
    )
    assert u.output.tokens == 125
    assert u.output.method == "provider:completion_tokens+reasoning_tokens"
    assert u.reasoning.tokens == 120


def test_missing_or_malformed_usage_is_none():
    assert parse_usage(None, "m") is None
    assert parse_usage({"prompt_tokens": "x", "completion_tokens": 1}, "m") is None
    result = Server((200, _body(None))).client().invoke(_invocation())
    assert isinstance(result, ModelResponse) and result.usage is None


@pytest.mark.parametrize(
    ("finish", "expected"),
    [
        ("stop", FinishReason.COMPLETE),
        ("length", FinishReason.LENGTH),
        ("content_filter", FinishReason.CONTENT_FILTER),
        ("tool_calls", FinishReason.OTHER),
        ("insufficient_system_resource", FinishReason.OTHER),
        (None, FinishReason.OTHER),
    ],
)
def test_finish_reason_is_normalised(finish, expected):
    result = (
        Server((200, _body(_usage(), finish=finish))).client().invoke(_invocation())
    )
    assert result.finish_reason == expected


def test_null_content_becomes_empty_text():
    result = Server((200, _body(_usage(), content=None))).client().invoke(_invocation())
    assert result.text == ""


def test_no_choices_is_an_unknown_error():
    body = _body(_usage())
    body["choices"] = []
    result = Server((200, body)).client().invoke(_invocation())
    assert isinstance(result, ModelError)
    assert result.error_class == ErrorClass.UNKNOWN
    assert result.provider_error_code == "malformed_response:no_choices"


def _error(status, code=None, type_=None, message="[SYNTHETIC] secret user text"):
    return (status, {"error": {"message": message, "type": type_, "code": code}})


@pytest.mark.parametrize(
    ("reply", "expected", "retryable"),
    [
        (_error(500, type_="server_error"), ErrorClass.UNAVAILABLE, True),
        (_error(503), ErrorClass.UNAVAILABLE, True),
        (_error(429, code="rate_limit_exceeded"), ErrorClass.RATE_LIMITED, True),
        (_error(429, code="insufficient_quota"), ErrorClass.AUTH, False),
        (_error(401, code="invalid_api_key"), ErrorClass.AUTH, False),
        (_error(402), ErrorClass.AUTH, False),
        (_error(403), ErrorClass.AUTH, False),
        (_error(408), ErrorClass.TIMEOUT, True),
        (
            _error(400, code="context_length_exceeded"),
            ErrorClass.CONTEXT_OVERFLOW,
            False,
        ),
        (_error(400, code="content_filter"), ErrorClass.CONTENT_FILTERED, False),
        (_error(400, code="invalid_value"), ErrorClass.INVALID_REQUEST, False),
        (_error(404, code="model_not_found"), ErrorClass.INVALID_REQUEST, False),
        (_error(422), ErrorClass.INVALID_REQUEST, False),
    ],
)
def test_http_errors_are_normalised_with_one_request(reply, expected, retryable):
    server = Server(reply)
    result = server.client().invoke(_invocation())
    assert isinstance(result, ModelError)
    assert result.error_class == expected
    assert result.retryable is retryable
    assert result.source == AnswerSource.LIVE
    # A-33: SDK retries are off, so a retryable status is still ONE request.
    assert len(server.requests) == 1
    # The provider message can echo content: it never reaches the code.
    assert "secret" not in (result.provider_error_code or "")
    assert result.provider_error_code.startswith(f"http_{reply[0]}")


def test_timeout_and_connection_errors_make_one_request():
    for exc, expected in [
        (httpx2.ReadTimeout("synthetic"), ErrorClass.TIMEOUT),
        (httpx2.ConnectError("synthetic"), ErrorClass.CONNECTION),
    ]:
        server = Server(exc)
        result = server.client().invoke(_invocation())
        assert isinstance(result, ModelError)
        assert result.error_class == expected and result.retryable
        assert len(server.requests) == 1


def test_per_attempt_timeout_is_passed():
    server = Server((200, _body(_usage())))
    server.client().invoke(_invocation(timeout_ms=2500))
    timeout = server.requests[0].extensions["timeout"]
    assert timeout["read"] == pytest.approx(2.5)


def test_configuration_errors_raise():
    client = Server((200, _body())).client()
    with pytest.raises(ValueError, match="no enabled OpenAI-compatible endpoint"):
        client.invoke(_invocation("gem-model"))
    with pytest.raises(ValueError, match="no enabled"):
        client.invoke(_invocation("not-in-catalogue"))


def test_request_options_are_sent_only_for_their_model():
    server = Server((200, _body(_usage())))
    client = OpenAICompatibleClient(
        api_key=KEY,
        catalogue=CATALOGUE,
        endpoints=ROUTES,
        http_client_factory=lambda: httpx2.Client(
            transport=httpx2.MockTransport(server.handler)
        ),
        request_options={"ds-model": {"thinking": {"type": "disabled"}}},
    )
    client.invoke(_invocation("ds-model"))
    client.invoke(_invocation("oa-model"))
    first, second = (json.loads(r.content) for r in server.requests)
    assert first["thinking"] == {"type": "disabled"}
    assert "thinking" not in second
