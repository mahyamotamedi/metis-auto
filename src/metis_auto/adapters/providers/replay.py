"""Counterfactual-source clients without new calls (ADR-0014;
evaluation.md §4): replay (``logged_match`` / ``recorded``) and ``proxy``.

``ProxyModelClient``: a proxy run has no answers by definition.

``ReplayModelClient`` (Stage 8), built with one of two constructors:
- ``logged(references, label_models)``: the logged answer of the case, **only**
  when the invocation's target is the catalogue model its label maps to
  (``label_models``, from the label-mapping reference file). Otherwise
  ``ModelNoAnswer``: ``label_unmapped`` (no answer of the case has a mapped
  label), ``target_not_logged_model`` (mapped, but to another model), or
  ``not_recorded`` (the case has no answer or no case ID). A logged answer
  carries no usage (the pipeline counts it, A-40) and is assumed complete.
- ``recorded(directory)``: answers recorded from live calls by
  ``RecordingModelClient`` (``data/recorded/*.jsonl``). The lookup key is the
  target model plus a digest of the exact input (ordered parts and
  attachments), computed in memory when the files are read and never
  written. That makes the lookup independent of the fingerprint key (A-44),
  so records from any run are reusable; the case ID is not needed (ADR-0014's
  "case × model × composition" is the same input). The latest recorded
  complete response wins, else the latest response; errors are not
  replayed. Reported usage and latency come back with ``source = recorded``.

Implements ``ports.ModelClient``. Built by: wiring for evaluation runs.
Privacy: references and recordings are content; they stay in memory.
Status: implemented (Stage 8).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import TypeAdapter

from metis_auto.contracts import (
    AnswerSource,
    FinishReason,
    Identifier,
    InputPart,
    ModelInvocation,
    ModelNoAnswer,
    ModelResponse,
    ModelResult,
    NoAnswerReason,
)

from .recording import read_records

_RESULT = TypeAdapter(ModelResult)
LoggedAnswer = tuple[str | None, str]
"""(logged model label or None when unknown, answer text)."""


class ProxyModelClient:
    """No answers at all: cost and overhead estimates only."""

    @property
    def source(self) -> AnswerSource:
        return AnswerSource.NONE

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        return ModelNoAnswer(
            reason=NoAnswerReason.PROXY_SOURCE, source=AnswerSource.NONE
        )


def input_digest(parts: Sequence[InputPart], attachments: Sequence[object]) -> str:
    """In-memory lookup key of one model input (never persisted)."""
    payload = {
        "parts": [p.model_dump(mode="json") for p in parts],
        "attachments": [
            a.model_dump(mode="json") if hasattr(a, "model_dump") else a
            for a in attachments
        ],
    }
    text = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ReplayModelClient:
    def __init__(
        self,
        source: AnswerSource,
        *,
        references: Mapping[Identifier, Sequence[LoggedAnswer]] | None = None,
        label_models: Mapping[str, str] | None = None,
        recorded: Mapping[tuple[str, str], ModelResponse] | None = None,
    ) -> None:
        if source not in (AnswerSource.LOGGED, AnswerSource.RECORDED):
            raise ValueError("replay sources are logged or recorded")
        self._source = source
        self._references = dict(references or {})
        self._labels = dict(label_models or {})
        self._recorded = dict(recorded or {})

    @classmethod
    def logged(
        cls,
        references: Mapping[Identifier, Sequence[LoggedAnswer]],
        label_models: Mapping[str, str],
    ) -> ReplayModelClient:
        return cls(
            AnswerSource.LOGGED, references=references, label_models=label_models
        )

    @classmethod
    def recorded_from(cls, directory: Path) -> ReplayModelClient:
        """Index every ``*.jsonl`` recording under ``directory`` (sorted by
        name, then line order: later records win)."""
        index: dict[tuple[str, str], ModelResponse] = {}
        for path in sorted(Path(directory).glob("*.jsonl")):
            for record in read_records(path):
                result = _RESULT.validate_python(record["result"])
                if not isinstance(result, ModelResponse):
                    continue
                inv = ModelInvocation.model_validate(record["invocation"])
                key = (inv.model_id, input_digest(inv.parts, inv.attachments))
                old = index.get(key)
                complete = result.finish_reason == FinishReason.COMPLETE
                if (
                    old is None
                    or complete
                    or old.finish_reason != FinishReason.COMPLETE
                ):
                    index[key] = result
        return cls(AnswerSource.RECORDED, recorded=index)

    @property
    def source(self) -> AnswerSource:
        return self._source

    @property
    def size(self) -> int:
        """Cases (logged) or recorded inputs (recorded) available."""
        return (
            len(self._references)
            if self._source == AnswerSource.LOGGED
            else len(self._recorded)
        )

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        if self._source == AnswerSource.RECORDED:
            return self._from_recordings(invocation)
        return self._from_log(invocation)

    def _no(self, reason: NoAnswerReason) -> ModelNoAnswer:
        return ModelNoAnswer(reason=reason, source=self._source)

    def _from_recordings(self, invocation: ModelInvocation) -> ModelResult:
        key = (
            invocation.model_id,
            input_digest(invocation.parts, invocation.attachments),
        )
        found = self._recorded.get(key)
        if found is None:
            return self._no(NoAnswerReason.NOT_RECORDED)
        return found.model_copy(update={"source": AnswerSource.RECORDED})

    def _from_log(self, invocation: ModelInvocation) -> ModelResult:
        answers = self._references.get(invocation.case_id or "", ())
        if not answers:
            return self._no(NoAnswerReason.NOT_RECORDED)
        mapped = [(self._labels.get(label or ""), text) for label, text in answers]
        for model_id, text in mapped:
            if model_id == invocation.model_id:
                return ModelResponse(
                    text=text,
                    finish_reason=FinishReason.COMPLETE,
                    source=AnswerSource.LOGGED,
                )
        if all(model_id is None for model_id, _ in mapped):
            return self._no(NoAnswerReason.LABEL_UNMAPPED)
        return self._no(NoAnswerReason.TARGET_NOT_LOGGED_MODEL)
