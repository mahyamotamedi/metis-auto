"""The decision router's live check (R6; J-4 remapped). SYNTHETIC text only.

    python scripts/router_live_check.py plan                 # no call, no key needed
    python scripts/router_live_check.py run --yes            # the pre-approved calls
    python scripts/router_live_check.py run --yes --out runs/finish_router/live.json
    python scripts/router_live_check.py diagnose --yes    # mimo-v2.5 + json_schema

One tiny call each: Jev via Metis (jev-latest), the LLM-as-System-One backup
on gpt-4.1-nano, gpt-4o-mini and mimo-v2.5, and a response_format json_schema
probe on the OpenAI wrapper. ``plan`` prints every call's pre-call estimate
(upper bound) and keeps calls, in that order, while the total fits the run cap
(the smaller of ``budget.run_cap`` and 0.05 USD). ``run`` charges each call to
the persistent ledger (data/spend/ledger.jsonl) through the spend guard.

Live calls need both keys (ADR-0018): this script asks for ``live``; the
runtime switch comes from config/local.toml or ``METIS__LIVE__ENABLED``, and
METIS_API_KEY from .env or the environment (never read or printed here: only
whether it is set). Without the key, ``run`` skips the calls and says so.
Prints and writes content-free JSON only. Logic: metis_auto.wiring.router_live_check.
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from metis_auto.adapters.system import FileSpendLedger
from metis_auto.contracts import Money
from metis_auto.settings import load_settings
from metis_auto.wiring import router_live_check as lc
from metis_auto.wiring.from_settings import live_permission
from metis_auto.wiring.live import live_overrides


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("action", choices=["plan", "run", "diagnose"])
    ap.add_argument("--yes", action="store_true", help="the owner approved this run")
    ap.add_argument("--out", type=Path, help="also write the JSON here")
    args = ap.parse_args()

    def emit(data: dict) -> None:
        text = json.dumps(data, indent=2, ensure_ascii=False)
        print(text)
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")

    loaded = load_settings(overrides=live_overrides())
    router = loaded.settings.router
    questions = loaded.reference.router_questions.get(
        router.question_set, router.question_language
    )
    budget = loaded.settings.budget
    cap = min(budget.run_cap or lc.RUN_CAP, lc.RUN_CAP)
    planned = lc.plan(loaded, questions, run_cap=cap)
    permission = live_permission(loaded)
    out: dict = {
        "action": args.action,
        "plan": planned,
        "key_set": loaded.secrets.metis_api_key is not None,
        "live_allowed": permission.allowed,
        "blocked_because": list(permission.reasons),
    }
    if args.action == "plan":
        emit(out)
        return 0
    if args.action == "diagnose":
        # At most three tiny calls (two to mimo-v2.5, one to gpt-4o-mini): the
        # plan's per-call bounds, far below the run cap.
        planned = {**planned, "fits": True, "kept": ["diagnose"]}
    if loaded.secrets.metis_api_key is None:
        out["skipped"] = "METIS_API_KEY is not set: no live call was made"
        emit(out)
        return 0
    if not permission.allowed:
        out["skipped"] = "live calls are blocked (see blocked_because)"
        emit(out)
        return 1
    if not args.yes:
        out["skipped"] = "add --yes (the owner's approval) to make the calls"
        emit(out)
        return 1
    if not planned["fits"] or not planned["kept"]:
        out["skipped"] = "nothing fits the run cap"
        emit(out)
        return 1
    assert budget.lifetime_cap is not None
    ledger = FileSpendLedger(
        loaded.path(loaded.settings.paths.spend_ledger),
        run_id="router-live-check",
        lifetime_cap=Money(amount=budget.lifetime_cap, currency=budget.currency),
        run_cap=Money(amount=Decimal(cap), currency=budget.currency),
        warn_at=budget.warn_at,
    )
    if args.action == "diagnose":
        out["diagnose"] = lc.diagnose(loaded, questions, ledger)
    else:
        out["run"] = lc.run(loaded, questions, ledger, keep=tuple(planned["kept"]))
    emit(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
