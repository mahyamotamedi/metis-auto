"""Which reranker files are ready: pinned, present and matching their sha256.

Responsibility: read ``config/reference/rerankers.toml`` (plain TOML, no heavy
import) and decide, without touching the network or a model, whether a
reranker's weights may be loaded. A missing revision, a file without a pinned
sha256, an absent file or a hash mismatch each give a stated reason. Nothing is
downloaded here (``scripts/fetch_reranker_assets.py`` does, from pinned values
only). Traces: H-2, FR-CTX-02, ADR-0040. Status: provisional.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from metis_auto.adapters.tokenizers import sha256_of


@dataclass(frozen=True)
class RerankerFile:
    name: str
    sha256: str | None
    size_bytes: int | None = None


@dataclass(frozen=True)
class RerankerSpec:
    ref: str
    model: str
    revision: str | None
    files: tuple[RerankerFile, ...]

    @property
    def directory(self) -> str:
        return f"{self.ref}/{self.revision}"

    def url(self, name: str) -> str:
        return f"https://huggingface.co/{self.model}/resolve/{self.revision}/{name}"


def load_specs(path: Path) -> dict[str, RerankerSpec]:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in raw.get("rerankers", []):
        files = tuple(
            RerankerFile(f["name"], f.get("sha256"), f.get("size_bytes"))
            for f in item.get("files", [])
        )
        out[item["ref"]] = RerankerSpec(
            item["ref"], item["model"], item.get("revision"), files
        )
    return out


def unpinned_reasons(spec: RerankerSpec) -> list[str]:
    """Why the spec cannot be fetched or loaded yet (empty when fully pinned)."""
    reasons = []
    if not spec.revision:
        reasons.append(f"{spec.ref}: revision is not pinned (set by owner)")
    if not spec.files:
        reasons.append(f"{spec.ref}: no files are listed (set by owner)")
    reasons += [
        f"{spec.ref}/{f.name}: sha256 is not pinned (set by owner)"
        for f in spec.files
        if not f.sha256
    ]
    return reasons


def not_ready_reasons(spec: RerankerSpec, root: Path) -> list[str]:
    """Every reason the weights cannot be loaded from ``root`` (empty = ready)."""
    reasons = unpinned_reasons(spec)
    if reasons:
        return reasons
    base = root / spec.directory
    for f in spec.files:
        target = base / f.name
        if not target.is_file():
            reasons.append(f"{spec.ref}/{f.name}: missing at {target}")
        elif sha256_of(target) != f.sha256:
            reasons.append(f"{spec.ref}/{f.name}: sha256 differs from the pin")
    if reasons:
        reasons.append("fetch with: python scripts/fetch_reranker_assets.py")
    return reasons
