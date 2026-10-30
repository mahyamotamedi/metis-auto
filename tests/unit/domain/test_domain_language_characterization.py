"""Characterization of ``detect_language`` and ``length_bucket`` AS THEY ARE
(Stage E0). These pin current behavior, including its stated limits; they do
not endorse the placeholder thresholds (A-43). SYNTHETIC strings. A change
that breaks one of these is a change to routing's feature extractor and needs
its own decision."""

import pytest

from metis_auto.contracts import Language
from metis_auto.domain.features import detect_language, length_bucket
from metis_auto.domain.features.detectors import LanguageConfig

CONFIG = LanguageConfig()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("سلام دنیا چطوری", Language.PERSIAN),
        ("hello world how are you", Language.ENGLISH),
        ("سلام hello دنیا world", Language.MIXED),
        # one English word in a Persian sentence stays Persian (stated limit)
        ("من از Google استفاده می‌کنم و خیلی خوبه", Language.PERSIAN),
        # Arabic-only letter with no Persian-only letter → other
        ("هذه مدرسة", Language.OTHER),
        # a Persian-only letter outweighs it
        ("مدرسة پیتزا", Language.PERSIAN),
        ("привет мир", Language.OTHER),
        ("12 ۱۲", Language.UNDETERMINED),
        ("a", Language.UNDETERMINED),
        ("", Language.UNDETERMINED),
        # code is stripped before detection
        ("```python\nprint(1)\n```", Language.UNDETERMINED),
        ("سلام `x = 1`", Language.PERSIAN),
    ],
)
def test_detect_language_today(text, expected):
    assert detect_language(text, CONFIG) == expected


def test_arabic_script_is_not_verified_to_be_persian():
    """Without Arabic-only or Persian-only letters, Arabic-script text counts
    as Persian: the detector cannot tell Arabic or Urdu prose apart."""
    assert detect_language("ما هو الكتاب", CONFIG) == Language.PERSIAN


@pytest.mark.parametrize(
    "chars, bucket",
    [(0, 0), (79, 0), (80, 1), (399, 1), (400, 2), (1999, 2), (2000, 3), (10**6, 3)],
)
def test_length_bucket_boundaries_belong_to_the_higher_bucket(chars, bucket):
    assert length_bucket(chars, (80, 400, 2000)) == bucket


def test_length_bucket_without_bounds_is_one_bucket():
    assert length_bucket(5, ()) == 0
