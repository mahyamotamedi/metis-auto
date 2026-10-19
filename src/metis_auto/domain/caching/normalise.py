"""Message normalisation treatments for cache keys (CMP-06; FR-XCACHE-03).

Responsibility: the configured treatment applied to a text **before** it is
fingerprinted (ADR-0015 amendment 1: fingerprints never normalise
implicitly; the key records the treatment in ``KeyComponent.treatment``).
Pure. Called by: evaluation.cache_candidates (Stage 8 measurement variants);
the serving path still uses ``literal`` only (``policy.SUPPORTED_TREATMENTS``)
until evidence justifies another treatment for serving (P-5).

Treatments (the sample EDA's three variants, re-implemented here):
- ``literal``: the text as given;
- ``whitespace``: runs of Unicode whitespace collapsed to one space, ends
  stripped;
- ``nfkc_casefold_ws``: Unicode NFKC, then ``str.casefold``, then whitespace.

Not done (a caching-plan item, docs/experiments/caching_plan.md): Persian
folding (Arabic yeh/kaf → Persian, ZWNJ, diacritics, tatweel, digits). NFKC
does not unify those letters.
Status: decided (treatments); which one serving may use is open.
"""

from __future__ import annotations

import re
import unicodedata

TREATMENTS = ("literal", "whitespace", "nfkc_casefold_ws")
_SPACE = re.compile(r"\s+")


def normalise(text: str, treatment: str) -> str:
    if treatment == "literal":
        return text
    if treatment == "whitespace":
        return _SPACE.sub(" ", text).strip()
    if treatment == "nfkc_casefold_ws":
        return _SPACE.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()
    raise ValueError(f"unknown treatment {treatment!r}; known: {TREATMENTS}")
