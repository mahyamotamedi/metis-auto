"""E3: full-prompt input counts, slices, ranking flips, instruction reuse and the
compression break-even. SYNTHETIC text, fake tokenizers (characters per token
differ by tokenizer), and the repo's historical price snapshot (g55). No real
recorded usage exists; nothing here establishes real-data validity."""

import math
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.contracts import (
    Component,
    Fidelity,
    PairingFlag,
    PairingMethod,
    Reference,
    ReplayCase,
    RetrievedContext,
    RetrievedItem,
    Role,
    TokenCount,
    Turn,
)
from metis_auto.contracts import Request as Req
from metis_auto.domain.features.detectors import LanguageConfig
from metis_auto.evaluation.inputs import (
    ORDER,
    build_report,
    case_inputs,
    compression_break_even,
    input_prices,
    slice_report,
)
from metis_auto.settings import repo_root
from metis_auto.settings.reference import read_catalogue, read_prices

CONFIG = repo_root() / "config" / "reference"
PRICES = read_prices(CONFIG / "prices-metis-2026-10-18-g55.toml")
CATALOGUE = {
    e.model_id: e for e in read_catalogue(CONFIG / "catalogue-metis-test.toml").entries
}
MODELS = [
    CATALOGUE[m]
    for m in ("gpt-5-nano", "deepseek-v4-flash", "mimo-v2.5", "grok-4-1-fast")
]
AS_OF = date(2026, 10, 30)


class Tok:
    """Fake tokenizer: ceil(characters / chars_per_token)."""

    def __init__(self, ref, per, fidelity=Fidelity.EXACT_LOCAL):
        self.ref, self._per, self._fidelity = ref, per, fidelity

    def count(self, text):
        return TokenCount(
            tokens=math.ceil(len(text) / self._per),
            fidelity=self._fidelity,
            method=f"fake-{self.ref}@1",
        )


class Clock:
    def now(self):
        return datetime(2026, 10, 30, tzinfo=UTC)

    def monotonic_ms(self):
        return 0.0


FP = Fingerprinter(ex.SYNTHETIC_TEST_KEY)
# tokens-per-character differ by tokenizer, like the measured Persian gap
SERVICE = MeasurementService(
    FP,
    Clock(),
    Tok("approx-chars-div-4", 4, Fidelity.APPROXIMATION),
    {
        "openai-o200k-base": Tok("openai-o200k-base", 3),
        "deepseek-v4": Tok("deepseek-v4", 2.5),
        "mimo-v2": Tok("mimo-v2", 1.5),
        "grok-approx": Tok("grok-approx", 4, Fidelity.APPROXIMATION),
    },
)
M = "[SYNTHETIC] "


def case(
    i,
    message,
    *,
    instructions=None,
    history=None,
    retrieved=None,
    depth=0,
    session=None,
):
    sess = session or f"s{i}"
    return ReplayCase(
        case_id=f"c{i}",
        session_ref=sess,
        turn_index=depth,
        request=Req(
            message=message,
            history=Component.present(tuple(history))
            if history
            else Component.absent(),
            instructions=(
                Component.present(instructions) if instructions else Component.absent()
            ),
            retrieved=(
                Component.present(
                    RetrievedContext(
                        items=tuple(RetrievedItem(text=t) for t in retrieved),
                        query=Component[str].absent(),
                    )
                )
                if retrieved
                else Component.absent()
            ),
            session_ref=sess,
        ),
        references=(Reference(position=1, text=M + "answer"),),
        pairing_method=PairingMethod.HEURISTIC_ARRAY_ORDER,
        pairing_flag=PairingFlag.CLEAN,
    )


def inputs_for(cases):
    return [
        case_inputs(
            c,
            measurement=SERVICE,
            entries=MODELS,
            fingerprinter=FP,
            language=LanguageConfig(),
            length_bounds=(20, 60),
        )
        for c in cases
    ]


FA = M + "سلام لطفا ساعت کاری فروشگاه را بگویید"
EN = M + "hello please tell me the opening hours"
LONG_INSTRUCTIONS = M + "You are a careful assistant. " * 40


# --- counting ---------------------------------------------------------------


