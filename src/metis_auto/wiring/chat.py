"""Chat session over the real pipeline (CMP-20; Stage 7.5, brief §10 precursor).

Responsibility: hold one conversation's history (P-8: the caller sends it every
turn), build the pipeline from settings for a fixed target model, rebuild it
when the model changes (keeping the cache store, event sink, run ID, and so
the per-run cap), and report each turn as **content-free** numbers: served by,
model, provider-reported model, tokens with fidelity, cost, premium-baseline
estimate, savings decomposition (message and session), Metis overhead, and the
budget. No logic of its own: every number comes from the pipeline, the
accounting service, or the spend ledger.

Live or fake: ``live=True`` builds recording(live) through ``wiring.live``
(refused unless ``live_permission`` allows it); ``live=False`` uses the fake
client, offline. Used by ``scripts/chat.py`` and ``scripts/live_wrapper_check.py``;
the Demo UI will use it too.
Calls: settings, wiring.{from_settings, live}, application, domain.accounting,
adapters (fake client, memory store and sink).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.adapters.system import FileSpendLedger
from metis_auto.application.accounting import AccountingService
from metis_auto.application.pipeline import RequestPipeline
from metis_auto.contracts import (
    Component,
    Cost,
    CostStatus,
    FinalResponse,
    Request,
    ResponseStatus,
    Role,
    RunMode,
    SavingsDecomposition,
    ServedBy,
    SpanName,
    TokenCount,
    TokenUsage,
    Turn,
)
from metis_auto.contracts.events import AttemptFinished
from metis_auto.domain.accounting import sum_decompositions
from metis_auto.ports import ModelClient
from metis_auto.settings import LoadedSettings, load_settings

from .from_settings import (
    build_accounting_service,
    build_pipeline_from_settings,
    spend_ledger,
)
from .live import build_live_client, live_overrides
from .tokenizers import TokenizerSet, build_tokenizers

SettingsLoader = Callable[[Mapping[str, Any]], LoadedSettings]
ClientFactory = Callable[[LoadedSettings, str], ModelClient]


@dataclass(frozen=True)
class TurnReport:
    """One turn, content-free (amounts as decimal strings)."""

    status: str
    served_by: str
    model_id: str | None
    provider_model: str | None
    tokens: dict[str, str]
    cost: str
    cost_caveats: tuple[str, ...]
    premium_estimate: str
    premium_caveats: tuple[str, ...]
    decomposition: tuple[tuple[str, str], ...]
    session_decomposition: tuple[tuple[str, str], ...]
    overhead_ms: float | None
    overhead_cost: str
    budget: dict[str, str] = field(default_factory=dict)
    failure: str | None = None
    live_stopped: str | None = None


class ChatSession:
    def __init__(
        self,
        model_id: str,
        *,
        live: bool,
        instructions: str | None = None,
        allow_unknown_window: bool = False,
        single_attempt: bool = False,
        settings_loader: SettingsLoader | None = None,
        client_factory: ClientFactory | None = None,
        run_id: str | None = None,
    ) -> None:
        self._live = live
        self._instructions = instructions
        self._allow_unknown = allow_unknown_window
        self._single = single_attempt
        self._load = settings_loader or (lambda o: load_settings(overrides=o))
        self._client_factory = client_factory or (
            build_live_client if live else (lambda _loaded, _run: FakeModelClient())
        )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = run_id or f"chat-{stamp}-{uuid.uuid4().hex[:8]}"
        self.session_ref = f"sess-{uuid.uuid4().hex[:12]}"
        self.history: list[Turn] = []
        self._store = InMemoryCacheStore()
        self._sink = InMemoryEventSink()
        self._decompositions: list[SavingsDecomposition] = []
        self._tokenizers: TokenizerSet | None = None
        self.switch_model(model_id)

    # --- configuration ---

    def switch_model(self, model_id: str) -> None:
        """(Re)build the pipeline for ``model_id``; history, cache, and the
        run's ledger total are kept."""
        overrides = live_overrides(
            model_id,
            allow_unknown_window=self._allow_unknown,
            single_attempt=self._single,
        )
        if not self._live:
            overrides.pop("experiment.counterfactual_source")
        loaded = self._load(overrides)
        if model_id not in {e.model_id for e in loaded.reference.catalogue.entries}:
            raise ValueError(f"unknown model {model_id!r}")
        self._tokenizers = self._tokenizers or build_tokenizers(loaded)
        client = self._client_factory(loaded, self.run_id)
        self.pipeline: RequestPipeline = build_pipeline_from_settings(
            loaded,
            model_client=client,
            cache_store=self._store,
            sink=self._sink,
            run_id=self.run_id,
            run_mode=RunMode.LIVE if self._live else RunMode.SIMULATED,
            tokenizers=self._tokenizers,
        )
        self.loaded = loaded
        self.model_id = model_id
        self.accounting: AccountingService = build_accounting_service(
            loaded, self._tokenizers
        )
        baselines = loaded.reference.baselines
        premium = (
            next((b for b in baselines.baselines if b.name == "premium"), None)
            if baselines
            else None
        )
        self.premium_model_id = premium.model_id if premium else None
        self.ledger: FileSpendLedger | None = (
            spend_ledger(loaded, self.run_id) if loaded.settings.budget.capped else None
        )

    def reset(self) -> None:
        """Forget the history (the cache keeps its entries)."""
        self.history.clear()

    # --- one turn ---

    def request_for(self, message: str) -> Request:
        return Request(
            message=message,
            history=Component.present(tuple(self.history))
            if self.history
            else Component.absent(),
            instructions=Component.present(self._instructions)
            if self._instructions and self._instructions.strip()
            else Component.absent(),
            retrieved=Component.absent(),
            attachments=Component.absent(),
            structured_input=Component.absent(),
            session_ref=self.session_ref,
        )

    def ask(self, message: str) -> tuple[FinalResponse, TurnReport]:
        request = self.request_for(message)
        response = self.pipeline.handle(request)
        if response.status == ResponseStatus.OK and response.answer is not None:
            self.history.append(Turn(role=Role.USER, text=message))
            self.history.append(Turn(role=Role.ASSISTANT, text=response.answer))
        return response, self._report(request, response)

    # --- reporting (content-free) ---

    def _report(self, request: Request, response: FinalResponse) -> TurnReport:
        meta = response.metadata
        premium, premium_caveats = "n/a", ()
        decomposition: tuple[tuple[str, str], ...] = ()
        answered = response.answer is not None and meta.final_model_id is not None
        if answered and self.premium_model_id is not None:
            assert response.answer is not None
            estimate = self.accounting.premium_estimate(
                request, response.answer, self.premium_model_id
            )
            premium = _cost(estimate.cost)
            premium_caveats = tuple(c.value for c in estimate.cost.caveats)
            parts = self.accounting.decompose(
                request, response, premium_model_id=self.premium_model_id
            )
            self._decompositions.append(parts)
            decomposition = _terms(parts)
        session = (
            _terms(sum_decompositions(self._decompositions))
            if self._decompositions
            else ()
        )
        return TurnReport(
            status=response.status.value,
            served_by=meta.served_by.value,
            model_id=meta.final_model_id,
            provider_model=self._provider_model(meta.request_id, meta.attempt_ids),
            tokens=_tokens(meta.answer_usage)
            if meta.served_by == ServedBy.MODEL
            else {},
            cost=_cost(meta.total_cost),
            cost_caveats=tuple(c.value for c in meta.total_cost.caveats),
            premium_estimate=premium,
            premium_caveats=premium_caveats,
            decomposition=decomposition,
            session_decomposition=session,
            overhead_ms=_overhead_ms(response),
            overhead_cost=_cost(meta.overhead_cost),
            budget=self.budget(),
            failure=meta.failure.value if meta.failure else None,
            live_stopped=self.pipeline.live_stopped,
        )

    def budget(self) -> dict[str, str]:
        if self.ledger is None:
            return {}
        status = self.ledger.status()
        return {
            "lifetime_spent": str(status.lifetime_spent),
            "lifetime_cap": str(status.lifetime_cap),
            "lifetime_used": f"{status.lifetime_fraction:.2%}",
            "run_spent": str(status.run_spent),
            "run_cap": str(status.run_cap),
            "currency": status.currency,
        }

    def _provider_model(
        self, request_id: str, attempt_ids: tuple[str, ...]
    ) -> str | None:
        if not attempt_ids:
            return None
        for event in reversed(self._sink.events):
            if (
                event.request_id == request_id
                and event.attempt_id == attempt_ids[-1]
                and isinstance(event.payload, AttemptFinished)
            ):
                return event.payload.provider_model_version
        return None


