"""R8 shadow evaluation of the decision router on the frozen dev slice
(exp-route-013; ADR-0047 point 12).

Each slice record goes through two pipelines with the fake answering client:
**rules only** (``decision_router`` policy with ``router.mode = "off"``: the
policy falls back to the rules) and **with the router** (a local chain:
``thx01`` from settings on the owner's machine, or the ``fake`` backend in
tests and CI). Per record we keep the routed model's catalogue tier, the
router's path, the decision status, the lowest confidence over the gate's
questions (Q-61) and the decision step's duration: ``ShadowRow``. The rows
are summarised by ``evaluation.router_eval.summarise`` (per split, balanced
and traffic-weighted, Persian first). Labels do not exist yet: agreement here
is agreement with the rules, not accuracy.

Two modes: the **inline settings** (the configured deadline, cache and gate:
what serving would see) and **offline** (``OFFLINE``: 60 s per request, no
cache, gate off; the evaluation mode, owner 2026-11-03), which also returns
each question's confidence and probability distribution and the provisional
gate proposal (``evaluation.router_eval.propose_gate``).

**Jev on the slice** (``backend="jev"``, owner 2026-11-03 after Metis's
written OK, Q-55): a hosted chain (``jev_metis`` only) under the offline
settings with a 30 s backend timeout. It sends dataset text to Metis, so it
runs only when the runtime sets ``router.real_data_approved`` (a runtime-only
key; the cascade's approval check refuses otherwise) and every call goes
through the spend guard over the given ledger. THX-01 and the fake backend
stay local; their chains never reach a hosted backend. Each row also keeps the
models routed to (rules and router), so ``evaluation.router_eval.costs`` can
price the same logged tokens on each. Output: counts, shares, timings and
costs only. Called by scripts/evaluate_router_slice.py and tests.
"""

from __future__ import annotations

import dataclasses
import json
import tomllib
from collections import Counter
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from metis_auto.adapters.system import SystemClock
from metis_auto.contracts import DecisionStatus
from metis_auto.domain.routing import DecisionRouterConfig
from metis_auto.domain.routing.decision import (
    answer_strength,
    mapping_question_ids,
    result_confidence,
)
from metis_auto.evaluation.router_eval import (
    ShadowRow,
    against_labels,
    answer_distributions,
    propose_gate,
    skip_breakdown,
    summarise,
)
from metis_auto.evaluation.router_eval.costs import compare_costs
from metis_auto.evaluation.router_slice.records import to_request
from metis_auto.ports import Clock, SpendLedger
from metis_auto.settings import LoadedSettings
from metis_auto.settings.loader import repo_root

from .from_settings import pipeline_config
from .router_replay import replay_pipeline
from .routers import router_spec

Loader = Callable[[dict[str, Any]], LoadedSettings]
BACKENDS = ("thx01", "fake", "jev")
HOSTED_BACKENDS = ("jev",)
"""Backends that send the slice's text to a hosted service (Q-55)."""
JEV_TIMEOUT_MS = 30_000
FAKE = "fake_local"


OFFLINE_TIMEOUT_MS = 60_000
OFFLINE = {
    "router.deadline_ms": OFFLINE_TIMEOUT_MS,
    "router.cache.enabled": False,
    "router.min_confidence": 0.0,
    "router.circuit.failure_threshold": 1_000_000,
}
"""Offline evaluation (owner, 2026-11-03): no inline deadline (60 s per
request), no router cache, the confidence gate off (every answer is used; the
gate is studied afterwards from the recorded strengths) and a breaker that
never opens, so the rows hold THX-01's real answers, never a fallback caused
by the inline budget."""


NOT_CALLABLE = {
    "gpt-4.1-nano": "Metis: HTTP 404 model_not_found, 'has been deprecated' "
    "(live check and owner probe 2026-11-03; TODO-17)",
    "mimo-v2.5": "Metis: HTTP 400 'Unsupported model' in every request shape "
    "(live check and owner probe 2026-11-03; Q-42)",
}
"""Models Metis no longer serves. The catalogue still lists them enabled until
its owner applies TODO-17 / Q-42; ``without_gone_models`` disables them for one
run, in memory only (no file changes), so a cost view never routes to a model
that cannot be called."""


