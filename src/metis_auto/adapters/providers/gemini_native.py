"""Live client for Gemini's native ``generateContent`` through the Metis wrapper
(CMP-10; providers.md §2–§3, ADR-0018, ADR-0021,
ADR-0043).

Responsibility: turn a ``ModelInvocation`` into one Gemini REST request, and
the reply into a ``ModelResult``: answer text, normalised finish reason,
provider-reported usage (cached and thinking tokens when reported), and the
provider-reported model version. Provider failures become ``ModelError``
values in the nine normalised classes, mapped as in ``openai_compat``; an
exception means a programming or configuration error. Implements
``ports.ModelClient`` with source ``live``.

- **No SDK, no new dependency.** Plain HTTPS + JSON over an injectable
  ``Transport`` (request in; status, headers, body out). The default is
  ``urllib_transport`` (standard library); tests inject a fake. This is the
  only module that imports ``urllib.request`` for a model call (tested).
- **One request per invoke**, no automatic retry: every retry is the
  pipeline's, so it is recorded and charged (ADR-0013).
- **Thinking is never left to the provider.** Every call sends an explicit
  thinking budget from configuration (``[model_options] thinking_budget``);
  a model without one is refused before any request. Thinking tokens bill as
  output (token_accounting.md §3.1).
- **Message layout (A-55, adapted):** Gemini has one system instruction, so
  instructions and each retrieved item are its parts, in order; history and
  the message are ``contents`` with roles ``user`` and ``model``.
- **Privacy:** error bodies are read only for the ``error.status`` identifier,
  never the message (it can echo content). Nothing here logs content.

Wire format provenance. Verified (docs/references/metis_wrapper_api.md §1,
from https://metisai.ir/api/wrapper/gemini saved 2026-10-18; re-read
2026-11-02): base URL ``https://api.metisai.ir``, the path
``/v1beta/models/<model>:generateContent``, the ``x-goog-api-key`` header, and
the google-genai format. NOT verified (the Metis page shows only the SDK; no
recorded Gemini response is in the repository, checked 2026-11-02): every
request and response JSON field name below. They are the expected Gemini REST
names, marked ``UNVERIFIED`` where used, to re-verify with the live check
(``scripts/live_gemini_check.py``).

Built by: ``wiring.live``, wrapped in the recording decorator. Called by:
application.pipeline. Status: provisional (offline only; the endpoint row
stays ``deferred`` until an owner-approved live check).
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

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

PATH = "/v1beta/models/{model}:generateContent"
"""Verified: metis_wrapper_api.md §1 (Metis page saved 2026-10-18), 2026-11-02."""
AUTH_HEADER = "x-goog-api-key"
"""Verified: metis_wrapper_api.md §1 and endpoints-metis.toml, 2026-11-02."""

SYSTEM_ROLES = frozenset({PartRole.INSTRUCTIONS, PartRole.RETRIEVED})
ROLE_TO_WIRE: dict[PartRole, str] = {
    PartRole.USER: "user",
    PartRole.ASSISTANT: "model",
}
"""UNVERIFIED (2026-11-02): ``contents[].role`` values ``user``/``model`` and
``systemInstruction.parts[].text``, expected Gemini REST names; not in the
Metis docs, no recorded response in the repository."""

FINISH_REASONS: dict[str, FinishReason] = {
    "STOP": FinishReason.COMPLETE,
    "MAX_TOKENS": FinishReason.LENGTH,
    "SAFETY": FinishReason.CONTENT_FILTER,
    "RECITATION": FinishReason.CONTENT_FILTER,
    "BLOCKLIST": FinishReason.CONTENT_FILTER,
    "PROHIBITED_CONTENT": FinishReason.CONTENT_FILTER,
    "SPII": FinishReason.CONTENT_FILTER,
}
"""UNVERIFIED (2026-11-02): ``candidates[].finishReason`` and its values,
expected Gemini REST names. Anything else (``MALFORMED_FUNCTION_CALL``,
``OTHER``, unspecified, missing) is ``other``."""

RETRYABLE: frozenset[ErrorClass] = frozenset(
    {
        ErrorClass.TIMEOUT,
        ErrorClass.RATE_LIMITED,
        ErrorClass.UNAVAILABLE,
        ErrorClass.CONNECTION,
        ErrorClass.UNKNOWN,
    }
)
"""providers.md §3 defaults, as in ``openai_compat``."""

USAGE = "provider:"
"""Prefix of ``TokenCount.method``; the rest names the usage field(s)."""

PROMPT_COUNT_INCLUDES_CACHED: bool | None = None
"""Whether ``usageMetadata.promptTokenCount`` already includes
``cachedContentTokenCount`` (the project's convention: input includes cached,
token_accounting.md §3.1). UNKNOWN (2026-11-02): neither the Metis docs nor any
recorded response in the repository says. While None, a response with cached
tokens > 0 has unknown usage (logged); the live check sets it."""


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes
    timeout_s: float


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class TransportError(Exception):
    """No HTTP response: ``kind`` is ``timeout`` or ``connection``."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


