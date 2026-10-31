"""Seeded cluster bootstrap and Holm correction (Stage E1; framework §6).

``cluster_bootstrap`` resamples whole clusters (sessions, not messages, because
turns in a session are correlated) with replacement and recomputes a
statistic; the interval is the percentile interval of the replicates. The
number of replicates, the level and the seed are arguments (config): there are
no defaults. A bootstrap p-value has resolution 1/n_boot. Pure.
Status: provisional (Stage E1).
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapResult:
    point: float | None
    low: float | None
    high: float | None
    replicates: tuple[float, ...]
    n_items: int
    n_clusters: int
    n_valid: int
    level: float


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def cluster_bootstrap[T](
    items: Sequence[T],
    cluster_of: Callable[[T], Hashable],
    statistic: Callable[[Sequence[T]], float | None],
    *,
    n_boot: int,
    seed: int | str,
    level: float,
) -> BootstrapResult:
    if n_boot < 1:
        raise ValueError("n_boot must be at least 1")
    if not 0 < level < 1:
        raise ValueError("level must be between 0 and 1")
    clusters: dict[Hashable, list[T]] = defaultdict(list)
    for item in items:
        clusters[cluster_of(item)].append(item)
    groups = list(clusters.values())
    point = statistic(items) if items else None
    if not groups:
        return BootstrapResult(point, None, None, (), 0, 0, 0, level)
    rng = random.Random(seed)
    replicates: list[float] = []
    for _ in range(n_boot):
        sample: list[T] = []
        for _ in groups:
            sample.extend(groups[rng.randrange(len(groups))])
        value = statistic(sample)
        if value is not None:
            replicates.append(value)
    if not replicates:
        return BootstrapResult(point, None, None, (), len(items), len(groups), 0, level)
    ordered = sorted(replicates)
    alpha = 1 - level
    return BootstrapResult(
        point=point,
        low=_quantile(ordered, alpha / 2),
        high=_quantile(ordered, 1 - alpha / 2),
        replicates=tuple(replicates),
        n_items=len(items),
        n_clusters=len(groups),
        n_valid=len(replicates),
        level=level,
    )


def holm(p_values: Mapping[str, float], alpha: float) -> dict[str, bool]:
    """Holm-Bonferroni step-down: label → rejected (claim allowed)."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    ordered = sorted(p_values.items(), key=lambda kv: (kv[1], kv[0]))
    m = len(ordered)
    rejected: dict[str, bool] = {label: False for label in p_values}
    for rank, (label, p) in enumerate(ordered):
        if p <= alpha / (m - rank):
            rejected[label] = True
        else:
            break
    return rejected
