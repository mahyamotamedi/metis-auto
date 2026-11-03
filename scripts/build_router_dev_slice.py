"""Build, check and report the routing dev slice (ADR-0047;
100–200 records). Thin CLI.

    python scripts/build_router_dev_slice.py plan     # counts only, no text read
    python scripts/build_router_dev_slice.py build    # pass 1, pass 2, outputs
    python scripts/build_router_dev_slice.py verify   # PASS or FAIL vs fingerprint
    python scripts/build_router_dev_slice.py report   # outputs from the local build
    python scripts/build_router_dev_slice.py import-labels <completed_review.csv>

The dataset location is ``[data] full_data_root`` (config/local.toml or
METIS__DATA__FULL_DATA_ROOT; default data/full_data/raw). Prints counts,
durations and peak memory only: never message text, instructions or chunks.
Text is written only to git-ignored folders (data/derived/, runs/). No model
is called and nothing goes over the network.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from metis_auto.adapters.system.resources import peak_rss_mb
from metis_auto.settings import load_settings, repo_root
from metis_auto.wiring.router_slice import DEFAULT_CONFIG, RouterSlice, SliceRefused


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument(
        "command", choices=["plan", "build", "verify", "report", "import-labels"]
    )
    ap.add_argument("file", nargs="?", help="completed review CSV for import-labels")
    ap.add_argument(
        "--config", default=DEFAULT_CONFIG, help="slice config (repo-relative)"
    )
    ap.add_argument(
        "--allow-source-mismatch",
        action="store_true",
        help="build even if the dataset differs from the pins (recorded)",
    )
    ap.add_argument(
        "--skip-source-hash",
        action="store_true",
        help="verify: skip the sha256 of every dataset file (revision checked)",
    )
    args = ap.parse_args()

    root = repo_root()
    settings = load_settings().settings
    started = time.perf_counter()
    try:
        sl = RouterSlice(root, settings.data.full_data_root, root / Path(args.config))
        print(f"Dataset root: {sl.data_root}")
        if args.command == "plan":
            _print(sl.plan())
        elif args.command == "build":
            _print(sl.build(allow_source_mismatch=args.allow_source_mismatch))
        elif args.command == "report":
            _print(sl.report())
        elif args.command == "verify":
            problems = sl.verify(hash_files=not args.skip_source_hash)
            if sl.last_audit:
                _print({k: v for k, v in sl.last_audit.items() if k != "problems"})
            for p in problems:
                print(f"  - {p}")
            print("FAIL" if problems else "PASS")
            if problems:
                return 1
        else:
            if not args.file:
                ap.error("import-labels needs the completed review CSV")
            _print(sl.import_labels(Path(args.file)))
    except SliceRefused as exc:
        print(f"Refused: {exc}")
        return 2
    finally:
        print(
            f"Duration {time.perf_counter() - started:.1f} s; "
            f"peak memory {peak_rss_mb()} MB"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