def test_components_are_counted_per_model_in_the_assumed_order():
    c = case(
        1,
        FA,
        instructions=LONG_INSTRUCTIONS,
        history=[
            Turn(role=Role.USER, text=M + "hi"),
            Turn(role=Role.ASSISTANT, text=M + "hello"),
        ],
        retrieved=[M + "doc one", M + "doc two"],
    )
    (got,) = inputs_for([c])
    nano = got.per_model["gpt-5-nano"]
    assert tuple(nano.components) == ORDER
    assert nano.components["instructions"] == math.ceil(len(LONG_INSTRUCTIONS) / 3)
    assert nano.components["message"] == math.ceil(len(FA) / 3)
    mimo = got.per_model["mimo-v2.5"]
    assert mimo.components["message"] == math.ceil(len(FA) / 1.5)
    assert mimo.content_tokens > nano.content_tokens  # the tokenizer gap
    assert got.reference.components["message"] == math.ceil(len(FA) / 4)
    assert nano.content_fidelity == "exact_local"
    assert got.per_model["grok-4-1-fast"].content_fidelity == "approximation"
    assert got.chars["message"] == len(FA) and "history" in got.chars


def test_strata_and_absent_components():
    got = inputs_for([case(2, FA, depth=3)])[0]
    assert got.strata["language"] == "fa"
    assert got.strata["turn_depth"] == "later"
    assert got.strata["instructions"] == "no" and got.strata["retrieved"] == "no"
    assert tuple(got.per_model["gpt-5-nano"].components) == ("message",)
    assert inputs_for([case(3, EN)])[0].strata["language"] == "en"


def test_the_instruction_fingerprint_is_keyed_and_never_the_text():
    a, b = inputs_for([case(4, FA, instructions=LONG_INSTRUCTIONS)] * 1 + [case(5, EN)])
    assert a.instructions_group == FP.fingerprint("instructions", LONG_INSTRUCTIONS)
    assert LONG_INSTRUCTIONS not in repr(a) and b.instructions_group is None


# --- slices, costs, rankings ------------------------------------------------


def make_cases(n_fa=6, n_en=2):
    cases = [
        case(
            i,
            FA,
            instructions=LONG_INSTRUCTIONS if i % 2 else M + "other prompt " * 10,
            session=f"s{i // 2}",
        )
        for i in range(n_fa)
    ]
    cases += [case(100 + i, EN, instructions=LONG_INSTRUCTIONS) for i in range(n_en)]
    return inputs_for(cases)


def test_costs_are_input_only_lower_bounds_from_the_price_table():
    cases = make_cases()
    rep = slice_report("all", "all", cases, models=MODELS, prices=PRICES, min_n=None)
    nano = rep.models["gpt-5-nano"]
    tokens = sum(c.per_model["gpt-5-nano"].total_tokens for c in cases)
    assert nano.input_cost_usd_total == Decimal(tokens) * Decimal("0.055") / 1_000_000
    assert nano.cost_label == "lower_bound_input_only_uncached"
    assert (nano.provenance, nano.n) == ("estimated", len(cases))
    assert nano.cases_in_long_tier is None  # untiered model
    chars = sum(sum(c.chars.values()) for c in cases)
    assert nano.tokens_per_char == pytest.approx(tokens / chars)
    assert 0 < nano.instruction_share_of_input_mean < 1


def test_quantiles_are_withheld_below_their_arithmetic_floor():
    small = slice_report(
        "all", "all", make_cases(6, 2), models=MODELS, prices=PRICES, min_n=None
    )
    assert small.models["gpt-5-nano"].tokens_p90 is None  # 8 cases < 10
    larger = slice_report(
        "all", "all", make_cases(12, 2), models=MODELS, prices=PRICES, min_n=None
    )
    assert larger.models["gpt-5-nano"].tokens_p90 is not None
    assert larger.models["gpt-5-nano"].tokens_p95 is None  # 14 cases < 20