def _count(count: TokenCount | None) -> str:
    if count is None:
        return "not reported"
    return f"{count.tokens} ({count.fidelity.value})"


def _tokens(usage: TokenUsage | None) -> dict[str, str]:
    if usage is None:
        return {}
    return {
        "input": _count(usage.input),
        "output": _count(usage.output),
        "cached_input": _count(usage.cached_input),
        "reasoning": _count(usage.reasoning),
        "template_overhead": _count(usage.template_overhead)
        if usage.template_overhead
        else "-",
    }


def _money(amount: Decimal, currency: str) -> str:
    return f"{amount:.6f} {currency}"


def _cost(cost: Cost) -> str:
    if cost.status == CostStatus.COMPUTED and cost.amount is not None:
        return _money(cost.amount.amount, cost.amount.currency)
    return f"not computed ({cost.reason.value if cost.reason else 'unknown'})"


def _terms(parts: SavingsDecomposition) -> tuple[tuple[str, str], ...]:
    out = []
    for term in parts.terms:
        if term.amount is not None:
            value = _money(term.amount.amount, term.amount.currency)
        else:
            value = f"not computed ({term.reason.value if term.reason else '?'})"
        out.append((term.term.value, value))
    return tuple(out)


def _overhead_ms(response: FinalResponse) -> float | None:
    """Metis's own time: the whole request minus model calls."""
    spans = response.metadata.spans
    total = next((s.duration_ms for s in spans if s.span == SpanName.REQUEST), None)
    if total is None:
        return None
    calls = sum(s.duration_ms for s in spans if s.span == SpanName.MODEL_CALL)
    return max(0.0, total - calls)


