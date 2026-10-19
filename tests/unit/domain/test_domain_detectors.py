"""Cheap text detectors (Demo milestone, FR-FEAT-01, FR-FEAT-03).

Every text below is SYNTHETIC, written for these tests (none from any
dataset). They carry no inline ``[SYNTHETIC]`` marker on purpose: the marker
is Latin-script text and would itself change the language result.
"""

import pytest

from metis_auto.contracts import Language
from metis_auto.domain.features import (
    CodeConfig,
    CodingIntentConfig,
    GreetingConfig,
    LanguageConfig,
    detect_code,
    detect_coding_intent,
    detect_language,
    is_greeting,
    length_bucket,
    normalise_phrase,
)

L = LanguageConfig()
C = CodeConfig()
G = GreetingConfig(
    phrases=(
        "سلام",
        "سلام علیکم",
        "مرسی",
        "خیلی ممنون",
        "خوبی",
        "hi",
        "hello",
        "thanks",
        "thank you",
        "ok",
        "good morning",
    ),
)

SYNTHETIC_LANGUAGE = [
    ("سلام، سفارشم کی می‌رسه؟", Language.PERSIAN),
    ("ساعت کاری فروشگاه شما از چند تا چند است؟", Language.PERSIAN),
    ("من یک گوشی iPhone خریدم که روشن نمی‌شود، چه کار کنم؟", Language.PERSIAN),
    ("Where is my order? It has been two weeks.", Language.ENGLISH),
    ("Please tell me how to reset my password, merci", Language.ENGLISH),
    ("سلام، لطفاً بگید چطور password رو reset کنم؟", Language.MIXED),
    ("I need help با سفارش شماره ۴۵ please", Language.MIXED),
    ("Привет, как дела у тебя сегодня?", Language.OTHER),
    ("مرحبا، أين تقع المدينة الجامعية؟", Language.OTHER),  # Arabic: ة, no پچژگ
    ("۱۲۳۴ ؟؟", Language.UNDETERMINED),
    ("👍", Language.UNDETERMINED),
]


@pytest.mark.parametrize(("text", "expected"), SYNTHETIC_LANGUAGE)
def test_language(text, expected):
    assert detect_language(text, L) == expected


def test_code_blocks_do_not_decide_the_language():
    text = "چرا این کد خطا می‌دهد؟\n```python\ndef add(a, b):\n    return a + b\n```"
    assert detect_language(text, L) == Language.PERSIAN
    assert detect_code(text, C) is True


def test_arabic_letter_folding_does_not_make_persian_other():
    # Persian typed with Arabic yeh/kaf (ي, ك) stays Persian.
    assert detect_language("كتاب را كي مي‌فرستيد؟", L) == Language.PERSIAN


SYNTHETIC_CODE = [
    ("def total(items):\n    return sum(items)", True),
    ("const x = fetch(url).then(r => r.json());", True),
    ("SELECT name FROM users WHERE id = 3", True),
    ('<div class="a">hi</div>', True),
    ("این خطا را می‌دهد: user.get_name() is undefined;", True),
    ("x == 2 && y != 3", True),
    ("How do I write a for loop in Python?", False),
    ("سلام، لطفاً هزینه ارسال را بگویید.", False),
    ("My order (number 45) has not arrived :)", False),
    ("Visit https://example.com/help for details.", False),
]


@pytest.mark.parametrize(("text", "expected"), SYNTHETIC_CODE)
def test_code(text, expected):
    assert detect_code(text, C) is expected


def test_length_buckets():
    bounds = (80, 400, 2000)
    assert [length_bucket(n, bounds) for n in (0, 79, 80, 399, 400, 1999, 2000)] == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
    ]


@pytest.mark.parametrize(
    "text",
    [
        "سلام",
        "سلام!",
        "سلام علیكم",
        "سلام خوبی؟",
        "مرسی 🙏",
        "خیلی ممنون.",
        "Hi",
        "hello!!",
        "Thanks, ok",
        "Thank you",
        "Good morning :)",
        "👍",
    ],
)
def test_greetings(text):
    assert is_greeting(text, G) is True


@pytest.mark.parametrize(
    "text",
    [
        "سلام، سفارشم کی می‌رسه؟",
        "hi, where is my order?",
        "ok but why?",
        "yes",
        "قیمت؟",
        "",
        "thanks " * 10,
    ],
)
def test_not_greetings(text):
    # Never "short = trivial": a short question is substantive.
    assert is_greeting(text, G) is False


def test_symbols_only_can_be_switched_off():
    config = G.model_copy(update={"symbols_only_is_small_talk": False})
    assert is_greeting("👍", config) is False


