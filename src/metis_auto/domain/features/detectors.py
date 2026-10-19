"""Cheap text detectors for request features (CMP-04; FR-FEAT-01, FR-FEAT-03).

Responsibility: classify a text's language (Persian, English, mixed, other,
undetermined), detect code, detect a coding intent (a request for code or
programming help with no code in the message), bucket its length, and
recognise greetings and small talk from a configured phrase list. Pure,
deterministic, no model, no network: they run on every request and on
every earlier user turn (sticky routing), so they must stay well inside the
overhead budget.
Called by: domain.features.extractor. Calls: stdlib only.
Config: ``LanguageConfig``, ``CodeConfig``, ``CodingIntentConfig``,
``GreetingConfig`` (thresholds, word lists, and phrases are placeholders,
A-43 style: not tuned on any data).
Status: demo components (Demo milestone, ADR-0023). Written for this module
and tested; nothing is taken from the sample-EDA helpers (ADR-0008).

Known limits (stated, not hidden):
- Script, not language: Arabic-script text counts as Persian unless it has an
  Arabic-only letter and no Persian-only letter; Latin-script text counts as
  English (French or German come out ``en``).
- "Mixed" is by words: the minority script's share of words must reach
  ``mixed_min_share``. A Persian sentence with one English brand name stays
  ``fa``.
- Code detection is a heuristic over lines (fences, keywords, call syntax,
  operators); prose about code without code stays ``False``.
- Coding intent is keywords, request cues, and word templates, not meaning:
  "fix this error" is a request for programming help only if the error is a
  program's. A shop customer asking how to fix a payment error («چطور خطای
  پرداخت را رفع کنم») comes out ``True`` (a keyword and a cue); "how do I
  return this" with no keyword comes out ``False``. Persian «برنامه» also
  means "plan" or "schedule". Configured exclusions («کد تخفیف», "discount
  code", …) remove the commonest shop uses of "code" first.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from functools import cache

from metis_auto.contracts import ContractModel, Language

_FENCE = re.compile(r"```.*?(```|$)", re.DOTALL)
_INLINE = re.compile(r"`[^`\n]+`")


def _is_arabic_script(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x0600 <= cp <= 0x06FF
        or 0x0750 <= cp <= 0x077F
        or 0x08A0 <= cp <= 0x08FF
        or 0xFB50 <= cp <= 0xFDFF
        or 0xFE70 <= cp <= 0xFEFF
    )


def _is_latin(ch: str) -> bool:
    return ch.isascii() or 0x00C0 <= ord(ch) <= 0x024F


# --- language ---------------------------------------------------------------


class LanguageConfig(ContractModel):
    """Placeholders (A-43 style). Shares are of words, not characters."""

    min_letters: int = 2
    """Fewer letters than this (after removing code) → undetermined."""
    mixed_min_share: float = 0.15
    """Minority script's share of words at or above this → mixed."""
    other_min_share: float = 0.5
    """Share of letters in other scripts (Cyrillic, CJK, …) → other."""
    arabic_only_letters: str = "ةى"
    """Letters that mark Arabic rather than Persian (with no Persian-only one)."""
    persian_only_letters: str = "پچژگ"


def strip_code(text: str) -> str:
    """The text without fenced blocks and inline code spans."""
    return _INLINE.sub(" ", _FENCE.sub(" ", text))


def detect_language(text: str, config: LanguageConfig) -> Language:
    """Language of ``text`` by script (see the module's known limits)."""
    prose = strip_code(text)
    arabic = latin = other = 0
    words = {"arabic": 0, "latin": 0}
    current: str | None = None
    for ch in prose:
        if not ch.isalpha():
            current = None
            continue
        if _is_arabic_script(ch):
            script = "arabic"
            arabic += 1
        elif _is_latin(ch):
            script = "latin"
            latin += 1
        else:
            other += 1
            current = None
            continue
        if script != current:
            words[script] += 1
            current = script
    letters = arabic + latin + other
    if letters < config.min_letters:
        return Language.UNDETERMINED
    if other / letters >= config.other_min_share:
        return Language.OTHER
    total_words = words["arabic"] + words["latin"]
    if total_words == 0:
        return Language.OTHER
    minority = min(words["arabic"], words["latin"]) / total_words
    if minority >= config.mixed_min_share:
        return Language.MIXED
    if words["arabic"] > words["latin"]:
        if any(c in prose for c in config.arabic_only_letters) and not any(
            c in prose for c in config.persian_only_letters
        ):
            return Language.OTHER
        return Language.PERSIAN
    return Language.ENGLISH


