"""Recording decorator: writes live results to ``data/recorded/`` for reuse
by the replay client (ADR-0014; brief §1 "pay once, replay free").

Responsibility: pass each invocation to the inner client and append the
invocation and its result to a JSON Lines file. Implements
``ports.ModelClient`` around another client, with the inner client's source.
Built by: ``wiring.live`` around the live client. Called by:
application.pipeline.

Records hold **content** (input parts and answers), so the directory is
git-ignored and inside the privacy boundary (deployment_and_data.md); only the
owner's own or synthetic messages are sent live (ADR-0018). Only ``live``
results are written. A failed write is logged (without content) and never
raised: the call is already paid, and the pipeline must still charge it.

One line per call: ``{"v": 1, "time": ISO-UTC, "run_id", "client_source",
"invocation": …, "result": …}`` (the contracts' JSON form). ``client_source`` is
the recording client's source (always ``live``, since only live results are
written); the replay loader uses it to refuse any record not made live.
Status: writing done (Stage 7.5). TODO(Stage 8): the replay client's lookup by
case ID × model × composition fingerprint over these files.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from metis_auto.contracts import AnswerSource, ModelInvocation, ModelResult
from metis_auto.ports import ModelClient

RECORD_FORMAT = 1
log = logging.getLogger(__name__)
_RESULT = TypeAdapter(ModelResult)


class RecordingModelClient:
    def __init__(
        self,
        inner: ModelClient,
        path: Path | None = None,
        *,
        run_id: str = "",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """``path`` is the JSON Lines file to append to; None records nothing
        (a pass-through, e.g. for non-live sources)."""
        self._inner = inner
        self._path = Path(path) if path is not None else None
        self._run_id = run_id
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def source(self) -> AnswerSource:
        return self._inner.source

    @property
    def path(self) -> Path | None:
        return self._path

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        result = self._inner.invoke(invocation)
        if self._path is not None and self.source == AnswerSource.LIVE:
            self._write(invocation, result)
        return result

    def _write(self, invocation: ModelInvocation, result: ModelResult) -> None:
        assert self._path is not None
        record = {
            "v": RECORD_FORMAT,
            "time": self._now().isoformat(),
            "run_id": self._run_id,
            "client_source": self.source.value,
            "invocation": invocation.model_dump(mode="json"),
            "result": _RESULT.dump_python(result, mode="json"),
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.error(
                "recording failed for attempt %s (%s); the answer is not saved",
                invocation.attempt_id,
                type(exc).__name__,
            )


def read_records(path: Path) -> list[dict]:
    """The records in a recording file (for the replay client and scripts)."""
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