def format_report(report: TurnReport) -> str:
    """Plain-text rendering of a turn report for the CLI."""
    lines = [
        f"served_by: {report.served_by}   model: {report.model_id}   "
        f"provider-reported model: {report.provider_model or '-'}",
    ]
    if report.failure:
        lines.append(f"failure: {report.failure}")
    if report.tokens:
        lines.append(
            "tokens: " + ", ".join(f"{k} {v}" for k, v in report.tokens.items())
        )
    lines.append(
        f"cost: {report.cost}"
        + (f"  [{', '.join(report.cost_caveats)}]" if report.cost_caveats else "")
    )
    lines.append(
        f"premium-baseline estimate: {report.premium_estimate}"
        + (f"  [{', '.join(report.premium_caveats)}]" if report.premium_caveats else "")
    )
    if report.decomposition:
        lines.append("savings (this message | session):")
        session = dict(report.session_decomposition)
        for term, value in report.decomposition:
            lines.append(f"  {term:<22} {value:>24} | {session.get(term, '-')}")
    overhead = f"{report.overhead_ms:.2f} ms" if report.overhead_ms is not None else "-"
    lines.append(f"overhead: {overhead}, cost {report.overhead_cost}")
    if report.budget:
        b = report.budget
        lines.append(
            f"budget: {b['lifetime_spent']} of {b['lifetime_cap']} {b['currency']} "
            f"used ({b['lifetime_used']}); this run {b['run_spent']} of "
            f"{b['run_cap']}"
        )
    if report.live_stopped:
        lines.append(f"LIVE CALLS STOPPED: {report.live_stopped}")
    return "\n".join(lines)
