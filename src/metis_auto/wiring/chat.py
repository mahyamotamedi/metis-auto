"""Chat session over the real pipeline (CMP-20; Stage 7.5; Demo milestone A).

Responsibility: hold one bot's conversation (P-8: the caller sends the
history every turn, and records who produced each answer in
``Turn.producer``), build the pipeline from settings for the chosen routing
mode and demo toggles, rebuild it when a toggle changes (keeping the cache
store, the fingerprint key, the event sink, the run ID, and so the per-run
cap), and report each turn as **content-free** numbers: the routing decision
and its reason (anchored, re-routed, greeting, escalated), served by, model,
provider-reported model, tokens with fidelity, cost, premium-baseline
estimate, the savings decomposition (routing, compression, cache, provider
cache; message and session), compression, overhead, and the budget. No
logic of its own: every number comes from the pipeline, the accounting
service, or the spend ledger.

Routing modes: ``sticky_v1`` and ``per_request`` (the ``sticky`` policy) and
``fixed`` (one model, the Stage 7.5 behaviour). Demo toggles (ADR-0023):
compression (LLMLingua-2, or the labelled fake), bot-level cache scope, the
demo seed (logged answers, local only), DeepSeek thinking. ``new_user`` starts
another user of the same bot (new session and user references, empty
history, same instructions and cache).

Live or fake: ``live=True`` builds recording(live) through ``wiring.live``
(refused unless ``live_permission`` allows it); ``live=False`` uses the fake
client, offline. Used by ``scripts/chat.py`` and ``scripts/live_wrapper_check.py``;
and the Demo B UI
(``scripts/demo_ui.py`` through ``wiring.demo_ui``).
Calls: settings, wiring.{from_settings, live, compression, demo}, application,
domain.accounting, adapters (fake client and compressor, memory store and
sink).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from metis_auto.adapters.compressors import FakeCompressor
from metis_auto.adapters.providers import (
    FakeModelClient,
    Quality,
    QualityInjectingClient,
)
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.adapters.system import FileSpendLedger
from metis_auto.application.accounting import AccountingService
from metis_auto.application.pipeline import (
    SEED_PRODUCER,
    RequestPipeline,
    RequestTrace,
)
from metis_auto.contracts import (
    CACHE_PRODUCER,
    Component,
    Cost,
    CostStatus,
    FinalResponse,
    LookupOutcome,
    Request,
    ResponseStatus,
    RetrievedContext,
    RetrievedItem,
    Role,
    RunMode,
    SavingsDecomposition,
    ServedBy,
    SpanName,
    TokenCount,
    TokenUsage,
    Turn,
)
from metis_auto.contracts.events import AttemptFinished, FeaturesExtracted
from metis_auto.domain.accounting import sum_decompositions
from metis_auto.ports import ModelClient, TextCompressor
from metis_auto.settings import LoadedSettings, load_settings

from .from_settings import (
    build_accounting_service,
    build_pipeline_from_settings,
    fingerprint_key,
    spend_ledger,
)
from .live import build_live_client, live_overrides
from .tokenizers import TokenizerSet, build_tokenizers

SettingsLoader = Callable[[Mapping[str, Any]], LoadedSettings]
ClientFactory = Callable[[LoadedSettings, str], ModelClient]
CompressorFactory = Callable[[LoadedSettings, str], TextCompressor]

DEEPSEEK = "deepseek-v4-flash"


class RoutingMode(StrEnum):
    STICKY_V1 = "sticky_v1"
    PER_REQUEST = "per_request"
    FIXED = "fixed"


class CompressionMode(StrEnum):
    OFF = "off"
    LLMLINGUA2 = "llmlingua2"
    """EXPERIMENTAL: the real compressor (extra ``compress`` + model files)."""
    FAKE = "fake"
    """A SYNTHETIC word-dropping double: shows the mechanics, measures nothing."""


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
    routing: dict[str, str] = field(default_factory=dict)
    features: dict[str, str] = field(default_factory=dict)
    cache: tuple[str, ...] = ()
    compression: dict[str, str] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=dict)
    parts: SavingsDecomposition | None = None
    """The message's decomposition as numbers (content-free; for the UI)."""
    session_parts: SavingsDecomposition | None = None
    """The session's summed decomposition as numbers."""


