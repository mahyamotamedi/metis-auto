"""Fetch and pin decision-router model files (ADR-XXXX (system-one-decision-router)
point 7; R5).

``scripts/fetch_router_assets.py`` is the only caller and the only step that
touches the network for router models (explicit, like installing a package).

- ``plan``: metadata only. Resolves the revision (the pinned one, or a branch
  such as ``main`` to its commit), lists the files the asset includes with
  their sizes, and checks that every required part is there. Downloads
  nothing.
- ``pin``: downloads those files at that commit (each file retried and
  resumed; verified files kept, so a dropped connection never costs a whole
  restart) and verifies each against the
  Hub's own tree at that commit, never trusting the first download: an LFS
  file's content sha256 must equal the sha256 the Hub lists, a small file's
  git blob ID (sha1 of ``blob <size>\\0`` + content) must equal the tree's. It
  then records every file's sha256 and size; the caller rewrites
  ``config/reference/routers.toml`` with the pins.
- ``fetch``: for a pinned asset, downloads what is missing or wrong and checks
  sha256 against the pins.
- ``check``: no network; verifies the local files against the pins.

Files go to ``paths.router_assets/<ref>/<revision>/`` (git-ignored), keeping
their paths relative to the asset's subfolder, so that directory is the
checkpoint directory THX-01 loads. A ``.part`` file is renamed only after it
verifies; a failing one is deleted. Prints nothing; returns counts.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Protocol

from metis_auto.adapters.routers.hub import HubFile
from metis_auto.settings import (
    RouterAssetFile,
    RouterAssetSpec,
    RouterAssetTable,
)

CHUNK = 1 << 20


class Hub(Protocol):
    def revision_sha(self, repo: str, revision: str) -> str: ...

    def tree(
        self, repo: str, revision: str, path: str | None, *, recursive: bool = False
    ) -> list[HubFile]: ...

    def download(
        self,
        repo: str,
        revision: str,
        path: str,
        target: Path,
        *,
        progress: Callable[[int], None] | None = None,
    ) -> None: ...


class AssetError(RuntimeError):
    """The asset cannot be planned, pinned or fetched as configured."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def git_blob_id(path: Path) -> str:
    """Git's object ID of a file's content: sha1 of ``blob <size>\\0`` + bytes."""
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class PlannedFile:
    path: str
    """Relative to the asset's subfolder (and to its local directory)."""
    repo_path: str
    size: int
    blob_id: str
    lfs_sha256: str | None


@dataclass(frozen=True)
class Plan:
    ref: str
    model: str
    revision: str
    files: tuple[PlannedFile, ...]

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)

    def summary(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "model": self.model,
            "revision": self.revision,
            "files": len(self.files),
            "lfs_files": sum(f.lfs_sha256 is not None for f in self.files),
            "total_bytes": self.total_bytes,
            "total_mb": round(self.total_bytes / 1e6, 1),
            "file_list": [
                {"path": f.path, "bytes": f.size, "lfs": f.lfs_sha256 is not None}
                for f in self.files
            ],
        }


def _included(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(rel, p) for p in patterns)


def _folders(spec: RouterAssetSpec) -> list[str | None]:
    """The folders the include patterns name (the asset's root, then e.g.
    ``tokenizer``): listed one by one, never recursively, so a repository's
    demo, training and result folders are never walked."""
    base = spec.subfolder
    folders: list[str | None] = [base]
    for pattern in spec.include:
        if "/" in pattern:
            sub = pattern.rsplit("/", 1)[0]
            folder = f"{base}/{sub}" if base else sub
            if folder not in folders:
                folders.append(folder)
    return folders


def plan(spec: RouterAssetSpec, hub: Hub, *, revision: str | None = None) -> Plan:
    """What ``pin`` would download. ``revision``: a branch, tag or commit; by
    default the pinned commit, else ``main``. A Hub failure raises
    ``HubError`` naming the URL and the HTTP status."""
    wanted = revision or spec.revision or "main"
    commit = wanted if len(wanted) == 40 else hub.revision_sha(spec.model, wanted)
    prefix = f"{spec.subfolder}/" if spec.subfolder else ""
    files = []
    entries = [
        e for folder in _folders(spec) for e in hub.tree(spec.model, commit, folder)
    ]
    for entry in entries:
        if not entry.path.startswith(prefix):
            continue
        rel = entry.path[len(prefix) :]
        if _included(rel, spec.include):
            files.append(
                PlannedFile(
                    rel, entry.path, entry.size, entry.blob_id, entry.lfs_sha256
                )
            )
    files.sort(key=lambda f: f.path)
    found = [f.path for f in files]
    for need in spec.required:
        ok = (
            any(p.startswith(need) for p in found)
            if need.endswith("/")
            else need in found
        )
        if not ok:
            raise AssetError(
                f"{spec.ref}: {need!r} is not in {spec.model}@{commit[:12]}"
                f"{'/' + spec.subfolder if spec.subfolder else ''}; refusing a "
                "partial checkpoint"
            )
    return Plan(spec.ref, spec.model, commit, tuple(files))


