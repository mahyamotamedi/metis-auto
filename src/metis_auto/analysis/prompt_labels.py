"""Local rule-based labels for user turns and bot instructions (heuristic).

Rules run on this machine and call no service. They are **heuristic labels, not
ground truth**: the review sets exist to measure their error. A prompt receives
one primary category by explicit precedence, plus secondary tags.

The word lists are visible configuration. Coding, intent to code and debugging are
one primary category by project rule; subtags only refine it.

Traces: FR-DATA-07/08, ADR-0006, ADR-0008.
"""

from __future__ import annotations

import re

CODING = "coding_intent_debugging"
ACCOUNT = "account_service_support"
TRANSLATION = "translation_language"
SUMMARIZE = "summarization_extraction"
MATH = "reasoning_math"
WRITING = "writing_editing"
ADVICE = "advice_planning"
FACTUAL = "factual_question"
CONVERSATION = "conversational_support"
MEDIA = "media_generation"
UNKNOWN = "unknown_uncertain"

# Precedence: an explicit transformation or task beats its topic. The first match
# wins and later matches become secondary tags.
PRECEDENCE = (
    CODING,
    MEDIA,
    TRANSLATION,
    SUMMARIZE,
    MATH,
    WRITING,
    ACCOUNT,
    ADVICE,
    FACTUAL,
    CONVERSATION,
)


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.I)


_W = r"(?<![^\W_])"  # word start
_E = r"(?![^\W_])"  # word end


def _words(*ws: str) -> str:
    return _W + "(?:" + "|".join(ws) + ")" + _E


RULES: dict[str, re.Pattern[str]] = {
    CODING: _rx(
        r"```",
        r"\b(?:def|class|import|function|const|var)\s+\w+",
        r"\b(?:traceback|stack ?trace|exception|nullpointer|syntaxerror|typeerror)\b",
        _words(
            "python",
            "javascript",
            "typescript",
            "java",
            "php",
            "html",
            "css",
            "sql",
            "api",
            "json",
            "regex",
            "docker",
            "git",
            "django",
            "laravel",
            "react",
            "debug",
            "code",
            "coding",
            "script",
            "bug",
            "compile",
            "کد",
            "کدنویسی",
            "برنامه‌نویسی",
            "برنامه نویسی",
            "پایتون",
            "جاوا",
            "دیباگ",
            "اسکریپت",
        ),
    ),
    MEDIA: _rx(
        _words(
            "imagine",
            "midjourney",
            "dalle",
            "flux",
            "عکس بساز",
            "تصویر بساز",
            "نقاشی کن",
            "عکس بکش",
            "طراحی کن",
            "ساخت عکس",
            "تولید تصویر",
        ),
        r"(?:generate|create|draw|make) (?:an? )?(?:image|picture|photo|logo)",
    ),
    TRANSLATION: _rx(
        _words(
            "ترجمه",
            "ترجمه کن",
            "معنی",
            "معنیش",
            "معادل",
            "تلفظ",
            "گرامر",
            "translate",
            "translation",
            "grammar",
            "pronunciation",
            "به انگلیسی",
            "به فارسی",
        ),
    ),
    SUMMARIZE: _rx(
        _words(
            "خلاصه",
            "خلاصه کن",
            "استخراج",
            "دسته بندی",
            "دسته‌بندی",
            "summarize",
            "summary",
            "extract",
            "classify",
            "tldr",
            "نکات کلیدی",
        ),
    ),
    MATH: _rx(
        r"\d+\s*[-+*/^=×÷]\s*\d+",
        _words(
            "ریاضی",
            "معادله",
            "انتگرال",
            "مشتق",
            "احتمال",
            "محاسبه",
            "حل کن",
            "اثبات",
            "فیزیک",
            "شیمی",
            "equation",
            "integral",
            "derivative",
            "probability",
            "calculate",
            "solve",
            "prove",
        ),
    ),
    WRITING: _rx(
        _words(
            "بنویس",
            "بنویسید",
            "بنویسی",
            "ویرایش",
            "بازنویسی",
            "انشا",
            "مقاله",
            "متن",
            "کپشن",
            "نامه",
            "شعر",
            "داستان",
            "لحن",
            "rewrite",
            "paraphrase",
            "essay",
            "draft",
            "proofread",
            "caption",
            "write",
        ),
    ),
    ACCOUNT: _rx(
        _words(
            "برداشت",
            "واریز",
            "کیف پول",
            "کیف",
            "ریالی",
            "احراز",
            "احراز هویت",
            "حسابم",
            "پشتیبانی",
            "کارشناس",
            "تیکت",
            "کارت",
            "شارژ",
            "تراکنش",
            "پولم",
            "مسدود",
            "بازگشت",
            "پیگیری",
            "سفارش",
            "اشتراک",
            "رمز",
            "اکانت",
            "کاربری",
            "معامله",
            "معاملات",
            "تتر",
            "withdraw",
            "withdrawal",
            "deposit",
            "refund",
            "ticket",
            "subscription",
            "password",
            "login",
        ),
    ),
    ADVICE: _rx(
        _words(
            "پیشنهاد",
            "توصیه",
            "نظرت",
            "نظرتون",
            "برنامه ریزی",
            "برنامه‌ریزی",
            "چیکار کنم",
            "چکار کنم",
            "چه کنم",
            "بهتره",
            "راهنمایی",
            "کمکم",
            "advice",
            "recommend",
            "suggest",
            "should i",
            "plan",
        ),
    ),
    FACTUAL: _rx(
        r"[؟?]\s*$",
        _words(
            "چیست",
            "چیه",
            "چه",
            "چی",
            "کجاست",
            "کجا",
            "کی",
            "چرا",
            "چطور",
            "چطوری",
            "چگونه",
            "چجوری",
            "چند",
            "چقدر",
            "آیا",
            "ایا",
            "کدام",
            "کدوم",
            "توضیح",
            "what",
            "why",
            "how",
            "when",
            "where",
            "who",
            "which",
            "explain",
        ),
    ),
    CONVERSATION: _rx(
        _words(
            "سلام",
            "درود",
            "خوبی",
            "خوبم",
            "ممنون",
            "ممنونم",
            "مرسی",
            "متشکرم",
            "خداحافظ",
            "بخیر",
            "عزیزم",
            "عشقم",
            "دوستت",
            "ناراحتم",
            "خسته",
            "حوصله",
            "باشه",
            "اوکی",
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "bye",
            "ok",
            "okay",
        ),
    ),
}

