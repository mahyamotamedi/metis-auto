"""Fake model client: canned, clearly synthetic answers (providers.md §2).

Responsibility: let the pipeline run offline with no keys. Deterministic:
answer n is the same in every run. Reports no usage, so the pipeline counts
tokens itself (fidelity labelled). Implements ``ports.ModelClient``.
Built by: wiring. Called by: application.pipeline. Status: stable (test double).
"""

from __future__ import annotations

from metis_auto.contracts import (
    AnswerSource,
    FinishReason,
    ModelInvocation,
    ModelResponse,
    ModelResult,
)

SYNTHETIC_MARKER = "[SYNTHETIC]"


class FakeModelClient:
    def __init__(self, simulated_latency_ms: float = 0.0) -> None:
        self._latency = simulated_latency_ms
        self._calls = 0

    @property
    def source(self) -> AnswerSource:
        return AnswerSource.FAKE

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        self._calls += 1
        return ModelResponse(
            text=f"{SYNTHETIC_MARKER} fake answer {self._calls} from "
            f"{invocation.model_id}",
            finish_reason=FinishReason.COMPLETE,
            provider_latency_ms=self._latency,
            source=AnswerSource.FAKE,
        )
