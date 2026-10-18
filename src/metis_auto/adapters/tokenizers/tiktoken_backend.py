"""tiktoken tokenizer (CMP-12): exact local counts for OpenAI models.

Responsibility: count tokens with a named tiktoken encoding (``o200k_base``
for gpt-5-nano, gpt-4.1-nano, gpt-4o-mini, gpt-5.4; token_accounting.md §2),
loaded **offline** from a pre-fetched, sha256-checked file. tiktoken reads its
cache directory (``TIKTOKEN_CACHE_DIR``) for files named by the sha1 of their
URL; the asset is stored in that layout, its hash is checked first, and the
variable is set only while the encoding loads, so tiktoken finds the file and
never downloads. Special-token text in content is counted as ordinary text
(``disallowed_special=()``), as the provider treats message content.
Implements ``ports.Tokenizer``. Built by: wiring.tokenizers. Called by:
application.measurement. Optional dependency: extra ``tokenizers``.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from metis_auto.contracts import Fidelity, Name, TokenCount

from .assets import TokenizerUnavailable, verified_asset

_ENV_LOCK = threading.Lock()


class TiktokenTokenizer:
    def __init__(
        self,
        ref: Name,
        encoding: str,
        asset: Path,
        sha256: str,
        fidelity: Fidelity = Fidelity.EXACT_LOCAL,
    ) -> None:
        try:
            import tiktoken
        except ImportError as exc:  # optional extra not installed
            raise TokenizerUnavailable(
                "tiktoken is not installed (pip extra `tokenizers`)"
            ) from exc
        verified_asset(asset, sha256)
        with _ENV_LOCK:
            previous = os.environ.get("TIKTOKEN_CACHE_DIR")
            os.environ["TIKTOKEN_CACHE_DIR"] = str(asset.parent)
            try:
                self._encoding = tiktoken.get_encoding(encoding)
            finally:
                if previous is None:
                    del os.environ["TIKTOKEN_CACHE_DIR"]
                else:
                    os.environ["TIKTOKEN_CACHE_DIR"] = previous
        self._ref = ref
        self._fidelity = fidelity
        self._method = f"tiktoken-{encoding}@{tiktoken.__version__}"

    @property
    def ref(self) -> Name:
        return self._ref

    def count(self, text: str) -> TokenCount:
        tokens = len(self._encoding.encode(text, disallowed_special=()))
        return TokenCount(tokens=tokens, fidelity=self._fidelity, method=self._method)
