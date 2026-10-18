"""Show the live-call budget: cumulative spend vs the lifetime cap (ADR-0018).

    python scripts/show_budget.py

Reads settings (defaults, config/local.toml, .env, METIS__* overrides) and the
persistent spend ledger. Prints amounts only: no content, no secrets. Makes
no calls. Thin wrapper: all logic is in metis_auto.wiring and adapters.
"""

from __future__ import annotations

import json

from metis_auto.settings import load_settings
from metis_auto.wiring.from_settings import live_permission, spend_ledger


def main() -> None:
    loaded = load_settings()
    budget = loaded.settings.budget
    report: dict[str, object] = {
        "ledger": str(loaded.path(loaded.settings.paths.spend_ledger)),
        "currency": budget.currency,
        "lifetime_ceiling": str(budget.lifetime_ceiling),
        "lifetime_cap": str(budget.lifetime_cap),
        "run_cap": str(budget.run_cap),
    }
    if budget.capped:
        status = spend_ledger(loaded, "budget-report").status()
        report |= {
            "lifetime_spent": str(status.lifetime_spent),
            "lifetime_used": f"{status.lifetime_fraction:.1%}",
            "charges": status.charges,
        }
    permission = live_permission(loaded)
    report["live_allowed"] = permission.allowed
    report["live_blocked_by"] = list(permission.reasons)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
