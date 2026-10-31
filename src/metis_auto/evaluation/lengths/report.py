"""Bucket-versus-token comparison (CMP-23; evaluation framework §0.5).

Responsibility: for items with a character length and a token count per
tokenizer, report per character bucket (``domain.features.length_bucket``,
bounds from config) and per tokenizer: n, median and p95 tokens, tokens per
character, and the share of items that would change bucket if buckets were
defined on tokens. Token buckets are matched by rank to the character buckets
(each token bucket holds as many items as the character bucket, so the share
measures disagreement of ordering, not of bucket sizes) unless explicit token
bounds are given. Ties at a bound go to the higher bucket, so realised token
bucket sizes can differ slightly.

Token counts are **estimates** (local tokenizers, fidelity given by the
caller); the report is labelled ``estimated``. Pure. Takes counts as data, so
it needs no tokenizer. Called by: evaluation code and scripts.
Status: provisional (Stage E0).
"""

from __future__ import annotations

import statistics
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from metis_auto.domain.features import length_bucket


@dataclass(frozen=True)
class LengthSample:
    """One item: its length in characters and its token count per tokenizer."""

    chars: int
    tokens: Mapping[str, int]


@dataclass(frozen=True)
class BucketStats:
    bucket: int
    n: int
    tokens_median: float | None
    tokens_p95: int | None
    tokens_per_char: float | None


@dataclass(frozen=True)
class TokenizerBucketReport:
    ref: str
    buckets: tuple[BucketStats, ...]
    token_bounds: tuple[int, ...]
    bounds_source: str
    """``rank_matched`` or ``explicit``."""
    bucket_change_share: float | None


@dataclass(frozen=True)
class BucketTokenReport:
    n: int
    char_bounds: tuple[int, ...]
    per_tokenizer: tuple[TokenizerBucketReport, ...]
    provenance: str = field(default="estimated")


def _p95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def _rank_matched_bounds(
    token_counts: list[int], char_buckets: list[int], n_buckets: int
) -> tuple[int, ...]:
    ordered = sorted(token_counts)
    n = len(ordered)
    sizes = [char_buckets.count(k) for k in range(n_buckets)]
    bounds: list[int] = []
    cumulative = 0
    for k in range(n_buckets - 1):
        cumulative += sizes[k]
        bounds.append(ordered[cumulative] if cumulative < n else ordered[-1] + 1)
    return tuple(bounds)


def bucket_token_report(
    samples: Sequence[LengthSample],
    char_bounds: Sequence[int],
    refs: Sequence[str],
    token_bounds: Mapping[str, Sequence[int]] | None = None,
) -> BucketTokenReport:
    bounds = tuple(char_bounds)
    n_buckets = len(bounds) + 1
    for sample in samples:
        missing = [r for r in refs if r not in sample.tokens]
        if missing:
            raise ValueError(f"a sample has no token count for {missing}")
    char_buckets = [length_bucket(s.chars, bounds) for s in samples]
    reports = []
    for ref in refs:
        tokens = [s.tokens[ref] for s in samples]
        stats = []
        for k in range(n_buckets):
            idx = [i for i, b in enumerate(char_buckets) if b == k]
            if not idx:
                stats.append(BucketStats(k, 0, None, None, None))
                continue
            t = [tokens[i] for i in idx]
            chars = sum(samples[i].chars for i in idx)
            stats.append(
                BucketStats(
                    bucket=k,
                    n=len(idx),
                    tokens_median=statistics.median(t),
                    tokens_p95=_p95(t),
                    tokens_per_char=(sum(t) / chars) if chars else None,
                )
            )
        if token_bounds is not None and ref in token_bounds:
            tb = tuple(token_bounds[ref])
            source = "explicit"
        elif samples:
            tb = _rank_matched_bounds(tokens, char_buckets, n_buckets)
            source = "rank_matched"
        else:
            tb, source = (), "rank_matched"
        changed = (
            sum(
                1
                for t, b in zip(tokens, char_buckets, strict=True)
                if bisect_right(tb, t) != b
            )
            / len(samples)
            if samples
            else None
        )
        reports.append(TokenizerBucketReport(ref, tuple(stats), tb, source, changed))
    return BucketTokenReport(len(samples), bounds, tuple(reports))
