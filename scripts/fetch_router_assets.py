"""Fetch and pin the local decision-router models in config/reference/routers.toml.

    python scripts/fetch_router_assets.py plan        # sizes only, no download
    python scripts/fetch_router_assets.py pin --yes   # download, verify, pin
    python scripts/fetch_router_assets.py fetch       # pinned files that are missing
    python scripts/fetch_router_assets.py check       # verify only, no network
    ... --asset mizan-1.5-4b-q4-k-m                   # the optional Mizan GGUF

The only step that downloads router models (network, explicit;
ADR-0047 point 7). ``plan`` reads Hub metadata only and
prints the files and their sizes. ``pin`` downloads exactly those files at one commit
(each file retried up to five times; a dropped connection resumes the partial file;
verified files are kept, so re-running ``pin`` continues where it stopped), verifies
every file against the Hub's own tree at that commit (LFS sha256, or git blob ID for
small files), and rewrites config/reference/routers.toml with the commit and every
file's sha256 (a copy of the previous file goes to runs/routers/). Without ``--yes`` it
prints the plan and stops. Files go to paths.router_assets (default data/routers/,
git-ignored). Public files only; no API key, no model call, no spend. Prints counts,
sizes and paths only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date

from metis_auto.adapters.routers.hub import HubClient, HubError
from metis_auto.settings import load_settings
from metis_auto.wiring import router_assets as ra


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2))


def _log(line: str) -> None:
    """Progress (file names, sizes, retries; never content) on stderr."""
    print(line, file=sys.stderr, flush=True)


def _mb(n: int) -> float:
    return round(n / 1e6, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("command", choices=["plan", "pin", "fetch", "check"])
    ap.add_argument("--asset", default="thx01")
    ap.add_argument(
        "--revision", help="plan/pin: branch, tag or commit (default: pin, else main)"
    )
    ap.add_argument("--yes", action="store_true", help="pin: download after the plan")
    args = ap.parse_args()

    loaded = load_settings()
    table = loaded.reference.routers
    spec = table.get(args.asset) if table is not None else None
    if table is None or spec is None:
        print(f"no router asset {args.asset!r} in reference.routers", file=sys.stderr)
        return 2
    root = loaded.path(loaded.settings.paths.router_assets)
    hub = HubClient()
    started = time.perf_counter()

    if args.command == "check":
        report = ra.check(spec, root)
        directory = ra.asset_dir(root, spec)
        _print(
            {
                "asset": spec.ref,
                "ok": report.ok,
                "problems": report.problems,
                "disk_mb": _mb(ra.disk_bytes(directory)) if directory.is_dir() else 0,
            }
        )
        return 1 if report.problems else 0
    if args.command == "fetch":
        report = ra.fetch(spec, hub, root, log=_log)
        _print(
            {
                "asset": spec.ref,
                "ok": report.ok,
                "downloaded": report.downloaded,
                "downloaded_mb": _mb(report.downloaded_bytes),
                "problems": report.problems,
                "disk_mb": _mb(ra.disk_bytes(ra.asset_dir(root, spec))),
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
        return 1 if report.problems else 0

    try:
        the_plan = ra.plan(spec, hub, revision=args.revision)
    except HubError as exc:
        _print(
            {
                "plan_failed": True,
                "url": exc.url,
                "http_status": exc.status,
                "error": str(exc),
            }
        )
        return 1
    except (ra.AssetError, OSError, ValueError) as exc:
        print(f"plan failed: {exc}", file=sys.stderr)
        return 1
    _print(
        {
            "plan": the_plan.summary(),
            "target": str(ra.asset_dir(root, spec, the_plan.revision)),
        }
    )
    if args.command == "plan":
        return 0
    if not args.yes:
        print("pin: nothing downloaded; re-run with --yes to download and pin")
        return 0
    pinned, report = ra.pin(spec, hub, root, the_plan, log=_log)
    directory = ra.asset_dir(root, spec, the_plan.revision)
    if report.problems:
        _print(
            {
                "pinned": False,
                "problems": report.problems,
                "kept_verified_files": report.ok + report.downloaded,
                "disk_mb": _mb(ra.disk_bytes(directory)),
                "next": "run the same pin command again: verified files are kept "
                "and partial files resume",
            }
        )
        return 1
    path = loaded.root / "config" / loaded.settings.reference.routers
    backup = (
        loaded.root / "runs" / "routers" / f"routers.toml.before-pin-{int(time.time())}"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    text = path.read_text(encoding="utf-8")
    updated = ra.with_pins(table, pinned, date.today())
    path.write_text(ra.render_table(updated, ra.header_of(text)), encoding="utf-8")
    _print(
        {
            "pinned": True,
            "asset": pinned.ref,
            "revision": pinned.revision,
            "files": len(pinned.files),
            "downloaded": report.downloaded,
            "downloaded_mb": _mb(report.downloaded_bytes),
            "already_present": report.ok,
            "disk_mb": _mb(ra.disk_bytes(directory)),
            "table_version": updated.version,
            "wrote": str(path.relative_to(loaded.root)),
            "previous_saved_to": str(backup.relative_to(loaded.root)),
            "seconds": round(time.perf_counter() - started, 1),
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
