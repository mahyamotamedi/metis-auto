"""Character-count approximation tokenizer.

Responsibility: a cheap, clearly labelled **approximation** (characters ÷ 4,
rounded up), the heuristic the sample EDA used. It is known to be inaccurate,
especially for Persian; every count says ``approximation`` (FR-ACCT-01, H-7).
Implements ``ports.Tokenizer``. Built by: wiring. Called by:
application.measurement. Status: stable as a fallback; its error against the
exact tokenizers is measured in tests/unit/adapters/test_adapters_tokenizers.py
and reports/cost/ (Stage 7).
"""

from __future__ import annotations

import math

from metis_auto.contracts import Fidelity, Name, TokenCount


class ApproxCharsTokenizer:
    def __init__(self, ref: Name = "approx-chars-div-4", chars_per_token: int = 4):
        self._ref = ref
        self._per = chars_per_token

    @property
    def ref(self) -> Name:
        return self._ref

    def count(self, text: str) -> TokenCount:
        return TokenCount(
            tokens=math.ceil(len(text) / self._per),
            fidelity=Fidelity.APPROXIMATION,
            method=f"approx-chars-div-{self._per}@1",
        )
