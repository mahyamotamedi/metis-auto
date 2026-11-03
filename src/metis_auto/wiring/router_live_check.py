"""The decision router's live check, R6 (J-4 remapped; owner pre-approval
2026-11-03).

One tiny call to each of: Jev via Metis (``/typesafe/v1/systemone``,
``jev-latest``), the LLM-as-System-One backup on ``mimo-v2.5``,
``gpt-4.1-nano`` and ``gpt-4o-mini`` (which also shows that each model still
answers through its Metis wrapper), and a ``response_format: json_schema``
probe on the OpenAI wrapper (``gpt-4.1-nano``). Every call carries one
**SYNTHETIC** state (``SYNTHETIC_STATE``); no dataset text exists here.

Money: ``plan`` prints each call's pre-call estimate (an upper bound) and the
total; calls are dropped from the end of ``CALLS`` until the total fits the
run cap (0.05 USD in the owner's approval). ``run`` charges every call to the
persistent file ledger through a ``SpendGuard`` (one guard per call, so one
failed call does not stop the others; an unknown actual cost is charged at
its estimate). The ledger enforces the lifetime and run caps.

Live calls need the live permission (ADR-0018: the runtime switch from
``config/local.toml`` or the environment, both caps, ``METIS_API_KEY``).
Without the key the run is skipped and says so. The result is content-free:
model IDs, reported versions, outcomes, error classes, token counts, costs,
latencies, and whether the JSON reply parsed. Called by
scripts/router_live_check.py; tests use a fake transport and client.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from metis_auto.adapters.system import SystemClock
from metis_auto.application.pipeline.spend_guard import SpendGuard
from metis_auto.contracts import (
    Component,
    ComponentState,
    CostEstimate,
    CostStatus,
    DecisionError,
    DecisionQuestionSet,
    DecisionResult,
    DecisionState,
    Language,
    LastAssistantTurnKind,
)
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.ports import BaseRouter, ModelClient, SpendLedger
from metis_auto.settings import (
    JevMetisBackendSettings,
    LlmSystemOneBackendSettings,
    LoadedSettings,
)

from .routers import backend_builder

SYNTHETIC_STATE = DecisionState(
    message="[SYNTHETIC] سلام، ساعت کاری فروشگاه در روزهای تعطیل چیست؟",
    previous_user_turn=Component[str].absent(),
    last_assistant_turn_kind=LastAssistantTurnKind.NONE,
    retrieved_state=ComponentState.ABSENT,
    language=Language.PERSIAN,
    turn_depth=0,
    dataset_derived=False,
)
STATE_TOKENS_BOUND = 60
"""The synthetic state is about 70 characters: 60 tokens is an upper bound."""
RUN_CAP = Decimal("0.05")


@dataclass(frozen=True)
class Call:
    label: str
    kind: str  # "jev" | "llm" | "llm_json_schema"
    model: str


CALLS = (
    Call("jev", "jev", "jev-latest"),
    Call("gpt-4o-mini", "llm", "gpt-4o-mini"),
    Call("mimo-v2.5", "llm", "mimo-v2.5"),
    Call("json_schema_probe", "llm_json_schema", "gpt-4o-mini"),
)
"""In priority order: the plan drops from the end until the total fits. The
first run (2026-11-03) also called gpt-4.1-nano, which Metis no longer serves
(HTTP 404 model_not_found, TODO-17); it is not called again."""

ANSWER_SCHEMA_NAME = "systemone_answers"


def answers_schema(questions: DecisionQuestionSet) -> dict[str, Any]:
    """A strict JSON schema for the LLM backup's reply (the probe)."""
    props: dict[str, Any] = {}
    for q in questions.questions:
        kind = q.type.value
        value_key = {"choice": "choice", "score": "score", "noul": "noul"}[kind]
        value: dict[str, Any] = (
            {"type": "string", "enum": list(q.option_names)}
            if kind == "choice"
            else {"type": "number"}
        )
        props[q.id] = {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": [kind]},
                value_key: value,
                "confidence": {"type": "number"},
            },
            "required": ["type", value_key, "confidence"],
            "additionalProperties": False,
        }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": ANSWER_SCHEMA_NAME,
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "answers": {
                        "type": "object",
                        "properties": props,
                        "required": list(props),
                        "additionalProperties": False,
                    }
                },
                "required": ["answers"],
                "additionalProperties": False,
            },
        },
    }


