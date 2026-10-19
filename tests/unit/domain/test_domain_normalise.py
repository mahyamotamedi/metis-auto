"""Cache-key message treatments (FR-XCACHE-03). SYNTHETIC strings."""

import pytest

from metis_auto.domain.caching import TREATMENTS, normalise


def test_literal_keeps_everything():
    assert normalise(" A  b\n", "literal") == " A  b\n"


def test_whitespace_collapses_unicode_space():
    assert normalise(" سلام  \t دنیا \n", "whitespace") == "سلام دنیا"


def test_nfkc_casefold_unifies_width_and_case():
    assert normalise("ＨＥＬＬＯ  Straße", "nfkc_casefold_ws") == "hello strasse"
    # NFKC maps Arabic presentation forms to base letters ...
    assert normalise("ﻻ", "nfkc_casefold_ws") == "لا"
    # ... but does not fold Arabic yeh into Persian yeh (a plan item)
    assert normalise("ي", "nfkc_casefold_ws") != normalise("ی", "nfkc_casefold_ws")


def test_unknown_treatment_fails():
    assert TREATMENTS == ("literal", "whitespace", "nfkc_casefold_ws")
    with pytest.raises(ValueError):
        normalise("x", "persian_fold")
