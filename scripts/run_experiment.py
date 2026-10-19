"""Run one experiment config (docs/experiments/framework.md §5).

    python scripts/run_experiment.py <experiments/<area>/<id>-<slug>/config.toml>
        [--set key=value ...] [--report-dir reports/<area>/<id>]

Offline only: no live call is ever made (live experiment runs are not wired
in Stage 8). Writes runs/<EXP-ID>/<run-id>/ (manifest, events, results,
extras; git-ignored) and prints the overall comparison table. With
``--report-dir`` it also writes the content-free summary files (results and
extras JSON plus the comparison table) there for committing. Prints no
content: only IDs, fingerprint-free codes, counts, and money.
Without METIS_FINGERPRINT_KEY the run uses a random key (A-44): fingerprints
and case IDs then do not compare across runs, while every count does.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tomllib
from pathlib import Path

from metis_auto.evaluation.runner import markdown, rows
from metis_auto.wiring.experiments import prepare


def parse_set(items: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for item in items:
        key, sep, raw = item.partition("=")
        if not sep:
            raise SystemExit(f"--set expects key=value, got {item!r}")
        try:
            out[key] = tomllib.loads(f"v = {raw}")["v"]
        except tomllib.TOMLDecodeError:
            out[key] = raw
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()

    prepared = prepare(args.config, overrides=parse_set(args.set) or None)
    try:
        out = prepared.runner.run(prepared.cases.cases, prepared.cases.exclusions)
    finally:
        prepared.sink.close()
    manifest = prepared.runner._s.manifest  # noqa: SLF001 (script access)
    table = rows([(manifest, out.result)])
    text = markdown(table)
    print(f"run: {out.run_dir}")
    print(text)
    if args.report_dir:
        target = args.report_dir / manifest.run_id
        target.mkdir(parents=True, exist_ok=True)
        for name in ("manifest.json", "results.json", "extras.json"):
            shutil.copy(out.run_dir / name, target / name)
        (target / "comparison.md").write_text(text, encoding="utf-8")
        print(f"report files: {target}")
    json.dumps(out.extras)  # extras must stay JSON (content-free counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
