"""Fault- and quality-injecting decorators (FR-FAIL-06; providers.md §2).

Responsibility: script errors (``ModelError`` values) or degraded answers per
call, so retry, failover, escalation, and detectors are testable offline.
Implements ``ports.ModelClient`` around another client. Built by: tests and
wiring. Status: stable (test doubles). TODO(Stage 8): wrong-language and
refusal answers for detector experiments; scripted delays via the fake clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from metis_auto.contracts import (
    AnswerSource,
    FinishReason,
    ModelError,
    ModelInvocation,
    ModelResponse,
    ModelResult,
)
from metis_auto.ports import ModelClient


class FaultInjectingClient:
    """Call n returns ``script[n]`` if it is an error, else the inner result."""

    def __init__(self, inner: ModelClient, script: Sequence[ModelError | None]) -> None:
        self._inner = inner
        self._script = list(script)
        self._calls = 0

    @property
    def source(self) -> AnswerSource:
        return self._inner.source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        n = self._calls
        self._calls += 1
        fault = self._script[n] if n < len(self._script) else None
        return fault if fault is not None else self._inner.invoke(invocation)


class Quality(StrEnum):
    EMPTY = "empty"
    TRUNCATED = "truncated"


class QualityInjectingClient:
    """Call n degrades the inner response as ``script[n]`` says."""

    def __init__(self, inner: ModelClient, script: Sequence[Quality | None]) -> None:
        self._inner = inner
        self._script = list(script)
        self._calls = 0

    @property
    def source(self) -> AnswerSource:
        return self._inner.source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        n = self._calls
        self._calls += 1
        result = self._inner.invoke(invocation)
        quality = self._script[n] if n < len(self._script) else None
        if quality is None or not isinstance(result, ModelResponse):
            return result
        if quality == Quality.EMPTY:
            return result.model_copy(update={"text": ""})
        return result.model_copy(update={"finish_reason": FinishReason.LENGTH})