Transport = Callable[[HttpRequest], HttpResponse]
"""Sends one request. Returns any HTTP status as a response; raises
``TransportError`` only when there is no response."""


def urllib_transport(request: HttpRequest) -> HttpResponse:
    """The default transport (standard library). No retry, no redirect logic
    beyond urllib's own. An HTTP error status is returned, not raised; its
    body is read when available."""
    wire = urllib.request.Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method=request.method,
    )
    try:
        with urllib.request.urlopen(wire, timeout=request.timeout_s) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        headers = dict(exc.headers.items()) if exc.headers else {}
        return HttpResponse(status=exc.code, headers=headers, body=body)
    except urllib.error.URLError as exc:
        timeout = isinstance(exc.reason, TimeoutError)
        raise TransportError("timeout" if timeout else "connection") from None
    except TimeoutError:
        raise TransportError("timeout") from None
    except OSError:
        raise TransportError("connection") from None


class GeminiNativeClient:
    """One live client for the Gemini family through the Metis wrapper."""

    def __init__(
        self,
        *,
        api_key: str,
        catalogue: ModelCatalogue,
        routes: Mapping[str, str],
        thinking_budgets: Mapping[str, int],
        transport: Transport | None = None,
        default_timeout_s: float = 120.0,
    ) -> None:
        """``routes``: family → base URL (``google_genai`` endpoints).
        ``thinking_budgets``: catalogue model → thinking budget (tokens, ≥ 0),
        from ``[model_options]``; a model without one is refused at invoke."""
        for model_id, budget in thinking_budgets.items():
            if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
                raise ValueError(
                    f"{model_id}: the thinking budget must be an integer >= 0"
                )
        self._key = api_key
        self._routes = dict(routes)
        self._budgets = dict(thinking_budgets)
        self._models = {
            e.model_id: e for e in catalogue.entries if e.provider in routes
        }
        self._transport = transport or urllib_transport
        self._timeout = default_timeout_s

    @property
    def source(self) -> AnswerSource:
        return AnswerSource.LIVE

    @property
    def model_ids(self) -> frozenset[str]:
        return frozenset(self._models)

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        entry = self._models.get(invocation.model_id)
        if entry is None:
            raise ValueError(
                f"model {invocation.model_id!r} has no enabled Gemini endpoint "
                "in the configuration"
            )
        if invocation.attachments:
            raise ValueError("this adapter does not send attachments")
        budget = self._budgets.get(invocation.model_id)
        if budget is None:
            raise ValueError(
                f"model {invocation.model_id!r} has no thinking budget configured "
                "([model_options] thinking_budget); refusing to call, so no call "
                "thinks at the provider's default"
            )
        timeout_s = (
            invocation.timeout_ms / 1000
            if invocation.timeout_ms is not None
            else self._timeout
        )
        request = HttpRequest(
            method="POST",
            url=self._routes[entry.provider].rstrip("/")
            + PATH.format(model=entry.provider_model_name),
            headers={AUTH_HEADER: self._key, "Content-Type": "application/json"},
            body=json.dumps(
                build_body(invocation, budget), ensure_ascii=False
            ).encode(),
            timeout_s=timeout_s,
        )
        start = time.perf_counter()
        try:
            response = self._transport(request)
        except TransportError as exc:
            error_class = (
                ErrorClass.TIMEOUT if exc.kind == "timeout" else ErrorClass.CONNECTION
            )
            return _error(error_class, exc.kind, _elapsed_ms(start))
        latency = _elapsed_ms(start)
        if response.status != 200:
            error_class, code = classify_status(response.status, response.body)
            return _error(error_class, code, latency)
        try:
            data = json.loads(response.body)
        except (ValueError, UnicodeDecodeError):
            data = None
        if not isinstance(data, Mapping):
            return _error(ErrorClass.UNKNOWN, "malformed_response:not_json", latency)
        return parse_response(data, invocation.model_id, latency)