ClientFactory = Callable[[Mapping[str, Mapping[str, Any]] | None], ModelClient]
"""``model_options → ModelClient``: the live client (``build_live_client``),
or a fake in tests."""


def _backend(
    call: Call,
    loaded: LoadedSettings,
    questions: DecisionQuestionSet,
    clients: ClientFactory | None,
) -> BaseRouter:
    policy = DecisionRouterConfig()
    root = loaded.path(loaded.settings.paths.router_assets)
    if call.kind == "jev":
        base = loaded.settings.router.backends.get("jev_metis")
        settings = (
            base
            if isinstance(base, JevMetisBackendSettings)
            else JevMetisBackendSettings()
        )
        return backend_builder(
            call.label,
            settings.model_copy(update={"enabled": True}),
            policy,
            assets=None,
            assets_root=root,
            loaded=loaded,
            questions=questions,
        )(SystemClock())
    options = (
        {call.model: answers_schema(questions)}
        if call.kind == "llm_json_schema"
        else None
    )

    def client() -> ModelClient:
        if clients is not None:
            return clients(options)
        from .live import build_live_client  # noqa: PLC0415

        return build_live_client(loaded, "router-live-check", model_options=options)

    return backend_builder(
        call.label,
        LlmSystemOneBackendSettings(enabled=True, model_id=call.model),
        policy,
        assets=None,
        assets_root=root,
        loaded=loaded,
        questions=questions,
        model_client=client,
    )(SystemClock())


def plan(
    loaded: LoadedSettings,
    questions: DecisionQuestionSet,
    *,
    run_cap: Decimal = RUN_CAP,
    clients: ClientFactory | None = None,
) -> dict[str, Any]:
    """Each call's estimate (upper bound) and the calls that fit ``run_cap``.
    Builds no live client: estimates need only prices."""
    rows = []
    for call in CALLS:
        backend = _backend(call, loaded, questions, clients or _no_client)
        est = backend.estimate_cost(STATE_TOKENS_BOUND)
        amount = (
            est.cost.amount.amount
            if est is not None
            and est.cost.status == CostStatus.COMPUTED
            and est.cost.amount is not None
            else None
        )
        rows.append({"call": call.label, "model": call.model, "estimate_usd": amount})
    kept: list[dict[str, Any]] = []
    total = Decimal(0)
    for row in rows:
        amount = row["estimate_usd"]
        if amount is None:
            row["dropped"] = "estimate not computed"
            continue
        if total + amount > run_cap:
            row["dropped"] = "over the run cap"
            continue
        total += amount
        kept.append(row)
    return {
        "calls": [{**r, "estimate_usd": _s(r["estimate_usd"])} for r in rows],
        "kept": [r["call"] for r in kept],
        "total_upper_bound_usd": _s(total),
        "run_cap_usd": _s(run_cap),
        "fits": total <= run_cap,
    }


