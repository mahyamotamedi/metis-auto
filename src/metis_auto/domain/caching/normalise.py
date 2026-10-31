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

Persian folding (caching-plan C1b; evaluation framework §0.3) is a separate,
versioned family, ``PERSIAN_TREATMENTS``, for measurement variants only. NFKC
does not unify Arabic and Persian yeh or kaf, so the family does it. Every
variant: NFKC; Arabic yeh (U+064A) and alef maksura (U+0649) → Persian yeh
(U+06CC); Arabic kaf (U+0643) → Persian kaf (U+06A9); Persian (U+06F0..9) and
Arabic-Indic (U+0660..9) digits → ASCII digits; bidirectional control marks
removed; whitespace collapsed. Logical order is never changed, Latin runs are
left alone, and Latin case is **not** folded. They differ only in the open
decisions, so none is a default:
- ``persian_fold_v1``: ZWNJ, diacritics, and tatweel kept;
- ``persian_fold_zwnj_space_v1``: ZWNJ (U+200C) becomes a space;
- ``persian_fold_marks_v1``: diacritics (U+064B..065F, U+0670) and tatweel
  (U+0640) removed, ZWNJ kept.
The behavior of a named version never changes: a change is a new name. These
are not in ``TREATMENTS`` (the default measurement set) and not in
``policy.SUPPORTED_TREATMENTS``: serving stays ``literal``. The original text
is never modified; ``normalise`` returns a new string used only as a
comparison or fingerprint input, never sent to a model or a judge.
Status: decided (treatments); which one serving may use is open.
"""

from __future__ import annotations

import re
import unicodedata

TREATMENTS = ("literal", "whitespace", "nfkc_casefold_ws")
PERSIAN_TREATMENTS = (
    "persian_fold_v1",
    "persian_fold_zwnj_space_v1",
    "persian_fold_marks_v1",
)
ALL_TREATMENTS = TREATMENTS + PERSIAN_TREATMENTS

_SPACE = re.compile(r"\s+")
_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"})
_DIGITS = str.maketrans(
    {
        **{0x06F0 + i: str(i) for i in range(10)},
        **{0x0660 + i: str(i) for i in range(10)},
    }
)
_BIDI = re.compile("[؜‎‏‪-‮⁦-⁩]")
_ZWNJ = "‌"
_MARKS = re.compile("[ً-ٰٟـ]")


def _persian_fold(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_LETTERS).translate(_DIGITS)
    return _BIDI.sub("", folded)


def normalise(text: str, treatment: str) -> str:
    if treatment == "literal":
        return text
    if treatment == "whitespace":
        return _SPACE.sub(" ", text).strip()
    if treatment == "nfkc_casefold_ws":
        return _SPACE.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()
    if treatment == "persian_fold_v1":
        return _SPACE.sub(" ", _persian_fold(text)).strip()
    if treatment == "persian_fold_zwnj_space_v1":
        return _SPACE.sub(" ", _persian_fold(text).replace(_ZWNJ, " ")).strip()
    if treatment == "persian_fold_marks_v1":
        return _SPACE.sub(" ", _MARKS.sub("", _persian_fold(text))).strip()
    raise ValueError(f"unknown treatment {treatment!r}; known: {ALL_TREATMENTS}")
