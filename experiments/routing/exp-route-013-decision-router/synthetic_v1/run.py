r"""First signal on decision quality: rules vs THX-01 vs Jev on 100 SYNTHETIC
requests with the owner's tier labels (jev-synth-v1, frozen 2026-11-03).

    powershell -ExecutionPolicy Bypass -File experiments\routing\exp-route-013-decision-router\synthetic_v1\run.ps1

or step by step (``run.ps1`` sets and clears the live switches for ``jev``):

    python experiments/routing/exp-route-013-decision-router/synthetic_v1/run.py plan
    python experiments/routing/exp-route-013-decision-router/synthetic_v1/run.py local
    python experiments/routing/exp-route-013-decision-router/synthetic_v1/run.py jev --yes
    python experiments/routing/exp-route-013-decision-router/synthetic_v1/run.py report

Every request is SYNTHETIC (written for this check, never from the dataset).
The frozen labels are checked against labels_frozen.json before anything runs.
The ``[SYNTHETIC]`` marker is removed before routing (``--keep-marker`` keeps it)
because it makes the language detector call Persian text "mixed"; all three
routers see the same text either way.

Routers, all through the real pipeline (fake answering client, so no answer is
ever generated or paid for):
- ``rules``: the decision router with the router off (R8's "rules"): fast gate,
  then a matching rule's tier, else ``safe_tier`` (1);
- ``rule_based``: the plain rule-based policy (ADR-0023 demo rules), whose
  default rule is the cheapest tier;
- ``gate``: the decision router's fast gate with a fake backend (free), used
  for the "as configured" view;
- ``thx01`` / ``jev``: the decision router with the gate off, so the model is
  asked on every row; offline settings (no inline deadline, no router cache,
  confidence gate off, breaker never opens). Jev is live: Metis wrapper,
  charged to data/spend/ledger.jsonl by the cascade's spend guard, run cap at
  most 0.02 USD.
Per-row outputs go to runs/jev_synth_eval/ (git-ignored); the report goes to
reports/routing/exp-route-013/synthetic_v1/ (tiers and IDs only). Never reads
.env itself: the key comes from the project's settings loader and is never
printed. Results and limits: the experiment README (exp-route-013).
"""

# ruff: noqa: E501  (report sentences and table rows)

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
FROZEN = HERE / "labels_frozen.csv"
MANIFEST = HERE / "labels_frozen.json"
OUT = ROOT / "runs" / "jev_synth_eval"
REPORT_DIR = ROOT / "reports" / "routing" / "exp-route-013" / "synthetic_v1"
MARKER = "[SYNTHETIC] "
RUN_CAP = Decimal("0.02")
JEV_TIMEOUT_MS = 30_000
GATE_OFF = {
    "pipeline.routing.decision_router.gate.greeting_tier": None,
    "pipeline.routing.decision_router.gate.code_tier": None,
    "pipeline.routing.decision_router.gate.attachment_tier": None,
    "pipeline.routing.decision_router.gate.long_message_tier": None,
}
ROUTERS = ("rules", "rule_based", "thx01", "jev")
"""The routers compared (``gate`` only feeds the "with gate" views)."""


# --------------------------------------------------------------------- inputs
def load_rows() -> list[dict[str, str]]:
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    digest = hashlib.sha256(FROZEN.read_bytes()).hexdigest()
    if digest != man["frozen_sha256"]:
        raise SystemExit(
            f"labels_frozen.csv changed after freezing (sha256 {digest[:12]}..., "
            f"manifest {man['frozen_sha256'][:12]}...): refusing"
        )
    rows = list(csv.DictReader(FROZEN.open(encoding="utf-8-sig")))
    if len(rows) != man["rows"] or not all(
        r["message"].startswith(MARKER) for r in rows
    ):
        raise SystemExit("frozen set is not the approved SYNTHETIC set: refusing")
    return rows


def text(value: str, keep_marker: bool) -> str:
    return value if keep_marker else value.removeprefix(MARKER)


