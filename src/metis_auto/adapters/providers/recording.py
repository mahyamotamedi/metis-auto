"""Recording decorator: writes live results to ``data/recorded/`` for reuse
by the replay client (ADR-0014). Responses are content: the directory is
gitignored and inside the privacy boundary.

Status: skeleton. TODO(Stage 8, with the first live adapter): storage format
keyed by case ID × model × composition fingerprint; written only for live
sources, and only under the spend cap.
"""

from __future__ import annotations

from metis_auto.contracts import AnswerSource, ModelInvocation, ModelResult
from metis_auto.ports import ModelClient


class RecordingModelClient:
    def __init__(self, inner: ModelClient) -> None:
        self._inner = inner

    @property
    def source(self) -> AnswerSource:
        return self._inner.source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        raise NotImplementedError("TODO(Stage 8): record live results")
