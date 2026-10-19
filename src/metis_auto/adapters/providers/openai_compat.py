"""Live client for OpenAI-compatible chat completions through the Metis wrapper
(CMP-10; providers.md §2–§3, ADR-0018, ADR-0021).

Responsibility: turn a ``ModelInvocation`` into one chat-completions request to
the base URL of the model's family (OpenAI, DeepSeek, Grok), and the reply into
a ``ModelResult``: answer text, normalised finish reason, provider-reported
usage (with cached and reasoning tokens when reported), and the
provider-reported model. Provider failures become ``ModelError`` values in the
nine normalised classes; an exception means a programming or configuration
error. Implements ``ports.ModelClient`` with source ``live``.

- **One request per invoke.** SDK automatic retries are off (``max_retries=0``,
  A-33, verified with the openai SDK 3.24.0): every retry is the pipeline's,
  so it is recorded and charged (ADR-0013).
- **Message layout (A-55):** each input part is one message; instructions and
  each retrieved item are ``system`` messages; history turns keep their role.
- **Privacy:** the SDK's and HTTP library's loggers are held at WARNING, since
  their DEBUG output includes request bodies. Error codes are kept, provider
  error messages never (they can echo content).
- The ``openai`` package (extra ``live``) is imported only here.

Built by: ``wiring.live``, wrapped in the recording decorator. Called by:
application.pipeline. Status: Stage 7.5; mappings provisional until checked
against the wrapper (TODO-12, docs/references/metis_wrapper_live_check.md).
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx2
import openai

from metis_auto.contracts import (
    AnswerSource,
    ErrorClass,
    Fidelity,
    FinishReason,
    InputPart,
    ModelCatalogue,
    ModelError,
    ModelInvocation,
    ModelResponse,
    ModelResult,
    PartRole,
    TokenCount,
    TokenUsage,
)

log = logging.getLogger(__name__)

for _noisy in ("openai", "httpx2", "httpcore2"):
    # DEBUG records from these libraries include request bodies (content).
    logging.getLogger(_noisy).setLevel(logging.WARNING)

ROLE_TO_WIRE: dict[PartRole, str] = {
    PartRole.INSTRUCTIONS: "system",
    PartRole.RETRIEVED: "system",
    PartRole.USER: "user",
    PartRole.ASSISTANT: "assistant",
}
"""A-55: one message per part; retrieved context as its own system message."""

FINISH_REASONS: dict[str, FinishReason] = {
    "stop": FinishReason.COMPLETE,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}
"""Anything else (``tool_calls``, DeepSeek's ``insufficient_system_resource``
and ``aborted``, missing) is ``other``."""

RETRYABLE: frozenset[ErrorClass] = frozenset(
    {
        ErrorClass.TIMEOUT,
        ErrorClass.RATE_LIMITED,
        ErrorClass.UNAVAILABLE,
        ErrorClass.CONNECTION,
        ErrorClass.UNKNOWN,
    }
)
"""providers.md §3 defaults; the attempt policy bounds the retries."""

USAGE = "provider:"
"""Prefix of ``TokenCount.method`` for provider-reported counts; the rest names
the usage field(s), so a record shows which convention the provider used."""


@dataclass(frozen=True)
class EndpointRoute:
    """How to reach one family (from ``config/reference/endpoints-*.toml``)."""

    family: str
    base_url: str
    max_tokens_param: str
    """``max_completion_tokens`` or ``max_tokens``."""


class OpenAICompatibleClient:
    """One live client for every OpenAI-compatible family."""

    def __init__(
        self,
        *,
        api_key: str,
        catalogue: ModelCatalogue,
        endpoints: Mapping[str, EndpointRoute],
        default_timeout_s: float = 120.0,
        http_client_factory: Callable[[], httpx2.Client] | None = None,
        request_options: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        """``request_options``: extra request-body fields per catalogue model
        (e.g. ``{"thinking": {"type": "disabled"}}``), built and checked by
        wiring from ``[model_options]``; none = the provider's defaults.
        ``http_client_factory`` exists for tests (mocked HTTP); production
        uses the SDK's default HTTP client."""
        self._options = {k: dict(v) for k, v in (request_options or {}).items()}
        self._models = {
            e.model_id: e for e in catalogue.entries if e.provider in endpoints
        }
        self._endpoints = dict(endpoints)
        self._clients = {
            family: openai.OpenAI(
                api_key=api_key,
                base_url=route.base_url,
                max_retries=0,  # A-33: no hidden attempts (ADR-0013)
                timeout=default_timeout_s,
                http_client=http_client_factory() if http_client_factory else None,
            )
            for family, route in self._endpoints.items()
        }

    @property
    def source(self) -> AnswerSource:
        return AnswerSource.LIVE

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        entry = self._models.get(invocation.model_id)
        if entry is None:
            raise ValueError(
                f"model {invocation.model_id!r} has no enabled OpenAI-compatible "
                "endpoint in the configuration"
            )
        if invocation.attachments:
            # Routing never sends attachments here: no catalogue model has a
            # verified image capability (FR-ROUTE-05), and content is never
            # inspected (NG-07).
            raise ValueError("this adapter does not send attachments")
        route = self._endpoints[entry.provider]
        request: dict[str, Any] = {
            "model": entry.provider_model_name,
            "messages": to_messages(invocation.parts),
        }
        if invocation.max_output_tokens is not None:
            request[route.max_tokens_param] = invocation.max_output_tokens
        if invocation.timeout_ms is not None:
            request["timeout"] = invocation.timeout_ms / 1000
        if invocation.model_id in self._options:
            request["extra_body"] = self._options[invocation.model_id]
        start = time.perf_counter()
        try:
            completion = self._clients[entry.provider].chat.completions.create(
                **request
            )
        except openai.OpenAIError as exc:
            error_class, code = classify_error(exc)
            return ModelError(
                error_class=error_class,
                retryable=error_class in RETRYABLE,
                provider_error_code=code,
                provider_latency_ms=_elapsed_ms(start),
                source=AnswerSource.LIVE,
            )
        return parse_completion(
            completion.to_dict(), invocation.model_id, _elapsed_ms(start)
        )