CODING_SUBTAGS = {
    "debugging": _rx(
        r"\b(?:debug|bug|traceback|exception|stack ?trace)\b",
        _words("خطا", "ارور", "دیباگ"),
    ),
    "code_explanation": _rx(r"\bexplain\b.*\bcode\b", _words("این کد", "کد رو توضیح")),
}

_FOLLOWUP = _rx(
    r"^\s*(?:(?:و|خب|پس|بعد)\s)?(?:ادامه|بیشتر|دوباره|کوتاه|خلاصه|بله|آره|اره|نه|خیر)",
    _words(
        "اون",
        "اونا",
        "همون",
        "همین",
        "قبلی",
        "بالا",
        "گفتی",
        "دومی",
        "اولی",
        "ادامه بده",
        "continue",
        "previous",
        "above",
        "that one",
        "the second",
        "shorter",
        "again",
    ),
)
_FORMAT = _rx(
    r"\bjson\b",
    r"\b(?:table|bullet|exactly \d+|in \d+ words)\b",
    _words(
        "جدول",
        "فهرست",
        "لیست",
        "در حداکثر",
        "کلمه‌ای",
        "کلمه ای",
        "فقط جواب",
        "بدون توضیح",
    ),
)
_REASONING = _rx(
    _words(
        "اثبات",
        "تحلیل",
        "مقایسه",
        "استدلال",
        "مرحله به مرحله",
        "گام به گام",
        "دلیل",
        "prove",
        "analyze",
        "compare",
        "step by step",
        "derive",
        "trade-off",
    ),
)
_TEMPLATE_HINT = _rx(r"\b(?:national|family|phone|attached|history)\b")