def to_record(row: dict[str, str], keep_marker: bool) -> dict[str, Any]:
    history = []
    if row["previous_user_turn"]:
        history = [
            {"role": "user", "text": text(row["previous_user_turn"], keep_marker)},
            {"role": "assistant", "text": "[SYNTHETIC] (previous answer)"},
        ]
    return {
        "slice_record_id": row["id"],
        "session_id": row["id"],
        "message": text(row["message"], keep_marker),
        "history_json": json.dumps(history, ensure_ascii=False),
        "history_turns_total": len(history),
        "instructions_state": "absent",
        "instructions": "",
        "retrieved_json": "[]",
        "attachment_types_json": "[]",
        "previous_ai_input_state": "none",
    }


# ------------------------------------------------------------------ pipelines
def _settings(extra: dict[str, Any]):
    from metis_auto.settings import load_settings

    return load_settings(overrides=extra)


def router_overrides(kind: str) -> dict[str, Any]:
    from metis_auto.wiring.router_eval import OFFLINE, OFFLINE_TIMEOUT_MS

    base: dict[str, Any] = {"pipeline.routing.policy": "decision_router"}
    if kind == "rules":
        return base
    if kind == "rule_based":
        return {"pipeline.routing.policy": "rule_based"}
    if kind == "gate":
        return {
            **base,
            "router.mode": "local",
            "router.backends.fake_gate": {
                "type": "fake",
                "enabled": True,
                "profile": "neutral",
            },
            "router.chains.local": ["fake_gate"],
        }
    if kind == "thx01":
        return {
            **base,
            **OFFLINE,
            **GATE_OFF,
            "router.mode": "local",
            "router.backends.thx01.enabled": True,
            "router.backends.thx01.timeout_ms": OFFLINE_TIMEOUT_MS,
            "router.chains.local": ["thx01"],
        }
    if kind == "jev":
        from metis_auto.wiring.live import live_overrides

        return {
            **base,
            **OFFLINE,
            **GATE_OFF,
            **live_overrides(),
            "router.mode": "hosted",
            "router.backends.jev_metis.enabled": True,
            "router.backends.jev_metis.timeout_ms": JEV_TIMEOUT_MS,
            "router.chains.hosted": ["jev_metis"],
        }
    raise ValueError(kind)


def build(kind: str, *, ledger=None, backends=None):
    from metis_auto.adapters.system import SystemClock
    from metis_auto.domain.routing import DecisionRouterConfig
    from metis_auto.wiring.from_settings import pipeline_config
    from metis_auto.wiring.router_replay import replay_pipeline
    from metis_auto.wiring.routers import router_spec

    loaded = _settings(router_overrides(kind))
    policy = pipeline_config(loaded).routing.decision_router or DecisionRouterConfig()
    spec = (
        None
        if kind in ("rules", "rule_based")
        else router_spec(
            loaded,
            policy,
            backends=backends,
            spend_ledger=ledger,
            states_dataset_derived=False,  # SYNTHETIC: never dataset text
        )
    )
    pipe, sink = replay_pipeline(
        loaded, spec, run_id=f"run-synth-{kind}", clock=SystemClock()
    )
    tiers = {
        e.model_id: e.tier
        for e in loaded.reference.catalogue.entries
        if getattr(e, "tier", None) is not None
    }
    return loaded, pipe, sink, tiers