def to_messages(parts: tuple[InputPart, ...]) -> list[dict[str, str]]:
    return [{"role": ROLE_TO_WIRE[p.role], "content": p.text} for p in parts]


def parse_completion(
    data: Mapping[str, Any], model_id: str, latency_ms: float | None = None
) -> ModelResult:
    """A chat-completions response body → ``ModelResponse`` (or an
    ``unknown`` error if it has no choice)."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ModelError(
            error_class=ErrorClass.UNKNOWN,
            retryable=True,
            provider_error_code="malformed_response:no_choices",
            provider_latency_ms=latency_ms,
            source=AnswerSource.LIVE,
        )
    choice = choices[0] if isinstance(choices[0], Mapping) else {}
    message = choice.get("message")
    text = message.get("content") if isinstance(message, Mapping) else None
    reported_model = data.get("model")
    return ModelResponse(
        text=text if isinstance(text, str) else "",
        finish_reason=FINISH_REASONS.get(
            choice.get("finish_reason") or "", FinishReason.OTHER
        ),
        usage=parse_usage(data.get("usage"), model_id),
        provider_latency_ms=latency_ms,
        provider_model_version=reported_model
        if isinstance(reported_model, str) and reported_model
        else None,
        source=AnswerSource.LIVE,
    )


def parse_usage(usage: object, model_id: str) -> TokenUsage | None:
    """Provider usage → ``TokenUsage`` under the inclusion rules
    (token_accounting.md §3.1): ``input`` = ``prompt_tokens`` (cached tokens are
    a reported subset); ``output`` includes reasoning. If ``reasoning_tokens``
    is reported **outside** ``completion_tokens`` (``total`` = prompt +
    completion + reasoning, or reasoning > completion), it is added to output,
    and the method says so. Cache-write counts are not mapped: no test model
    prices them (2026-10-18). None when usage is missing or malformed."""
    if not isinstance(usage, Mapping):
        return None
    prompt = _int(usage.get("prompt_tokens"))
    completion = _int(usage.get("completion_tokens"))
    if prompt is None or completion is None:
        return None
    total = _int(usage.get("total_tokens"))
    reasoning = _int(_get(usage, "completion_tokens_details", "reasoning_tokens"))

    output_tokens, output_method = completion, "completion_tokens"
    reasoning_outside = bool(reasoning) and (
        (total is not None and total == prompt + completion + reasoning)
        or reasoning > completion
    )
    if reasoning_outside:
        output_tokens = completion + reasoning
        output_method = "completion_tokens+reasoning_tokens"

    cached, cached_method = _cached(usage)
    if cached is not None and cached > prompt:
        log.warning("provider usage: cached tokens exceed prompt tokens; ignored")
        cached = None

    def count(tokens: int, method: str) -> TokenCount:
        return TokenCount(
            tokens=tokens, fidelity=Fidelity.PROVIDER_REPORTED, method=USAGE + method
        )

    return TokenUsage(
        model_id=model_id,
        input=count(prompt, "prompt_tokens"),
        output=count(output_tokens, output_method),
        total=count(prompt + output_tokens, "sum"),
        cached_input=count(cached, cached_method) if cached is not None else None,
        reasoning=count(reasoning, "reasoning_tokens")
        if reasoning is not None
        else None,
    )


def _cached(usage: Mapping[str, Any]) -> tuple[int | None, str]:
    """OpenAI style ``prompt_tokens_details.cached_tokens``, else DeepSeek's
    ``prompt_cache_hit_tokens`` (DeepSeek documents both as equal)."""
    details = _int(_get(usage, "prompt_tokens_details", "cached_tokens"))
    if details is not None:
        return details, "prompt_tokens_details.cached_tokens"
    hit = _int(usage.get("prompt_cache_hit_tokens"))
    return hit, "prompt_cache_hit_tokens"


def classify_error(exc: openai.OpenAIError) -> tuple[ErrorClass, str]:
    """An SDK exception → (normalised class, provider error code).

    The code is built from the HTTP status and the provider's error ``code`` or
    ``type`` (identifiers), never from the message. Mapping (providers.md §3):
    timeout → ``timeout``; no response → ``connection``; HTTP 429 →
    ``rate_limited`` (but ``insufficient_quota`` → ``auth``); 401, 402 (DeepSeek:
    insufficient balance), 403 → ``auth``; 408 → ``timeout``; codes naming the
    context length → ``context_overflow``; codes naming a content filter or
    policy → ``content_filtered``; other 4xx → ``invalid_request``; 5xx →
    ``unavailable``; anything else → ``unknown``."""
    if isinstance(exc, openai.APITimeoutError):
        return ErrorClass.TIMEOUT, "timeout"
    if isinstance(exc, openai.APIConnectionError):
        return ErrorClass.CONNECTION, "connection"
    if not isinstance(exc, openai.APIStatusError):
        return ErrorClass.UNKNOWN, _code(type(exc).__name__)
    status = exc.status_code
    ident = (exc.code or getattr(exc, "type", None) or "").lower()
    code = f"http_{status}" + (f":{_code(ident)}" if ident else "")
    if "context_length" in ident or "context_window" in ident:
        return ErrorClass.CONTEXT_OVERFLOW, code
    if "content_filter" in ident or "content_policy" in ident:
        return ErrorClass.CONTENT_FILTERED, code
    if ident == "insufficient_quota":
        return ErrorClass.AUTH, code
    if status == 429:
        return ErrorClass.RATE_LIMITED, code
    if status in (401, 402, 403):
        return ErrorClass.AUTH, code
    if status == 408:
        return ErrorClass.TIMEOUT, code
    if 400 <= status < 500:
        return ErrorClass.INVALID_REQUEST, code
    if status >= 500:
        return ErrorClass.UNAVAILABLE, code
    return ErrorClass.UNKNOWN, code


def _code(text: str) -> str:
    """A provider identifier made safe for the ``Name`` pattern."""
    cleaned = re.sub(r"[^a-z0-9_.:\-]", "_", text.lower()).strip("_") or "error"
    return cleaned[:96]


def _get(mapping: Mapping[str, Any], outer: str, inner: str) -> object:
    nested = mapping.get(outer)
    return nested.get(inner) if isinstance(nested, Mapping) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000
