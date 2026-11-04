"""Is a benchmark judge's short reply non-empty and valid? (ADR-0053 amendment 5)

    python scripts/judge_reply_check.py                 # plan only: no call
    python scripts/judge_reply_check.py --run --yes     # one SYNTHETIC pair per judge

Sends one SYNTHETIC pair through the real judge (``LlmPairwiseJudge``: the
benchmark's prompt, reply limit and strict-JSON parser, the request options of
``config/local.toml``) to each model given, and prints whether the reply parsed,
its token usage and cost. Content-free. Uses this machine's local spend ledger
and its caps (ADR-0018); the cost is a fraction of a cent.
"""

from __future__ import annotations

import argparse
import sys

from metis_auto.adapters.system import FileSpendLedger, SystemClock
from metis_auto.contracts import CostBasis, Money
from metis_auto.domain.accounting.cost import cost_of
from metis_auto.evaluation.benchmark.judge import (
    JudgeCallFailed,
    JudgeOutputInvalid,
    LlmPairwiseJudge,
)
from metis_auto.evaluation.judging.types import JudgeRequestView
from metis_auto.wiring.benchmark import Benchmark, _amount
from metis_auto.wiring.from_settings import live_permission

VIEW = JudgeRequestView(
    message="[SYNTHETIC] سلام! Please say hello in one short sentence.",
    instructions="[SYNTHETIC] You are a test assistant.",
)
FIRST = "[SYNTHETIC] Hello!"
SECOND = "[SYNTHETIC] Hi there, I hope you are well today."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--models", nargs="+", default=["deepseek-v4.1-flash"])
    args = parser.parse_args()
    bench = Benchmark()
    loaded = bench.loaded(live=True)
    catalogue = bench.catalogue(loaded)
    cfg = bench.config.judges
    print(
        f"judge reply limit {cfg.max_output_tokens} tokens; models {args.models}; "
        "one call each, SYNTHETIC text"
    )
    permission = live_permission(loaded)
    if not permission.allowed:
        print("live calls are blocked: " + "; ".join(permission.reasons))
        return 1 if args.run else 0
    if not args.run:
        print("plan only; add --run to make the calls")
        return 0
    if not args.yes and input("Make the calls? Type yes: ") != "yes":
        return 0
    b = loaded.settings.budget
    run_id = "judge-reply-check-" + SystemClock().now().strftime("%Y%m%dT%H%M%SZ")
    ledger = FileSpendLedger(
        loaded.path(loaded.settings.paths.spend_ledger),
        run_id=run_id,
        lifetime_cap=Money(amount=b.lifetime_cap, currency=b.currency),
        run_cap=Money(amount=b.run_cap, currency=b.currency),
        warn_at=b.warn_at,
    )
    client_for = bench.live_clients(loaded=loaded, run_id=run_id, ledger=ledger)
    prices = loaded.reference.prices
    for model in args.models:
        entry = catalogue[model]
        judge = LlmPairwiseJudge(
            client_for(model, None),
            model_id=model,
            instruction_language=cfg.instruction_language,
            max_output_tokens=cfg.max_output_tokens,
            price=lambda u, e=entry: _amount(cost_of(u, e, prices, CostBasis.ACTUAL)),
            clock=SystemClock(),
            run_id=run_id,
        )
        try:
            verdict = judge.compare(VIEW, FIRST, SECOND)
            outcome = f"valid reply: choice={verdict.choice}"
        except (JudgeOutputInvalid, JudgeCallFailed) as exc:
            outcome = f"NOT usable: {exc.reason}"
        rec = judge.records[-1]
        print(
            f"{model}: {outcome}; in {rec.input_tokens} out {rec.output_tokens} "
            f"tokens; cost {rec.cost_usd} USD; {rec.latency_ms} ms"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