# --- code -------------------------------------------------------------------

_STRONG = (
    re.compile(
        r"^\s*(def|class|import|from\s+[\w.]+\s+import|function|const|let|var|"
        r"public|private|protected|static|return|#include|package|using|fn|func)"
        r"\b[\s\w(<{:]",
        re.MULTILINE,
    ),
    re.compile(r"\b[A-Za-z_]\w*\s*\([^()\n]*\)\s*(\{|:\s*$|=>)", re.MULTILINE),
    re.compile(
        r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE)\b.*\b(FROM|INTO|SET|WHERE|TABLE)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(r"<([a-zA-Z][\w-]*)(\s[^<>]*)?>.*</\1>", re.DOTALL),
)
_OPERATORS = re.compile(r"(==|!=|<=|>=|&&|\|\||=>|->|::|\+=|-=)")
_WEAK = (
    re.compile(r";\s*$", re.MULTILINE),
    re.compile(r"^\s*[{}\[\]]\s*$", re.MULTILINE),
    re.compile(r"\b[A-Za-z_]\w*\.[A-Za-z_]\w*\("),
    re.compile(r"\b[A-Za-z_]\w*\([^()\n]*\)"),
    re.compile(r"^\s*(#|//)\s?\S", re.MULTILINE),
    re.compile(r"\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z]\w+\b"),
)


class CodeConfig(ContractModel):
    min_weak_signals: int = 2
    """Distinct weak signals needed when no fence or strong signal is found."""


def detect_code(text: str, config: CodeConfig) -> bool:
    """Code present: a fenced block, one strong signal (keyword at a line
    start, a call followed by a block, SQL, a matched markup tag pair), or
    ``min_weak_signals`` weak signals: each distinct operator (``==``, ``&&``,
    ``->``, …; at most two count), a trailing semicolon, a brace line, a
    call, a comment, a snake/camel identifier."""
    if "```" in text:
        return True
    if any(p.search(text) for p in _STRONG):
        return True
    operators = min(len(set(_OPERATORS.findall(text))), 2)
    weak = operators + sum(1 for p in _WEAK if p.search(text))
    return weak >= config.min_weak_signals


# --- coding intent ----------------------------------------------------------

_GAP = "..."


class CodingIntentConfig(ContractModel):
    """Placeholders (A-71, A-65 style), configured in
    ``[pipeline.features.coding_intent]``. All entries are phrases of whole
    words, matched after ``normalise_phrase`` (casefold, Persian letter
    folding, ZWNJ → space, punctuation removed)."""

    keywords: tuple[str, ...] = ()
    """Programming words (python, function, error, کد, تابع, خطا, …)."""
    request_cues: tuple[str, ...] = ()
    """Words that ask for something (write, fix, how, can you, بنویس, چطور, …).
    A keyword counts only together with a cue: "I studied python" is no."""
    templates: tuple[str, ...] = ()
    """Word templates enough on their own; ``...`` stands for up to
    ``max_gap`` words: "write ... function", "تابع ... بنویس"."""
    exclude_phrases: tuple[str, ...] = ()
    """Removed before matching keywords: "discount code", «کد تخفیف», …; the
    last word also matches with a suffix («کد تخفیفم»). Keywords match whole
    words only (a prefix «کد» would match «کدام», "which"), so inflected
    keywords are listed («خطای»)."""
    max_gap: int = 4


@cache
def _phrases(entries: tuple[str, ...]) -> frozenset[tuple[str, ...]]:
    """Normalised once per configured list (lists are tuples: hashable)."""
    return frozenset(normalise_phrase(p) for p in entries) - {()}


