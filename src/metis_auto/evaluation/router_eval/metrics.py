"""R8 metrics over shadow rows (pure; exp-route-013).

Every number is a count, a share or a timing: no text, no identifier beyond
the opaque slice record ID (which never leaves ``runs/``; ``summarise`` does
not output it). Two views of every block:

- ``balanced``: each record counts once (the slice's own composition);
- ``traffic_weighted``: each record counts ``traffic_weight`` (owner,
  2026-11-02; ``weights.py``), so the block estimates the traffic mix.
  Records without a weight are left out of this view and counted.

Blocks: ``all``, ``tune`` and ``check`` (the slice's split; thresholds are
fitted on tune only), and the same per language group, Persian first.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

LANGUAGE_ORDER = ("persian", "mixed", "english", "other_arabic_script", "structured")
"""Persian first (owner): the groups are reported in this order; any other
group follows alphabetically."""


@dataclass(frozen=True)
class ShadowRow:
    """One request under the rules alone and under the decision router."""

    record_id: str
    split: str
    language_group: str
    weight: float | None
    rules_tier: int | None
    router_tier: int | None
    """The routed model's catalogue tier with the router; None when no model."""
    router_path: str
    decision_status: str
    """``answered``, ``skipped`` (the gate), ``failed`` or ``off``."""
    confidence: float | None
    """Lowest reported confidence over the gate's questions (Q-61)."""
    below_gate: bool
    decide_ms: float | None
    strengths: tuple[tuple[str, float | None, float | None], ...] = ()
    """Per answered question: (question ID, reported confidence, probability
    strength) as ``domain.routing.decision.answer_strength`` reads them."""
    gate_reported: float | None = None
    """Lowest reported confidence over the gate's questions (mapping, Q-61)."""
    gate_probability: float | None = None
    """Lowest probability strength over the same questions."""


def _share(counter: Counter, total: float) -> dict[str, float]:
    if total <= 0:
        return {}
    return {k: round(v / total, 4) for k, v in sorted(counter.items())}


def _pct(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)

    def at(q: float) -> float:
        return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 2)

    return {
        "n": len(ordered),
        "p50": round(statistics.median(ordered), 2),
        "p95": at(0.95),
        "max": round(ordered[-1], 2),
    }


def _block(rows: Sequence[ShadowRow], weighted: bool) -> dict:
    use = [r for r in rows if not weighted or r.weight is not None]
    w = {id(r): (r.weight if weighted else 1.0) or 0.0 for r in use}
    total = sum(w.values())
    rules_mix: Counter = Counter()
    router_mix: Counter = Counter()
    status: Counter = Counter()
    paths: Counter = Counter()
    agree = both = 0.0
    up = down = 0.0
    below = answered = 0.0
    for r in use:
        x = w[id(r)]
        rules_mix[str(r.rules_tier) if r.rules_tier is not None else "none"] += x
        router_mix[str(r.router_tier) if r.router_tier is not None else "none"] += x
        status[r.decision_status] += x
        paths[r.router_path] += x
        if r.rules_tier is not None and r.router_tier is not None:
            both += x
            if r.rules_tier == r.router_tier:
                agree += x
            elif r.router_tier > r.rules_tier:
                up += x
            else:
                down += x
        if r.decision_status == "answered":
            answered += x
            if r.below_gate:
                below += x
    confidences = [r.confidence for r in use if r.confidence is not None]
    latencies = [r.decide_ms for r in use if r.decide_ms is not None]
    return {
        "records": len(use),
        "left_out_without_weight": len(rows) - len(use) if weighted else 0,
        "weight_total": round(total, 4),
        "tier_mix_rules": _share(rules_mix, total),
        "tier_mix_router": _share(router_mix, total),
        "agreement": round(agree / both, 4) if both else None,
        "router_higher_tier_share": round(up / both, 4) if both else None,
        "router_lower_tier_share": round(down / both, 4) if both else None,
        "decision_status": _share(status, total),
        "gate_skip_share": round(status.get("skipped", 0) / total, 4)
        if total
        else None,
        "below_confidence_gate_share": round(below / answered, 4) if answered else None,
        "path_mix": _share(paths, total),
        "confidence": {
            "n": len(confidences),
            "p10": round(sorted(confidences)[int(0.1 * len(confidences))], 3)
            if confidences
            else None,
            "p50": round(statistics.median(confidences), 3) if confidences else None,
            "p90": round(
                sorted(confidences)[
                    min(len(confidences) - 1, int(0.9 * len(confidences)))
                ],
                3,
            )
            if confidences
            else None,
        },
        "decision_step_ms": _pct(latencies),
    }


def _views(rows: Sequence[ShadowRow]) -> dict:
    return {"balanced": _block(rows, False), "traffic_weighted": _block(rows, True)}


