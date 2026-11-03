"""Jev (TypeSafe) through the Metis wrapper: the hosted System-One decision
backend, Mode 1 (ADR-0047 points 1-2, 6; R6).

Endpoint ``POST <base_url>/v1/systemone`` with ``Authorization: Bearer <Metis
key>`` (Metis TypeSafe page, saved 2026-11-02:
``docs/references/metis_typesafe_wrapper_page.md``). Body
``{model, state, questions}`` in the shared wire shape (``wire.py``); the
response holds ``answers``, the versioned ``model`` (``jev-1.13.0`` for
``jev-latest``) and ``usage.input_tokens``. Jev is **not** OpenAI-compatible
and generates no text: it is a router, never a model to route to (J-1).

Cost: the router price table (``prices-metis-router-2026-11-02``, Metis
pricing page, family ``typesafe``, model ``jev-latest``, checked by the owner
2026-11-02): input tokens at the input price, output at the output price
(0.0000). TypeSafe's own direct price is never used (owner decision). The
pre-call estimate counts twice the state's tokens, the questions' text
(one token per character) and a template allowance per question: an upper
bound (the first live call billed 699 tokens; now estimated at about
1,350), and the output row's price on ``assumed_output_tokens``. Without a
price row the estimate and the cost are "not computed"; the cascade then
refuses the call unless ``allow_unpriced``.

Shadow runs and labelling only (owner, 2026-11-02): SYNTHETIC or
owner-written text; a dataset-derived state is refused by the cascade before
this adapter is reached (``real_data_approved`` stays false). No internal
retries. The key is held as a ``SecretStr`` and sent only in the header.

Built by wiring.routers. Status: provisional.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import httpx
from pydantic import SecretStr

from metis_auto.contracts import (
    AvailabilityReason,
    BackendAvailability,
    BackendKind,
    Cost,
    CostBasis,
    CostEstimate,
    CostStatus,
    DecisionError,
    DecisionLatencySource,
    DecisionQuestionSet,
    DecisionResult,
    DecisionState,
    ErrorClass,
    Fidelity,
    Money,
    NotComputedReason,
    PolicyRef,
    PriceTable,
    TokenCount,
    TokenType,
    TokenUsage,
)
from metis_auto.ports import Clock

from .wire import StateFormat, WireError, parse_answers, render_questions, render_state

PATH = "/v1/systemone"
CHARS_PER_TOKEN_BOUND = 1
"""Characters per token for the pre-call estimate of the question text: one
token per character, a deliberate over-count. The first live call
(2026-11-03) billed 699 input tokens where characters / 2 had estimated 593,
because Jev wraps every question in its own template."""
TOKENS_PER_QUESTION = 32
"""Template tokens per question, on top of its text (an allowance)."""
STATE_FACTOR = 2
"""The cascade counts state tokens with an approximate tokenizer; doubled for
the bound."""


def _questions_chars(questions: DecisionQuestionSet) -> int:
    total = 0
    for q in render_questions(questions).values():
        total += len(str(q.get("instructions", "")))
        criteria = q.get("criteria")
        if isinstance(criteria, dict):
            total += sum(len(k) + len(str(v)) for k, v in criteria.items())
        elif isinstance(criteria, list):
            total += sum(len(str(v)) for v in criteria)
    return total


def price_amounts(
    prices: PriceTable | None, price_ref: str | None
) -> tuple[Decimal, Decimal, int, str] | None:
    """(input, output, per_tokens, currency) of ``price_ref``, or None when a
    row is missing or has no amount (the price is then unknown, never 0)."""
    if prices is None or price_ref is None:
        return None
    rows = {
        e.token_type: e
        for e in prices.entries
        if e.price_ref == price_ref and not e.min_input_tokens
    }
    inp, out = rows.get(TokenType.INPUT), rows.get(TokenType.OUTPUT)
    if inp is None or out is None or inp.amount is None or out.amount is None:
        return None
    if inp.per_tokens != out.per_tokens or inp.currency != out.currency:
        return None
    return inp.amount, out.amount, inp.per_tokens, inp.currency


class JevMetisBackend:
    def __init__(
        self,
        clock: Clock,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key: SecretStr | None,
        prices: PriceTable | None,
        price_ref: str | None,
        questions: DecisionQuestionSet | None = None,
        state_format: StateFormat = "text",
        assumed_output_tokens: int = 0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._clock = clock
        self._name = name
        self._url = base_url.rstrip("/") + PATH
        self._model = model
        self._key = api_key
        self._prices = prices
        self._price_ref = price_ref
        self._price = price_amounts(prices, price_ref)
        self._format: StateFormat = state_format
        self._assumed_output = assumed_output_tokens
        self._question_tokens = (
            -(-_questions_chars(questions) // CHARS_PER_TOKEN_BOUND)
            + TOKENS_PER_QUESTION * len(questions.questions)
            if questions is not None
            else 0
        )
        self._client = httpx.Client(transport=transport, trust_env=False)
        self.calls = 0
        self.last_reported_model: str | None = None

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(name=self._name, version=self._model[:64])

    @property
    def kind(self) -> Literal["hosted"]:
        return "hosted"

    def available(self) -> BackendAvailability:
        if self._key is None or not self._key.get_secret_value():
            return BackendAvailability.unavailable(AvailabilityReason.NOT_CONFIGURED)
        return BackendAvailability.ok()

    # ------------------------------------------------------------------ cost

    def _cost(self, input_tokens: int, output_tokens: int, basis: CostBasis) -> Cost:
        if self._price is None:
            return Cost(
                status=CostStatus.NOT_COMPUTED,
                basis=basis,
                reason=NotComputedReason.PRICE_UNKNOWN,
            )
        inp, out, per, currency = self._price
        amount = (Decimal(input_tokens) * inp + Decimal(output_tokens) * out) / per
        assert self._prices is not None and self._price_ref is not None
        return Cost(
            status=CostStatus.COMPUTED,
            basis=basis,
            amount=Money(amount=amount, currency=currency),
            price_table_version=self._prices.version,
            price_refs=(self._price_ref,),
            token_fidelity=Fidelity.PROVIDER_REPORTED
            if basis == CostBasis.ACTUAL
            else Fidelity.APPROXIMATION,
        )

    def estimate_cost(self, state_tokens: int) -> CostEstimate | None:
        tokens = STATE_FACTOR * state_tokens + self._question_tokens
        return CostEstimate(
            model_id=self._name,
            input_tokens=TokenCount(
                tokens=tokens,
                fidelity=Fidelity.APPROXIMATION,
                method="2*state_tokens+questions_chars+32/question",
            ),
            assumed_output_tokens=self._assumed_output,
            cost=self._cost(tokens, self._assumed_output, CostBasis.PRE_CALL_ESTIMATE),
        )

    # ---------------------------------------------------------------- decide

    def decide(
        self,
        state: DecisionState,
        questions: DecisionQuestionSet,
        *,
        timeout_ms: float,
    ) -> DecisionResult | DecisionError:
        if self._key is None:
            return DecisionError(
                backend=self.ref, error_class=ErrorClass.AUTH, latency_ms=0.0
            )
        self.calls += 1
        body = {
            "model": self._model,
            "state": render_state(state, self._format),
            "questions": render_questions(questions),
        }
        headers = {"Authorization": f"Bearer {self._key.get_secret_value()}"}
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
                self._url, json=body, headers=headers, timeout=timeout_ms / 1000.0
            )
        except httpx.TimeoutException:
            return error(ErrorClass.TIMEOUT)
        except httpx.ConnectError:
            return error(ErrorClass.CONNECTION)
        except httpx.HTTPError:
            return error(ErrorClass.UNKNOWN)
        elapsed = self._clock.monotonic_ms() - start
        status = response.status_code
        if status != 200:
            kind = {
                401: ErrorClass.AUTH,
                403: ErrorClass.AUTH,
                402: ErrorClass.AUTH,  # payment required: an account problem
                429: ErrorClass.RATE_LIMITED,
            }.get(status)
            if kind is None:
                kind = (
                    ErrorClass.UNAVAILABLE
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
        self.last_reported_model = revision[:64]
        raw_usage = payload.get("usage") or {}
        tokens_in = raw_usage.get("input_tokens")
        tokens_out = raw_usage.get("output_tokens", 0)
        usage = None
        cost = Cost(
            status=CostStatus.NOT_COMPUTED,
            basis=CostBasis.ACTUAL,
            reason=NotComputedReason.USAGE_UNKNOWN,
        )
        if isinstance(tokens_in, int) and tokens_in >= 0:
            out_tokens = tokens_out if isinstance(tokens_out, int) else 0
            usage = TokenUsage(
                model_id=self._name,
                input=TokenCount(
                    tokens=tokens_in,
                    fidelity=Fidelity.PROVIDER_REPORTED,
                    method="systemone.usage.input_tokens",
                ),
                output=TokenCount(
                    tokens=max(out_tokens, 0),
                    fidelity=Fidelity.PROVIDER_REPORTED,
                    method="systemone.usage.output_tokens",
                ),
            )
            cost = self._cost(tokens_in, max(out_tokens, 0), CostBasis.ACTUAL)
        return DecisionResult(
            answers=answers,
            backend=self.ref,
            backend_kind=BackendKind.HOSTED,
            model_revision=revision[:64],
            question_set_version=questions.version,
            latency_ms=elapsed,
            latency_source=DecisionLatencySource.MEASURED_REMOTE,
            usage=usage,
            cost=cost,
            calibrated=False,
        )

    def close(self) -> None:
        self._client.close()