class ChatSession:
    def __init__(
        self,
        model_id: str | None = None,
        *,
        live: bool,
        instructions: str | None = None,
        retrieved: Sequence[str] = (),
        allow_unknown_window: bool = False,
        single_attempt: bool = False,
        settings_loader: SettingsLoader | None = None,
        client_factory: ClientFactory | None = None,
        run_id: str | None = None,
        routing: RoutingMode | None = None,
        compression: CompressionMode = CompressionMode.OFF,
        bot_cache: bool = False,
        seed: bool = False,
        deepseek_thinking: bool = True,
        compressor_factory: CompressorFactory | None = None,
        seed_path: Path | None = None,
        seed_size: int = 5,
    ) -> None:
        """``model_id`` without ``routing`` means fixed routing (Stage 7.5);
        no model means sticky routing v1."""
        self._live = live
        self.instructions = instructions
        self.retrieved = tuple(r for r in retrieved if r.strip())
        self._allow_unknown = allow_unknown_window
        self._single = single_attempt
        self._load = settings_loader or (lambda o: load_settings(overrides=o))
        self._client_factory = client_factory or (
            build_live_client if live else (lambda _loaded, _run: FakeModelClient())
        )
        self._compressor_factory = compressor_factory
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = run_id or f"chat-{stamp}-{uuid.uuid4().hex[:8]}"
        self.users = 0
        self._new_refs()
        self.history: list[Turn] = []
        self._store = InMemoryCacheStore()
        self._sink = InMemoryEventSink()
        self._decompositions: list[SavingsDecomposition] = []
        self._tokenizers: TokenizerSet | None = None
        self._fp_key: bytes | None = None
        self._compressors: dict[CompressionMode, TextCompressor] = {}
        self._degrade_next = False
        self.seed_path = seed_path
        self.seed_size = seed_size
        self.seeded: tuple[str, ...] | None = None
        """Seeded questions (sample content: show locally only)."""
        self.routing = routing or (
            RoutingMode.FIXED if model_id is not None else RoutingMode.STICKY_V1
        )
        self.model_id = model_id or "gpt-4o-mini"
        self.compression = compression
        self.bot_cache = bot_cache
        self.seed = seed
        self.deepseek_thinking = deepseek_thinking
        self._rebuild()

    # --- configuration ---

    def _overrides(self) -> dict[str, Any]:
        fixed = self.routing == RoutingMode.FIXED
        overrides = live_overrides(
            self.model_id if fixed else None,
            allow_unknown_window=self._allow_unknown,
            single_attempt=self._single,
        )
        if not self._live:
            overrides.pop("experiment.counterfactual_source")
        if not fixed:
            overrides["pipeline.routing.policy"] = "sticky"
            overrides["pipeline.routing.sticky.mode"] = self.routing.value
        if self.compression != CompressionMode.OFF:
            overrides["pipeline.context.compression.enabled"] = True
        if self.bot_cache:
            overrides["pipeline.cache.scope_rule"] = "demo_bot_level"
        if self.seed:
            overrides["pipeline.cache.demo_seed.enabled"] = True
        if not self.deepseek_thinking:
            overrides[f"model_options.{DEEPSEEK}.thinking"] = "disabled"
        return overrides

    def _rebuild(self) -> None:
        """(Re)build the pipeline; history, cache, fingerprint key, and the
        run's ledger total are kept."""
        loaded = self._load(self._overrides())
        catalogue = {e.model_id for e in loaded.reference.catalogue.entries}
        if self.routing == RoutingMode.FIXED and self.model_id not in catalogue:
            raise ValueError(f"unknown model {self.model_id!r}")
        self._tokenizers = self._tokenizers or build_tokenizers(loaded)
        self._fp_key = self._fp_key or fingerprint_key(loaded)
        client = self._client_factory(loaded, self.run_id)
        if self._degrade_next:
            client = QualityInjectingClient(client, [Quality.TRUNCATED])
        self.pipeline: RequestPipeline = build_pipeline_from_settings(
            loaded,
            model_client=client,
            cache_store=self._store,
            sink=self._sink,
            run_id=self.run_id,
            run_mode=RunMode.LIVE if self._live else RunMode.SIMULATED,
            tokenizers=self._tokenizers,
            compressor=self._compressor(loaded),
            fingerprint_key_bytes=self._fp_key,
        )
        self.loaded = loaded
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
        if self.seed and self.seeded is None:
            from .demo import seed_from_sample

            self.seeded = seed_from_sample(
                loaded, self.pipeline, limit=self.seed_size, path=self.seed_path
            )

    def _compressor(self, loaded: LoadedSettings) -> TextCompressor | None:
        mode = self.compression
        if mode == CompressionMode.OFF:
            return None
        if mode not in self._compressors:
            ref = loaded.settings.pipeline.get("context", {}).get("compression", {})
            name = ref.get("compressor", "llmlingua-2-xlm-roberta-large-meetingbank")
            if mode == CompressionMode.FAKE:
                self._compressors[mode] = FakeCompressor()
            elif self._compressor_factory is not None:
                self._compressors[mode] = self._compressor_factory(loaded, name)
            else:
                from .compression import build_compressor

                self._compressors[mode] = build_compressor(loaded, name)
        return self._compressors[mode]

    def _set(self, **changes: Any) -> None:
        """Apply toggles and rebuild; on failure restore the previous ones."""
        previous = {k: getattr(self, k) for k in changes}
        for k, v in changes.items():
            setattr(self, k, v)
        try:
            self._rebuild()
        except Exception:
            for k, v in previous.items():
                setattr(self, k, v)
            self._rebuild()
            raise

    def switch_model(self, model_id: str) -> None:
        """Fixed routing to ``model_id``."""
        self._set(routing=RoutingMode.FIXED, model_id=model_id)

    def set_routing(self, mode: RoutingMode) -> None:
        self._set(routing=mode)

    def set_compression(self, mode: CompressionMode) -> None:
        self._set(compression=mode)

    def set_bot_cache(self, on: bool) -> None:
        self._set(bot_cache=on)

    def set_seed(self, on: bool) -> None:
        self._set(seed=on)

    def set_deepseek_thinking(self, on: bool) -> None:
        self._set(deepseek_thinking=on)

    def set_instructions(self, text: str | None) -> None:
        self.instructions = text

    def set_retrieved(self, documents: Sequence[str]) -> None:
        """Replace the retrieved context (one document per item; blanks dropped)."""
        self.retrieved = tuple(d for d in documents if d.strip())

    @property
    def live(self) -> bool:
        return self._live

    def degrade_next(self) -> None:
        """Fake mode: the next model answer comes back truncated, so the
        truncation detector fires and the attempt loop escalates (offline
        demo of escalation)."""
        if self._live:
            raise ValueError("degrade_next is for the fake mode only")
        self._degrade_next = True
        self._rebuild()

    def reset(self) -> None:
        """Forget the history (the cache keeps its entries)."""
        self.history.clear()

    def _new_refs(self) -> None:
        self.users += 1
        self.session_ref = f"sess-{uuid.uuid4().hex[:12]}"
        self.user_ref = f"user-{uuid.uuid4().hex[:12]}"

    def new_user(self) -> None:
        """Another user of the same bot: new session and user references,
        empty history; instructions, retrieved context, and cache kept."""
        self._new_refs()
        self.history.clear()

    # --- one turn ---

    def request_for(self, message: str) -> Request:
        retrieved = (
            Component.present(
                RetrievedContext(
                    items=tuple(RetrievedItem(text=t) for t in self.retrieved)
                )
            )
            if self.retrieved
            else Component.absent()
        )
        return Request(
            message=message,
            history=Component.present(tuple(self.history))
            if self.history
            else Component.absent(),
            instructions=Component.present(self.instructions)
            if self.instructions and self.instructions.strip()
            else Component.absent(),
            retrieved=retrieved,
            attachments=Component.absent(),
            structured_input=Component.absent(),
            session_ref=self.session_ref,
            user_ref=self.user_ref,
        )

    def ask(self, message: str) -> tuple[FinalResponse, TurnReport]:
        request = self.request_for(message)
        response, trace = self.pipeline.handle_traced(request)
        self.last_trace: RequestTrace | None = trace
        """In memory only: holds the request actually sent (content)."""
        if self._degrade_next:
            self._degrade_next = False
            self._rebuild()
        if response.status == ResponseStatus.OK and response.answer is not None:
            meta = response.metadata
            producer = (
                CACHE_PRODUCER
                if meta.served_by == ServedBy.CACHE
                else meta.final_model_id
            )
            self.history.append(
                Turn(role=Role.USER, text=message, producer=Component.absent())
            )
            self.history.append(
                Turn(
                    role=Role.ASSISTANT,
                    text=response.answer,
                    producer=Component.present(producer)
                    if producer
                    else Component.unknown(),
                )
            )
        return response, self._report(request, response, trace)

    # --- reporting (content-free) ---

    def _report(
        self, request: Request, response: FinalResponse, trace: RequestTrace
    ) -> TurnReport:
        meta = response.metadata
        premium, premium_caveats = "n/a", ()
        decomposition: tuple[tuple[str, str], ...] = ()
        hit = meta.served_by == ServedBy.CACHE
        chosen = (
            trace.decision.target_model_id
            if hit and trace.decision is not None
            else meta.final_model_id
        )
        answered = response.answer is not None and chosen is not None
        if answered and self.premium_model_id is not None:
            assert response.answer is not None
            estimate = self.accounting.premium_estimate(
                request, response.answer, self.premium_model_id
            )
            premium = _cost(estimate.cost)
            premium_caveats = tuple(c.value for c in estimate.cost.caveats)
            parts = self.accounting.decompose(
                request,
                response,
                premium_model_id=self.premium_model_id,
                chosen_model_id=chosen,
                sent_request=None if hit else trace.sent_request,
            )
            self._decompositions.append(parts)
            decomposition = _terms(parts)
        parts_obj = self._decompositions[-1] if decomposition else None
        session_obj = (
            sum_decompositions(self._decompositions) if self._decompositions else None
        )
        session = _terms(session_obj) if session_obj is not None else ()
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
            routing=self._routing(response, trace),
            features=self._features(meta.request_id),
            cache=_cache(trace),
            compression=_compression(response, trace),
            settings=self.settings(),
            parts=parts_obj,
            session_parts=session_obj,
        )

    def settings(self) -> dict[str, str]:
        return {
            "routing": self.routing.value
            + (f" ({self.model_id})" if self.routing == RoutingMode.FIXED else ""),
            "compression": self.compression.value,
            "cache_scope": "bot-level [DEMO]" if self.bot_cache else "session",
            "seed": "on [DEMO]" if self.seed else "off",
            "deepseek_thinking": "on (default)" if self.deepseek_thinking else "off",
            "user": str(self.users),
        }

    def _routing(self, response: FinalResponse, trace: RequestTrace) -> dict[str, str]:
        decision = trace.decision
        if decision is None:
            return {}
        meta = response.metadata
        out = {
            "policy": f"{decision.policy.name}@{decision.policy.version}",
            "reason_code": decision.reason_code,
            "target": decision.target_model_id or "-",
            "anchor_before": decision.anchor_model_id or "-",
            "chain": ", ".join(decision.chain) or "-",
        }
        code = decision.reason_code
        final = meta.final_model_id
        if meta.served_by == ServedBy.CACHE:
            label = "served from cache: does not anchor the session"
        elif code == "sticky.greeting.stay":
            label = (
                f"greeting/small talk in an anchored session → stayed on the "
                f"anchor {decision.anchor_model_id}; does not anchor"
            )
        elif code.startswith("sticky.greeting"):
            label = "greeting/small talk → cheapest model; does not anchor" + (
                f" (anchor {decision.anchor_model_id} not eligible)"
                if decision.anchor_model_id
                else ""
            )
        elif code.startswith("sticky.first_substantive"):
            label = f"anchored: first substantive message → {final}"
        elif code.startswith("sticky.stay"):
            label = f"stayed on the anchor {decision.anchor_model_id}" + (
                " (raised by an earlier escalation)" if "escalated" in code else ""
            )
        elif code.startswith("sticky.reroute"):
            why = code.split(".")[2] if code.count(".") >= 2 else "?"
            label = f"re-routed ({why}) and re-anchored → {final}"
        elif code.startswith("per_request"):
            label = "per-request rules (no anchor)"
        else:
            label = code
        if meta.escalations:
            label += f"; ESCALATED {decision.target_model_id} → {final}" + (
                "; the session now anchors on it" if code.startswith("sticky") else ""
            )
        out["decision"] = label
        return out

    def _features(self, request_id: str) -> dict[str, str]:
        for event in reversed(self._sink.events):
            if event.request_id == request_id and isinstance(
                event.payload, FeaturesExtracted
            ):
                f = event.payload.features
                return {
                    "language": f.language.value,
                    "code": _flag(f.has_code),
                    "coding_intent": _flag(f.has_coding_intent),
                    "length_bucket": str(f.length_bucket),
                    "greeting": _flag(f.is_greeting),
                    "turn_depth": str(f.turn_depth),
                }
        return {}

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


