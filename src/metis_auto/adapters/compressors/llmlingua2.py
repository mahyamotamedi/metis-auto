"""LLMLingua-2 context compressor (Demo milestone, EXPERIMENTAL; context
plan X3, ADR-0023).

Responsibility: shorten one text with Microsoft's LLMLingua-2 token
classifier (``microsoft/llmlingua-2-xlm-roberta-large-meetingbank``) on CPU,
through the ``llmlingua`` package's ``compress_prompt_llmlingua2``. Loads
**local, sha256-checked files only**: every file is verified first, the
Hugging Face libraries are set offline while loading, remote code is refused,
and tiktoken's cl100k file (which llmlingua loads to count its own tokens) is
read from the same directory. Its token counts are llmlingua's (tiktoken
cl100k), not the target model's.
Quality is unmeasured: trained on English meeting transcripts, so Persian
quality is unknown (context plan §4). Unpromoted: needs ablation evidence
(FR-CTX-03).
Implements ``ports.TextCompressor``. Built by: wiring.compression. Called by:
application.pipeline. Optional dependency: extra ``compress`` (torch,
transformers, llmlingua); never in the runtime lock.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from pathlib import Path

from metis_auto.adapters.tokenizers import sha256_of
from metis_auto.contracts import PolicyRef
from metis_auto.ports import CompressedText

_ENV_LOCK = threading.Lock()
_OFFLINE = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
FORCE_TOKENS = ("\n", ".", "!", "?", ",", "،", "؟", "؛")
"""Kept whatever the classifier says: sentence and list structure (Latin and
Persian punctuation)."""


class CompressorUnavailable(RuntimeError):
    """The extra or a model file is missing, or a file's hash differs."""


class LLMLingua2Compressor:
    def __init__(
        self,
        name: str,
        revision: str,
        directory: Path,
        files: Sequence[tuple[str, str]],
        library_version: str,
    ) -> None:
        """``files``: (file name, pinned sha256) pairs in ``directory``, the
        cl100k file among them (under tiktoken's cache name)."""
        for file_name, sha256 in files:
            path = directory / file_name
            if not path.is_file():
                raise CompressorUnavailable(
                    f"compressor file missing: {path} "
                    "(run: python scripts/fetch_compressor_assets.py)"
                )
            if sha256_of(path) != sha256:
                raise CompressorUnavailable(f"compressor file {path}: wrong sha256")
        with _ENV_LOCK:
            previous = {k: os.environ.get(k) for k in (*_OFFLINE, "TIKTOKEN_CACHE_DIR")}
            os.environ.update(_OFFLINE)
            os.environ["TIKTOKEN_CACHE_DIR"] = str(directory)
            try:
                try:
                    from llmlingua import PromptCompressor
                except ImportError as exc:  # optional extra not installed
                    raise CompressorUnavailable(
                        "llmlingua is not installed (extra `compress`: "
                        "pip install --require-hashes -r requirements-compress.lock)"
                    ) from exc
                self._compressor = PromptCompressor(
                    model_name=str(directory),
                    device_map="cpu",
                    model_config={"trust_remote_code": False},
                    use_llmlingua2=True,
                )
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        self._ref = PolicyRef(name=name, version=f"{revision[:12]}@{library_version}")

    @property
    def ref(self) -> PolicyRef:
        return self._ref

    @property
    def token_method(self) -> str:
        return "llmlingua-tiktoken-cl100k"

    def compress(self, text: str, rate: float) -> CompressedText:
        result = self._compressor.compress_prompt_llmlingua2(
            [text],
            rate=rate,
            force_tokens=list(FORCE_TOKENS),
            drop_consecutive=True,
        )
        return CompressedText(
            text=result["compressed_prompt"],
            tokens_before=int(result["origin_tokens"]),
            tokens_after=int(result["compressed_tokens"]),
        )