def build_body(invocation: ModelInvocation, thinking_budget: int) -> dict[str, Any]:
    """The ``generateContent`` request body. UNVERIFIED field names
    (2026-11-02): ``systemInstruction``, ``contents``, ``generationConfig``,
    ``maxOutputTokens``, ``thinkingConfig.thinkingBudget``."""
    body: dict[str, Any] = {}
    system = [{"text": p.text} for p in invocation.parts if p.role in SYSTEM_ROLES]
    if system:
        body["systemInstruction"] = {"parts": system}
    body["contents"] = to_contents(invocation.parts)
    config: dict[str, Any] = {}
    if invocation.max_output_tokens is not None:
        config["maxOutputTokens"] = invocation.max_output_tokens
    config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    body["generationConfig"] = config
    return body


def to_contents(parts: tuple[InputPart, ...]) -> list[dict[str, Any]]:
    return [
        {"role": ROLE_TO_WIRE[p.role], "parts": [{"text": p.text}]}
        for p in parts
        if p.role not in SYSTEM_ROLES
    ]


def parse_response(
    data: Mapping[str, Any], model_id: str, latency_ms: float | None = None
) -> ModelResult:
    """A ``generateContent`` response body → ``ModelResponse``, or an error:
    a blocked prompt (``promptFeedback.blockReason``, UNVERIFIED) is
    ``content_filtered``; no candidate is ``unknown``."""
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = data.get("promptFeedback")
        reason = feedback.get("blockReason") if isinstance(feedback, Mapping) else None
        if isinstance(reason, str) and reason:
            return _error(
                ErrorClass.CONTENT_FILTERED,
                f"prompt_blocked:{_code(reason)}",
                latency_ms,
                retryable=False,
            )
        return _error(
            ErrorClass.UNKNOWN, "malformed_response:no_candidates", latency_ms
        )
    candidate = candidates[0] if isinstance(candidates[0], Mapping) else {}
    version = data.get("modelVersion")  # UNVERIFIED (2026-11-02)
    finish = candidate.get("finishReason")
    return ModelResponse(
        text=_answer_text(candidate.get("content")),
        finish_reason=FINISH_REASONS.get(
            finish if isinstance(finish, str) else "", FinishReason.OTHER
        ),
        usage=parse_usage(data.get("usageMetadata"), model_id),
        provider_latency_ms=latency_ms,
        provider_model_version=version
        if isinstance(version, str) and version
        else None,
        source=AnswerSource.LIVE,
    )


def _answer_text(content: object) -> str:
    """Visible text parts joined; parts marked ``thought`` (UNVERIFIED) are
    thinking summaries, not the answer."""
    parts = content.get("parts") if isinstance(content, Mapping) else None
    if not isinstance(parts, list):
        return ""
    return "".join(
        p["text"]
        for p in parts
        if isinstance(p, Mapping)
        and isinstance(p.get("text"), str)
        and p.get("thought") is not True
    )


