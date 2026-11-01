"""Exact-total quotas for the golden set: one margin, then a joint table (pure).

Margins come from a transparent policy: a floor per key, then a largest-remainder
split of the rest by the square root of population (rare cases gain coverage, large
ones still get more). The joint table has both margins exact, respects population
caps, and never places a sample in an empty cell.

Status: provisional. Selecting candidates does not approve a golden set.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from metis_auto.evaluation.sampling.allocation import _apportion

_SCALE = 1_000_000


def margin_quotas(
    population: Mapping[str, int], total: int, floor: int, sqrt_weight: bool = True
) -> dict[str, int]:
    """Integer quotas summing to exactly ``total``; each is capped by population."""
    live = {k: n for k, n in population.items() if n > 0}
    base = {k: min(floor, n) for k, n in live.items()}
    rest = total - sum(base.values())
    if rest < 0:
        raise ValueError("floors exceed the total")
    weights = {
        k: max(1, round((math.sqrt(n) if sqrt_weight else n) * _SCALE))
        for k, n in live.items()
    }
    caps = {k: live[k] - base[k] for k in live}
    extra = _apportion(rest, weights, caps)
    out = {k: base[k] + extra[k] for k in live}
    if sum(out.values()) != total:
        raise ValueError("population too small for the total")
    return out


def joint_quotas(
    population: Mapping[tuple[str, str], int],
    row_margin: Mapping[str, int],
    col_margin: Mapping[str, int],
    iterations: int = 200,
) -> dict[tuple[str, str], int]:
    """Integer table matching both margins exactly (raking, then repair).

    Start from the population, rake to the margins, floor, then add units one at a
    time to the open cell with the largest remainder. If greedy placement gets
    stuck, a swap along an alternating path restores feasibility.
    """
    if sum(row_margin.values()) != sum(col_margin.values()):
        raise ValueError("margins disagree")
    cells = {c: n for c, n in population.items() if n > 0}
    x = {c: float(n) for c, n in cells.items()}
    for _ in range(iterations):
        for margin, axis in ((row_margin, 0), (col_margin, 1)):
            totals: dict[str, float] = {}
            for c, v in x.items():
                totals[c[axis]] = totals.get(c[axis], 0.0) + v
            for c in x:
                if totals[c[axis]] > 0:
                    x[c] *= margin.get(c[axis], 0) / totals[c[axis]]
    out = {c: min(int(v), cells[c]) for c, v in x.items()}
    need_r = {
        r: m - sum(v for c, v in out.items() if c[0] == r)
        for r, m in row_margin.items()
    }
    need_c = {
        k: m - sum(v for c, v in out.items() if c[1] == k)
        for k, m in col_margin.items()
    }
    for c in sorted(x, key=lambda c: (-(x[c] - int(x[c])), c)):
        if need_r.get(c[0], 0) > 0 and need_c.get(c[1], 0) > 0 and out[c] < cells[c]:
            out[c] += 1
            need_r[c[0]] -= 1
            need_c[c[1]] -= 1
    for c in sorted(cells, key=lambda c: (-cells[c], c)):
        while need_r.get(c[0], 0) > 0 and need_c.get(c[1], 0) > 0 and out[c] < cells[c]:
            out[c] += 1
            need_r[c[0]] -= 1
            need_c[c[1]] -= 1
    for r, short in list(need_r.items()):
        while short > 0:
            col = next(k for k, v in need_c.items() if v > 0)
            moved = False
            for c1 in sorted(cells, key=lambda c: (-cells[c], c)):
                if c1[0] != r or out[c1] >= cells[c1]:
                    continue
                for c2 in sorted(cells, key=lambda c: (-cells[c], c)):
                    swap = (c2[0], col)
                    if (
                        c2[1] == c1[1]
                        and c2[0] != r
                        and out[c2] > 0
                        and swap in cells
                        and out[swap] < cells[swap]
                    ):
                        out[c1] += 1
                        out[c2] -= 1
                        out[swap] += 1
                        short -= 1
                        need_c[col] -= 1
                        moved = True
                        break
                if moved:
                    break
            if not moved:
                raise ValueError(f"no feasible table for row {r}")
        need_r[r] = 0
    return {c: v for c, v in out.items() if v > 0}