def _contains(words: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    return any(words[i : i + n] == phrase for i in range(len(words) - n + 1))


def _remove(words: tuple[str, ...], phrase: tuple[str, ...]) -> tuple[str, ...]:
    """``words`` without ``phrase``; its last word also matches as a prefix
    (Persian suffixes: «کد تخفیفم»). Removing more is the safe side."""
    out: list[str] = []
    i, n = 0, len(phrase)
    while i < len(words):
        window = words[i : i + n]
        if (
            len(window) == n
            and window[:-1] == phrase[:-1]
            and window[-1].startswith(phrase[-1])
        ):
            i += n
        else:
            out.append(words[i])
            i += 1
    return tuple(out)


@cache
def _template(raw: str) -> tuple[tuple[str, ...], ...]:
    """A template's word groups between the gaps."""
    parts = [normalise_phrase(part) for part in raw.split(_GAP)]
    return tuple(p for p in parts if p)


def _matches(
    words: tuple[str, ...], groups: tuple[tuple[str, ...], ...], gap: int
) -> bool:
    def from_(start: int, k: int, first: bool) -> bool:
        if k == len(groups):
            return True
        group = groups[k]
        last = len(words) - len(group)
        end = last if first else min(last, start + gap)
        for i in range(start, end + 1):
            if words[i : i + len(group)] == group and from_(
                i + len(group), k + 1, False
            ):
                return True
        return False

    return bool(groups) and from_(0, 0, True)


def detect_coding_intent(text: str, has_code: bool, config: CodingIntentConfig) -> bool:
    """The message asks for code or programming help and has no code
    (``has_code`` from ``detect_code``): a template matches, or a keyword
    (after removing the exclusions) and a request cue both appear."""
    if has_code:
        return False
    words = normalise_phrase(text)
    if not words:
        return False
    if any(_matches(words, _template(t), config.max_gap) for t in config.templates):
        return True
    rest = words
    words_set = set(words)
    for phrase in _phrases(config.exclude_phrases):
        if phrase[0] in words_set:
            rest = _remove(rest, phrase)
    present = set(rest)
    keyword = any(
        p[0] in present and _contains(rest, p) for p in _phrases(config.keywords)
    )
    if not keyword:
        return False
    return any(
        p[0] in words_set and _contains(words, p) for p in _phrases(config.request_cues)
    )


# --- length -----------------------------------------------------------------


def length_bucket(chars: int, bounds: tuple[int, ...]) -> int:
    """0 for ``chars < bounds[0]``, 1 below ``bounds[1]``, …, ``len(bounds)``
    at or above the last bound."""
    return bisect_right(bounds, chars)


# --- greetings and small talk -----------------------------------------------

_TRANSLATE = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "‌": " ", "ـ": ""})
_DIACRITICS = re.compile(r"[ً-ٰٟ]")


class GreetingConfig(ContractModel):
    """Owner brief §7: a configurable Persian + English phrase list. Never
    "short = trivial": a short message that is not made of these phrases is
    substantive."""

    phrases: tuple[str, ...] = ()
    """Placeholders, configured in ``[pipeline.features.greeting]``."""
    max_chars: int = 40
    """Longer messages are never greetings."""
    symbols_only_is_small_talk: bool = True
    """A message of only emoji or punctuation (e.g. "👍", "!!") counts as small
    talk."""


def normalise_phrase(text: str) -> tuple[str, ...]:
    """Casefold, NFKC, Arabic yeh/kaf → Persian, ZWNJ → space, no diacritics
    or tatweel, punctuation and symbols removed; the words."""
    folded = unicodedata.normalize("NFKC", text).casefold().translate(_TRANSLATE)
    folded = _DIACRITICS.sub("", folded)
    kept = "".join(ch if ch.isalnum() else " " for ch in folded)
    return tuple(kept.split())


def is_greeting(text: str, config: GreetingConfig) -> bool:
    """True if ``text`` is short and made only of configured phrases (in any
    order, any punctuation), or only of symbols when that counts."""
    stripped = text.strip()
    if not stripped or len(stripped) > config.max_chars:
        return False
    words = normalise_phrase(stripped)
    if not words:
        return config.symbols_only_is_small_talk
    phrases = {normalise_phrase(p) for p in config.phrases}
    phrases.discard(())
    longest = max((len(p) for p in phrases), default=0)
    i = 0
    while i < len(words):
        for size in range(min(longest, len(words) - i), 0, -1):
            if words[i : i + size] in phrases:
                i += size
                break
        else:
            return False
    return True
