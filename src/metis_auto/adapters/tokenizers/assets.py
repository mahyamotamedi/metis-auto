"""Tokenizer asset checks (CMP-12).

Responsibility: confirm a tokenizer file exists and has the pinned sha256
before any library reads it, so a missing or altered file fails loudly and a
library never falls back to downloading (token_accounting.md §2).
Called by: the tiktoken and Hugging Face tokenizer adapters,
scripts/fetch_tokenizer_assets.py. Network: none.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class TokenizerUnavailable(RuntimeError):
    """A tokenizer cannot be loaded: its library or asset is missing, or the
    asset's hash differs from the pinned one. Wiring then falls back to the
    labelled approximation for that ref."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verified_asset(path: Path, sha256: str) -> Path:
    """``path`` if it exists and matches ``sha256``; else TokenizerUnavailable."""
    if not path.is_file():
        raise TokenizerUnavailable(
            f"tokenizer asset missing: {path} "
            "(run: python scripts/fetch_tokenizer_assets.py)"
        )
    actual = sha256_of(path)
    if actual != sha256:
        raise TokenizerUnavailable(
            f"tokenizer asset {path} has sha256 {actual}, expected {sha256}"
        )
    return path