def _no_client(_options) -> ModelClient:
    class _Unused:
        source = None

        def invoke(self, _invocation):  # pragma: no cover - never called by plan
            raise RuntimeError("plan makes no calls")

    return _Unused()  # type: ignore[return-value]


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def run(
    loaded: LoadedSettings,
    questions: DecisionQuestionSet,
    ledger: SpendLedger,
    *,
    keep: tuple[str, ...],
    clients: ClientFactory | None = None,
    backends: Callable[[Call], BaseRouter] | None = None,
) -> dict[str, Any]:
    """Make the kept calls, each under its own spend guard over ``ledger``.
    ``backends`` replaces the built backends (tests)."""
    results = []
    for call in CALLS:
        if call.label not in keep:
            continue
        backend = (
            backends(call)
            if backends is not None
            else _backend(call, loaded, questions, clients)
        )
        row: dict[str, Any] = {"call": call.label, "model": call.model}
        est: CostEstimate | None = backend.estimate_cost(STATE_TOKENS_BOUND)
        guard = SpendGuard(ledger)
        if est is None or not guard.allows(est):
            row["outcome"] = "refused_by_spend_guard"
            results.append(row)
            continue
        if not backend.available().available:
            row["outcome"] = "unavailable"
            row["reason"] = backend.available().reason.value  # type: ignore[union-attr]
            results.append(row)
            continue
        t0 = time.perf_counter()
        reply = backend.decide(SYNTHETIC_STATE, questions, timeout_ms=30_000)
        row["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        cost = reply.cost if isinstance(reply, DecisionResult) else None
        guard.charge(cost, est)
        if isinstance(reply, DecisionError):
            row["outcome"] = (
                "invalid_response"
                if reply.invalid_response
                else f"error:{reply.error_class.value if reply.error_class else '?'}"
            )
            row["provider_error_code"] = reply.provider_error_code
            row["charged_usd"] = _s(est.cost.amount.amount if est.cost.amount else None)
        else:
            row["outcome"] = "answered"
            row["reported_model"] = reply.model_revision
            row["answers"] = len(reply.answers)
            row["confidences_reported"] = sum(
                a.confidence is not None for a in reply.answers
            )
            if reply.usage is not None:
                row["input_tokens"] = reply.usage.input.tokens
                row["output_tokens"] = (
                    reply.usage.output.tokens if reply.usage.output else None
                )
            row["cost_usd"] = _s(
                reply.cost.amount.amount if reply.cost.amount is not None else None
            )
            row["cost_status"] = reply.cost.status.value
        results.append(row)
    left = ledger.remaining()
    return {
        "results": results,
        "ledger_remaining_usd": _s(left.amount) if left is not None else None,
    }


# --- R6 follow-up diagnostics (owner, 2026-11-03) --------------------------------
# At most two tiny SYNTHETIC calls to find out why mimo-v2.5 answered HTTP 400,
# and the json_schema probe again, on gpt-4o-mini (gpt-4.1-nano is gone on
# Metis: HTTP 404 model_not_found). Same run cap, same ledger.

DIAG_TEXT = "[SYNTHETIC] Reply with the single word OK."
DIAG_MAX_OUTPUT = 64
JSON_PROBE_MODEL = "gpt-4o-mini"


def _diag_invocation(model_id: str, *, with_system: bool, n: int):
    from metis_auto.contracts import (  # noqa: PLC0415
        AttemptKind,
        ComponentName,
        InputPart,
        ModelInvocation,
        PartRole,
    )

    parts = [
        InputPart(role=PartRole.USER, text=DIAG_TEXT, component=ComponentName.MESSAGE)
    ]
    if with_system:
        parts.insert(
            0,
            InputPart(
                role=PartRole.INSTRUCTIONS,
                text="[SYNTHETIC] You are a test assistant.",
                component=ComponentName.INSTRUCTIONS,
            ),
        )
    return ModelInvocation(
        request_id="router-live-diag",
        attempt_id=f"router-live-diag-{n}",
        attempt_kind=AttemptKind.PRIMARY,
        model_id=model_id,
        parts=tuple(parts),
        max_output_tokens=DIAG_MAX_OUTPUT,
        timeout_ms=30_000,
    )


def _diag_estimate(loaded: LoadedSettings, model_id: str) -> CostEstimate | None:
    from metis_auto.contracts import Fidelity, TokenCount  # noqa: PLC0415
    from metis_auto.domain.accounting.cost import pre_call_estimate  # noqa: PLC0415

    entry = next(
        (e for e in loaded.reference.catalogue.entries if e.model_id == model_id), None
    )
    if entry is None:
        return None
    return pre_call_estimate(
        entry,
        TokenCount(tokens=60, fidelity=Fidelity.APPROXIMATION, method="diag_bound"),
        DIAG_MAX_OUTPUT,
        loaded.reference.prices,
    )


def _raw_call(
    loaded: LoadedSettings,
    ledger: SpendLedger,
    client: ModelClient,
    label: str,
    invocation,
) -> dict[str, Any]:
    from metis_auto.contracts import ModelError  # noqa: PLC0415
    from metis_auto.domain.accounting.cost import cost_of  # noqa: PLC0415

    row: dict[str, Any] = {"call": label, "model": invocation.model_id}
    est = _diag_estimate(loaded, invocation.model_id)
    guard = SpendGuard(ledger)
    if est is None or not guard.allows(est):
        row["outcome"] = "refused_by_spend_guard"
        return row
    t0 = time.perf_counter()
    result = client.invoke(invocation)
    row["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if isinstance(result, ModelError):
        guard.charge(None, est)
        row["outcome"] = f"error:{result.error_class.value}"
        row["provider_error_code"] = result.provider_error_code
        row["charged_usd"] = _s(est.cost.amount.amount if est.cost.amount else None)
        return row
    entry = next(
        e
        for e in loaded.reference.catalogue.entries
        if e.model_id == invocation.model_id
    )
    cost = cost_of(result.usage, entry, loaded.reference.prices)
    guard.charge(cost, est)
    row["outcome"] = "answered"
    row["reported_model"] = result.provider_model_version
    row["finish_reason"] = result.finish_reason.value
    row["empty_text"] = not result.text.strip()
    if result.usage is not None:
        row["input_tokens"] = result.usage.input.tokens
        row["output_tokens"] = (
            result.usage.output.tokens if result.usage.output else None
        )
    row["cost_usd"] = _s(cost.amount.amount if cost.amount is not None else None)
    return row


DiagClients = Callable[[Mapping[str, Mapping[str, Any]] | None], ModelClient]


def diagnose(
    loaded: LoadedSettings,
    questions: DecisionQuestionSet,
    ledger: SpendLedger,
    *,
    clients: DiagClients | None = None,
    backends: Callable[[Call], BaseRouter] | None = None,
) -> dict[str, Any]:
    """Three tiny SYNTHETIC calls at most:

    1. ``mimo-v2.5``, user message only, ``max_completion_tokens`` 64: does
       the model still answer at all?
    2. If (1) answered: the same with a system message, our backup's message
       shape (is the system role what MiMo refused?). If (1) failed: the same
       as (1) with thinking disabled (is the default thinking mode refused?).
       If that fails too, the model ID is gone: Q-42 applies.
    3. The ``json_schema`` probe through the LLM backup on ``gpt-4o-mini``.
    """

    def client(options=None) -> ModelClient:
        if clients is not None:
            return clients(options)
        from .live import build_live_client  # noqa: PLC0415

        return build_live_client(loaded, "router-live-diag", model_options=options)

    rows = []
    first = _raw_call(
        loaded,
        ledger,
        client(),
        "mimo_user_only",
        _diag_invocation("mimo-v2.5", with_system=False, n=1),
    )
    rows.append(first)
    if first["outcome"] == "answered":
        second = _raw_call(
            loaded,
            ledger,
            client(),
            "mimo_with_system_message",
            _diag_invocation("mimo-v2.5", with_system=True, n=2),
        )
    elif first["outcome"].startswith("error"):
        second = _raw_call(
            loaded,
            ledger,
            client({"mimo-v2.5": {"thinking": {"type": "disabled"}}}),
            "mimo_user_only_thinking_disabled",
            _diag_invocation("mimo-v2.5", with_system=False, n=2),
        )
    else:
        second = None
    if second is not None:
        rows.append(second)
    probe = Call("json_schema_probe_4o_mini", "llm_json_schema", JSON_PROBE_MODEL)
    backend = (
        backends(probe)
        if backends is not None
        else _backend(probe, loaded, questions, clients)
    )
    est = backend.estimate_cost(STATE_TOKENS_BOUND)
    guard = SpendGuard(ledger)
    row: dict[str, Any] = {"call": probe.label, "model": probe.model}
    if est is None or not guard.allows(est):
        row["outcome"] = "refused_by_spend_guard"
    else:
        t0 = time.perf_counter()
        reply = backend.decide(SYNTHETIC_STATE, questions, timeout_ms=30_000)
        row["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        guard.charge(reply.cost if isinstance(reply, DecisionResult) else None, est)
        if isinstance(reply, DecisionError):
            row["outcome"] = (
                "invalid_response"
                if reply.invalid_response
                else f"error:{reply.error_class.value if reply.error_class else '?'}"
            )
            row["provider_error_code"] = reply.provider_error_code
        else:
            row["outcome"] = "answered"
            row["reported_model"] = reply.model_revision
            row["answers"] = len(reply.answers)
            row["cost_usd"] = _s(
                reply.cost.amount.amount if reply.cost.amount else None
            )
    rows.append(row)
    verdict = _mimo_verdict(first, second)
    left = ledger.remaining()
    return {
        "results": rows,
        "mimo_verdict": verdict,
        "ledger_remaining_usd": _s(left.amount) if left is not None else None,
    }


def _mimo_verdict(first: dict, second: dict | None) -> str:
    one = first.get("outcome")
    two = second.get("outcome") if second else None
    if one == "answered" and two == "answered":
        return "model works; the 400 came from our backup's request (prompt or length)"
    if one == "answered":
        return "model works; it refuses a system message (our request shape)"
    if two == "answered":
        return "model works only with thinking disabled (our request option)"
    if one and one.startswith("error") and two and two.startswith("error"):
        return "model refused in every shape: the ID is gone (Q-42: enabled = false)"
    return "inconclusive"