def observe(pipe, sink, tiers, record) -> dict[str, Any]:
    from metis_auto.domain.routing.decision import answer_strength
    from metis_auto.evaluation.router_slice.records import to_request

    request = to_request(record, profile="pre_retrieval")
    sink.events.clear()
    t0 = time.perf_counter()
    pipe.handle(request)
    out: dict[str, Any] = {
        "id": record["slice_record_id"],
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "target": None,
        "tier": None,
        "path": None,
        "status": "off",
    }
    for e in sink.events:
        p = e.payload
        if p.event_type == "routing_decided":
            out["target"] = p.decision.target_model_id
            out["tier"] = tiers.get(p.decision.target_model_id)
            if p.decision.router_summary:
                out["path"] = p.decision.router_summary.path.value
        elif p.event_type == "decision_measured":
            o = p.outcome
            out["status"] = o.status.value
            out["decide_ms"] = e.duration_ms
            for name in ("failure_reason", "skip_reason", "rule_id"):
                value = getattr(o, name, None)
                if value is not None:
                    out[name] = getattr(value, "value", str(value))
            r = o.result
            if r is not None:
                out["model_revision"] = r.model_revision
                out["backend_latency_ms"] = r.latency_ms
                amount = r.cost.amount.amount if r.cost and r.cost.amount else None
                out["cost_usd"] = None if amount is None else str(amount)
                if r.usage is not None:
                    out["input_tokens"] = r.usage.input.tokens
                out["answers"] = [
                    {
                        "q": a.question_id,
                        "confidence": a.confidence,
                        "strength_prob": answer_strength(a, "probability"),
                        "value": (
                            a.score
                            if getattr(a, "score", None) is not None
                            else a.p_yes
                            if getattr(a, "p_yes", None) is not None
                            else getattr(a, "choice", None)
                        ),
                    }
                    for a in r.answers
                ]
    return out


# ------------------------------------------------------------------- commands
def jev_estimate(loaded, rows, keep_marker):
    from metis_auto.adapters.system import SystemClock
    from metis_auto.domain.routing import DecisionRouterConfig
    from metis_auto.settings import JevMetisBackendSettings
    from metis_auto.wiring.routers import backend_builder

    router = loaded.settings.router
    questions = loaded.reference.router_questions.get(
        router.question_set, router.question_language
    )
    base = router.backends.get("jev_metis")
    settings = base if isinstance(base, JevMetisBackendSettings) else None
    backend = backend_builder(
        "jev_metis",
        (settings or JevMetisBackendSettings()).model_copy(update={"enabled": True}),
        DecisionRouterConfig(),
        assets=None,
        assets_root=loaded.path(loaded.settings.paths.router_assets),
        loaded=loaded,
        questions=questions,
    )(SystemClock())
    total = Decimal(0)
    for r in rows:
        chars = len(text(r["message"], keep_marker)) + len(
            text(r["previous_user_turn"], keep_marker)
        )
        est = backend.estimate_cost(chars + 64)  # >= 1 token per character, + framing
        if est is None or est.cost.amount is None:
            return None
        total += est.cost.amount.amount
    return total


def cmd_plan(args) -> dict[str, Any]:
    from metis_auto.wiring.from_settings import live_permission

    rows = load_rows()
    loaded = _settings(router_overrides("jev"))
    total = jev_estimate(loaded, rows, args.keep_marker)
    permission = live_permission(loaded)
    budget = loaded.settings.budget
    cap = min(budget.run_cap or RUN_CAP, RUN_CAP)
    return {
        "action": "plan",
        "rows": len(rows),
        "jev_calls": len(rows),
        "jev_upper_bound_usd": None if total is None else format(total, "f"),
        "run_cap_usd": format(cap, "f"),
        "fits": total is not None and total <= cap,
        "key_set": loaded.secrets.metis_api_key is not None,
        "live_allowed": permission.allowed,
        "blocked_because": list(permission.reasons),
        "marker_sent": args.keep_marker,
        "note": "plan makes no call; the cascade's spend guard enforces the cap per call",
    }


def run_kind(kind, rows, keep_marker, *, ledger=None, backends=None, progress=True):
    _, pipe, sink, tiers = build(kind, ledger=ledger, backends=backends)
    out = []
    for i, row in enumerate(rows, 1):
        out.append(observe(pipe, sink, tiers, to_record(row, keep_marker)))
        if progress and kind in ("thx01", "jev") and (i % 10 == 0 or i == len(rows)):
            print(f"  {kind}: {i}/{len(rows)}", file=sys.stderr, flush=True)
    return out