def _languages(rows: Sequence[ShadowRow]) -> list[str]:
    seen = {r.language_group for r in rows}
    head = [g for g in LANGUAGE_ORDER if g in seen]
    return head + sorted(seen - set(LANGUAGE_ORDER))


def summarise(rows: Iterable[ShadowRow]) -> dict:
    """The R8 comparison of rules-only and the decision router: per split
    (all, tune, check) and per language group (Persian first), each with a
    balanced and a traffic-weighted view. Content-free."""
    rows = list(rows)
    by_split: dict[str, list[ShadowRow]] = defaultdict(list)
    for r in rows:
        by_split[r.split].append(r)
    out = {"records": len(rows), "splits": {"all": _views(rows)}}
    for split in ("tune", "check"):
        out["splits"][split] = _views(by_split.get(split, []))
    out["languages"] = {
        g: _views([r for r in rows if r.language_group == g]) for g in _languages(rows)
    }
    return out


def against_labels(
    rows: Iterable[ShadowRow], labels: Mapping[str, int]
) -> dict[str, object]:
    """Tier accuracy of rules and router against labels by record ID (L4
    synthetic labels in CI; L1/L3 once they exist). Unlabelled records are
    counted, never guessed."""
    n = rules_ok = router_ok = unlabelled = 0
    confusion: Counter = Counter()
    for r in rows:
        label = labels.get(r.record_id)
        if label is None:
            unlabelled += 1
            continue
        n += 1
        rules_ok += r.rules_tier == label
        router_ok += r.router_tier == label
        confusion[f"label={label}|router={r.router_tier}"] += 1
    return {
        "labelled": n,
        "unlabelled": unlabelled,
        "rules_accuracy": round(rules_ok / n, 4) if n else None,
        "router_accuracy": round(router_ok / n, 4) if n else None,
        "router_confusion": dict(sorted(confusion.items())),
    }


def _quantiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"n": 0, "min": None, "p10": None, "p50": None, "p90": None}
    v = sorted(values)

    def at(q: float) -> float:
        return round(v[min(len(v) - 1, int(q * len(v)))], 3)

    return {
        "n": len(v),
        "min": round(v[0], 3),
        "p10": at(0.10),
        "p50": round(statistics.median(v), 3),
        "p90": at(0.90),
    }


def answer_distributions(rows: Iterable[ShadowRow]) -> dict[str, dict]:
    """Per question: the distribution of the reported confidence and of the
    probability strength over answered records."""
    reported: dict[str, list[float]] = defaultdict(list)
    probability: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        for qid, conf, prob in r.strengths:
            if conf is not None:
                reported[qid].append(conf)
            if prob is not None:
                probability[qid].append(prob)
    return {
        q: {
            "reported_confidence": _quantiles(reported.get(q, [])),
            "probability": _quantiles(probability.get(q, [])),
        }
        for q in sorted(set(reported) | set(probability))
    }


GATE_KEEP_SHARE = 0.8
"""The provisional gate rule (declared before the results, 2026-11-03): on the
tune split, keep the most certain 80% of answered records, i.e. the threshold
is the tune split's 20th percentile of the gate value. To be recalibrated on
labels (L1/L3)."""


def propose_gate(
    rows: Iterable[ShadowRow], *, keep_share: float = GATE_KEEP_SHARE
) -> dict[str, object]:
    """For each gate statistic: the threshold from the **tune** split and its
    effect on the **check** split (share gated; tier mix and agreement with the
    rules when gated records fall back to the rules). Provisional."""
    rows = list(rows)
    out: dict[str, object] = {"keep_share_on_tune": keep_share}
    for name, attr in (
        ("reported", "gate_reported"),
        ("probability", "gate_probability"),
    ):
        tune = sorted(
            getattr(r, attr)
            for r in rows
            if r.split == "tune" and getattr(r, attr) is not None
        )
        if not tune:
            out[name] = {"threshold": None, "tune_answered": 0}
            continue
        threshold = round(
            tune[min(len(tune) - 1, int(round((1 - keep_share) * len(tune), 9)))], 4
        )
        check = [r for r in rows if r.split == "check" and getattr(r, attr) is not None]
        gated = [r for r in check if getattr(r, attr) < threshold]
        mix: Counter = Counter()
        agree = both = 0
        for r in check:
            tier = r.rules_tier if getattr(r, attr) < threshold else r.router_tier
            mix[str(tier) if tier is not None else "none"] += 1
            if tier is not None and r.rules_tier is not None:
                both += 1
                agree += tier == r.rules_tier
        out[name] = {
            "threshold": threshold,
            "tune_answered": len(tune),
            "check_answered": len(check),
            "check_gated_share": round(len(gated) / len(check), 4) if check else None,
            "check_tier_mix_with_gate": _share(mix, len(check)),
            "check_agreement_with_rules_with_gate": round(agree / both, 4)
            if both
            else None,
        }
    return out
