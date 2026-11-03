"""LLM-as-System-One: the Mode 1 backup decision backend
(ADR-0047 point 2; R6).

A tier-0 chat model (default ``gpt-4.1-nano``) is asked the same typed
questions as Jev and answers in JSON, in the shared wire shape
(``{"answers": {<id>: {...}}}``). It goes through the project's live
``ModelClient`` (the OpenAI-compatible adapter, ADR-0021), so the SDK stays
in its one adapter; this module only builds the prompt and parses the reply.
Answers are **uncalibrated** (``calibrated = False``): a chat model's stated
confidence is not a probability.

Cost: injected by wiring (adapters import only ports and contracts):
``cost`` prices a call's usage with the catalogue entry's price through
``domain.accounting.cost_of`` (the same rule as every answering call), and
``estimate`` gives the pre-call estimate from the state plus the prompt text
(``PROMPT_CHARS`` / 2, an upper bound) and ``max_output_tokens``.
Hosted, so the cascade's approval check and spend guard apply: SYNTHETIC or
owner-written text only until Metis confirms the licence (owner decision).

Built by wiring.routers. Status: provisional (uncalibrated backup).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal

from metis_auto.contracts import (
    AttemptKind,
    AvailabilityReason,
    BackendAvailability,
    BackendKind,
    ComponentName,
    Cost,
    CostEstimate,
    DecisionError,
    DecisionLatencySource,
    DecisionQuestionSet,
    DecisionResult,
    DecisionState,
    ErrorClass,
    InputPart,
    ModelError,
    ModelInvocation,
    PartRole,
    PolicyRef,
    TokenUsage,
)
from metis_auto.ports import Clock, ModelClient

from .wire import StateFormat, WireError, parse_answers, render_questions, render_state

PROMPT_VERSION = "llm-s1-prompt-v1"
CHARS_PER_TOKEN_BOUND = 2
PROMPT_CHARS = 3_000
"""Characters of the fixed prompt plus the questions JSON (about 2,200 for
``routing_qs_v1``), rounded up for the pre-call estimate."""

SYSTEM_PROMPT = (
    "You are a System-One decision model. You never answer the user. You "
    "read the STATE and answer every QUESTION about it.\n"
    "Return only one JSON object, no prose: "
    '{"answers": {"<question id>": <answer>}}.\n'
    'For type "choice": {"type": "choice", "choice": "<one option name>", '
    '"confidence": <0..1>}.\n'
    'For type "score": {"type": "score", "score": <level index, 0-based>, '
    '"confidence": <0..1>}.\n'
    'For type "noul": {"type": "noul", "noul": <probability of yes, 0..1>, '
    '"confidence": <0..1>}.\n'
    "QUESTIONS (id -> type, instructions, criteria):\n"
)


def prompt_parts(
    state: DecisionState, questions: DecisionQuestionSet, fmt: StateFormat
) -> tuple[InputPart, InputPart]:
    rendered = render_state(state, fmt)
    state_text = (
        rendered
        if isinstance(rendered, str)
        else json.dumps(rendered, ensure_ascii=False)
    )
    system = SYSTEM_PROMPT + json.dumps(render_questions(questions), ensure_ascii=False)
    return (
        InputPart(
            role=PartRole.INSTRUCTIONS,
            text=system,
            component=ComponentName.INSTRUCTIONS,
        ),
        InputPart(
            role=PartRole.USER,
            text="STATE:\n" + state_text,
            component=ComponentName.MESSAGE,
        ),
    )


def _json_object(text: str) -> object:
    """The reply's JSON object (a fenced block or leading prose is tolerated)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise WireError("no JSON object in the reply")
    return json.loads(text[start : end + 1])


class LlmSystemOneBackend:
    def __init__(
        self,
        clock: Clock,
        *,
        name: str,
        client: ModelClient | None,
        model_id: str,
        cost: Callable[[TokenUsage | None], Cost] | None,
        estimate: Callable[[int], CostEstimate | None] | None,
        max_output_tokens: int = 300,
        state_format: StateFormat = "text",
    ) -> None:
        self._clock = clock
        self._name = name
        self._client = client
        self._model_id = model_id
        self._cost = cost
        self._estimate = estimate
        self._max_out = max_output_tokens
        self._format: StateFormat = state_format
        self.calls = 0

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(
            name=self._name, version=f"{self._model_id}+{PROMPT_VERSION}"[:64]
        )

    @property
    def kind(self) -> Literal["hosted"]:
        return "hosted"

    def available(self) -> BackendAvailability:
        if self._client is None or self._cost is None or self._estimate is None:
            return BackendAvailability.unavailable(AvailabilityReason.NOT_CONFIGURED)
        return BackendAvailability.ok()

    def estimate_cost(self, state_tokens: int) -> CostEstimate | None:
        if self._estimate is None:
            return None
        return self._estimate(state_tokens + -(-PROMPT_CHARS // CHARS_PER_TOKEN_BOUND))

    def decide(
        self,
        state: DecisionState,
        questions: DecisionQuestionSet,
        *,
        timeout_ms: float,
    ) -> DecisionResult | DecisionError:
        if self._client is None or self._cost is None:
            return DecisionError(
                backend=self.ref, error_class=ErrorClass.AUTH, latency_ms=0.0
            )
        self.calls += 1
        invocation = ModelInvocation(
            request_id="router-llm-s1",
            attempt_id=f"router-llm-s1-{self.calls}",
            attempt_kind=AttemptKind.PRIMARY,
            model_id=self._model_id,
            parts=prompt_parts(state, questions, self._format),
            max_output_tokens=self._max_out,
            timeout_ms=max(1, int(timeout_ms)),
        )
        start = self._clock.monotonic_ms()
        result = self._client.invoke(invocation)
        elapsed = self._clock.monotonic_ms() - start
        if isinstance(result, ModelError):
            return DecisionError(
                backend=self.ref,
                error_class=result.error_class,
                provider_error_code=result.provider_error_code,
                latency_ms=elapsed,
            )
        cost = self._cost(result.usage)
        try:
            payload = _json_object(result.text)
            raw = payload.get("answers") if isinstance(payload, dict) else None
            answers = parse_answers(raw, questions)
        except (ValueError, WireError):
            # Billed even when unusable: the cost travels on the error only
            # through the cascade's estimate charge (never silently dropped).
            return DecisionError(
                backend=self.ref, invalid_response=True, latency_ms=elapsed
            )
        return DecisionResult(
            answers=answers,
            backend=self.ref,
            backend_kind=BackendKind.HOSTED,
            model_revision=(result.provider_model_version or self._model_id)[:64],
            question_set_version=questions.version,
            latency_ms=elapsed,
            latency_source=DecisionLatencySource.MEASURED_REMOTE,
            usage=result.usage,
            cost=cost,
            calibrated=False,
        )
