"""Fake context compressor: a SYNTHETIC test double (Demo milestone).

Responsibility: let compression run offline in tests and in ``chat.py
--fake`` without the heavy extra: keeps about ``rate`` of the words, evenly
spaced, deterministically. It measures nothing about LLMLingua-2's quality
or speed; its ref says ``fake``. Implements ``ports.TextCompressor``.
"""

from __future__ import annotations

from metis_auto.contracts import PolicyRef
from metis_auto.ports import CompressedText


class FakeCompressor:
    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(name="fake_word_drop", version="1.0.0")

    @property
    def token_method(self) -> str:
        return "whitespace-words@1"

    def compress(self, text: str, rate: float) -> CompressedText:
        words = text.split()
        kept = [w for i, w in enumerate(words) if int((i + 1) * rate) > int(i * rate)]
        return CompressedText(" ".join(kept), len(words), len(kept))