def cmd_local(args, backends=None) -> dict[str, Any]:
    rows = load_rows()
    t0 = time.perf_counter()
    result = {"action": "local", "marker_sent": args.keep_marker}
    for kind in ("rules", "rule_based", "gate", "thx01"):
        print(f"[{kind}]", file=sys.stderr, flush=True)
        result[kind] = run_kind(
            kind, rows, args.keep_marker, backends=(backends or {}).get(kind)
        )
    result["total_s"] = round(time.perf_counter() - t0, 1)
    return result


def cmd_jev(args, ledger=None, backends=None) -> dict[str, Any]:
    from metis_auto.adapters.system import FileSpendLedger
    from metis_auto.contracts import Money
    from metis_auto.wiring.from_settings import live_permission

    plan = cmd_plan(args)
    out: dict[str, Any] = {"action": "jev", "plan": plan}
    if ledger is None:
        if not plan["key_set"]:
            out["skipped"] = "METIS_API_KEY is not set: no live call was made"
            return out
        if not plan["live_allowed"]:
            out["skipped"] = "live calls are blocked (see plan.blocked_because)"
            return out
        if not args.yes:
            out["skipped"] = "add --yes (the owner's approval) to make the calls"
            return out
        if not plan["fits"]:
            out["skipped"] = "the plan does not fit the run cap"
            return out
        loaded = _settings(router_overrides("jev"))
        if not live_permission(loaded).allowed:
            out["skipped"] = "live calls are blocked"
            return out
        budget = loaded.settings.budget
        assert budget.lifetime_cap is not None
        ledger = FileSpendLedger(
            loaded.path(loaded.settings.paths.spend_ledger),
            run_id="jev-synth-eval",
            lifetime_cap=Money(amount=budget.lifetime_cap, currency=budget.currency),
            run_cap=Money(
                amount=Decimal(plan["run_cap_usd"]), currency=budget.currency
            ),
            warn_at=budget.warn_at,
        )
    rows = load_rows()
    t0 = time.perf_counter()
    out["jev"] = run_kind(
        "jev", rows, args.keep_marker, ledger=ledger, backends=backends
    )
    out["total_s"] = round(time.perf_counter() - t0, 1)
    left = ledger.remaining()
    out["ledger_remaining_usd"] = None if left is None else str(left.amount)
    return out


