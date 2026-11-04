"""UI Stage 2b polish (owner review 2026-11-03, ADR-0052 Amendment 1): the
wordmark, the header budget, readable version names, one number formatter,
centred HTML legends, right-to-left bar charts and the chat texts of
``wiring.demo_ui`` in both languages. Config files and wiring only, no
Streamlit."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.wiring.demo_ui import (
    BudgetView,
    blocked_banner,
    detail_sections,
    friendly_failure,
    live_banner,
    term_text,
)
from metis_auto.wiring.lever_view import (
    LEVERS_DIR,
    display_name,
    load_lever_names,
)
from metis_auto.wiring.ui_config import load_strings, load_theme, translator
from metis_auto.wiring.ui_format import fmt
from metis_auto.wiring.ui_style import (
    bar_layout,
    budget_html,
    header_brand_html,
    legend_html,
)

REPO = Path(__file__).resolve().parents[3]
STRINGS = load_strings()
FA, EN = translator(STRINGS, "fa"), translator(STRINGS, "en")


# --- (1) wordmark -----------------------------------------------------------------


def test_wordmark_is_metis_auto_with_the_prototype_pill():
    fa, en = header_brand_html(FA), header_brand_html(EN)
    assert "متیس‌اتو" in fa and "نمونه‌ی آزمایشی" in fa
    assert "Metis-Auto" in en and "prototype" in en
    assert ">متیس<" not in fa  # never Metis's own name alone
    assert "<svg" not in fa + en and "<img" not in fa + en


# --- (2) header budget --------------------------------------------------------------


def _budget(spent: str, cap: str) -> BudgetView:
    return BudgetView(
        currency="USD",
        lifetime_spent=Decimal(spent),
        lifetime_cap=Decimal(cap),
        lifetime_fraction=float(Decimal(spent) / Decimal(cap)),
        run_spent=Decimal(0),
        run_cap=None,
        run_fraction=None,
        warn_at=(0.5, 0.8),
        crossed=None,
    )


def test_header_budget_is_the_real_amount_left_of_the_cap():
    html = budget_html(FA, budget=_budget("12.60", "20"))
    assert "بودجه:" in html and "از" in html
    assert '<b><bdi dir="ltr" class="mx-ltr">$7.40</bdi></b>' in html
    assert "$20.00" in html
    assert "آزمایشی" not in html  # the mode is only in the chip
    en = budget_html(EN, budget=_budget("2.5", "10"))
    assert "Budget:" in en and "$7.50" in en and "$10.00" in en


def test_header_budget_unknown_is_never_a_made_up_number():
    html = budget_html(FA, budget=None)
    assert "بودجه:" in html and "نامعلوم" in html
    assert not re.search(r"[0-9]", html)


# --- (3) readable version names -----------------------------------------------------


def _committed_ids() -> set[str]:
    """Lever IDs of the result files; other JSON in the folder (a summary such as
    ``pipeline_b_overhead.json``) has no ``lever_id`` and is skipped, as
    ``load_view`` skips it."""
    folder = REPO / LEVERS_DIR
    data = (json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*.json"))
    return {d["lever_id"] for d in data if isinstance(d, dict) and "lever_id" in d}


@pytest.mark.skipif(not (REPO / LEVERS_DIR).is_dir(), reason="no lever results")
def test_every_committed_lever_id_has_a_display_name():
    names = load_lever_names()
    ids = _committed_ids()
    assert len(ids) > 30
    for lang in ("fa", "en"):
        t = translator(STRINGS, lang)
        missing = [i for i in ids if display_name(i, lang, t, names).missing]
        assert missing == [], (lang, sorted(missing))


def test_display_name_is_short_with_its_owner_and_keeps_the_id():
    names = load_lever_names()
    fa = display_name(
        "rb1.retrieval-cache.ttl-90d.user.tune.as_logged", "fa", FA, names
    )
    assert fa.text == "حافظه‌ی بازیابی، ۹۰ روز (B)"
    assert fa.id == "rb1.retrieval-cache.ttl-90d.user.tune" and not fa.missing
    en = display_name("rb1.retrieval-cache.ttl-90d.user.tune", "en", EN, names)
    assert en.text == "Retrieval cache, 90 days (B)"
    hb = display_name("ctx.history_budget.b8000.todays_models", "en", EN, names)
    assert hb.text == "History budget, 8,000 tokens (C)"
    pq = display_name("cache.popular_question.first_turn", "en", EN, names)
    assert pq.text.endswith("(A)") and "." not in pq.text.removesuffix(" (A)")


def test_unknown_id_falls_back_to_the_raw_id_with_a_marker():
    names = load_lever_names()
    for lang, t in (("fa", FA), ("en", EN)):
        name = display_name("route.synth_rules", lang, t, names)
        assert name.missing and name.id == "route.synth_rules"
        assert name.text.startswith("route.synth_rules")
        assert t("name_missing") in name.text


def test_lever_names_file_is_complete_in_both_languages():
    names = load_lever_names()
    assert names and all(n.fa and n.en and n.owner in "ABCD" for n in names)


# --- (4) one number formatter -------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "kind", "kwargs", "expected"),
    [
        (Decimal("327.779"), "money", {}, "327.78"),
        (Decimal("8212.0"), "money", {}, "8,212.00"),
        (Decimal("1234567.891"), "money", {"currency": "USD"}, "$1,234,567.89"),
        (Decimal("0.001921"), "money", {"currency": "USD"}, "$0.001921"),
        (Decimal("0.000320"), "money", {"currency": "USD"}, "$0.00032"),
        (Decimal("0.0086082"), "money", {}, "0.008608"),
        (Decimal("0.99996"), "money", {}, "1.00"),
        (Decimal("0"), "money", {"currency": "USD"}, "$0.00"),
        (Decimal("-0.008440"), "money", {"currency": "USD"}, "-$0.00844"),
        (Decimal("-0.008440"), "money", {"signed": True}, "-0.00844"),
        (Decimal("0.5"), "money", {"signed": True}, "+0.5"),
        (Decimal("7.4"), "money", {"currency": "EUR"}, "7.40 EUR"),
        (8667, "count", {}, "8,667"),
        (Decimal("355965"), "count", {}, "355,965"),
        (0.0251, "percent", {}, "2.5%"),
        (Decimal("0.98"), "percent", {}, "98.0%"),
        (0.0225, "percent", {}, "2.3%"),
        ((0.0225, 0.0278), "interval", {}, "[2.3%, 2.8%]"),
        (None, "money", {"unknown": "نامعلوم"}, "نامعلوم"),
    ],
)
def test_fmt(value, kind, kwargs, expected):
    assert fmt(value, kind, **kwargs) == expected


def test_fmt_never_changes_the_value():
    value = Decimal("0.0086082")
    fmt(value, "money")
    assert value == Decimal("0.0086082")


def test_fmt_refuses_an_unknown_kind():
    with pytest.raises(ValueError):
        fmt(1, "colour")


# --- (6) legends and (7) right-to-left bars -------------------------------------------


def test_legend_is_a_centred_html_row_of_square_swatches():
    theme = load_theme("dark")
    html = legend_html(
        [("قبل", theme.chart["cat_1"]), ("gpt-4.1-nano", theme.chart["cat_2"])]
    )
    assert 'class="mx-legend"' in html and html.count('class="mx-swatch"') == 2
    assert theme.chart["cat_1"] in html and "قبل" in html
    assert '<bdi dir="ltr" class="mx-ltr">gpt-4.1-nano</bdi>' in html
    assert legend_html([]) == ""


def test_bars_read_right_to_left_in_persian():
    assert bar_layout("fa") == {"y_orient": "right", "x_reverse": True}
    assert bar_layout("en") == {"y_orient": "left", "x_reverse": False}


# --- (8) chat texts in both languages -------------------------------------------------


def _english_values() -> list[str]:
    return [
        STRINGS.text(k, "en")
        for k in STRINGS.keys()
        if k.startswith(("term_", "det_", "banner_", "fail_", "rkind_"))
    ]


def test_cost_terms_are_translated_without_changing_the_terms():
    assert term_text("Premium estimate", FA) == FA("term_premium_estimate")
    assert term_text("Actually paid", EN) == "Actually paid"
    assert term_text("Provider cache", FA) != "Provider cache"


def test_banners_and_failures_speak_persian():
    texts = [
        live_banner(live=False, allowed=True, reasons=(), t=FA).detail,
        live_banner(live=True, allowed=True, reasons=(), t=FA).detail,
        live_banner(live=True, allowed=True, reasons=(), stopped="x", t=FA).detail,
        blocked_banner("x", t=FA).detail,
    ]
    for text in texts:
        assert re.search(r"[؀-ۿ]", text), text
        for english in ("Answers are canned", "Every call goes", "Switch to fake"):
            assert english not in text
    # the English defaults are unchanged (the view tests read them)
    assert (
        "Answers are canned" in live_banner(live=False, allowed=True, reasons=()).detail
    )
    assert len(_english_values()) > 30


def test_detail_sections_keep_order_and_translate_labels():
    from metis_auto.wiring.chat import TurnReport

    report = TurnReport(
        status="ok",
        served_by="model",
        model_id="gpt-4.1-nano",
        provider_model=None,
        tokens={"input": "12", "output": "3"},
        cost="0.000010 USD",
        cost_caveats=(),
        premium_estimate="0.000500 USD",
        premium_caveats=(),
        decomposition=(),
        session_decomposition=(),
        overhead_ms=1.5,
        overhead_cost="0.000000 USD",
    )
    en = detail_sections(report)
    fa = detail_sections(report, t=FA)
    assert [len(rows) for _, rows in en] == [len(rows) for _, rows in fa]
    en_values = [v for _, rows in en for _, v in rows]
    fa_values = [v for _, rows in fa for _, v in rows]
    # data values (model id, tokens, amounts) are unchanged; words are translated
    for data in ("gpt-4.1-nano", "12", "0.000010 USD", "1.50 ms"):
        assert en_values.index(data) == fa_values.index(data)
    assert "model" in en_values and "model" not in fa_values
    assert en[0][0] == "Served" and fa[0][0] == FA("det_sec_served")
    for title, rows in fa:
        assert re.search(r"[؀-ۿ]", title), title
        for label, _ in rows:
            assert re.search(r"[؀-ۿ]", label), label
    fail = friendly_failure(
        TurnReport(**{**report.__dict__, "status": "error", "failure": "boom"}), t=FA
    )
    assert fail and "No answer" not in fail and "boom" in fail


def test_dollar_amounts_survive_markdown():
    """Streamlit reads text between two ``$`` as LaTeX: markdown labels (the
    budget bars, the message badge) escape the sign."""
    from metis_auto.wiring.ui_style import md_safe

    text = md_safe("مصرف: $12.60 از $20.00")
    assert text == "مصرف: \\$12.60 از \\$20.00"
    assert md_safe(md_safe("$1")) == "\\$1"  # idempotent