def test_the_tokenizer_gap_flips_a_ranking_that_chars_div_4_gets_wrong():
    rep = slice_report(
        "all", "all", make_cases(), models=MODELS, prices=PRICES, min_n=None
    )
    # exact: price per token x tokens per character; chars/4 gives every model
    # the same tokens, so only the price per token orders them
    assert rep.exact_ranking == ("gpt-5-nano", "deepseek-v4-flash", "mimo-v2.5")
    assert rep.reference_ranking == ("gpt-5-nano", "mimo-v2.5", "deepseek-v4-flash")
    assert rep.flipped_pairs == (("deepseek-v4-flash", "mimo-v2.5"),)
    # approximation-only models are never ranked
    assert rep.excluded_from_ranking == ("grok-4-1-fast",)
    assert "grok-4-1-fast" in rep.models  # still described


@pytest.mark.parametrize(
    "min_n, label, reason",
    [
        (None, "descriptive", "min_n_unset"),
        (100, "descriptive", "n_below_minimum"),
        (5, "rankable", None),
    ],
)
def test_a_slice_is_rankable_only_if_its_minimum_is_met(min_n, label, reason):
    rep = slice_report(
        "all", "all", make_cases(), models=MODELS, prices=PRICES, min_n=min_n
    )
    assert (rep.label, rep.label_reason) == (label, reason)
    assert rep.flipped_pairs  # computed from this sample either way, labelled


def test_instruction_reuse_is_a_descriptive_count_not_a_hit_rate():
    a, b = M + "prompt A " * 5, M + "prompt B " * 5
    cases = inputs_for(
        [
            case(1, FA, instructions=a),
            case(2, FA, instructions=a),
            case(3, FA, instructions=b),
            case(4, FA),
        ]
    )
    rep = slice_report(
        "all", "all", cases, models=MODELS[:1], prices=PRICES, min_n=None
    )
    reuse = rep.instruction_reuse
    assert (reuse.cases_with_instructions, reuse.distinct_instruction_texts) == (3, 2)
    assert reuse.cases_sharing_instructions == 2
    assert reuse.share_sharing == pytest.approx(2 / 3)


def test_the_long_price_tier_is_counted_and_priced_for_the_whole_input():
    premium = [CATALOGUE["gpt-5.5"]]
    big = case(1, FA, instructions="x" * (3 * 270_000))  # 270,000 tokens + message
    small = case(2, FA)
    cases = [
        case_inputs(
            c,
            measurement=SERVICE,
            entries=premium,
            fingerprinter=FP,
            language=LanguageConfig(),
            length_bounds=(20, 60),
        )
        for c in (big, small)
    ]
    rep = slice_report("all", "all", cases, models=premium, prices=PRICES, min_n=None)
    stats = rep.models["gpt-5.5"]
    big_tokens = cases[0].per_model["gpt-5.5"].total_tokens
    small_tokens = cases[1].per_model["gpt-5.5"].total_tokens
    assert big_tokens > 270_000 and stats.cases_in_long_tier == 1
    assert (
        stats.input_cost_usd_total
        == (
            Decimal(big_tokens) * Decimal("11.0")
            + Decimal(small_tokens) * Decimal("5.5")
        )
        / 1_000_000
    )


# --- the whole report -------------------------------------------------------


def report_for(cases):
    return build_report(
        cases,
        models=MODELS,
        prices=PRICES,
        min_n=None,
        as_of=AS_OF,
        max_age_days=None,
        char_bounds=(20, 60),
    )


def test_the_report_is_persian_first_with_overall_labelled_and_nothing_cached():
    report = report_for(make_cases())
    languages = [s.value for s in report.slices if s.dimension == "language"]
    assert languages == ["fa", "en"]
    assert report.slices[0].note == "primary slice"
    assert report.slices[1].note == "separate slice, never pooled into Persian"
    assert (report.slices[-1].dimension, report.slices[-1].note) == (
        "all",
        "dominated_by_persian",
    )
    assert list(report.length_buckets) == ["fa", "en"]
    assert report.length_buckets["fa"].n == 6
    assert report.length_buckets["fa"].provenance == "estimated"
    # no cache or output scenario is set: stated, per model, not computed
    assert report.scenario_status == {
        "no_output_scenarios_configured": len(MODELS),
        "no_cache_scenarios_configured": len(MODELS),
    }
    age = report.price_age
    assert (age.state, age.reason, age.age_days) == (
        "not_evaluated",
        "max_age_unset",
        12,
    )
    assert any("no real recorded usage" in a for a in report.assumptions)