def without_gone_models(load: Loader) -> Loader:
    """``load`` with ``NOT_CALLABLE`` models disabled in the loaded catalogue."""

    def wrapped(overrides: dict[str, Any]) -> LoadedSettings:
        loaded = load(overrides)
        cat = loaded.reference.catalogue
        entries = tuple(
            e.model_copy(update={"enabled": False}) if e.model_id in NOT_CALLABLE else e
            for e in cat.entries
        )
        reference = dataclasses.replace(
            loaded.reference, catalogue=cat.model_copy(update={"entries": entries})
        )
        return dataclasses.replace(loaded, reference=reference)

    return wrapped


def _overrides(
    backend: str | None, profile: str, offline: bool = False
) -> dict[str, Any]:
    over: dict[str, Any] = {"pipeline.routing.policy": "decision_router"}
    if backend == "thx01":
        over.update(
            {
                "router.mode": "local",
                "router.backends.thx01.enabled": True,
                "router.chains.local": ["thx01"],
            }
        )
        if offline:
            over["router.backends.thx01.timeout_ms"] = OFFLINE_TIMEOUT_MS
    elif backend == "jev":
        over.update(
            {
                "router.mode": "hosted",
                "router.backends.jev_metis.enabled": True,
                "router.chains.hosted": ["jev_metis"],
            }
        )
        if offline:
            over["router.backends.jev_metis.timeout_ms"] = JEV_TIMEOUT_MS
    elif backend == "fake":
        over.update(
            {
                "router.mode": "local",
                f"router.backends.{FAKE}": {
                    "type": "fake",
                    "enabled": True,
                    "profile": profile,
                },
                "router.chains.local": [FAKE],
            }
        )
        if offline:
            over[f"router.backends.{FAKE}"]["timeout_ms"] = OFFLINE_TIMEOUT_MS
    if offline and backend is not None:
        over.update(OFFLINE)
    return over