def _flag(value: bool | None) -> str:
    return "unknown" if value is None else ("yes" if value else "no")


def _cache(trace: RequestTrace) -> tuple[str, ...]:
    rows = []
    for r in trace.lookups:
        demo = " [DEMO seed]" if r.key_variant and "demo_seed" in r.key_variant else ""
        scope = r.scope.value if r.scope else "-"
        detail = (
            r.ineligible_reason.value
            if r.outcome == LookupOutcome.INELIGIBLE and r.ineligible_reason
            else (r.invalid_reason.value if r.invalid_reason else "")
        )
        rows.append(
            f"{r.key_variant}/{scope}: {r.outcome.value}"
            + (f" ({detail})" if detail else "")
            + demo
        )
    if trace.seed_hit:
        rows.append("DEMO seed hit: a LOGGED answer, shown locally, never sent")
    return tuple(rows)


def _compression(response: FinalResponse, trace: RequestTrace) -> dict[str, str]:
    c = trace.compression
    if c is None:
        return {}
    ms = sum(
        s.duration_ms
        for s in response.metadata.spans
        if s.span == SpanName.CONTEXT_COMPRESS
    )
    parts = ", ".join(
        f"{x.component.value} {x.items_compressed} compressed/{x.items_skipped} "
        f"skipped, {x.tokens_before}→{x.tokens_after} tokens"
        for x in c.components
    )
    return {
        "compressor": f"{c.compressor.name}@{c.compressor.version} [EXPERIMENTAL]",
        "rate": str(c.rate),
        "components": parts or "nothing long enough to compress",
        "token_method": c.token_method,
        "time_ms": f"{ms:.1f}",
    }


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
    """Metis's own time: the whole request minus model calls (compression
    included)."""
    spans = response.metadata.spans
    total = next((s.duration_ms for s in spans if s.span == SpanName.REQUEST), None)
    if total is None:
        return None
    calls = sum(s.duration_ms for s in spans if s.span == SpanName.MODEL_CALL)
    return max(0.0, total - calls)


