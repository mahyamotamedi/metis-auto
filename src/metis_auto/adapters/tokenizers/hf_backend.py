"""Hugging Face ``tokenizer.json`` tokenizer (CMP-12): exact local counts for
open-weight models that publish their tokenizer (``deepseek-v4-flash``).

Responsibility: count tokens with the ``tokenizers`` library from a local,
sha256-checked file (``Tokenizer.from_file``: no Hub access, no download).
Counts content only (``add_special_tokens=False``); the chat template's
framing is counted separately (domain.accounting.overhead).
Implements ``ports.Tokenizer``. Built by: wiring.tokenizers. Called by:
application.measurement. Optional dependency: extra ``tokenizers``.
"""

from __future__ import annotations

from pathlib import Path

from metis_auto.contracts import Fidelity, Name, TokenCount

from .assets import TokenizerUnavailable, verified_asset


class HuggingFaceTokenizer:
    def __init__(
        self,
        ref: Name,
        asset: Path,
        sha256: str,
        fidelity: Fidelity = Fidelity.EXACT_LOCAL,
        label: str | None = None,
    ) -> None:
        try:
            import tokenizers
        except ImportError as exc:  # optional extra not installed
            raise TokenizerUnavailable(
                "tokenizers is not installed (pip extra `tokenizers`)"
            ) from exc
        verified_asset(asset, sha256)
        self._tokenizer = tokenizers.Tokenizer.from_file(str(asset))
        self._ref = ref
        self._fidelity = fidelity
        self._method = f"hf-{label or ref}-{sha256[:12]}@{tokenizers.__version__}"

    @property
    def ref(self) -> Name:
        return self._ref

    def count(self, text: str) -> TokenCount:
        tokens = len(self._tokenizer.encode(text, add_special_tokens=False).ids)
        return TokenCount(tokens=tokens, fidelity=self._fidelity, method=self._method)