def shadow_rows(
    load: Loader,
    records: Sequence[dict[str, Any]],
    *,
    backend: str = "thx01",
    profile: str = "cheap",
    clock: Clock | None = None,
    offline: bool = False,
    spend_ledger: SpendLedger | None = None,
    backends: Callable[[Clock], Any] | None = None,
) -> list[ShadowRow]:
    """One ``ShadowRow`` per record (content-free). ``offline``: the
    evaluation settings in ``OFFLINE`` (no inline deadline, no cache, gate off).
    ``backends`` replaces the configured decision backends (tests)."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}")
    clock = clock or SystemClock()
    rules_loaded = load(_overrides(None, profile))
    router_loaded = load(_overrides(backend, profile, offline))
    tier = {
        e.model_id: e.tier
        for e in router_loaded.reference.catalogue.entries
        if getattr(e, "tier", None) is not None
    }
    policy = (
        pipeline_config(router_loaded).routing.decision_router or DecisionRouterConfig()
    )
    gate_ids = (
        mapping_question_ids(policy.questions)
        if router_loaded.settings.router.confidence_questions == "mapping"
        else None
    )
    settings = router_loaded.settings.router
    min_confidence = settings.min_confidence
    statistic = settings.confidence_statistic
    mapping = mapping_question_ids(policy.questions)
    rules_pipe, rules_sink = replay_pipeline(
        rules_loaded, None, run_id="run-shadow-rules", clock=clock
    )
    spec = router_spec(
        router_loaded,
        policy,
        states_dataset_derived=True,
        spend_ledger=spend_ledger,
        backends=backends,
    )
    router_pipe, router_sink = replay_pipeline(
        router_loaded, spec, run_id="run-shadow-router", clock=clock
    )
    rows: list[ShadowRow] = []
    for record in records:
        request = to_request(record, profile="pre_retrieval")
        rules_sink.events.clear()
        router_sink.events.clear()
        rules_pipe.handle(request)
        router_pipe.handle(request)
        rules_target = _target(rules_sink.events)
        rules_reason, rules_exclusions = _rules_reason(rules_sink.events)
        router_target = _target(router_sink.events)
        path, status, confidence, ms = "none", "off", None, None
        cost_usd: str | None = None
        revision: str | None = None
        strengths: tuple = ()
        gate_reported = gate_probability = None
        skip_reason: str | None = None
        for e in router_sink.events:
            p = e.payload
            if p.event_type == "routing_decided" and p.decision.router_summary:
                path = p.decision.router_summary.path.value
            elif p.event_type == "decision_measured":
                status = p.outcome.status.value
                ms = e.duration_ms
                if p.outcome.skip_reason is not None:
                    skip_reason = p.outcome.skip_reason.value
                result = p.outcome.result
                if result is not None:
                    revision = result.model_revision
                    if result.cost is not None and result.cost.amount is not None:
                        cost_usd = str(result.cost.amount.amount)
                    confidence = result_confidence(result, gate_ids, statistic)
                    strengths = tuple(
                        (
                            a.question_id,
                            answer_strength(a, "reported"),
                            answer_strength(a, "probability"),
                        )
                        for a in result.answers
                    )
                    gate_reported = result_confidence(result, mapping, "reported")
                    gate_probability = result_confidence(result, mapping, "probability")
        rows.append(
            ShadowRow(
                record_id=str(record["slice_record_id"]),
                split=str(record.get("split", "unknown")),
                language_group=str(record.get("language_group", "unknown")),
                weight=_float(record.get("traffic_weight")),
                rules_tier=tier.get(rules_target) if rules_target else None,
                router_tier=tier.get(router_target) if router_target else None,
                router_path=path,
                decision_status=status,
                confidence=confidence,
                below_gate=status == DecisionStatus.ANSWERED.value
                and confidence is not None
                and confidence < min_confidence,
                decide_ms=ms,
                strengths=strengths,
                gate_reported=gate_reported,
                gate_probability=gate_probability,
                rules_target=rules_target,
                router_target=router_target,
                decision_cost_usd=cost_usd,
                model_revision=revision,
                skip_reason=skip_reason,
                rules_reason=rules_reason,
                rules_exclusions=rules_exclusions,
            )
        )
    return rows


def _target(events) -> str | None:
    for e in events:
        if e.payload.event_type == "routing_decided":
            return e.payload.decision.target_model_id
    return None


def _rules_reason(events) -> tuple[str | None, tuple[str, ...]]:
    for e in events:
        if e.payload.event_type == "routing_decided":
            d = e.payload.decision
            return d.reason_code, tuple(sorted({x.reason.value for x in d.exclusions}))
    return None, ()


def _float(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def evaluate(
    load: Loader,
    records: Sequence[dict[str, Any]],
    *,
    backend: str = "thx01",
    profile: str = "cheap",
    labels: dict[str, int] | None = None,
    offline: bool = False,
    spend_ledger: SpendLedger | None = None,
    backends: Callable[[Clock], Any] | None = None,
    exclude_gone_models: bool = False,
    rows_sink: list | None = None,
) -> dict[str, Any]:
    """The R8 summary. ``offline`` adds the per-question confidence and
    probability distributions and the provisional gate proposal (threshold
    from the tune split, effect on the check split). ``rows_sink``, if given,
    receives the shadow rows."""
    if exclude_gone_models:
        load = without_gone_models(load)
    rows = shadow_rows(
        load,
        records,
        backend=backend,
        profile=profile,
        offline=offline,
        spend_ledger=spend_ledger,
        backends=backends,
    )
    if rows_sink is not None:
        rows_sink.extend(rows)
    out: dict[str, Any] = {
        "backend": backend,
        "mode": "offline" if offline else "inline_settings",
        **summarise(rows),
    }
    if offline:
        answered = [r for r in rows if r.strengths]
        out["answer_strengths"] = {
            "all": answer_distributions(answered),
            "tune": answer_distributions(r for r in answered if r.split == "tune"),
        }
        out["gate_proposal"] = propose_gate(rows)
    if labels is not None:
        out["labels"] = against_labels(rows, labels)
    loaded = load({})
    rules = pipeline_config(loaded).routing.rule_based
    price, extra, basis = replay_pricing(
        records,
        expected_reasoning=dict(rules.cost_model.expected_reasoning_tokens)
        if rules is not None
        else {},
        default_reasoning=rules.cost_model.default_reasoning_tokens
        if rules is not None
        else 256,
    )
    out["costs"] = compare_costs(
        rows, records, price=price, extra_output=extra, price_basis=basis
    )
    out["skips"] = skip_breakdown(rows)
    out["excluded_models"] = dict(NOT_CALLABLE) if exclude_gone_models else {}
    decided = [r for r in rows if r.decision_cost_usd is not None]
    out["decision_cost_usd"] = str(
        sum((Decimal(r.decision_cost_usd) for r in decided), Decimal(0))
    )
    out["net_of_decision_cost"] = net_of_decision_cost(
        out["costs"], Decimal(out["decision_cost_usd"])
    )
    out["model_revisions"] = dict(
        Counter(r.model_revision for r in rows if r.model_revision)
    )
    return out


def net_of_decision_cost(costs: dict, decision_usd: Decimal) -> dict[str, Any]:
    """The router's saving on the whole slice once its own decision calls are
    paid for: the answering totals (``costs``) exclude them. One block per
    price variant; shares of the rules' and of today's total."""
    out: dict[str, Any] = {}
    for variant in ("logged_tokens", "with_expected_reasoning"):
        block = costs.get(variant, {}).get("all")
        if not block:
            continue
        t = {k: Decimal(v) for k, v in block["total_usd"].items()}
        router = t["router"] + decision_usd
        out[variant] = {
            "router_incl_decision_usd": format(router.normalize(), "f"),
            "saving_vs_rules_usd": format((t["rules"] - router).normalize(), "f"),
            "saving_vs_rules_share": round(float((t["rules"] - router) / t["rules"]), 4)
            if t["rules"]
            else None,
            "saving_vs_today_share": round(float((t["today"] - router) / t["today"]), 4)
            if t["today"]
            else None,
        }
    return out


# --- the hosted (Jev) run: plan with no call, and its ledger ----------------------

JEV_RUN_CAP = Decimal("0.05")
"""Upper limit of one Jev slice run (owner 2026-11-03: the plan's bound is
about 0.01 USD for 150 records)."""
STATE_FRAMING_TOKENS = 64
"""Allowance for the state's framing; the estimate counts one token per
character of the message and previous turn, an upper bound."""


def _state_chars(record: dict[str, Any], policy: DecisionRouterConfig) -> int:
    state = policy.state
    message = str(record.get("message") or "")[: state.max_message_chars]
    previous = ""
    for turn in reversed(json.loads(record.get("history_json") or "[]")):
        if turn.get("role") == "user":
            previous = str(turn.get("text") or "")[: state.max_previous_turn_chars]
            break
    return len(message) + len(previous)


def hosted_plan(
    loaded: LoadedSettings,
    records: Sequence[dict[str, Any]],
    *,
    run_cap: Decimal = JEV_RUN_CAP,
) -> dict[str, Any]:
    """What a Jev run on these records would cost at most, and every reason
    it may not start. No client is built for calls; no call is made."""
    from metis_auto.adapters.system import SystemClock as _Clock  # noqa: PLC0415
    from metis_auto.settings import JevMetisBackendSettings  # noqa: PLC0415

    from .from_settings import live_permission  # noqa: PLC0415
    from .routers import backend_builder  # noqa: PLC0415

    router = loaded.settings.router
    questions = loaded.reference.router_questions.get(
        router.question_set, router.question_language
    )
    policy = pipeline_config(loaded).routing.decision_router or DecisionRouterConfig()
    base = router.backends.get("jev_metis")
    settings = base if isinstance(base, JevMetisBackendSettings) else None
    backend = backend_builder(
        "jev_metis",
        (settings or JevMetisBackendSettings()).model_copy(update={"enabled": True}),
        policy,
        assets=None,
        assets_root=loaded.path(loaded.settings.paths.router_assets),
        loaded=loaded,
        questions=questions,
    )(_Clock())
    total: Decimal | None = Decimal(0)
    for record in records:
        est = backend.estimate_cost(_state_chars(record, policy) + STATE_FRAMING_TOKENS)
        if est is None or est.cost.amount is None:
            total = None
            break
        total += est.cost.amount.amount  # type: ignore[operator]
    budget = loaded.settings.budget
    cap = min(budget.run_cap or run_cap, run_cap)
    permission = live_permission(loaded)
    reasons = list(permission.reasons)
    if not router.real_data_approved:
        reasons.append(
            "router.real_data_approved is false (runtime only: config/local.toml or "
            "METIS__ROUTER__REAL_DATA_APPROVED=true for this run)"
        )
    if total is None:
        reasons.append("the Jev estimate is not computable (price unknown)")
    elif total > cap:
        reasons.append(f"upper bound {total} USD is above the run cap {cap} USD")
    return {
        "calls": len(records),
        "upper_bound_usd": None if total is None else format(total.normalize(), "f"),
        "run_cap_usd": format(cap.normalize(), "f"),
        "key_set": loaded.secrets.metis_api_key is not None,
        "real_data_approved": router.real_data_approved,
        "allowed": not reasons,
        "blocked_because": reasons,
        "makes_calls": False,
    }


def hosted_ledger(loaded: LoadedSettings, run_cap: Decimal, run_id: str):
    """The persistent ledger with the run's cap (ADR-0018)."""
    from metis_auto.adapters.system import FileSpendLedger  # noqa: PLC0415
    from metis_auto.contracts import Money  # noqa: PLC0415

    budget = loaded.settings.budget
    if budget.lifetime_cap is None:
        raise ValueError("budget.lifetime_cap is not set (ADR-0018)")
    return FileSpendLedger(
        loaded.path(loaded.settings.paths.spend_ledger),
        run_id=run_id,
        lifetime_cap=Money(amount=budget.lifetime_cap, currency=budget.currency),
        run_cap=Money(amount=run_cap, currency=budget.currency),
        warn_at=budget.warn_at,
    )


