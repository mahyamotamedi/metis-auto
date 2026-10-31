"""Content-free text features: script mix, language label, normalisation, hashes.

Every function returns derived features only. The language label is a
**heuristic label** (script ratios plus short stop-word lists), not ground truth.
Arabic script is not equated with Persian: a Persian label needs Persian-specific
letters or Persian function words. Latin script is not equated with English.

Traces: FR-DATA-07/08, ADR-0008. Written from requirements; nothing copied from
experiments/sample_eda/eda_helpers.py.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

ZWNJ = "‌"
# Persian-specific letters (absent from Arabic): peh, tcheh, jeh, gaf.
_FA_ONLY = set("پچژگ")
# Persian yeh/kaf vs Arabic yeh/kaf (variants seen in mixed data).
_FA_YEH_KAF = set("یک")
_AR_YEH_KAF = set("يك")
_ARABIC_BLOCKS = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)
_DIGITS_FA = set("۰۱۲۳۴۵۶۷۸۹")
_DIGITS_AR = set("٠١٢٣٤٥٦٧٨٩")
_DIGITS_LATIN = set("0123456789")
_URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+")
_CODE_HINT_RE = re.compile(
    r"(```|^\s*(def|class|import|function|const|let|var|SELECT|<\w+>)\b)", re.M
)
_DIACRITICS = {chr(c) for c in range(0x064B, 0x0653)} | {"ٰ"}

# Small function-word lists. Deliberately tiny and visible (configuration, not truth).
_FA_STOP = {
    "و",
    "در",
    "به",
    "از",
    "که",
    "این",
    "را",
    "با",
    "است",
    "برای",
    "من",
    "شما",
    "چی",
    "چه",
    "می",
}
_FINGLISH = {
    "salam",
    "slm",
    "merci",
    "mamnun",
    "mamnoon",
    "khoobi",
    "khobi",
    "chetori",
    "chetor",
    "man",
    "shoma",
    "che",
    "ke",
    "dar",
    "baraye",
    "mikham",
    "mikhaham",
    "nemidunam",
    "lotfan",
    "mersi",
    "hast",
    "nist",
    "bashe",
    "kon",
    "kardan",
    "chi",
    "chera",
    "ya",
}
_EN_STOP = {
    "the",
    "and",
    "is",
    "are",
    "to",
    "of",
    "in",
    "for",
    "what",
    "how",
    "you",
    "can",
    "please",
    "with",
    "this",
    "that",
}
_WORD_RE = re.compile(r"[A-Za-z']+")


def is_arabic_script(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _ARABIC_BLOCKS)


def fingerprint(text: str) -> str:
    """Unkeyed content hash for local, git-ignored derived tables only.

    Committed outputs never carry it (ADR-0015 keyed fingerprints are for
    production; this is an analysis-time grouping key).
    """
    return hashlib.blake2b(
        text.encode("utf-8", "surrogatepass"), digest_size=12
    ).hexdigest()


def normalize_exact(text: str) -> str:
    """Whitespace-only normalisation: trim and collapse runs of whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def normalize_safe(text: str) -> str:
    """Conservative normalisation for duplicate grouping.

    NFKC; Arabic yeh/kaf to Persian; Arabic-Indic and Persian digits to ASCII;
    remove diacritics and tatweel; ZWNJ to space; casefold; collapse whitespace.
    Numbers keep their value (digit shape only), so '2' and '3' never collide.
    """
    t = unicodedata.normalize("NFKC", text)
    out = []
    for ch in t:
        if ch in _DIACRITICS or ch == "ـ":
            continue
        if ch == "ي":
            ch = "ی"
        elif ch == "ك":
            ch = "ک"
        elif ch in _DIGITS_FA:
            ch = str("۰۱۲۳۴۵۶۷۸۹".index(ch))
        elif ch in _DIGITS_AR:
            ch = str("٠١٢٣٤٥٦٧٨٩".index(ch))
        elif ch == ZWNJ:
            ch = " "
        out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip().casefold()


