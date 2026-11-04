"""Run EXP-COST-001 (free, offline) on the logged requests (sprint plan F-1).

    .venv/bin/python scripts/gemini_thinking_check.py

Reads ``requests.parquet`` (local, git-ignored) and the EDA claims ledger (the
characters-per-token slope ``tok.chars_per_token_slope.all``), writes the
content-free ``reports/cost/exp-cost-001/summary.json``. No network, no model call.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "experiments/cost/exp-cost-001-gemini-thinking/check.py"
LEDGER = ROOT / "reports/full_eda/tables/claims_ledger.csv"
OUT = ROOT / "reports/cost/exp-cost-001/summary.json"
SLOPE = "tok.chars_per_token_slope.all"
MODEL = "gemini-2.5-flash"
COLUMNS = [
    "bot_provider_model",
    "a_bill_outputTokens",
    "a_n_chars",
    "a_bill_cachedInputTokens",
    "a_billing_state",
]


def main() -> int:
    spec = importlib.util.spec_from_file_location("exp_cost_001_check", CHECK)
    check = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = check
    spec.loader.exec_module(check)
    req = pd.read_parquet(
        ROOT / "data/derived/full_eda/requests.parquet", columns=COLUMNS
    )
    req["llm_request"] = (
        req["a_billing_state"].notna() & req["bot_provider_model"].notna()
    )
    slope = float(pd.read_csv(LEDGER).set_index("claim_id").loc[SLOPE, "value"])
    out = check.gemini_thinking(req, model_label=MODEL, chars_per_token=slope)
    out |= {
        "task": "F-1: free Gemini thinking check (offline)",
        "slope_source": (
            f"claims ledger {SLOPE} (instruction characters per input token, "
            "turn-0 OLS): assumed for answer characters, so a signal, not a measure"
        ),
        "created_at": datetime.now(UTC).isoformat(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    m = out["model"]
    print(
        f"{MODEL}: n={m['n']} median ratio {m['median_ratio']:.2f}, "
        f"p90 {m['p90_ratio']:.2f}"
    )
    v = out["verdict"]
    print(
        f"others median of medians {out['others_median_of_medians']:.2f}, "
        f"median p90 {out['others_median_p90']:.2f}"
    )
    print(
        f"median verdict {v['hidden_thinking_looks_likely']}; "
        f"tail verdict {v['heavy_tail_looks_likely']}; "
        f"cached tokens {m['cached_tokens']}"
    )
    for o in out["others"]:
        print(f"  {o['model']}: n={o['n']} median {o['median_ratio']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
