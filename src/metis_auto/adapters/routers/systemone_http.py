"""A local ``/v1/systemone`` server as a decision backend
(ADR-XXXX (system-one-decision-router); R5).

For Mizan-1.5-4B on the owner's own ``llama-server`` (or THX-01's own server).
Loopback only (validated in settings): dataset text may go to it because it
never leaves the machine. Implements ``ports.BaseRouter`` with ``httpx``
(already in every lock); the only router module that imports it.

- ``available``: ``GET <base_url><health_path>``, at most once per
  ``health_ttl_s`` (the cascade asks on every request).
- ``decide``: ``POST <base_url>/v1/systemone`` with ``{model, state,
  questions}`` (``wire``). Expected failures are returned, never raised:
  timeout, connection, HTTP status (``http_<code>``; never the body), an
  unparseable or mismatched answer (``invalid_response``).
- ``model_revision`` is the ``model`` the server reports (else the configured
  one). ``calibrated`` is False: whether llama-server applies Mizan's fitted
  temperatures is not documented (open, R0 findings §5).

Mizan is shadow and offline evaluation only, never inline on CPU (owner).
Built by wiring.routers. Status: provisional.
"""

from __future__ import annotations

from typing import Literal

import httpx

from metis_auto.contracts import (
    AvailabilityReason,
    BackendAvailability,
    BackendKind,
    CostEstimate,
    DecisionError,
    DecisionLatencySource,
    DecisionQuestionSet,
    DecisionResult,
    DecisionState,
    ErrorClass,
    Fidelity,
    PolicyRef,
    TokenCount,
    TokenUsage,
)
from metis_auto.ports import Clock

from .fake import local_zero_cost
from .wire import StateFormat, WireError, parse_answers, render_questions, render_state

PATH = "/v1/systemone"


class SystemOneHttpBackend:
    def __init__(
        self,
        clock: Clock,
        *,
        name: str,
        base_url: str,
        model: str,
        health_path: str = "/health",
        health_timeout_ms: float = 200,
        health_ttl_s: float = 5.0,
        state_format: StateFormat = "text",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._clock = clock
        self._name = name
        self._base = base_url.rstrip("/")
        self._model = model
        self._health_path = health_path
        self._health_timeout_s = health_timeout_ms / 1000.0
        self._health_ttl_ms = health_ttl_s * 1000.0
        self._format: StateFormat = state_format
        self._client = httpx.Client(transport=transport, trust_env=False)
        self._health: tuple[float, bool] | None = None
        self.calls = 0

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(name=self._name, version=self._model[:64])

    @property
    def kind(self) -> Literal["local"]:
        return "local"

    def estimate_cost(self, state_tokens: int) -> CostEstimate | None:
        return None

    def available(self) -> BackendAvailability:
        now = self._clock.monotonic_ms()
        if self._health is None or now - self._health[0] > self._health_ttl_ms:
            try:
                response = self._client.get(
                    self._base + self._health_path, timeout=self._health_timeout_s
                )
                ok = response.status_code == 200
            except httpx.HTTPError:
                ok = False
            self._health = (now, ok)
        if self._health[1]:
            return BackendAvailability.ok()
        return BackendAvailability.unavailable(AvailabilityReason.SERVER_UNREACHABLE)

    def decide(
        self,
        state: DecisionState,
        questions: DecisionQuestionSet,
        *,
        timeout_ms: float,
    ) -> DecisionResult | DecisionError:
        self.calls += 1
        body = {
            "model": self._model,
            "state": render_state(state, self._format),
            "questions": render_questions(questions),
        }
        start = self._clock.monotonic_ms()

        def error(kind: ErrorClass, code: str | None = None) -> DecisionError:
            return DecisionError(
                backend=self.ref,
                error_class=kind,
                provider_error_code=code,
                latency_ms=self._clock.monotonic_ms() - start,
            )

        try:
            response = self._client.post(
                self._base + PATH, json=body, timeout=timeout_ms / 1000.0
            )
        except httpx.TimeoutException:
            return error(ErrorClass.TIMEOUT)
        except httpx.ConnectError:
            self._health = None
            return error(ErrorClass.CONNECTION)
        except httpx.HTTPError:
            return error(ErrorClass.UNKNOWN)
        elapsed = self._clock.monotonic_ms() - start
        status = response.status_code
        if status != 200:
            kind = (
                ErrorClass.RATE_LIMITED
                if status == 429
                else ErrorClass.UNAVAILABLE
                if status >= 500
                else ErrorClass.INVALID_REQUEST
            )
            return error(kind, f"http_{status}")
        try:
            payload = response.json()
            answers = parse_answers(payload.get("answers"), questions)
        except (ValueError, WireError, AttributeError):
            return DecisionError(
                backend=self.ref, invalid_response=True, latency_ms=elapsed
            )
        reported = payload.get("model")
        revision = reported if isinstance(reported, str) and reported else self._model
        usage = None
        tokens = (payload.get("usage") or {}).get("input_tokens")
        if isinstance(tokens, int) and tokens >= 0:
            usage = TokenUsage(
                model_id=self._name,
                input=TokenCount(
                    tokens=tokens,
                    fidelity=Fidelity.PROVIDER_REPORTED,
                    method="systemone.usage.input_tokens",
                ),
            )
        return DecisionResult(
            answers=answers,
            backend=self.ref,
            backend_kind=BackendKind.LOCAL,
            model_revision=revision[:64],
            question_set_version=questions.version,
            latency_ms=elapsed,
            latency_source=DecisionLatencySource.MEASURED_LOCAL,
            usage=usage,
            cost=local_zero_cost(),
            calibrated=False,
        )

    def close(self) -> None:
        self._client.close()