def test_phrase_normalisation():
    assert normalise_phrase("  سلامٌ،  علیكم!! ") == ("سلام", "علیکم")
    assert normalise_phrase("Thank‌You") == ("thank", "you")  # ZWNJ → space


# --- coding intent (A-71) ---------------------------------------------------

INTENT = CodingIntentConfig(
    keywords=("python", "function", "error", "کد", "تابع", "خطا", "برنامه نویسی"),
    request_cues=("write", "how", "can you", "بنویس", "چطور"),
    templates=("write ... function", "تابع ... بنویس"),
    exclude_phrases=("discount code", "کد تخفیف"),
    max_gap=2,
)


def intent(text: str, config: CodingIntentConfig = INTENT) -> bool:
    return detect_coding_intent(text, detect_code(text, C), config)


def test_intent_mechanics_templates_keywords_cues_and_exclusions():
    # A template alone is enough, with at most max_gap words in each gap.
    only = CodingIntentConfig(templates=INTENT.templates, max_gap=2)
    assert intent("Write a small function", only)
    assert not intent("Write a very small and tidy function", only)  # gap 4 > 2
    assert not intent("function write", only)  # order matters
    assert intent("تابع جمع بنویس")
    # A keyword needs a cue; a cue needs a keyword.
    assert intent("How does a python list work?")
    assert not intent("I like python")
    assert not intent("How are you?")
    # Exclusions are removed before keywords; their last word takes suffixes.
    assert not intent("How do I use a discount code?")
    assert not intent("کد تخفیفم چطور کار می‌کنه")
    # Keywords match whole words only: «کد» is not «کدام» ("which").
    assert not intent("کدام رنگ را چطور انتخاب کنم")
    # Multi-word keywords survive ZWNJ (folded to a space).
    assert intent("برنامه‌نویسی را چطور شروع کنم")


def test_intent_is_never_set_when_code_is_present():
    text = "def add(a, b):\n    return a + b\nhow do I fix this error?"
    assert detect_code(text, C)
    assert not intent(text)
    assert not detect_coding_intent("write a python function", True, INTENT)


def test_intent_with_no_configuration_is_always_no():
    assert not intent("write a python function", CodingIntentConfig())
    assert not intent("", INTENT)


def _configured() -> CodingIntentConfig:
    """The shipped placeholder lists ([pipeline.features.coding_intent])."""
    from metis_auto.settings import load_settings
    from metis_auto.wiring.from_settings import pipeline_config

    loaded = load_settings(runtime=None, dotenv=None, environ={})
    return pipeline_config(loaded).features.coding_intent


# SYNTHETIC messages, written for these tests.
SYNTHETIC_INTENT = [
    # English: asks for code
    ("write a python function to add two numbers", True),
    ("fix this error in my script", True),
    ("how do I sort a list in javascript", True),
    ("can you write a sql query that counts orders per day", True),
    ("explain what a regex is", True),
    # English: mentions programming, does not ask
    ("I studied python at university and loved it", False),
    ("my brother works as a javascript developer", False),
    ("the python at the zoo was huge", False),
    ("write a short poem about the sea", False),
    ("how can I use my discount code", False),
    ("where is my order", False),
    # Persian: asks for code
    ("یک تابع پایتون بنویس که دو عدد را جمع کند", True),
    ("این خطا رو چطور رفع کنم", True),
    ("یه اسکریپت برای پشتیبان‌گیری بنویس", True),
    ("چرا کدم کار نمی‌کنه", True),
    # Persian: mentions programming, does not ask
    ("برادرم برنامه‌نویس است", False),
    ("دیروز کلاس پایتون داشتم", False),
    ("کد تخفیفم کار نمیکنه چطور استفاده کنم", False),
    ("کدام رنگ موجود است؟", False),
    ("سفارشم کی می‌رسه؟", False),
    ("سلام چطوری", False),
    # Mixed: asks for code
    ("لطفا یک function بنویس که دو عدد رو جمع کنه", True),
    ("چطور یک bug در کد python رو پیدا کنم", True),
    ("این SQL query رو بنویس لطفا", True),
    # Mixed: mentions programming, does not ask
    ("دوستم توی شرکت javascript کار می‌کنه", False),
    ("کتاب python رو دیروز خریدم", False),
]


@pytest.mark.parametrize(("text", "expected"), SYNTHETIC_INTENT)
def test_coding_intent_with_the_configured_placeholder_lists(text, expected):
    config = _configured()
    assert detect_code(text, C) is False  # intent, not presence
    assert detect_coding_intent(text, False, config) is expected


def test_known_false_positive_is_stated_not_hidden():
    # A shop customer's payment error looks like a programming request
    # (keyword + cue): a documented limit of the placeholder (A-71).
    assert detect_coding_intent("چطور خطای پرداخت رو رفع کنم", False, _configured())
