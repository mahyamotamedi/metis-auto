"""Per-model dispatching client (CMP-10; ADR-0043).

Responsibility: present several adapters as one ``ModelClient`` by sending
each invocation to the client configured for its catalogue model (e.g.
OpenAI-compatible families to ``openai_compat``, Gemini to
``gemini_native``). No decision of its own: the map comes from wiring. All
clients share one answer source, so the pipeline's spend guard sees one
``live`` client. Implements ``ports.ModelClient``.
Built by: ``wiring.live`` (only when more than one adapter is configured).
Called by: application.pipeline, through the recording decorator.
Status: provisional.
"""

from __future__ import annotations

from collections.abc import Mapping

from metis_auto.contracts import AnswerSource, ModelInvocation, ModelResult
from metis_auto.ports import ModelClient


class ModelDispatchClient:
    def __init__(self, clients: Mapping[str, ModelClient]) -> None:
        """``clients``: catalogue model ID → the client that answers it."""
        if not clients:
            raise ValueError("a dispatching client needs at least one client")
        sources = {c.source for c in clients.values()}
        if len(sources) != 1:
            raise ValueError("dispatched clients must share one source")
        self._clients = dict(clients)
        (self._source,) = sources

    @property
    def source(self) -> AnswerSource:
        return self._source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        client = self._clients.get(invocation.model_id)
        if client is None:
            raise ValueError(
                f"model {invocation.model_id!r}: no client is configured for it"
            )
        return client.invoke(invocation)