def test_the_report_holds_no_text_and_no_fingerprints():
    text = repr(report_for(make_cases()))
    assert "fp1:" not in text
    assert "[SYNTHETIC]" not in text and "careful assistant" not in text


# --- compression versus prefix caching --------------------------------------

P_IN, P_CACHED = Decimal("5.5") / 1_000_000, Decimal("0.55") / 1_000_000
BEFORE = {"instructions": 1000, "history": 200, "retrieved": 300, "message": 50}


def break_even(after, changed, cached=("instructions",)):
    return compression_break_even(
        BEFORE,
        after,
        changed=changed,
        cached_components=cached,
        price_input=P_IN,
        price_cached=P_CACHED,
    )


def test_compressing_after_the_cached_prefix_never_loses_the_discount():
    est = break_even({**BEFORE, "retrieved": 100}, ["retrieved"])
    assert est.value == float("inf")
    assert est.extra["reading"] == "never_loses_discount"


def test_compressing_the_cached_prefix_has_a_break_even_fraction_by_hand():
    est = break_even({**BEFORE, "instructions": 600}, ["instructions"])
    # saved 400 tokens at 5.5; exposed 1,000 cached-eligible tokens lose 4.95 each
    assert est.value == pytest.approx(400 * 5.5 / (1000 * 4.95))
    assert est.extra["reading"] == "net_negative_above_this_fraction"
    assert (est.provenance, est.method) == ("estimated", "break_even_cached_fraction")


def test_a_large_saving_pays_even_if_the_whole_prefix_were_cached():
    est = break_even({**BEFORE, "instructions": 1}, ["instructions"])
    assert est.value == pytest.approx(999 * 5.5 / (1000 * 4.95)) and est.value > 1
    assert est.extra["reading"] == "pays_even_if_fully_cached"


def test_a_history_change_exposes_only_the_cached_components_after_it():
    est = break_even(
        {**BEFORE, "history": 100}, ["history"], cached=("instructions", "history")
    )
    assert est.extra["cached_tokens_exposed"] == 200  # history only


@pytest.mark.parametrize(
    "after, changed, reason",
    [
        (BEFORE, ["retrieved"], "no_tokens_saved"),
        ({**BEFORE, "retrieved": 100}, [], "nothing_changed"),
    ],
)
def test_break_even_says_when_it_is_undefined(after, changed, reason):
    est = break_even(after, changed)
    assert (est.state, est.reason) == ("undefined", reason)


def test_break_even_needs_a_cached_discount_and_known_components():
    no_discount = compression_break_even(
        BEFORE,
        {**BEFORE, "retrieved": 1},
        changed=["retrieved"],
        cached_components=["instructions"],
        price_input=P_IN,
        price_cached=P_IN,
    )
    assert no_discount.reason == "no_cached_discount"
    with pytest.raises(ValueError):
        break_even({**BEFORE, "retrieved": 1}, ["rag"])


def test_input_prices_follow_the_tier_of_the_input_size():
    m = 1_000_000
    entry = CATALOGUE["gpt-5.5"]
    assert input_prices(entry, PRICES, 100_000) == (
        Decimal("5.5") / m,
        Decimal("0.55") / m,
    )
    assert input_prices(entry, PRICES, 300_000) == (
        Decimal("11.0") / m,
        Decimal("1.1") / m,
    )
    assert input_prices(entry, PRICES, 0) == "no_input_tokens"


def test_opaque_category_ids_are_reported_as_numbered_strata():
    secret = "fp1:" + "ab" * 32
    cases = []
    for i, category in enumerate([secret, secret, "fp1:" + "cd" * 32]):
        c = case(i, FA)
        cases.append(c.model_copy(update={"stratum": category}))
    report = report_for(inputs_for(cases))
    values = [s.value for s in report.slices if s.dimension == "category"]
    assert values == ["category_1", "category_2"]  # the larger stratum is first
    assert "fp1:" not in repr(report)