# --------------------------------------------------------------------- report
def _q(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return {"n": 0}

    def at(p):
        return round(v[min(len(v) - 1, max(0, math.ceil(p * len(v)) - 1))], 4)

    return {
        "n": len(v),
        "min": round(v[0], 4),
        "p10": at(0.1),
        "p50": at(0.5),
        "p90": at(0.9),
        "max": round(v[-1], 4),
    }


def _bin(tier):
    return None if tier is None else min(int(tier), 1)


def _score(rows, labels, pred):
    n = len(rows)
    have = [r for r in rows if pred.get(r["id"]) is not None]
    right = sum(_bin(pred[r["id"]]) == labels[r["id"]] for r in have)
    under = sum(labels[r["id"]] == 1 and _bin(pred[r["id"]]) == 0 for r in have)
    over = sum(labels[r["id"]] == 0 and _bin(pred[r["id"]]) == 1 for r in have)
    ones = sum(labels[r["id"]] == 1 for r in rows)
    zeros = n - ones
    return {
        "n": n,
        "decided": len(have),
        "correct": right,
        "accuracy": round(right / n, 3) if n else None,
        "under_routed_1_to_0": under,
        "over_routed_0_to_1": over,
        "tier1_recall": round(
            sum(labels[r["id"]] == 1 and _bin(pred.get(r["id"])) == 1 for r in rows)
            / ones,
            3,
        )
        if ones
        else None,
        "tier0_recall": round(
            sum(labels[r["id"]] == 0 and _bin(pred.get(r["id"])) == 0 for r in rows)
            / zeros,
            3,
        )
        if zeros
        else None,
    }


def cmd_report(_args) -> dict[str, Any]:
    rows = load_rows()
    labels = {r["id"]: int(r["final_tier"]) for r in rows}
    local = json.loads((OUT / "local.json").read_text(encoding="utf-8"))
    jev_path = OUT / "jev.json"
    jev = json.loads(jev_path.read_text(encoding="utf-8")) if jev_path.exists() else {}
    by = {
        k: {o["id"]: o for o in local.get(k, [])}
        for k in ("rules", "rule_based", "gate", "thx01")
    }
    by["jev"] = {o["id"]: o for o in jev.get("jev", [])}

    def tier(kind, rid):
        return (by[kind].get(rid) or {}).get("tier")

    def configured(model):
        out = {}
        for r in rows:
            g = by["gate"].get(r["id"]) or {}
            out[r["id"]] = (
                g.get("tier") if g.get("path") == "fast_rules" else tier(model, r["id"])
            )
        return out

    preds = {
        "rules": {r["id"]: tier("rules", r["id"]) for r in rows},
        "rule_based": {r["id"]: tier("rule_based", r["id"]) for r in rows},
        "thx01": {r["id"]: tier("thx01", r["id"]) for r in rows},
        "jev": {r["id"]: tier("jev", r["id"]) for r in rows} if by["jev"] else None,
        "thx01_with_gate": configured("thx01"),
        "jev_with_gate": configured("jev") if by["jev"] else None,
    }
    preds = {k: v for k, v in preds.items() if v is not None}
    slices = {
        "all": rows,
        "persian": [r for r in rows if r["language"] == "fa"],
        "english": [r for r in rows if r["language"] == "en"],
        "mixed": [r for r in rows if r["language"] == "mixed"],
        "borderline": [r for r in rows if r["borderline"] == "1"],
        "changed_by_owner": [r for r in rows if r["changed_by_owner"] == "1"],
    }
    accuracy = {
        s: {k: _score(rs, labels, p) for k, p in preds.items()} if rs else {"n": 0}
        for s, rs in slices.items()
    }
    categories = sorted({r["category"] for r in rows})
    by_category = {
        c: {
            k: _score([r for r in rows if r["category"] == c], labels, p)["accuracy"]
            for k, p in preds.items()
        }
        for c in categories
    }
    names = [k for k in ROUTERS if k in preds]
    agreement = {}
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            both = [
                r["id"]
                for r in rows
                if preds[a][r["id"]] is not None and preds[b][r["id"]] is not None
            ]
            same = sum(_bin(preds[a][x]) == _bin(preds[b][x]) for x in both)
            agreement[f"{a}~{b}"] = {
                "n": len(both),
                "agree": same,
                "share": round(same / len(both), 3) if both else None,
            }
    for rules_kind in ("rules", "rule_based"):
        trio = [rules_kind, "thx01", "jev"]
        if all(k in preds for k in trio):
            ids = [
                r["id"]
                for r in rows
                if all(preds[k][r["id"]] is not None for k in trio)
            ]
            agreement[f"all_three({rules_kind}, thx01, jev)"] = {
                "n": len(ids),
                "agree": sum(len({_bin(preds[k][x]) for k in trio}) == 1 for x in ids),
                "share": round(
                    sum(len({_bin(preds[k][x]) for k in trio}) == 1 for x in ids)
                    / len(ids),
                    3,
                )
                if ids
                else None,
            }
    routers = {}
    for k in ("thx01", "jev"):
        obs = list(by[k].values())
        if not obs:
            continue
        cost = [Decimal(o["cost_usd"]) for o in obs if o.get("cost_usd")]
        routers[k] = {
            "status": dict(Counter(o["status"] for o in obs)),
            "path": dict(Counter(o.get("path") for o in obs)),
            "failure_reasons": dict(
                Counter(o["failure_reason"] for o in obs if o.get("failure_reason"))
            ),
            "model_revision": dict(
                Counter(o.get("model_revision") for o in obs if o.get("model_revision"))
            ),
            "decide_ms": _q([o.get("decide_ms") for o in obs]),
            "backend_latency_ms": _q([o.get("backend_latency_ms") for o in obs]),
            "input_tokens": _q([o.get("input_tokens") for o in obs]),
            "cost_total_usd": format(sum(cost, Decimal(0)), "f"),
            "cost_per_call_usd": format(sum(cost, Decimal(0)) / len(cost), "f")
            if cost
            else None,
            "answered_by_model_accuracy": _score(
                [
                    r
                    for r in rows
                    if (by[k].get(r["id"]) or {}).get("path")
                    in ("slow_local", "slow_hosted")
                ],
                labels,
                preds[k],
            ),
        }
        qs: dict[str, dict[str, list]] = {}
        for o in obs:
            for a in o.get("answers", []):
                d = qs.setdefault(a["q"], {"confidence": [], "prob": [], "missing": 0})
                d["confidence"].append(a["confidence"])
                d["prob"].append(a["strength_prob"])
                d["missing"] += a["confidence"] is None
        routers[k]["confidence_by_question"] = {
            q: {
                "reported_confidence": _q(d["confidence"]),
                "confidence_missing": d["missing"],
                "probability_strength": _q(d["prob"]),
            }
            for q, d in qs.items()
        }
    gate_obs = list(by["gate"].values())
    gate = {
        "gated_rows": sum(o.get("path") == "fast_rules" for o in gate_obs),
        "gate_rules": dict(
            Counter(o.get("rule_id") for o in gate_obs if o.get("path") == "fast_rules")
        ),
    }
    disagreements = []
    for r in rows:
        p = {k: _bin(preds[k][r["id"]]) for k in names}
        if any(v != labels[r["id"]] for v in p.values()):
            disagreements.append(
                {
                    "id": r["id"],
                    "language": r["language"],
                    "category": r["category"],
                    "label": labels[r["id"]],
                    "borderline": r["borderline"] == "1",
                    **p,
                }
            )
    return {
        "set": json.loads(MANIFEST.read_text(encoding="utf-8")),
        "marker_sent": local.get("marker_sent"),
        "jev_ran": bool(by["jev"]),
        "jev_skipped": jev.get("skipped"),
        "accuracy": accuracy,
        "accuracy_by_category": by_category,
        "agreement": agreement,
        "gate": gate,
        "routers": routers,
        "jev_ledger_remaining_usd": jev.get("ledger_remaining_usd"),
        "rows_with_any_error": disagreements,
        "limits": [
            "SYNTHETIC requests written for this check, not real traffic: lengths, topics and phrasing differ from the dataset.",
            "Labels are one person's judgement (the owner); no second rater, no agreement measure.",
            "n = 100 (70 / 15 / 15 by language; 5 borderline): per-language and per-category numbers rest on 15 or fewer rows each.",
            "Tier 0/1 only: router tiers >= 1 count as 1. Accuracy is against labels, not answer quality.",
            "Models asked with the gate off and offline settings (no inline deadline, no router cache, confidence gate off).",
            "A first signal, not proof.",
        ],
    }


def render_md(rep: dict[str, Any]) -> str:
    L = []
    names = list(rep["accuracy"]["all"].keys())
    L.append("# Decision quality, first signal (jev-synth-v1)\n")
    L.append(
        f"100 SYNTHETIC requests, owner labels (60 tier 0 / 40 tier 1). Marker sent: {rep['marker_sent']}. Jev ran: {rep['jev_ran']}"
        + (f" (skipped: {rep['jev_skipped']})" if rep.get("jev_skipped") else "")
        + ".\n"
    )
    L.append("## Accuracy against the labels\n")
    L.append("| Slice | n | " + " | ".join(names) + " |")
    L.append("|---|---|" + "---|" * len(names))
    for s, block in rep["accuracy"].items():
        if block.get("n") == 0:
            L.append(f"| {s} | 0 | " + " | ".join("—" for _ in names) + " |")
            continue
        n = next(iter(block.values()))["n"]
        L.append(
            f"| {s} | {n} | "
            + " | ".join(
                f"{b['accuracy']:.0%} ({b['correct']})"
                if b["accuracy"] is not None
                else "—"
                for b in block.values()
            )
            + " |"
        )
    L.append("\n## Errors by direction (all rows)\n")
    L.append(
        "| Router | under-routed (label 1 → 0, quality risk) | over-routed (label 0 → 1, cost) | tier-1 recall | tier-0 recall | no decision |"
    )
    L.append("|---|---|---|---|---|---|")
    for k, b in rep["accuracy"]["all"].items():
        L.append(
            f"| {k} | {b['under_routed_1_to_0']} | {b['over_routed_0_to_1']} | {b['tier1_recall']} | {b['tier0_recall']} | {b['n'] - b['decided']} |"
        )
    L.append("\n## Agreement between routers (tier 0/1)\n")
    for k, v in rep["agreement"].items():
        L.append(f"- {k}: {v['agree']}/{v['n']}")
    L.append(
        f"\nGate (as configured): {rep['gate']['gated_rows']} rows decided by the fast gate {rep['gate']['gate_rules']}.\n"
    )
    L.append("## Accuracy by category\n")
    L.append("| Category | " + " | ".join(names) + " |")
    L.append("|---|" + "---|" * len(names))
    for c, v in rep["accuracy_by_category"].items():
        L.append(
            f"| {c} | "
            + " | ".join("—" if x is None else f"{x:.0%}" for x in v.values())
            + " |"
        )
    for k, r in rep["routers"].items():
        L.append(f"\n## {k}: status, cost, latency\n")
        L.append(
            f"- status {r['status']}; path {r['path']}; failures {r['failure_reasons'] or 'none'}; version {r['model_revision']}"
        )
        L.append(
            f"- accuracy where the model itself decided (not a fallback): {r['answered_by_model_accuracy']['accuracy']} on {r['answered_by_model_accuracy']['n']} rows"
        )
        L.append(f"- decide_ms {r['decide_ms']}")
        L.append(
            f"- cost total {r['cost_total_usd']} USD, per call {r['cost_per_call_usd']}; input tokens {r['input_tokens']}"
        )
        L.append(
            "\n| Question | reported confidence (n, p10, p50, p90) | missing | probability strength (p10, p50, p90) |"
        )
        L.append("|---|---|---|---|")
        for q, d in r["confidence_by_question"].items():
            c, p = d["reported_confidence"], d["probability_strength"]
            L.append(
                f"| {q} | {c.get('n')}, {c.get('p10')}, {c.get('p50')}, {c.get('p90')} | {d['confidence_missing']} | {p.get('p10')}, {p.get('p50')}, {p.get('p90')} |"
            )
    L.append("\n## Rows where at least one router missed the label\n")
    cols = [k for k in ROUTERS if k in names]
    L.append("| id | lang | category | label | " + " | ".join(cols) + " | borderline |")
    L.append("|---|---|---|---|" + "---|" * len(cols) + "---|")
    for d in rep["rows_with_any_error"]:
        L.append(
            f"| {d['id']} | {d['language']} | {d['category']} | {d['label']} | "
            + " | ".join(str(d.get(k)) for k in cols)
            + f" | {'yes' if d['borderline'] else ''} |"
        )
    L.append("\n## Limits\n")
    L.extend(f"- {x}" for x in rep["limits"])
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("action", choices=["plan", "local", "jev", "report"])
    ap.add_argument(
        "--yes", action="store_true", help="the owner approved the live Jev run"
    )
    ap.add_argument(
        "--keep-marker", action="store_true", help="send the [SYNTHETIC] marker"
    )
    args = ap.parse_args()
    if args.action == "plan":
        out = cmd_plan(args)
    elif args.action == "local":
        out = cmd_local(args)
    elif args.action == "jev":
        out = cmd_jev(args)
    else:
        out = cmd_report(args)
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "report.md").write_text(render_md(out), encoding="utf-8")
    name = {
        "plan": "plan.json",
        "local": "local.json",
        "jev": "jev.json",
        "report": "report.json",
    }[args.action]
    target = REPORT_DIR if args.action == "report" else OUT
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if args.action in ("plan", "report"):
        print(
            json.dumps(
                out if args.action == "plan" else {"wrote": "report.md, report.json"},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(
            json.dumps(
                {k: v for k, v in out.items() if k not in (*ROUTERS, "gate")},
                indent=2,
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
