"""Bucket-versus-token report (spec §0.5). SYNTHETIC numbers."""

import pytest

from metis_auto.evaluation.lengths import LengthSample, bucket_token_report

BOUNDS = (10, 20)  # buckets: <10, <20, >=20


def sample(chars, **tokens):
    return LengthSample(chars, tokens)


def test_per_bucket_statistics_by_hand():
    samples = [
        sample(4, a=2),
        sample(8, a=4),
        sample(12, a=6),
        sample(20, a=10),
        sample(40, a=20),
    ]
    report = bucket_token_report(samples, BOUNDS, ["a"])
    assert report.provenance == "estimated"
    assert report.n == 5
    (a,) = report.per_tokenizer
    b0, b1, b2 = a.buckets
    assert (b0.n, b0.tokens_median, b0.tokens_p95) == (2, 3.0, 4)
    assert b0.tokens_per_char == pytest.approx(6 / 12)
    assert (b1.n, b1.tokens_median) == (1, 6.0)
    assert (b2.n, b2.tokens_per_char) == (2, pytest.approx(30 / 60))


def test_a_monotone_tokenizer_changes_no_bucket_under_rank_matching():
    samples = [sample(c, a=c * 2, b=c * 3) for c in (1, 5, 9, 11, 15, 25, 30, 99)]
    report = bucket_token_report(samples, BOUNDS, ["a", "b"])
    assert [r.bucket_change_share for r in report.per_tokenizer] == [0.0, 0.0]


def test_a_tokenizer_that_reorders_lengths_changes_buckets():
    chars = (1, 5, 9, 11, 15, 25, 30, 99)
    samples = [sample(c, a=c, rev=1000 - c) for c in chars]
    report = bucket_token_report(samples, BOUNDS, ["a", "rev"])
    a, rev = report.per_tokenizer
    assert a.bucket_change_share == 0.0
    assert rev.bucket_change_share > 0.5


def test_explicit_token_bounds_are_used_and_labelled():
    samples = [sample(5, a=5), sample(15, a=15), sample(30, a=30)]
    report = bucket_token_report(samples, BOUNDS, ["a"], {"a": (50, 60)})
    (a,) = report.per_tokenizer
    assert a.bounds_source == "explicit" and a.token_bounds == (50, 60)
    assert a.bucket_change_share == pytest.approx(2 / 3)  # all in token bucket 0


def test_empty_buckets_and_empty_input_say_so():
    report = bucket_token_report([sample(1, a=1), sample(2, a=1)], BOUNDS, ["a"])
    assert report.per_tokenizer[0].buckets[2].n == 0
    assert report.per_tokenizer[0].buckets[2].tokens_median is None
    empty = bucket_token_report([], BOUNDS, ["a"])
    assert empty.n == 0 and empty.per_tokenizer[0].bucket_change_share is None


def test_a_missing_token_count_is_refused():
    with pytest.raises(ValueError, match="b"):
        bucket_token_report([sample(1, a=1)], BOUNDS, ["a", "b"])