def parse_usage(usage: object, model_id: str) -> TokenUsage | None:
    """``usageMetadata`` → ``TokenUsage`` under the inclusion rules
    (token_accounting.md §3.1). UNVERIFIED field names (2026-11-02, expected
    Gemini REST names; not in the Metis docs, no recorded response):
    ``promptTokenCount``, ``candidatesTokenCount``, ``cachedContentTokenCount``,
    ``thoughtsTokenCount``, ``totalTokenCount``.

    - ``input`` = ``promptTokenCount``. Cached tokens > 0 need
      ``PROMPT_COUNT_INCLUDES_CACHED``; while it is unknown the whole usage is
      unknown (None, logged), never a guess. Cached = 0 is reported as 0.
    - ``output`` includes thinking (thinking bills as output). Whether
      ``candidatesTokenCount`` already includes ``thoughtsTokenCount`` is
      UNVERIFIED, so it is decided per response from ``totalTokenCount``:
      total = prompt + candidates + thoughts → thoughts are added;
      total = prompt + candidates → they are inside. Undecidable → output,
      total, and reasoning unknown (None: reasoning is part of output in
      ``TokenUsage``, so it cannot stand without it).
    - Missing or malformed counts are None, never 0."""
    if not isinstance(usage, Mapping):
        return None
    prompt = _int(usage.get("promptTokenCount"))
    if prompt is None:
        return None
    candidates = _int(usage.get("candidatesTokenCount"))
    thoughts = _int(usage.get("thoughtsTokenCount"))
    cached = _int(usage.get("cachedContentTokenCount"))
    reported_total = _int(usage.get("totalTokenCount"))

    input_tokens, input_method = prompt, "promptTokenCount"
    if cached:
        if PROMPT_COUNT_INCLUDES_CACHED is None:
            log.warning(
                "gemini usage unknown: cached-token convention unverified "
                "(PROMPT_COUNT_INCLUDES_CACHED)"
            )
            return None
        if not PROMPT_COUNT_INCLUDES_CACHED:
            input_tokens = prompt + cached
            input_method = "promptTokenCount+cachedContentTokenCount"
        elif cached > prompt:
            log.warning("gemini usage: cached tokens exceed prompt tokens; ignored")
            cached = None

    output: tuple[int, str] | None = None
    if candidates is not None:
        if not thoughts:
            output = (candidates, "candidatesTokenCount")
        elif reported_total == prompt + candidates + thoughts:
            output = (candidates + thoughts, "candidatesTokenCount+thoughtsTokenCount")
        elif reported_total == prompt + candidates and thoughts <= candidates:
            output = (candidates, "candidatesTokenCount")

    def count(tokens: int, method: str) -> TokenCount:
        return TokenCount(
            tokens=tokens, fidelity=Fidelity.PROVIDER_REPORTED, method=USAGE + method
        )

    return TokenUsage(
        model_id=model_id,
        input=count(input_tokens, input_method),
        output=count(*output) if output else None,
        total=count(input_tokens + output[0], "sum") if output else None,
        cached_input=count(cached, "cachedContentTokenCount")
        if cached is not None
        else None,
        reasoning=count(thoughts, "thoughtsTokenCount")
        if thoughts is not None and output
        else None,
    )


def classify_status(status: int, body: bytes) -> tuple[ErrorClass, str]:
    """An HTTP error status → (normalised class, provider error code).

    The code is ``http_<status>`` plus the body's ``error.status`` identifier
    (UNVERIFIED Google error format, 2026-11-02), never the message. Mapping as
    ``openai_compat`` (providers.md §3): 429 → ``rate_limited``; 401, 403 →
    ``auth``; **402 → ``auth``** with the reason ``payment_required`` in the
    code (the nine classes have no budget or payment class); 408 and 504 (or
    ``DEADLINE_EXCEEDED``) → ``timeout``; other 4xx → ``invalid_request``;
    other 5xx → ``unavailable``; anything else → ``unknown``."""
    ident = _error_status(body)
    if status == 402 and not ident:
        ident = "payment_required"
    code = f"http_{status}" + (f":{_code(ident)}" if ident else "")
    if status == 429:
        return ErrorClass.RATE_LIMITED, code
    if status in (401, 402, 403):
        return ErrorClass.AUTH, code
    if status in (408, 504) or ident.upper() == "DEADLINE_EXCEEDED":
        return ErrorClass.TIMEOUT, code
    if 400 <= status < 500:
        return ErrorClass.INVALID_REQUEST, code
    if status >= 500:
        return ErrorClass.UNAVAILABLE, code
    return ErrorClass.UNKNOWN, code


def _error_status(body: bytes) -> str:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return ""
    error = data.get("error") if isinstance(data, Mapping) else None
    status = error.get("status") if isinstance(error, Mapping) else None
    return status if isinstance(status, str) else ""


def _error(
    error_class: ErrorClass,
    code: str,
    latency_ms: float | None,
    *,
    retryable: bool | None = None,
) -> ModelError:
    return ModelError(
        error_class=error_class,
        retryable=error_class in RETRYABLE if retryable is None else retryable,
        provider_error_code=code,
        provider_latency_ms=latency_ms,
        source=AnswerSource.LIVE,
    )


def _code(text: str) -> str:
    """A provider identifier made safe for the ``Name`` pattern."""
    cleaned = re.sub(r"[^a-z0-9_.:\-]", "_", text.lower()).strip("_") or "error"
    return cleaned[:96]


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000
