"""What the decision router's choices would cost on the dev slice (R8 cost
view; exp-route-013).

For each slice record, the same **logged** billing tokens are priced on
three models: **today's** model (the logged ``provider_model``, the "today's
models" baseline), the model the **rules** routed to, and the model the
**router** routed to. The price function is injected: wiring builds it from
the team's replay pricing (``analysis.baselines_full.model_row_costs`` over the
``sprint.toml [baselines]`` catalogue and logged-model price table, ADR-0041),
so these numbers price like R-0, R-A3 and R-C3. Two variants:

- ``logged_tokens``: the logged output tokens as they were;
- ``with_expected_reasoning``: plus ``extra_output(model)`` output tokens,
  the rule-based cost model's expected reasoning (a reasoning model's real
  output is larger than another model's logged answer).

Totals and savings are over records where all three are priced; the rest are
counted by reason. A **cost simulation**: token counts are assumed
model-independent (tokenizers differ), the logged answer's length stands in
for each model's, and **quality is not proven**. Pure.
Traces: FR-ROUTE-03, H-1, QA-COST, ADR-0041, ADR-0047. Status: provisional.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from .metrics import ShadowRow

ARMS = ("today", "rules", "router")
PriceFn = Callable[[str, str, int], Decimal | None]
"""(model, record ID, extra output tokens) → cost in USD, or None (unpriced)."""


def compare_costs(
    rows: Iterable[ShadowRow],
    records: Sequence[Mapping[str, Any]],
    *,
    price: PriceFn,
    extra_output: Callable[[str], int],
    price_basis: str,
) -> dict[str, Any]:
    by_id = {str(r["slice_record_id"]): r for r in records}
    rows = list(rows)
    out: dict[str, Any] = {
        "evidence": "cost simulation on logged tokens; quality not proven",
        "price_basis": price_basis,
    }
    for variant in ("logged_tokens", "with_expected_reasoning"):
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            rec = by_id.get(row.record_id)
            if rec is None:
                continue
            models = {
                "today": rec.get("provider_model"),
                "rules": row.rules_target,
                "router": row.router_target,
            }
            costs: dict[str, Decimal] = {}
            missing = None
            for arm, model in models.items():
                if not model:
                    missing = f"{arm}_no_model"
                    break
                extra = extra_output(str(model)) if variant != "logged_tokens" else 0
                value = price(str(model), row.record_id, extra)
                if value is None:
                    missing = f"{arm}_unpriced"
                    break
                costs[arm] = value
            for split in ("all", row.split):
                g = groups.setdefault(split, _empty())
                g["records"] += 1
                if missing is not None:
                    g["unpriced"][missing] += 1
                    continue
                g["priced"] += 1
                for arm in ARMS:
                    g["totals"][arm] += costs[arm]
                g["router_moved_from_today"] += models["router"] != models["today"]
                g["router_differs_from_rules"] += models["router"] != models["rules"]
                g["router_models"][str(models["router"])] += 1
                g["rules_models"][str(models["rules"])] += 1
        out[variant] = {k: _finish(v) for k, v in sorted(groups.items())}
    return out


def _empty() -> dict[str, Any]:
    return {
        "records": 0,
        "priced": 0,
        "unpriced": Counter(),
        "totals": dict.fromkeys(ARMS, Decimal(0)),
        "router_moved_from_today": 0,
        "router_differs_from_rules": 0,
        "router_models": Counter(),
        "rules_models": Counter(),
    }


def _share(saving: Decimal, base: Decimal) -> float | None:
    return round(float(saving / base), 4) if base else None


def _finish(g: dict[str, Any]) -> dict[str, Any]:
    t = g["totals"]
    return {
        "records": g["records"],
        "priced": g["priced"],
        "unpriced": dict(sorted(g["unpriced"].items())),
        "total_usd": {k: format(v.normalize(), "f") for k, v in t.items()},
        "router_saving_vs_today_share": _share(t["today"] - t["router"], t["today"]),
        "rules_saving_vs_today_share": _share(t["today"] - t["rules"], t["today"]),
        "router_saving_vs_rules_share": _share(t["rules"] - t["router"], t["rules"]),
        "router_moved_from_today": g["router_moved_from_today"],
        "router_differs_from_rules": g["router_differs_from_rules"],
        "router_models": dict(sorted(g["router_models"].items())),
        "rules_models": dict(sorted(g["rules_models"].items())),
    }