@dataclass
class Report:
    ok: int = 0
    downloaded: int = 0
    downloaded_bytes: int = 0
    problems: list[str] = field(default_factory=list)


def asset_dir(root: Path, spec: RouterAssetSpec, revision: str | None = None) -> Path:
    return root / spec.ref / (revision or spec.revision or "unpinned")


Log = Callable[[str], None]
Sleep = Callable[[float], None]
ATTEMPTS = 5
"""Tries per file; a dropped connection resumes the partial file."""


def _download_verified(
    hub: Hub,
    spec: RouterAssetSpec,
    revision: str,
    repo_path: str,
    target: Path,
    verify: Callable[[Path], str | None],
    *,
    size: int,
    log: Log,
    sleep: Sleep,
    attempts: int = ATTEMPTS,
) -> str | None:
    """Download to ``target.part``, verify, rename; returns a problem or None.

    A transport failure keeps the partial file and retries (``attempts``,
    backing off 2, 4, 8 … s), resuming it with a range request; the partial
    file also survives the run, so the next ``pin`` or ``fetch`` resumes it.
    A file that fails verification is deleted and downloaded once more from
    scratch within the same attempts; it is never kept."""
    partial = target.with_name(target.name + ".part")
    last = "not attempted"
    for attempt in range(1, attempts + 1):
        have = partial.stat().st_size if partial.exists() else 0
        log(
            f"{repo_path}: {'resuming at ' + str(have) + ' of ' if have else ''}"
            f"{size:,} bytes (attempt {attempt}/{attempts})"
        )
        try:
            hub.download(spec.model, revision, repo_path, partial)
        except OSError as exc:  # HubError names the URL and status; no content
            last = str(exc) or type(exc).__name__
            log(f"{repo_path}: {last}")
            if attempt < attempts:
                sleep(2.0**attempt)
            continue
        problem = verify(partial)
        if problem is None:
            partial.replace(target)
            return None
        partial.unlink(missing_ok=True)
        last = problem
        log(f"{repo_path}: {problem}; deleted, downloading again")
    return f"{repo_path}: {last} (after {attempts} attempts)"


def disk_bytes(directory: Path) -> int:
    """Bytes of the files under ``directory`` (pins and partial files)."""
    return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())


def pin(
    spec: RouterAssetSpec,
    hub: Hub,
    root: Path,
    the_plan: Plan,
    *,
    log: Log = lambda _: None,
    sleep: Sleep = time.sleep,
) -> tuple[RouterAssetSpec, Report]:
    """Download ``the_plan``'s files, verify each against the Hub's tree at
    that commit, and return the spec with its pins (or the problems). Files
    already present and verified are kept; a failed run is resumed by running
    ``pin`` again."""
    report = Report()
    pinned: list[RouterAssetFile] = []
    directory = asset_dir(root, spec, the_plan.revision)
    for f in the_plan.files:
        target = directory / f.path

        def verify(path: Path, f: PlannedFile = f) -> str | None:
            if path.stat().st_size != f.size:
                return f"size {path.stat().st_size} != the Hub's {f.size}"
            if f.lfs_sha256 is not None:
                if sha256_file(path) != f.lfs_sha256:
                    return "sha256 differs from the Hub's LFS sha256"
            elif git_blob_id(path) != f.blob_id:
                return "git blob ID differs from the Hub's tree"
            return None

        if target.is_file() and verify(target) is None:
            report.ok += 1
        else:
            problem = _download_verified(
                hub,
                spec,
                the_plan.revision,
                f.repo_path,
                target,
                verify,
                size=f.size,
                log=log,
                sleep=sleep,
            )
            if problem is not None:
                report.problems.append(problem)
                continue
            report.downloaded += 1
            report.downloaded_bytes += f.size
        pinned.append(
            RouterAssetFile(
                path=f.path,
                sha256=f.lfs_sha256 or sha256_file(target),
                size_bytes=f.size,
                verified_by="lfs_sha256" if f.lfs_sha256 else "git_blob_sha1",
            )
        )
    if report.problems:
        return spec, report
    updated = spec.model_copy(
        update={"revision": the_plan.revision, "files": tuple(pinned)}
    )
    return RouterAssetSpec.model_validate(updated.model_dump()), report