def is_json_like(text: str) -> bool:
    s = text.strip()
    if not s or s[0] not in "{[":
        return False
    try:
        json.loads(s)
    except ValueError:
        return False
    return True


_AR_LETTER = re.compile(
    "[\u0621-\u064a\u066e-\u06d3\u06fa-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]"
)
_LATIN_LETTER = re.compile("[A-Za-z]")
_OTHER_ALPHA = re.compile(
    "[^\\W\\d_A-Za-z\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]"
)
_FA_ONLY_RE = re.compile("[پچژگ]")
_FA_VARIANT_RE = re.compile("[\u06cc\u06a9]")
_AR_VARIANT_RE = re.compile("[\u064a\u0643]")
_DIGIT_FA_RE = re.compile("[۰-۹]")
_DIGIT_AR_RE = re.compile("[٠-٩]")
_DIGIT_LATIN_RE = re.compile("[0-9]")


def script_counts(text: str) -> dict[str, int]:
    """Counts by character class over ``text`` with URLs removed (regex based)."""
    t = _URL_RE.sub(" ", text)
    return {
        "n_arabic_script": len(_AR_LETTER.findall(t)),
        "n_latin": len(_LATIN_LETTER.findall(t)),
        "n_digit_latin": len(_DIGIT_LATIN_RE.findall(t)),
        "n_digit_fa": len(_DIGIT_FA_RE.findall(t)),
        "n_digit_ar": len(_DIGIT_AR_RE.findall(t)),
        "n_zwnj": t.count(ZWNJ),
        "n_fa_only": len(_FA_ONLY_RE.findall(t)),
        "n_ar_variant": len(_AR_VARIANT_RE.findall(t)),
        "n_fa_variant": len(_FA_VARIANT_RE.findall(t)),
        "n_other_alpha": len(_OTHER_ALPHA.findall(t)),
    }


def language_label(text: str, min_letters: int = 6) -> str:
    """Heuristic language label.

    One of: ``empty``, ``short_uncertain``, ``structured``, ``fa``, ``en``,
    ``fa_en_mixed``, ``finglish``, ``arabic_script_other``, ``other``.

    "Mixed" means natural-language mixing: both scripts contribute at least 15% of
    letters after URLs are removed. Code fences and JSON-like strings are labelled
    ``structured`` before any language rule.
    """
    if not text or not text.strip():
        return "empty"
    if is_json_like(text) or _CODE_HINT_RE.search(text):
        return "structured"
    c = script_counts(text)
    ar, la, oth = c["n_arabic_script"], c["n_latin"], c["n_other_alpha"]
    letters = ar + la + oth
    if letters < min_letters:
        return "short_uncertain"
    ar_f, la_f = ar / letters, la / letters
    if ar_f >= 0.15 and la_f >= 0.15:
        return "fa_en_mixed"
    if oth / letters > 0.5:
        return "other"
    if ar_f > 0.5:
        words = set(text.replace(ZWNJ, " ").split())
        persian_signal = (
            c["n_fa_only"] > 0
            or c["n_fa_variant"] > c["n_ar_variant"]
            or bool(words & _FA_STOP)
        )
        return "fa" if persian_signal else "arabic_script_other"
    if la_f > 0.5:
        words = [w.lower() for w in _WORD_RE.findall(text)]
        if not words:
            return "short_uncertain"
        fing = sum(w in _FINGLISH for w in words)
        eng = sum(w in _EN_STOP for w in words)
        if fing >= 2 and fing > eng:
            return "finglish"
        return "en"
    return "other"


def text_features(text: str | None) -> dict[str, object]:
    """All content-free features for one string (``None`` is unknown, not empty)."""
    if text is None:
        return {"content_state": "null"}
    feats: dict[str, object] = {
        "content_state": "blank" if not text.strip() else "text",
        "n_chars": len(text),
        "n_words": len(text.split()),
        "n_lines": text.count("\n") + 1 if text else 0,
        "lang": language_label(text),
        "is_json": is_json_like(text),
        "has_url": bool(_URL_RE.search(text)),
    }
    feats.update(script_counts(text))
    return feats
