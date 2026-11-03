"""The full dataset on disk: where it is, and whether it is the pinned one.

Responsibility: resolve the dataset root (``Path.resolve()`` follows the NTFS
junction on Windows), list its Parquet files, and check them against the pins
in ``config/evaluation/source_v1.toml``: the Hugging Face revision recorded in
the download metadata, and each file's sha256. Reads no content.
Called by: wiring.router_slice. Traces: FR-DATA-02, QA-REPRO, ADR-0027.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

CHUNK = 1 << 20


@dataclass(frozen=True)
class SourcePins:
    repo: str
    revision: str
    files: dict[str, str]
    """Relative POSIX path → pinned sha256."""
    expected_rows: dict[str, int]
    """Logical table → pinned row count."""


@dataclass
class SourceCheck:
    root: Path
    revision_seen: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)
    hashed: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def read_pins(path: Path) -> SourcePins:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    files: dict[str, str] = {}
    rows: dict[str, int] = {}
    for name, spec in raw.get("tables", {}).items():
        rows[name] = int(spec["expected_rows"])
        for entry in spec.get("files", []):
            files[entry["path"]] = entry["sha256"]
    return SourcePins(
        repo=raw["source"]["repo"],
        revision=raw["source"]["revision"],
        files=files,
        expected_rows=rows,
    )


def is_absolute_root(configured: str) -> bool:
    """Absolute on this platform, or a Windows absolute path (``C:\\...``,
    ``C:/...``, ``\\\\server\\share``) whatever the platform."""
    return Path(configured).is_absolute() or PureWindowsPath(configured).is_absolute()


def resolve_root(configured: str, repo_root: Path) -> Path:
    """The dataset root: absolute as given, else relative to the repository.
    ``Path.resolve()`` follows the NTFS junction ``data\\full_data\\raw``."""
    path = Path(configured)
    if not is_absolute_root(configured):
        path = repo_root / path
    return path.resolve()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def revisions_seen(root: Path) -> set[str]:
    """Commit hashes in the Hugging Face download metadata (first line of each
    ``*.metadata`` file), if the folder was fetched with ``hf download``."""
    folder = root / ".cache" / "huggingface" / "download"
    found: set[str] = set()
    if folder.is_dir():
        for meta in folder.rglob("*.metadata"):
            first = meta.read_text(encoding="utf-8", errors="replace").splitlines()
            if first:
                found.add(first[0].strip())
    return found


def check_source(
    root: Path, pins: SourcePins, *, hash_files: bool = True
) -> SourceCheck:
    """Problems with the dataset at ``root``; empty means it is the pinned one.

    A missing download metadata folder is a problem (the revision cannot be
    shown); the caller may accept it only with an explicit override.
    """
    check = SourceCheck(root=root)
    if not root.is_dir():
        check.problems.append(f"dataset root not found: {root}")
        return check
    check.revision_seen = revisions_seen(root)
    if not check.revision_seen:
        check.problems.append("no Hugging Face download metadata: revision unknown")
    elif check.revision_seen != {pins.revision}:
        check.problems.append(
            f"revision differs from the pin {pins.revision[:12]}: "
            f"{sorted(r[:12] for r in check.revision_seen)}"
        )
    present = {
        p.relative_to(root).as_posix() for p in (root / "data").rglob("*.parquet")
    }
    for rel in sorted(set(pins.files) - present):
        check.problems.append(f"missing file: {rel}")
    for rel in sorted(present - set(pins.files)):
        check.problems.append(f"unpinned file: {rel}")
    if hash_files:
        for rel in sorted(set(pins.files) & present):
            check.hashed += 1
            if file_sha256(root / Path(rel)) != pins.files[rel]:
                check.problems.append(f"sha256 differs from the pin: {rel}")
    return check
