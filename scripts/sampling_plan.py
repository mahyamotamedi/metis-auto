"""Show the sampling plan's per-slice sample sizes BEFORE any run (Stage E4,
offline).

    python scripts/sampling_plan.py [--config path.toml] [--min-n N]

Builds one sampling unit per sample replay case (strata from the E3 case inputs
plus the attachment flag), then prints, aggregates only: the population per
slice, and, if ``--config`` gives an ``[allocation]`` table (``dimensions``,
``total``, ``seed``, optional ``floor_per_cell``, ``pool_below_n``,
``quotas``), the allocation: drawn n per language slice, the population,
sample and weighted shares, quota outcomes, and any budget overrun. With no
config nothing is chosen: every allocation value is unset, and the plan says so.
No case ID, no text, no hash is printed. Reads data/sample_data/raw/data.json
read-only. No network, no model call, no key. This script runs no sampling run.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import tomllib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.data_access.replay_cases.builder import build_all
from metis_auto.data_access.sample import SampleDataSource
from metis_auto.domain.features.detectors import LanguageConfig
from metis_auto.evaluation.inputs import case_inputs
from metis_auto.evaluation.sampling import (
    SamplingUnit,
    parse_allocation_config,
    plan_sample,
    slice_counts,
)
from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.tokenizers import build_tokenizers

SAMPLE = Path("data/sample_data/raw/data.json")


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> float:
        return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--min-n", type=int, default=None)
    args = parser.parse_args()

    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    tokens = build_tokenizers(loaded)
    fingerprinter = Fingerprinter(secrets.token_bytes(32))
    measurement = MeasurementService(
        fingerprinter,
        _Clock(),
        ApproxCharsTokenizer(),
        tokenizers=tokens.tokenizers,
        templates=tokens.templates,
    )
    source = SampleDataSource(
        repo_root() / SAMPLE,
        lambda purpose, raw: fingerprinter.fingerprint(purpose, raw),
        missing_key=loaded.settings.experiment.data.missing_key,
    )
    cases, _ = build_all(list(source.sessions()))
    entries = [e for e in loaded.reference.catalogue.entries if e.enabled][:1]
    bounds = loaded.settings.pipeline["features"]["length_bounds"]
    built = []
    for case in cases:
        got = case_inputs(
            case,
            measurement=measurement,
            entries=entries,
            fingerprinter=fingerprinter,
            language=LanguageConfig(),
            length_bounds=bounds,
        )
        built.append((case, got))
    # opaque category IDs are never printed: numbered strata, largest first
    sizes = Counter(g.strata["category"] for _, g in built if "category" in g.strata)
    numbered = {
        value: f"category_{i + 1}"
        for i, (value, _) in enumerate(
            sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0]))
        )
    }
    units = []
    for case, got in built:
        strata = dict(got.strata)
        if "category" in strata:
            strata["category"] = numbered[strata["category"]]
        logged = sum(len(r.text) for r in case.references[:1])
        units.append(
            SamplingUnit(
                case.case_id, case.session_ref, strata, {"logged_answer_chars": logged}
            )
        )
    raw = {}
    if args.config is not None:
        raw = tomllib.loads(args.config.read_text(encoding="utf-8")).get(
            "allocation", {}
        )
    config = parse_allocation_config(raw)
    plan = plan_sample(units, config)
    out: dict = {
        "kind": "PLAN ONLY: no run was made; sample-derived, provisional (ADR-0008)",
        "units": len(units),
        "population_by_slice": {
            dim: {
                r.value: r.population
                for r in slice_counts(plan, units, dim, min_n=args.min_n)
            }
            for dim in (
                "language",
                "length_bucket",
                "turn_depth",
                "retrieved",
                "attachments",
            )
        },
        "plan_state": plan.state,
        "plan_reason": plan.reason,
    }
    if plan.state == "planned":
        out["requested_total"] = plan.requested_total
        out["achieved_total"] = plan.achieved_total
        out["over_budget_by"] = plan.over_budget_by
        out["quotas"] = [vars(q) for q in plan.quotas]
        out["language"] = [
            vars(r) for r in slice_counts(plan, units, "language", min_n=args.min_n)
        ]
        out["cells"] = [
            {
                "cell": c.label,
                "population": c.population,
                "allocated": c.allocated,
                "achieved": c.achieved,
                "reasons": list(c.reasons),
                "pooled": c.pooled,
            }
            for c in plan.cells
        ]
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