def check(spec: RouterAssetSpec, root: Path) -> Report:
    """Local files against the pins; no network."""
    report = Report()
    if not spec.pinned:
        report.problems.append(f"{spec.ref}: not pinned (run pin)")
        return report
    directory = asset_dir(root, spec)
    for f in spec.files:
        target = directory / f.path
        if not target.is_file():
            report.problems.append(f"{f.path}: missing")
        elif target.stat().st_size != f.size_bytes or sha256_file(target) != f.sha256:
            report.problems.append(f"{f.path}: sha256 differs from the pin")
        else:
            report.ok += 1
    return report


def fetch(
    spec: RouterAssetSpec,
    hub: Hub,
    root: Path,
    *,
    log: Log = lambda _: None,
    sleep: Sleep = time.sleep,
) -> Report:
    """Download a pinned asset's missing or wrong files; sha256 must match."""
    report = Report()
    if not spec.pinned:
        report.problems.append(f"{spec.ref}: not pinned (run pin)")
        return report
    assert spec.revision is not None
    prefix = f"{spec.subfolder}/" if spec.subfolder else ""
    directory = asset_dir(root, spec)
    for f in spec.files:
        target = directory / f.path

        def verify(path: Path, f: RouterAssetFile = f) -> str | None:
            if path.stat().st_size != f.size_bytes or sha256_file(path) != f.sha256:
                return "sha256 differs from the pin"
            return None

        if target.is_file() and verify(target) is None:
            report.ok += 1
            continue
        problem = _download_verified(
            hub,
            spec,
            spec.revision,
            prefix + f.path,
            target,
            verify,
            size=f.size_bytes,
            log=log,
            sleep=sleep,
        )
        if problem is not None:
            report.problems.append(problem)
        else:
            report.downloaded += 1
            report.downloaded_bytes += f.size_bytes
    return report


# --- writing config/reference/routers.toml --------------------------------------------


def _s(value: str) -> str:
    """A TOML basic string (JSON escaping is valid TOML)."""
    return json.dumps(value, ensure_ascii=False)


def _list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_s(v) for v in values) + "]"


def render_table(table: RouterAssetTable, header: str) -> str:
    """The whole file: the existing comment header, then the data."""
    lines = [header.rstrip("\n"), "", f"version = {_s(table.version)}"]
    for a in table.assets:
        lines += [
            "",
            "[[assets]]",
            f"ref = {_s(a.ref)}",
            f"backend = {_s(a.backend.value)}",
        ]
        lines.append(f"model = {_s(a.model)}")
        if a.subfolder:
            lines.append(f"subfolder = {_s(a.subfolder)}")
        lines.append(f"include = {_list(a.include)}")
        if a.required:
            lines.append(f"required = {_list(a.required)}")
        if a.revision:
            lines.append(f"revision = {_s(a.revision)}")
        lines.append(f"licence = {_s(a.licence)}")
        if a.library:
            lines.append(f"library = {_s(a.library)}")
        if a.optional:
            lines.append("optional = true")
        lines.append(
            f"evidence = {{ source = {_s(a.evidence.source)}, "
            f"checked_on = {a.evidence.checked_on.isoformat()} }}"
        )
        for f in a.files:
            lines += [
                "",
                "[[assets.files]]",
                f"path = {_s(f.path)}",
                f"sha256 = {_s(f.sha256)}",
                f"size_bytes = {f.size_bytes}",
                f"verified_by = {_s(f.verified_by)}",
            ]
    return "\n".join(lines) + "\n"


def header_of(text: str) -> str:
    """The comment block before ``version = ``."""
    head = []
    for line in text.splitlines():
        if line.startswith("version"):
            break
        head.append(line)
    return "\n".join(head).rstrip("\n")


def with_pins(
    table: RouterAssetTable, spec: RouterAssetSpec, today: date
) -> RouterAssetTable:
    assets = tuple(spec if a.ref == spec.ref else a for a in table.assets)
    pinned = all(a.pinned for a in assets if not a.optional)
    version = f"routers-{today.isoformat()}" + ("" if pinned else "-partial")
    return RouterAssetTable(version=version, assets=assets)
