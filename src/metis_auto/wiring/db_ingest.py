"""Compose the ingestion: settings, source config, loader, reconciliation (ADR-0027).

Also the plain-language preflight. Nothing here prints a secret or a data value.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import ssl
import subprocess
import tomllib
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from pathlib import Path

from sqlalchemy import text

from metis_auto.data_access.postgres.loader import (
    IngestError,
    changed_files,
    discover,
    hash_problems,
    load_file,
    schema_problems,
)
from metis_auto.data_access.postgres.migrate import upgrade_head
from metis_auto.data_access.postgres.reconcile import Check, run_checks
from metis_auto.settings import load_settings
from metis_auto.settings.loader import repo_root
from metis_auto.wiring.database import database_url_from_settings, engine_from_settings

SOURCE_CONFIG = "config/evaluation/source_v1.toml"


@dataclass(frozen=True)
class IngestOptions:
    tables: tuple[str, ...] = ()
    limit_rows: int | None = None
    verify_only: bool = False
    dry_run: bool = False
    allow_changed_file: bool = False
    allow_other_revision: bool = False


def source_config(root: Path | None = None) -> dict:
    root = root or repo_root()
    return tomllib.loads((root / SOURCE_CONFIG).read_text(encoding="utf-8"))


def local_revision(raw_dir: Path) -> str | None:
    """The revision Hugging Face recorded when the files were downloaded."""
    meta = sorted(raw_dir.glob(".cache/huggingface/download/**/*.metadata"))
    if not meta:
        return None
    return meta[0].read_text(encoding="utf-8").splitlines()[0].strip()


def git_sha(root: Path) -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return done.stdout.strip()


def _versions() -> dict[str, str]:
    return {
        p: importlib_metadata.version(p)
        for p in ("sqlalchemy", "alembic", "psycopg", "pyarrow")
    }


def run_ingest(opts: IngestOptions, root: Path | None = None) -> int:
    root = root or repo_root()
    cfg = source_config(root)
    src = cfg["source"]
    raw_dir = root / src["raw_dir"]
    tables = {
        k: v for k, v in cfg["tables"].items() if not opts.tables or k in opts.tables
    }
    engine = engine_from_settings()
    expected = {k: v["expected_rows"] for k, v in cfg["tables"].items()}
    gaps = src["known_bot_owners_missing_from_users"]
    if opts.verify_only:
        checks = run_checks(engine, expected, gaps)
        for c in checks:
            print(
                f"{'ok  ' if c.ok else 'FAIL'} {c.name}: {c.actual} "
                f"(expected {c.expected})"
            )
        return 0 if all(c.ok for c in checks) else 1

    revision = local_revision(raw_dir)
    if revision != src["revision"]:
        message = (
            f"the local dataset revision is {revision}, the pinned one is "
            f"{src['revision']}"
        )
        if not opts.allow_other_revision:
            print(f"Refusing: {message}. Use --allow-other-revision to override.")
            return 2
        print(f"WARNING (logged): {message}")

    print("Checking files (sha256 and schema)...")
    sources = discover(raw_dir, tables)
    problems = schema_problems(sources, tables)
    if problems:
        print("Schema does not match config:\n  " + "\n  ".join(problems))
        return 2
    pinned = hash_problems(sources, tables)
    if pinned and not opts.allow_changed_file:
        print("Refusing, files changed:\n  " + "\n  ".join(pinned))
        return 2
    print(f"{len(sources)} files match the expected schema.")
    if opts.dry_run:
        print("Dry run: nothing loaded.")
        return 0

    upgrade_head(root / "infra" / "db" / "alembic.ini", database_url_from_settings())
    changed = changed_files(engine, sources)
    if changed and not opts.allow_changed_file:
        print(
            "Refusing, already loaded with another sha256:\n  " + "\n  ".join(changed)
        )
        return 2

    options = asdict(opts) | {"tables": list(opts.tables)}
    with engine.begin() as conn:
        run_id = conn.scalar(
            text(
                "INSERT INTO meta.ingest_run (started_at, git_sha, dataset_repo, "
                "dataset_revision, tool_versions, options, status) VALUES (:t, :g, "
                ":r, :v, CAST(:tv AS jsonb), CAST(:o AS jsonb), 'running') "
                "RETURNING run_id"
            ),
            {
                "t": datetime.now(UTC),
                "g": git_sha(root),
                "r": src["repo"],
                "v": revision or "unknown",
                "tv": json.dumps(_versions()),
                "o": json.dumps(options),
            },
        )
    print("Loading. Safe to interrupt: re-running skips files already loaded.")
    status = "failed"
    try:
        inserted = 0
        for source in sources:
            done = load_file(
                engine,
                source,
                run_id,
                batch_rows=src["batch_rows"],
                limit_rows=opts.limit_rows,
            )
            inserted += done["inserted"]
        print(f"{inserted} rows inserted in this run.")
        partial = bool(opts.limit_rows or opts.tables)
        checks = run_checks(engine, expected, gaps, partial=partial)
        checks.append(Check("rows_inserted_this_run", "info", str(inserted), True))
        with engine.begin() as conn:
            for c in checks:
                conn.execute(
                    text("INSERT INTO meta.reconciliation VALUES (:r,:n,:e,:a,:ok)"),
                    {
                        "r": run_id,
                        "n": c.name,
                        "e": c.expected,
                        "a": c.actual,
                        "ok": c.ok,
                    },
                )
        bad = [c for c in checks if not c.ok]
        for c in bad:
            print(f"FAIL {c.name}: {c.actual} (expected {c.expected})")
        status = "failed" if bad else "ok"
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE meta.ingest_run SET status=:s, finished_at=:t "
                    "WHERE run_id=:r"
                ),
                {"s": status, "t": datetime.now(UTC), "r": run_id},
            )
    print(f"Run {run_id}: {status}. {len(checks)} reconciliation checks.")
    return 0 if status == "ok" else 1


def _tls_context() -> ssl.SSLContext:
    """python.org builds on macOS ship without CA roots; certifi is in the db lock."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def preflight(root: Path | None = None) -> int:
    """Plain-language setup checks. Returns 0 when everything needed is in place."""
    root = root or repo_root()
    src = source_config(root)["source"]
    failures = 0

    def report(ok: bool | None, good: str, bad: str) -> None:
        nonlocal failures
        if ok is None:
            print(f"[skip] {bad}")
        elif ok:
            print(f"[ ok ] {good}")
        else:
            failures += 1
            print(f"[FAIL] {bad}")

    docker = shutil.which("docker") is not None and (
        subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    )
    report(docker, "Docker is running.", "Docker is not running. Start Docker Desktop.")
    loaded = load_settings()
    report(
        loaded.secrets.database_password is not None,
        "METIS_DB_PASSWORD is set (value not shown).",
        "METIS_DB_PASSWORD is not set. Add it to .env (see docs/guides/team_setup.md).",
    )
    db = loaded.settings.database
    with socket.socket() as sock:
        sock.settimeout(1)
        in_use = sock.connect_ex((db.host, db.port)) == 0
    ours = False
    if in_use and docker:
        names = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"publish={db.port}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
        ).stdout
        ours = "postgres" in names
    report(
        not in_use or ours,
        f"Port {db.port} is free or is our PostgreSQL.",
        f"Port {db.port} is used by another program. Stop it or change "
        "METIS__DATABASE__PORT.",
    )
    raw = root / src["raw_dir"]
    report(
        (raw / "data" / "users.parquet").exists(),
        f"The dataset is in {src['raw_dir']}.",
        f"The dataset is missing from {src['raw_dir']}. See the download step.",
    )
    revision = local_revision(raw)
    report(
        revision == src["revision"],
        "The dataset is the pinned revision.",
        f"The dataset revision is {revision}, expected {src['revision']}.",
    )
    free_gb = shutil.disk_usage(root).free / 1e9
    report(
        free_gb >= src["min_free_disk_gb"],
        f"{free_gb:.0f} GB free disk.",
        f"Only {free_gb:.0f} GB free; need {src['min_free_disk_gb']} GB.",
    )
    token = os.environ.get("HF_TOKEN")
    if token:
        request = urllib.request.Request(
            f"https://huggingface.co/api/datasets/{src['repo']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=15, context=_tls_context()
            ) as response:
                access = response.status == 200
        except (urllib.error.URLError, TimeoutError):
            access = False
        report(
            access,
            "The Hugging Face token has access to the dataset.",
            "The Hugging Face token has no access to the dataset, or no network.",
        )
    else:
        report(None, "", "HF_TOKEN is not set; token access was not checked.")
    print("Ready." if not failures else f"{failures} check(s) need attention.")
    return 0 if not failures else 1


__all__ = ["IngestError", "IngestOptions", "preflight", "run_ingest"]
