"""The Persian folding treatments are opt-in in the cache-candidate harness
(Stage E0); the default variant set is unchanged. SYNTHETIC."""

import pytest

from metis_auto.evaluation.cache_candidates.harness import variants


def test_default_variants_use_only_the_three_existing_treatments():
    used = {v.message_treatment for v in variants({})}
    assert used == {"literal", "whitespace", "nfkc_casefold_ws"}


def test_persian_treatments_are_accepted_by_name_with_distinct_ids():
    chosen = variants(
        {
            "bases": ["msg_only"],
            "message_treatments": [
                "persian_fold_v1",
                "persian_fold_zwnj_space_v1",
                "persian_fold_marks_v1",
            ],
            "unknown_modes": ["strict"],
        }
    )
    ids = [v.name for v in chosen]
    assert len(ids) == len(set(ids)) == 3


def test_an_unknown_treatment_is_still_refused():
    with pytest.raises(ValueError, match="persian_fold_v1"):
        variants({"message_treatments": ["persian_fold"]})