# --- replay pricing for the cost view (ADR-0041) ---------------------------------

REASONING_CAPABILITY = "hidden_reasoning_billed_as_output"


def replay_pricing(
    records: Sequence[dict[str, Any]],
    *,
    expected_reasoning: dict[str, int],
    default_reasoning: int,
    root: Path | None = None,
):
    """The team's replay pricing over the slice's logged billing tokens:
    ``analysis.baselines_full.model_row_costs`` with the ``sprint.toml
    [baselines]`` catalogue and logged-model price table (ADR-0041), as R-0,
    R-A3 and R-C3 price. Returns ``(price, extra_output, basis)`` for
    ``evaluation.router_eval.costs.compare_costs``."""
    import pandas as pd  # noqa: PLC0415

    from metis_auto.analysis.baselines_full import (  # noqa: PLC0415
        cached_reported_separately,
        model_row_costs,
    )

    root = root or repo_root()
    sprint = tomllib.loads((root / "config/evaluation/sprint.toml").read_text("utf-8"))
    base = sprint["baselines"]
    catalogue = tomllib.loads((root / base["catalogue"]).read_text("utf-8"))
    prices = tomllib.loads((root / base["price_table"]).read_text("utf-8"))
    models = {str(m["model_id"]): m for m in catalogue.get("models", [])}

    def num(value: Any) -> float:
        try:
            return float(value) if value is not None else float("nan")
        except (TypeError, ValueError):
            return float("nan")

    ids = [str(r["slice_record_id"]) for r in records]
    frame = pd.DataFrame(
        {
            "a_bill_inputTokens": [num(r.get("billing_input_tokens")) for r in records],
            "a_bill_cachedInputTokens": [
                num(r.get("billing_cached_input_tokens")) for r in records
            ],
            "a_bill_outputTokens": [
                num(r.get("billing_output_tokens")) for r in records
            ],
            "bot_provider_model": [str(r.get("provider_model") or "") for r in records],
            "a_billing_state": "items",
            "llm_request": True,
        },
        index=ids,
    )
    ctx = SimpleNamespace(catalogue=catalogue, price_table=prices)
    separately = cached_reported_separately(frame)
    cache: dict[tuple[str, int], Any] = {}

    def price(model: str, record_id: str, extra: int) -> Decimal | None:
        if model not in models:
            return None
        key = (model, extra)
        if key not in cache:
            f = frame.assign(a_bill_outputTokens=frame["a_bill_outputTokens"] + extra)
            cache[key] = model_row_costs(f, ctx, model, cached_separately=separately)
        value = cache[key].get(record_id)
        if value is None or value != value:  # NaN: unpriced or unknown tokens
            return None
        return Decimal(f"{float(value):.12f}")

    def bills_reasoning(model: str) -> bool:
        caps = models.get(model, {}).get("capabilities") or []
        return any(
            c.get("name") == REASONING_CAPABILITY and c.get("verified") for c in caps
        )

    def extra_output(model: str) -> int:
        if model in expected_reasoning:
            return expected_reasoning[model]
        return default_reasoning if bills_reasoning(model) else 0

    basis = f"replay pricing (ADR-0041): {base['catalogue']}, {base['price_table']}"
    return price, extra_output, basis
