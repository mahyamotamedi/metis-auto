"""Load the raw Parquet files into the local PostgreSQL (ADR-0027). Thin CLI.

    python scripts/db_ingest.py --preflight
    python scripts/db_ingest.py                 # migrate, load, reconcile
    python scripts/db_ingest.py --verify-only   # reconcile only
    python scripts/db_ingest.py --dry-run       # hash and check, load nothing

Safe to interrupt: each file is one transaction; re-running skips loaded files.
"""

from __future__ import annotations

import argparse
import sys

from metis_auto.wiring.db_ingest import IngestOptions, preflight, run_ingest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--preflight", action="store_true", help="check the setup, stop")
    ap.add_argument("--tables", nargs="*", help="only these logical tables")
    ap.add_argument("--limit-rows", type=int, help="smoke run: rows per file")
    ap.add_argument("--verify-only", action="store_true", help="reconcile only")
    ap.add_argument("--dry-run", action="store_true", help="check files, load nothing")
    ap.add_argument(
        "--allow-changed-file",
        action="store_true",
        help="accept a file whose sha256 differs from the pinned one (logged)",
    )
    ap.add_argument(
        "--allow-other-revision",
        action="store_true",
        help="accept a dataset revision other than the pinned one (logged)",
    )
    args = ap.parse_args()
    if args.preflight:
        return preflight()
    return run_ingest(
        IngestOptions(
            tables=tuple(args.tables or ()),
            limit_rows=args.limit_rows,
            verify_only=args.verify_only,
            dry_run=args.dry_run,
            allow_changed_file=args.allow_changed_file,
            allow_other_revision=args.allow_other_revision,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
