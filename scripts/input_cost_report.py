"""Full-prompt INPUT cost report over the sample (Stage E3, offline).

    python scripts/input_cost_report.py [--min-n N] [--max-age-days D]
        [--as-of YYYY-MM-DD] [--out-dir reports/cost]

For every replay case of the sample, counts the assumed full input
(instructions, history, retrieved context, message; no compression) with each
catalogue model's own tokenizer, then writes **aggregates only** (counts,
statistics, rankings, instruction-reuse counts, bucket-versus-token reports):
no text, no hash, no per-case value (CLAUDE.md). Costs are INPUT-ONLY,
UNCACHED LOWER BOUNDS from the historical price snapshot, with the table's age;
no output, reasoning or provider-cache scenario is set (E2), and nothing here
is a billed or measured cost. The sample is exploratory (ADR-0008): provisional.

``--min-n`` and ``--max-age-days`` have no default: unset means slices are
``descriptive`` (no ranking claim) and the price age is ``not_evaluated``.
Reads data/sample_data/raw/data.json read-only; never modifies it. No network,
no model call, no key. The output file is new and never overwrites another.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import secrets
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.data_access.replay_cases.builder import build_all
from metis_auto.data_access.sample import SampleDataSource
from metis_auto.domain.features.detectors import LanguageConfig
from metis_auto.evaluation.inputs import build_report, case_inputs
from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.tokenizers import build_tokenizers

SAMPLE = Path("data/sample_data/raw/data.json")


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ms(self) -> float:
        return 0.0


def _plain(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value == float("inf"):
        return "inf"
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-n", type=int, default=None)
    parser.add_argument("--max-age-days", type=int, default=None)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--out-dir", type=Path, default=Path("reports/cost"))
    args = parser.parse_args()

    root = repo_root()
    loaded = load_settings(environ={}, dotenv=None, runtime=None)
    tokens = build_tokenizers(loaded)
    # a random key: group IDs live in memory only and are never written
    fingerprinter = Fingerprinter(secrets.token_bytes(32))
    measurement = MeasurementService(
        fingerprinter,
        _Clock(),
        ApproxCharsTokenizer(),
        tokenizers=tokens.tokenizers,
        templates=tokens.templates,
    )
    path = root / SAMPLE
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    source = SampleDataSource(
        path,
        lambda purpose, raw: fingerprinter.fingerprint(purpose, raw),
        missing_key=loaded.settings.experiment.data.missing_key,
    )
    cases, exclusions = build_all(list(source.sessions()))
    entries = list(loaded.reference.catalogue.entries)
    bounds = loaded.settings.pipeline["features"]["length_bounds"]
    inputs = [
        case_inputs(
            c,
            measurement=measurement,
            entries=entries,
            fingerprinter=fingerprinter,
            language=LanguageConfig(),
            length_bounds=bounds,
        )
        for c in cases
    ]
    report = build_report(
        inputs,
        models=entries,
        prices=loaded.reference.prices,
        min_n=args.min_n,
        as_of=args.as_of,
        max_age_days=args.max_age_days,
        char_bounds=bounds,
    )
    result = {
        "kind": "ESTIMATE: full-prompt input token counts and input-only uncached "
        "cost lower bounds on the sample; not billed tokens, not measured costs",
        "generated_on": args.as_of.isoformat(),
        "sample_sha256": digest,
        "exclusions": [e.model_dump(mode="json") for e in exclusions],
        "tokenizers": [
            {"ref": s.ref, "counted_with": s.loaded, "fidelity": s.fidelity}
            for s in tokens.status
        ],
        "price_table_version": loaded.reference.prices.version,
        "min_n": args.min_n,
        "report": _plain(report),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"input_cost_full_prompt-{args.as_of.isoformat()}.json"
    if out.exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 1
    out.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"written": str(out), "cases": report.cases, "slices": len(report.slices)}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