BOT_ROLE_RULES: dict[str, re.Pattern[str]] = {
    "customer_support": _rx(
        _words(
            "پشتیبانی",
            "مشتری",
            "مشتریان",
            "کاربران",
            "تیکت",
            "کارشناس",
            "customer",
            "support",
            "agent",
            "helpdesk",
        ),
    ),
    "finance_trading": _rx(
        _words(
            "کیف پول",
            "واریز",
            "برداشت",
            "تتر",
            "طلا",
            "معامله",
            "ارز",
            "صرافی",
            "بانک",
            "وام",
            "wallet",
            "exchange",
            "crypto",
            "trading",
            "loan",
            "bank",
        ),
    ),
    "education_tutor": _rx(
        _words(
            "معلم",
            "دانش آموز",
            "دانش‌آموز",
            "تدریس",
            "آموزش",
            "درس",
            "کنکور",
            "استاد",
            "tutor",
            "teacher",
            "student",
            "lesson",
            "course",
        ),
    ),
    "language_learning": _rx(
        _words(
            "زبان انگلیسی",
            "مکالمه",
            "گرامر",
            "ترجمه",
            "language",
            "grammar",
            "translator",
        ),
    ),
    "health": _rx(
        _words(
            "پزشک",
            "دکتر",
            "درمان",
            "بیمار",
            "سلامت",
            "روانشناس",
            "doctor",
            "medical",
            "therapist",
        ),
    ),
    "legal": _rx(_words("حقوقی", "وکیل", "قانون", "lawyer", "legal")),
    "roleplay_companion": _rx(
        _words(
            "نقش",
            "شخصیت",
            "دوست دختر",
            "دوست پسر",
            "roleplay",
            "role-play",
            "persona",
            "character",
            "girlfriend",
            "boyfriend",
            "companion",
        ),
    ),
    "coding_assistant": _rx(
        _words(
            "برنامه نویس", "برنامه‌نویس", "developer", "programmer", "coding", "python"
        )
    ),
    "content_writing": _rx(
        _words("محتوا", "کپی رایت", "copywriter", "marketing", "seo", "اینستاگرام")
    ),
    "sales_commerce": _rx(
        _words(
            "فروش", "فروشگاه", "محصول", "محصولات", "قیمت", "sales", "shop", "product"
        )
    ),
}

BOT_CONSTRAINT_RULES: dict[str, re.Pattern[str]] = {
    "output_format": _rx(r"\bjson\b", _words("فرمت", "جدول", "format", "markdown")),
    "language_rule": _rx(
        _words("به زبان فارسی", "فارسی پاسخ", "in persian", "in farsi", "respond in")
    ),
    "length_rule": _rx(
        _words("کوتاه", "حداکثر", "خلاصه", "concise", "short", "maximum")
    ),
    "scope_restriction": _rx(
        _words("فقط", "نباید", "هرگز", "only", "never", "do not", "must not")
    ),
}


def primary_category(text: str | None) -> tuple[str, tuple[str, ...]]:
    """Return (primary category, other matched categories) by precedence."""
    if not text or not text.strip():
        return UNKNOWN, ()
    hits = [c for c in PRECEDENCE if RULES[c].search(text)]
    return (hits[0], tuple(hits[1:])) if hits else (UNKNOWN, ())


def coding_subtags(text: str | None) -> tuple[str, ...]:
    return tuple(k for k, rx in CODING_SUBTAGS.items() if text and rx.search(text))


def history_dependence(text: str | None, turn_index: int) -> str:
    """``first_turn``, ``likely_dependent`` or ``later_turn_no_signal``.

    Dependence needs a textual signal; a later turn alone is not proof.
    """
    if turn_index == 0:
        return "first_turn"
    t = text or ""
    if _FOLLOWUP.search(t) or len(t.strip()) <= 15:
        return "likely_dependent"
    return "later_turn_no_signal"


def has_format_constraint(text: str | None) -> bool:
    return bool(text and _FORMAT.search(text))


def reasoning_demand(text: str | None, category: str) -> str:
    """Operational proxy, not difficulty: ``high`` needs an explicit signal."""
    t = text or ""
    if category in (MATH, CODING) or _REASONING.search(t):
        return "high"
    return "medium" if len(t) > 200 else "low"


def has_template_hint(text: str | None) -> bool:
    """Words that suggest application-injected fields in a user turn."""
    return bool(text and len(_TEMPLATE_HINT.findall(text)) >= 2)


def skeleton(text: str | None, width: int = 60) -> str:
    """Structure of a message start: letters and digits collapsed by script.

    Grouping key for prompt patterns, local only. Holds no words.
    """
    out = []
    for ch in (text or "")[:width]:
        if ch.isdigit():
            c = "9"
        elif ch.isascii() and ch.isalpha():
            c = "a"
        elif ch.isalpha():
            c = "f"
        elif ch.isspace():
            c = " "
        else:
            c = ch
        if not out or out[-1] != c:
            out.append(c)
    return "".join(out)


def bot_tags(instruction: str | None) -> dict[str, tuple[str, ...]]:
    """Role and constraint tags from an instruction; multi-label, may be empty."""
    t = instruction or ""
    return {
        "roles": tuple(k for k, rx in BOT_ROLE_RULES.items() if rx.search(t)),
        "constraints": tuple(
            k for k, rx in BOT_CONSTRAINT_RULES.items() if rx.search(t)
        ),
    }
