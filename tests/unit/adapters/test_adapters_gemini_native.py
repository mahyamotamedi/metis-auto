"""The Gemini native adapter, over a FAKE transport only (no network, no key).

Every request and response body below is SYNTHETIC, shaped like the Gemini
REST ``generateContent`` format the adapter expects. Those field names are
expectations, not verified through the Metis wrapper (see the adapter's
module docstring); a live check re-verifies them. The default urllib
transport is monkeypatched to raise in every test, so a test that reached the
network would fail.
"""

import json
import urllib.error

import pytest

from metis_auto.adapters.providers import gemini_native
from metis_auto.adapters.providers.gemini_native import (
    GeminiNativeClient,
    HttpRequest,
    HttpResponse,
    TransportError,
    parse_usage,
)
from metis_auto.contracts import (
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
from metis_auto.ports import ModelClient

KEY = "synthetic-gemini-test-key"
BASE = "https://wrapper.test"


class NetworkReached(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The default transport's urlopen raises: no test may reach it."""

    def refuse(*args, **kwargs):
        raise NetworkReached("the default urllib transport was reached")

    monkeypatch.setattr(gemini_native.urllib.request, "urlopen", refuse)


def _entry(model_id: str, provider: str) -> CatalogueEntry:
    return CatalogueEntry(
        model_id=model_id,
        provider=provider,
        provider_model_name=f"{model_id}-wire",
        tier=0,
        equivalence_group="g",
        context_window=Limit(),
        max_output_tokens=Limit(),
        enabled=False,
    )


CATALOGUE = ModelCatalogue(
    version="cat-test",
    entries=(_entry("gem-model", "gemini"), _entry("oa-model", "openai")),
)


def _parts():
    return (
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


def _invocation(model_id="gem-model", **kw) -> ModelInvocation:
    return ModelInvocation(
        request_id="req-1",
        attempt_id="att-1",
        attempt_kind="primary",
        model_id=model_id,
        parts=_parts(),
        max_output_tokens=kw.pop("max_output_tokens", 64),
        **kw,
    )


def _body(usage=None, finish="STOP", text="[SYNTHETIC] ok", version="gem-wire-001"):
    body = {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": finish,
                "index": 0,
            }
        ],
        "modelVersion": version,
    }
    if usage is not None:
        body["usageMetadata"] = usage
    return body


class FakeTransport:
    """Records requests; replays scripted responses or raises scripted errors."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        return HttpResponse(
            status=status, headers={"content-type": "application/json"}, body=raw
        )


def _client(transport, budgets=None, **kw) -> GeminiNativeClient:
    return GeminiNativeClient(
        api_key=KEY,
        catalogue=CATALOGUE,
        routes={"gemini": BASE},
        thinking_budgets={"gem-model": 0} if budgets is None else budgets,
        transport=transport,
        **kw,
    )


# --- protocol and request building ----------------------------------------


def test_is_a_live_model_client():
    client = _client(FakeTransport())
    assert isinstance(client, ModelClient)
    assert client.source == AnswerSource.LIVE


def test_request_path_header_and_body():
    transport = FakeTransport((200, _body()))
    _client(transport, budgets={"gem-model": 512}).invoke(_invocation())

    (sent,) = transport.requests
    assert sent.method == "POST"
    assert sent.url == f"{BASE}/v1beta/models/gem-model-wire:generateContent"
    assert sent.headers["x-goog-api-key"] == KEY
    assert sent.headers["Content-Type"] == "application/json"
    assert "Authorization" not in sent.headers
    body = json.loads(sent.body)
    assert body["systemInstruction"] == {
        "parts": [{"text": "[SYNTHETIC] be brief"}, {"text": "[SYNTHETIC] doc"}]
    }
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "[SYNTHETIC] earlier"}]},
        {"role": "model", "parts": [{"text": "[SYNTHETIC] reply"}]},
        {"role": "user", "parts": [{"text": "[SYNTHETIC] hi"}]},
    ]
    assert body["generationConfig"] == {
        "maxOutputTokens": 64,
        "thinkingConfig": {"thinkingBudget": 512},
    }


def test_without_instructions_no_system_instruction_is_sent():
    transport = FakeTransport((200, _body()))
    parts = tuple(p for p in _parts() if p.role in (PartRole.USER,))
    invocation = _invocation().model_copy(update={"parts": parts})
    _client(transport).invoke(invocation)
    assert "systemInstruction" not in json.loads(transport.requests[0].body)


def test_the_timeout_comes_from_the_invocation_else_the_default():
    transport = FakeTransport((200, _body()), (200, _body()))
    client = _client(transport, default_timeout_s=30.0)
    client.invoke(_invocation(timeout_ms=2500))
    client.invoke(_invocation())
    assert [r.timeout_s for r in transport.requests] == [2.5, 30.0]


def test_the_thinking_budget_is_always_sent_even_zero():
    transport = FakeTransport((200, _body()))
    _client(transport, budgets={"gem-model": 0}).invoke(
        _invocation(max_output_tokens=None)
    )
    config = json.loads(transport.requests[0].body)["generationConfig"]
    assert config == {"thinkingConfig": {"thinkingBudget": 0}}


def test_refuses_to_call_without_a_thinking_budget():
    transport = FakeTransport((200, _body()))
    with pytest.raises(ValueError, match="thinking budget"):
        _client(transport, budgets={}).invoke(_invocation())
    assert transport.requests == []


def test_rejects_a_negative_thinking_budget():
    with pytest.raises(ValueError, match="thinking budget"):
        _client(FakeTransport(), budgets={"gem-model": -1})


def test_refuses_a_model_without_a_gemini_route():
    transport = FakeTransport()
    with pytest.raises(ValueError, match="no enabled Gemini endpoint"):
        _client(transport).invoke(_invocation("oa-model"))
    assert transport.requests == []


# --- responses ---------------------------------------------------------------


def test_parses_text_finish_reason_model_version_and_usage():
    usage = {
        "promptTokenCount": 40,
        "candidatesTokenCount": 5,
        "totalTokenCount": 45,
    }
    transport = FakeTransport((200, _body(usage=usage)))
    result = _client(transport).invoke(_invocation())

    assert isinstance(result, ModelResponse)
    assert result.text == "[SYNTHETIC] ok"
    assert result.finish_reason == FinishReason.COMPLETE
    assert result.provider_model_version == "gem-wire-001"
    assert result.source == AnswerSource.LIVE
    assert result.provider_latency_ms is not None
    assert result.usage.input.tokens == 40
    assert result.usage.input.fidelity == Fidelity.PROVIDER_REPORTED
    assert result.usage.input.method == "provider:promptTokenCount"
    assert result.usage.output.tokens == 5
    assert result.usage.total.tokens == 45
    assert result.usage.cached_input is None  # not reported: unknown, never 0
    assert result.usage.reasoning is None


def test_thought_parts_are_not_answer_text():
    body = _body()
    body["candidates"][0]["content"]["parts"] = [
        {"text": "[SYNTHETIC] hidden", "thought": True},
        {"text": "[SYNTHETIC] visible"},
    ]
    result = _client(FakeTransport((200, body))).invoke(_invocation())
    assert result.text == "[SYNTHETIC] visible"


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        ("STOP", FinishReason.COMPLETE),
        ("MAX_TOKENS", FinishReason.LENGTH),
        ("SAFETY", FinishReason.CONTENT_FILTER),
        ("RECITATION", FinishReason.CONTENT_FILTER),
        ("BLOCKLIST", FinishReason.CONTENT_FILTER),
        ("PROHIBITED_CONTENT", FinishReason.CONTENT_FILTER),
        ("SPII", FinishReason.CONTENT_FILTER),
        ("MALFORMED_FUNCTION_CALL", FinishReason.OTHER),
        ("FINISH_REASON_UNSPECIFIED", FinishReason.OTHER),
        (None, FinishReason.OTHER),
    ],
)
def test_finish_reasons(wire, expected):
    result = _client(FakeTransport((200, _body(finish=wire)))).invoke(_invocation())
    assert result.finish_reason == expected


def test_a_blocked_prompt_is_a_content_filtered_error():
    body = {"promptFeedback": {"blockReason": "SAFETY"}}
    result = _client(FakeTransport((200, body))).invoke(_invocation())
    assert isinstance(result, ModelError)
    assert result.error_class == ErrorClass.CONTENT_FILTERED
    assert result.retryable is False
    assert result.provider_error_code == "prompt_blocked:safety"


def test_no_candidates_and_bad_json_are_unknown_errors():
    client = _client(FakeTransport((200, {"candidates": []}), (200, b"not json")))
    first, second = client.invoke(_invocation()), client.invoke(_invocation())
    assert first.error_class == ErrorClass.UNKNOWN
    assert first.provider_error_code == "malformed_response:no_candidates"
    assert second.error_class == ErrorClass.UNKNOWN
    assert second.provider_error_code == "malformed_response:not_json"


# --- usage normalisation ------------------------------------------------------


def test_thinking_tokens_outside_candidates_are_added_to_output():
    usage = {
        "promptTokenCount": 40,
        "candidatesTokenCount": 5,
        "thoughtsTokenCount": 100,
        "totalTokenCount": 145,
    }
    parsed = parse_usage(usage, "gem-model")
    assert parsed.output.tokens == 105
    assert parsed.output.method == "provider:candidatesTokenCount+thoughtsTokenCount"
    assert parsed.reasoning.tokens == 100
    assert parsed.reasoning.method == "provider:thoughtsTokenCount"
    assert parsed.total.tokens == 145


def test_thinking_tokens_inside_candidates_are_not_added_twice():
    usage = {
        "promptTokenCount": 40,
        "candidatesTokenCount": 105,
        "thoughtsTokenCount": 100,
        "totalTokenCount": 145,
    }
    parsed = parse_usage(usage, "gem-model")
    assert parsed.output.tokens == 105
    assert parsed.output.method == "provider:candidatesTokenCount"
    assert parsed.reasoning.tokens == 100


def test_thinking_convention_undecidable_leaves_output_unknown():
    usage = {
        "promptTokenCount": 40,
        "candidatesTokenCount": 5,
        "thoughtsTokenCount": 100,
    }  # no total: inside or outside cannot be told
    parsed = parse_usage(usage, "gem-model")
    assert parsed.input.tokens == 40
    assert parsed.output is None
    assert parsed.total is None
    assert parsed.reasoning is None  # part of output: unknown with it


def test_contradictory_thinking_counts_leave_output_unknown():
    usage = {
        "promptTokenCount": 40,
        "candidatesTokenCount": 5,
        "thoughtsTokenCount": 100,
        "totalTokenCount": 45,
    }  # "inside" by the total, but thoughts exceed candidates
    parsed = parse_usage(usage, "gem-model")
    assert (parsed.output, parsed.reasoning) == (None, None)


def test_zero_cached_tokens_are_reported_as_zero():
    usage = {
        "promptTokenCount": 40,
        "candidatesTokenCount": 5,
        "cachedContentTokenCount": 0,
        "totalTokenCount": 45,
    }
    parsed = parse_usage(usage, "gem-model")
    assert parsed.input.tokens == 40
    assert parsed.cached_input.tokens == 0
    assert parsed.cached_input.method == "provider:cachedContentTokenCount"


def test_cached_tokens_with_an_unverified_convention_make_usage_unknown(
    monkeypatch, caplog
):
    usage = {
        "promptTokenCount": 2000,
        "candidatesTokenCount": 5,
        "cachedContentTokenCount": 1500,
        "totalTokenCount": 2005,
    }
    monkeypatch.setattr(gemini_native, "PROMPT_COUNT_INCLUDES_CACHED", None)
    with caplog.at_level("WARNING"):
        assert parse_usage(usage, "gem-model") is None
    assert "cached-token convention unverified" in caplog.text


def test_cached_tokens_once_the_convention_is_verified(monkeypatch):
    usage = {
        "promptTokenCount": 2000,
        "candidatesTokenCount": 5,
        "cachedContentTokenCount": 1500,
        "totalTokenCount": 2005,
    }
    monkeypatch.setattr(gemini_native, "PROMPT_COUNT_INCLUDES_CACHED", True)
    included = parse_usage(usage, "gem-model")
    assert (included.input.tokens, included.cached_input.tokens) == (2000, 1500)

    monkeypatch.setattr(gemini_native, "PROMPT_COUNT_INCLUDES_CACHED", False)
    excluded = parse_usage(usage, "gem-model")
    assert (excluded.input.tokens, excluded.cached_input.tokens) == (3500, 1500)
    assert excluded.input.method == "provider:promptTokenCount+cachedContentTokenCount"


def test_the_shipped_cached_convention_is_unverified():
    assert gemini_native.PROMPT_COUNT_INCLUDES_CACHED is None


@pytest.mark.parametrize(
    "usage",
    [
        None,
        "nonsense",
        {},
        {"candidatesTokenCount": 5},
        {"promptTokenCount": True, "candidatesTokenCount": 5},
    ],
)
def test_missing_or_malformed_usage_is_unknown(usage):
    assert parse_usage(usage, "gem-model") is None


def test_missing_candidates_count_leaves_output_unknown():
    parsed = parse_usage({"promptTokenCount": 40}, "gem-model")
    assert parsed.input.tokens == 40
    assert parsed.output is None
    assert parsed.total is None


# --- errors -------------------------------------------------------------------


def _error_body(status: str):
    return {"error": {"code": 0, "message": "[SYNTHETIC] secret", "status": status}}


@pytest.mark.parametrize(
    ("status", "wire", "expected", "code", "retryable"),
    [
        (
            400,
            "INVALID_ARGUMENT",
            ErrorClass.INVALID_REQUEST,
            "http_400:invalid_argument",
            False,
        ),
        (401, "UNAUTHENTICATED", ErrorClass.AUTH, "http_401:unauthenticated", False),
        (402, None, ErrorClass.AUTH, "http_402:payment_required", False),
        (
            403,
            "PERMISSION_DENIED",
            ErrorClass.AUTH,
            "http_403:permission_denied",
            False,
        ),
        (404, "NOT_FOUND", ErrorClass.INVALID_REQUEST, "http_404:not_found", False),
        (408, None, ErrorClass.TIMEOUT, "http_408", True),
        (
            429,
            "RESOURCE_EXHAUSTED",
            ErrorClass.RATE_LIMITED,
            "http_429:resource_exhausted",
            True,
        ),
        (500, "INTERNAL", ErrorClass.UNAVAILABLE, "http_500:internal", True),
        (503, "UNAVAILABLE", ErrorClass.UNAVAILABLE, "http_503:unavailable", True),
        (
            504,
            "DEADLINE_EXCEEDED",
            ErrorClass.TIMEOUT,
            "http_504:deadline_exceeded",
            True,
        ),
        (302, None, ErrorClass.UNKNOWN, "http_302", True),
    ],
)
def test_http_errors_are_classified_without_the_message(
    status, wire, expected, code, retryable
):
    body = _error_body(wire) if wire else b"<html>[SYNTHETIC]</html>"
    transport = FakeTransport((status, body))
    result = _client(transport).invoke(_invocation())
    assert isinstance(result, ModelError)
    assert result.error_class == expected
    assert result.provider_error_code == code
    assert result.retryable is retryable
    assert "secret" not in result.model_dump_json()
    assert len(transport.requests) == 1  # no automatic retry


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("timeout", ErrorClass.TIMEOUT), ("connection", ErrorClass.CONNECTION)],
)
def test_transport_errors_are_classified(kind, expected):
    transport = FakeTransport(TransportError(kind))
    result = _client(transport).invoke(_invocation())
    assert result.error_class == expected
    assert result.provider_error_code == kind
    assert result.retryable is True
    assert len(transport.requests) == 1


# --- the default transport ----------------------------------------------------


def test_the_default_transport_is_urllib_and_tests_never_reach_it():
    client = GeminiNativeClient(
        api_key=KEY,
        catalogue=CATALOGUE,
        routes={"gemini": BASE},
        thinking_budgets={"gem-model": 0},
    )
    with pytest.raises(NetworkReached):
        client.invoke(_invocation())


@pytest.mark.parametrize(
    ("raised", "kind"),
    [
        (TimeoutError(), "timeout"),
        (urllib.error.URLError(TimeoutError()), "timeout"),
        (urllib.error.URLError("refused"), "connection"),
        (ConnectionResetError(), "connection"),
    ],
)
def test_the_urllib_transport_maps_failures_to_transport_errors(
    monkeypatch, raised, kind
):
    def fail(*args, **kwargs):
        raise raised

    monkeypatch.setattr(gemini_native.urllib.request, "urlopen", fail)
    request = HttpRequest("POST", f"{BASE}/x", {}, b"{}", 1.0)
    with pytest.raises(TransportError) as info:
        gemini_native.urllib_transport(request)
    assert info.value.kind == kind


def test_the_urllib_transport_returns_http_error_responses(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            f"{BASE}/x", 429, "Too Many Requests", {"x-test": "1"}, None
        )

    monkeypatch.setattr(gemini_native.urllib.request, "urlopen", fail)
    request = HttpRequest("POST", f"{BASE}/x", {}, b"{}", 1.0)
    response = gemini_native.urllib_transport(request)
    assert response.status == 429
    assert response.body == b""