def format_report(report: TurnReport) -> str:
    """Plain-text rendering of a turn report for the CLI."""
    lines = []
    if report.routing:
        r = report.routing
        lines.append(f"routing: {r['decision']}")
        lines.append(
            f"  reason {r['reason_code']} | target {r['target']} | anchor before "
            f"{r['anchor_before']} | escalation chain {r['chain']} | {r['policy']}"
        )
    if report.features:
        lines.append(
            "  features: " + ", ".join(f"{k} {v}" for k, v in report.features.items())
        )
    lines.append(
        f"served_by: {report.served_by}   model: {report.model_id}   "
        f"provider-reported model: {report.provider_model or '-'}",
    )
    if report.cache:
        lines.append("cache: " + " | ".join(report.cache))
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
    if report.compression:
        c = report.compression
        lines.append(
            f"compression: {c['compressor']} rate {c['rate']}: {c['components']} "
            f"({c['token_method']}), {c['time_ms']} ms"
        )
    overhead = f"{report.overhead_ms:.2f} ms" if report.overhead_ms is not None else "-"
    lines.append(f"overhead: {overhead}, cost {report.overhead_cost}")
    if report.budget:
        b = report.budget
        lines.append(
            f"budget: {b['lifetime_spent']} of {b['lifetime_cap']} {b['currency']} "
            f"used ({b['lifetime_used']}); this run {b['run_spent']} of "
            f"{b['run_cap']}"
        )
    if report.settings:
        lines.append(
            "settings: " + ", ".join(f"{k} {v}" for k, v in report.settings.items())
        )
    if report.live_stopped:
        lines.append(f"LIVE CALLS STOPPED: {report.live_stopped}")
    return "\n".join(lines)


__all__ = [
    "SEED_PRODUCER",
    "ChatSession",
    "ClientFactory",
    "CompressionMode",
    "CompressorFactory",
    "RoutingMode",
    "SettingsLoader",
    "TurnReport",
    "format_report",
]
