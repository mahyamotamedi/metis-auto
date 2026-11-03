"""``BaseRouter``: the swap point for System-One decision backends
(ADR-0047).

A decision backend answers typed questions about a minimised request state
(``DecisionState``) and returns typed, probabilistic answers. It never picks a
model: a pure domain policy maps the answers to a tier and a model.

``BaseRouter`` plays the role of an abstract base class, written as a
runtime-checkable ``Protocol`` like every other port in this package
(repository convention). Implementations: ``adapters.routers`` (fake, Jev via
Metis, LLM-as-System-One, THX-01 in-process, a local ``/v1/systemone`` server)
and their recording and replay decorators; chosen by ``wiring.routers``.

Rules every implementation follows:
- ``decide`` **never raises** for expected failures (timeout, transport,
  provider error, unparseable or invalid answer): it returns a
  ``DecisionError``. An exception means a programming or configuration error.
- No internal retries on the request path; the cascade decides what to try next.
- Hosted backends are called only through the application's spend guard and
  never with a dataset-derived state unless the run is approved.

Called by: application.routing (the router cascade). Traces: FR-FEAT-02,
FR-ROUTE-03/04, FR-FAIL-04, QA-REPL, ADR-0003, ADR-0018.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from metis_auto.contracts import (
    BackendAvailability,
    CostEstimate,
    DecisionError,
    DecisionQuestionSet,
    DecisionResult,
    DecisionState,
    PolicyRef,
)

BackendKindName = Literal["hosted", "local"]


@runtime_checkable
class BaseRouter(Protocol):
    """One System-One decision backend. Synchronous (ADR-0010)."""

    @property
    def ref(self) -> PolicyRef:
        """Backend name and version (e.g. ``thx01`` @ pinned revision)."""
        ...

    @property
    def kind(self) -> BackendKindName:
        """``hosted`` (network, priced, spend-guarded) or ``local``."""
        ...

    def available(self) -> BackendAvailability:
        """Whether the backend can be called now (missing extra or weights, sha
        mismatch, server unreachable, disabled, not configured). Cheap."""
        ...

    def decide(
        self,
        state: DecisionState,
        questions: DecisionQuestionSet,
        *,
        timeout_ms: float,
    ) -> DecisionResult | DecisionError:
        """Answer every question about ``state`` within ``timeout_ms``.

        Returns a ``DecisionError`` for expected failures; never raises for
        them. An in-process backend that cannot be pre-empted measures its
        real duration and reports a timeout when it overran.
        """
        ...

    def estimate_cost(self, state_tokens: int) -> CostEstimate | None:
        """Pre-call cost estimate for the spend guard (hosted backends). Local
        backends return None: they cost nothing billable."""
        ...
