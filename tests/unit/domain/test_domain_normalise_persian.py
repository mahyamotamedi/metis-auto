"""Persian folding treatments (evaluation framework §0.3). SYNTHETIC strings;
invisible characters are written as escapes."""

import pytest

from metis_auto.domain.caching import (
    ALL_TREATMENTS,
    PERSIAN_TREATMENTS,
    TREATMENTS,
    normalise,
)
from metis_auto.domain.caching.policy import SUPPORTED_TREATMENTS

ZWNJ = "‌"
LRM, RLM = "‎", "‏"
V1, ZS, MARKS = PERSIAN_TREATMENTS


def test_the_default_set_and_serving_are_unchanged():
    assert TREATMENTS == ("literal", "whitespace", "nfkc_casefold_ws")
    assert ALL_TREATMENTS == TREATMENTS + PERSIAN_TREATMENTS
    assert not set(PERSIAN_TREATMENTS) & SUPPORTED_TREATMENTS


@pytest.mark.parametrize("treatment", PERSIAN_TREATMENTS)
def test_arabic_yeh_alef_maksura_and_kaf_fold_to_persian(treatment):
    assert normalise("يىك", treatment) == "ییک"
    # the existing treatment does not (the documented gap these close)
    assert normalise("ي", "nfkc_casefold_ws") != "ی"


@pytest.mark.parametrize("treatment", PERSIAN_TREATMENTS)
def test_both_digit_forms_become_ascii_and_distinct_numbers_stay_distinct(treatment):
    assert normalise("۱۲۳ ١٢٣ 123", treatment) == ("123 123 123")
    assert normalise("۱۲", treatment) != normalise("۱۳", treatment)


@pytest.mark.parametrize("treatment", PERSIAN_TREATMENTS)
def test_bidirectional_marks_are_removed(treatment):
    text = f"{RLM}سلام{LRM} hi ‫ x ⁧y⁩"
    assert normalise(text, treatment) == "سلام hi x y"


@pytest.mark.parametrize("treatment", PERSIAN_TREATMENTS)
def test_mixed_text_keeps_logical_order_and_latin_runs(treatment):
    text = "من Python می‌خواهم v3.13 ۲۰"
    out = normalise(text, treatment)
    assert out.index("Python") < out.index("v3.13")
    assert "Python" in out and "v3.13" in out  # Latin case and text untouched
    assert out.endswith("20")


@pytest.mark.parametrize("treatment", PERSIAN_TREATMENTS)
def test_latin_case_is_not_folded(treatment):
    assert normalise("Hello", treatment) != normalise("hello", treatment)


def test_zwnj_is_kept_by_default_variants_and_spaced_by_one():
    word = f"می{ZWNJ}خواهم"
    assert ZWNJ in normalise(word, V1)
    assert ZWNJ in normalise(word, MARKS)
    assert normalise(word, ZS) == "می خواهم"
    # a ZWNJ word and its unjoined spelling are different under v1
    assert normalise(word, V1) != normalise("میخواهم", V1)


def test_marks_variant_strips_diacritics_and_tatweel_others_keep_them():
    text = "سَلاـم"  # fatha, tatweel
    assert normalise(text, MARKS) == "سلام"
    assert normalise(text, V1) == text
    assert normalise(text, ZS) == text


@pytest.mark.parametrize("treatment", PERSIAN_TREATMENTS)
def test_whitespace_is_collapsed_and_ends_stripped(treatment):
    assert normalise(" سلام \t\n  دنیا ", treatment) == ("سلام دنیا")


@pytest.mark.parametrize("treatment", ALL_TREATMENTS)
def test_idempotent_and_the_input_is_left_alone(treatment):
    text = f"{RLM}يك ۱١ {ZWNJ} َ x  y "
    original = str(text)
    once = normalise(text, treatment)
    assert text == original
    assert normalise(once, treatment) == once


@pytest.mark.parametrize("treatment", PERSIAN_TREATMENTS)
def test_different_prompts_do_not_merge(treatment):
    a = normalise("سلام دنیا", treatment)
    b = normalise("دنیا سلام", treatment)
    assert a != b


def test_spelling_variants_of_one_prompt_do_merge():
    arabic = "كتاب يك ١٢"
    persian = "کتاب یک ۱۲"
    assert normalise(arabic, V1) == normalise(persian, V1)
    assert normalise(arabic, "literal") != normalise(persian, "literal")


def test_unknown_treatment_names_the_known_ones():
    with pytest.raises(ValueError, match="persian_fold_v1"):
        normalise("x", "persian_fold")
