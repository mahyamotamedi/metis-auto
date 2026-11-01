"""Descriptive statistics, session-clustered bootstrap, and the claims ledger."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

QUANTILES = (0.5, 0.9, 0.95, 0.99)


def describe(x: pd.Series) -> dict[str, float]:
    """count, total, mean, median, p90, p95, p99, max over non-null values."""
    x = x.dropna()
    if x.empty:
        return {"count": 0}
    q = x.quantile(list(QUANTILES))
    return {
        "count": float(len(x)),
        "total": float(x.sum()),
        "mean": float(x.mean()),
        "median": float(q[0.5]),
        "p90": float(q[0.9]),
        "p95": float(q[0.95]),
        "p99": float(q[0.99]),
        "max": float(x.max()),
    }


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman correlation as Pearson on average ranks (no SciPy needed)."""
    ok = a.notna() & b.notna()
    return float(a[ok].rank().corr(b[ok].rank()))


def cluster_bootstrap_ratio(
    num: np.ndarray,
    den: np.ndarray,
    clusters: np.ndarray,
    n_boot: int = 500,
    seed: int = 20261030,
) -> tuple[float, float, float]:
    """Ratio sum(num)/sum(den) with a session-clustered bootstrap 95% interval.

    Resamples whole clusters (sessions) with replacement, since requests within a
    session are correlated. Returns (estimate, lo, hi); (nan, nan, nan) if the
    denominator is zero.
    """
    num, den = np.asarray(num, float), np.asarray(den, float)
    codes, uniq = pd.factorize(clusters)
    k = len(uniq)
    sn = np.bincount(codes, weights=num, minlength=k)
    sd = np.bincount(codes, weights=den, minlength=k)
    if sd.sum() == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_boot, k))
    rat = sn[idx].sum(1) / np.where(sd[idx].sum(1) == 0, np.nan, sd[idx].sum(1))
    return (
        float(sn.sum() / sd.sum()),
        float(np.nanpercentile(rat, 2.5)),
        float(np.nanpercentile(rat, 97.5)),
    )


@dataclass
class Claim:
    """One reported number, with its provenance (section 4, claims ledger)."""

    claim_id: str
    metric: str
    value: float
    numerator: float | None
    denominator: float | None
    unit: str
    coverage: str
    evidence_class: str
    ci_low: float | None = None
    ci_high: float | None = None
    source_table: str = ""
    note: str = ""


@dataclass
class Ledger:
    claims: list[Claim] = field(default_factory=list)

    def add(
        self,
        claim_id: str,
        metric: str,
        value: float,
        unit: str,
        coverage: str,
        evidence_class: str,
        numerator: float | None = None,
        denominator: float | None = None,
        ci: tuple[float, float] | None = None,
        source_table: str = "",
        note: str = "",
    ) -> float:
        if any(c.claim_id == claim_id for c in self.claims):
            raise ValueError(f"duplicate claim id {claim_id}")
        self.claims.append(
            Claim(
                claim_id,
                metric,
                float(value),
                numerator,
                denominator,
                unit,
                coverage,
                evidence_class,
                ci[0] if ci else None,
                ci[1] if ci else None,
                source_table,
                note,
            )
        )
        return float(value)

    def ratio(
        self,
        claim_id: str,
        metric: str,
        num: float,
        den: float,
        unit: str,
        coverage: str,
        evidence_class: str,
        **kw: object,
    ) -> float:
        v = num / den if den else float("nan")
        return self.add(
            claim_id, metric, v, unit, coverage, evidence_class, num, den, **kw
        )  # type: ignore[arg-type]

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(asdict(self.claims[0]).keys()))
            w.writeheader()
            for c in self.claims:
                w.writerow(asdict(c))
