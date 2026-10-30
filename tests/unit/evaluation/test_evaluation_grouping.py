"""Duplicate groups and leakage-safe splits (spec §0.3). SYNTHETIC strings and
the synthetic test key (ADR-0015)."""

import pytest
from fixtures.synthetic import contract_examples as ex

from metis_auto.application.measurement import Fingerprinter
from metis_auto.evaluation.grouping import (
    TextItem,
    duplicate_groups,
    duplicate_summary,
    leakage_safe_split,
)

FP = Fingerprinter(ex.SYNTHETIC_TEST_KEY)
ARABIC = "كتاب يك ١٢"
PERSIAN = "کتاب یک ۱۲"


def item(i, session, text):
    return TextItem(f"i{i}", f"s{session}", text)


def test_spelling_variants_group_only_under_a_folding_treatment():
    items = [item(1, 1, ARABIC), item(2, 2, PERSIAN)]
    lit = duplicate_groups(items, "literal", FP)
    fold = duplicate_groups(items, "persian_fold_v1", FP)
    assert lit["i1"] != lit["i2"]
    assert fold["i1"] == fold["i2"]


def test_group_ids_are_keyed_fingerprints():
    (group,) = set(duplicate_groups([item(1, 1, PERSIAN)], "literal", FP).values())
    assert group == FP.fingerprint("dup_group", PERSIAN)
    other = Fingerprinter(b"another-synthetic-key--not-a-secret--0000")
    assert other.fingerprint("dup_group", PERSIAN) != group
    assert PERSIAN not in group


def test_empty_text_never_groups():
    items = [item(1, 1, "  "), item(2, 2, "‎"), item(3, 3, "")]
    groups = duplicate_groups(items, "persian_fold_v1", FP)
    assert len(set(groups.values())) == 3


def test_duplicate_item_ids_are_refused():
    with pytest.raises(ValueError):
        duplicate_groups([item(1, 1, "a"), item(1, 2, "b")], "literal", FP)


def test_summary_is_content_free_counts():
    items = [
        item(1, 1, "alpha"),
        item(2, 2, "alpha"),
        item(3, 2, "alpha"),
        item(4, 3, "beta"),
        item(5, 3, "gamma"),
        item(6, 4, "gamma"),
    ]
    s = duplicate_summary(items, duplicate_groups(items, "literal", FP))
    assert (s.items, s.groups, s.repeated_groups) == (6, 3, 2)
    assert (s.items_in_repeated_groups, s.largest_group) == (5, 3)
    assert s.groups_crossing_sessions == 2


def _many(n=300):
    items = []
    for i in range(n):
        # every 5th item repeats an earlier prompt; pairs of items share a session
        text = f"prompt {i if i % 5 else i - 1}"
        items.append(item(i, i // 2, text))
    return items


FRACTIONS = {"fit": 0.7, "test": 0.3}


def test_no_group_and_no_session_spans_two_parts():
    items = _many()
    result = leakage_safe_split(items, "literal", FP, FRACTIONS, "seed-a")
    groups = duplicate_groups(items, "literal", FP)
    by_group, by_session = {}, {}
    for it in items:
        part = result.assignment[it.item_id]
        assert by_group.setdefault(groups[it.item_id], part) == part
        assert by_session.setdefault(it.session_ref, part) == part
    assert sum(result.items_per_part.values()) == len(items)
    assert sum(result.components_per_part.values()) == result.components
    assert all(n > 0 for n in result.items_per_part.values())


def test_folded_duplicates_stay_together_under_the_folding_treatment():
    items = [item(i, i, ARABIC if i % 2 else PERSIAN) for i in range(40)]
    result = leakage_safe_split(items, "persian_fold_v1", FP, FRACTIONS, "seed-a")
    assert len(set(result.assignment.values())) == 1  # one component, one part
    assert result.components == 1


def test_split_is_deterministic_and_seed_dependent():
    items = _many()
    a = leakage_safe_split(items, "literal", FP, FRACTIONS, "seed-a")
    again = leakage_safe_split(
        list(reversed(items)), "literal", FP, FRACTIONS, "seed-a"
    )
    b = leakage_safe_split(items, "literal", FP, FRACTIONS, "seed-b")
    assert a.assignment == again.assignment
    assert a.assignment != b.assignment


@pytest.mark.parametrize(
    "fractions, seed",
    [
        ({}, "s"),
        ({"a": 0.5, "b": 0.4}, "s"),
        ({"a": 1.2, "b": -0.2}, "s"),
        ({"a": 1.0}, ""),
    ],
)
def test_fractions_and_seed_are_required_and_valid(fractions, seed):
    with pytest.raises(ValueError):
        leakage_safe_split([item(1, 1, "x")], "literal", FP, fractions, seed)


def test_result_records_what_was_requested_not_a_promise():
    result = leakage_safe_split(_many(), "literal", FP, FRACTIONS, "seed-a")
    assert result.requested_fractions == FRACTIONS
    assert (result.treatment, result.seed) == ("literal", "seed-a")
