"""Output-token estimators behind one port (Stage E2; framework §2.2).

(A) ``ObservedUsage``: the empirical q-quantile of recorded output tokens for a
(model, effort), ignoring request features. (B) ``StratifiedQuantile``: the
same within the request's stratum, falling back to (A) when the stratum is
below a **configured** minimum (unset → always the pooled value, with the
reason). (C) ``VerbosityRatio``: visible tokens only, from the ratio of the
model's visible answer length to the logged answer's length in characters,
converted to tokens with the model's own tokens per character (framework
§0.5); it is a mean, not a quantile, and never predicts reasoning tokens.

All three are fitted on recorded, provider-reported usage and say so in
``method``; their predictions are ``estimated``. A quantile is refused below
the arithmetic floor (``min_n_for_quantile``). ``compare_estimators`` scores
estimators on held-out records with a paired session-cluster bootstrap, so
"B beats C" is a statement with an interval, not an impression. Pure.
Status: provisional (Stage E2). Not fitted on any data yet.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from metis_auto.evaluation.comparison.stats import cluster_bootstrap
from metis_auto.evaluation.comparison.types import Estimate, not_measured, sufficient

from .usage import UsageRecord, empirical_quantile, min_n_for_quantile

PROVENANCE = "estimated"
TARGETS = ("output", "visible")
"""``output``: billed output including reasoning; ``visible``: output minus
reported reasoning (records without a reasoning count are left out)."""


@dataclass(frozen=True)
class RequestFeatures:
    strata: Mapping[str, str] = field(default_factory=dict)
    numeric: Mapping[str, float] = field(default_factory=dict)


class OutputTokenEstimator(Protocol):
    name: str

    def estimate(
        self,
        model_id: str,
        effort: str | None,
        request: RequestFeatures,
        q: float,
    ) -> Estimate: ...


def _target_values(records: Sequence[UsageRecord], target: str) -> list[float]:
    if target not in TARGETS:
        raise ValueError(f"target must be one of {TARGETS}")
    if target == "output":
        return [float(r.output_tokens) for r in records]
    return [float(v) for r in records if (v := r.visible_output_tokens) is not None]


def _quantile_estimate(
    values: list[float], q: float, method: str, extra: Mapping[str, str | float | None]
) -> Estimate:
    floor = min_n_for_quantile(q)
    if len(values) < floor:
        return Estimate(
            "insufficient",
            len(values),
            PROVENANCE,
            reason="quantile_not_identifiable",
            method=method,
            extra={**extra, "min_n_for_quantile": float(floor)},
        )
    value = empirical_quantile(values, q)
    assert value is not None
    return Estimate(
        "measured", len(values), PROVENANCE, value=value, method=method, extra=extra
    )


class ObservedUsage:
    """(A) Pooled empirical quantile per (model, effort)."""

    name = "observed_usage"

    def __init__(self, records: Sequence[UsageRecord], *, target: str = "output"):
        self._target = target
        grouped: dict[tuple[str, str | None], list[UsageRecord]] = defaultdict(list)
        for record in records:
            grouped[(record.model_id, record.effort)].append(record)
        self._values = {k: _target_values(v, target) for k, v in grouped.items()}

    def estimate(
        self, model_id: str, effort: str | None, request: RequestFeatures, q: float
    ) -> Estimate:
        values = self._values.get((model_id, effort))
        if not values:
            return not_measured("not_evaluated", "no_recorded_usage", 0, PROVENANCE)
        return _quantile_estimate(
            values, q, f"observed_usage/{self._target}", {"level": "pooled"}
        )


class StratifiedQuantile:
    """(B) Quantile within the request's stratum; pooled fallback."""

    name = "stratified_quantile"

    def __init__(
        self,
        records: Sequence[UsageRecord],
        *,
        strata_keys: Sequence[str],
        min_stratum_n: int | None,
        target: str = "output",
    ):
        self._keys = tuple(strata_keys)
        self._min = min_stratum_n
        self._target = target
        self._pooled = ObservedUsage(records, target=target)
        grouped: dict[tuple, list[UsageRecord]] = defaultdict(list)
        for record in records:
            if all(k in record.strata for k in self._keys):
                key = (
                    record.model_id,
                    record.effort,
                    tuple(record.strata[k] for k in self._keys),
                )
                grouped[key].append(record)
        self._values = {k: _target_values(v, target) for k, v in grouped.items()}

    def estimate(
        self, model_id: str, effort: str | None, request: RequestFeatures, q: float
    ) -> Estimate:
        pooled = self._pooled.estimate(model_id, effort, request, q)
        if self._min is None:
            return _with_extra(pooled, {"fallback": "min_stratum_n_unset"})
        if not all(k in request.strata for k in self._keys):
            return _with_extra(pooled, {"fallback": "request_strata_missing"})
        key = (model_id, effort, tuple(request.strata[k] for k in self._keys))
        values = self._values.get(key, [])
        ok, _ = sufficient(len(values), self._min)
        if not ok:
            return _with_extra(pooled, {"fallback": "stratum_below_min_n"})
        return _quantile_estimate(
            values,
            q,
            f"stratified_quantile/{self._target}",
            {"level": "stratum", "stratum_n": float(len(values))},
        )


def _with_extra(estimate: Estimate, extra: Mapping[str, str]) -> Estimate:
    return Estimate(
        estimate.state,
        estimate.n,
        estimate.provenance,
        value=estimate.value,
        interval=estimate.interval,
        level=estimate.level,
        method=estimate.method,
        reason=estimate.reason,
        extra={**estimate.extra, **extra},
    )


class VerbosityRatio:
    """(C) Visible tokens = ratio × logged answer chars × tokens per char."""

    name = "verbosity_ratio"

    def __init__(self, records: Sequence[UsageRecord]):
        sums: dict[tuple[str, str | None], list[float]] = defaultdict(
            lambda: [0.0, 0.0, 0.0, 0.0, 0.0]
        )
        for r in records:
            visible = r.visible_output_tokens
            if r.visible_output_chars is None or r.logged_answer_chars is None:
                continue
            acc = sums[(r.model_id, r.effort)]
            acc[0] += r.visible_output_chars
            acc[1] += r.logged_answer_chars
            acc[2] += 1
            if visible is not None:
                acc[3] += visible
                acc[4] += r.visible_output_chars
        self._fit = {}
        for key, (chars, logged, n, tokens, tok_chars) in sums.items():
            if logged > 0 and tok_chars > 0:
                self._fit[key] = (chars / logged, tokens / tok_chars, int(n))

    def estimate(
        self, model_id: str, effort: str | None, request: RequestFeatures, q: float
    ) -> Estimate:
        fit = self._fit.get((model_id, effort))
        if fit is None:
            return not_measured("not_evaluated", "no_recorded_usage", 0, PROVENANCE)
        logged = request.numeric.get("logged_answer_chars")
        if logged is None:
            return not_measured(
                "not_evaluated", "logged_answer_chars_missing", fit[2], PROVENANCE
            )
        ratio, tokens_per_char, n = fit
        return Estimate(
            "measured",
            n,
            PROVENANCE,
            value=ratio * logged * tokens_per_char,
            method="verbosity_ratio/visible",
            extra={
                "kind": "mean (q ignored)",
                "reasoning_tokens": "not_predicted",
                "ratio_chars": ratio,
                "tokens_per_char": tokens_per_char,
            },
        )


@dataclass(frozen=True)
class EstimatorComparison:
    q: float
    n: int
    """Held-out records scored by every estimator."""
    loss: Mapping[str, Estimate]
    """Mean pinball loss per estimator, with a cluster-bootstrap interval."""
    versus_reference: Mapping[str, Estimate]
    """Paired loss difference (estimator − reference); an interval entirely
    below zero means the estimator has lower loss."""
    reference: str
    better_than_reference: Mapping[str, bool | None]
    """True iff the whole interval is below zero; None if not evaluated."""


def _pinball(y: float, yhat: float, q: float) -> float:
    d = y - yhat
    return q * d if d >= 0 else (q - 1) * d


def compare_estimators(
    test: Sequence[UsageRecord],
    estimators: Mapping[str, OutputTokenEstimator],
    *,
    reference: str,
    q: float,
    target: str,
    features: Mapping[str, RequestFeatures],
    min_n: int | None,
    n_boot: int,
    seed: int | str,
    level: float,
) -> EstimatorComparison:
    """Score ``estimators`` on held-out ``test`` records they all answer.
    ``features`` maps request_id → ``RequestFeatures``. Held-out means the
    caller split by session and duplicate group (E0) before fitting."""
    if reference not in estimators:
        raise ValueError("reference must name one of the estimators")
    rows = []
    for record in test:
        truth = (
            float(record.output_tokens)
            if target == "output"
            else (
                None
                if record.visible_output_tokens is None
                else float(record.visible_output_tokens)
            )
        )
        if truth is None:
            continue
        request = features.get(record.request_id, RequestFeatures())
        losses = {}
        for name, estimator in estimators.items():
            est = estimator.estimate(record.model_id, record.effort, request, q)
            if est.value is None:
                break
            losses[name] = _pinball(truth, est.value, q)
        else:
            rows.append((record.session_ref, losses))
    n = len(rows)
    ok, reason = sufficient(n, min_n)
    loss: dict[str, Estimate] = {}
    versus: dict[str, Estimate] = {}
    better: dict[str, bool | None] = {}
    for name in estimators:
        if not ok:
            assert reason is not None
            loss[name] = not_measured("insufficient", reason, n, PROVENANCE)
            versus[name] = loss[name]
            better[name] = None
            continue
        boot = cluster_bootstrap(
            rows,
            lambda r: r[0],
            lambda rs, nm=name: sum(r[1][nm] for r in rs) / len(rs) if rs else None,
            n_boot=n_boot,
            seed=seed,
            level=level,
        )
        loss[name] = _boot_estimate(boot, n, level, "mean_pinball_loss")
        if name == reference:
            versus[name] = loss[name]
            better[name] = None
            continue
        diff = cluster_bootstrap(
            rows,
            lambda r: r[0],
            lambda rs, nm=name: (
                sum(r[1][nm] - r[1][reference] for r in rs) / len(rs) if rs else None
            ),
            n_boot=n_boot,
            seed=seed,
            level=level,
        )
        versus[name] = _boot_estimate(diff, n, level, "paired_loss_difference")
        better[name] = (
            versus[name].interval[1] < 0 if versus[name].interval is not None else None
        )
    return EstimatorComparison(q, n, loss, versus, reference, better)


def _boot_estimate(boot, n: int, level: float, method: str) -> Estimate:
    if boot.point is None or boot.low is None or boot.high is None:
        return not_measured("undefined", "statistic_undefined", n, PROVENANCE)
    return Estimate(
        "measured",
        n,
        PROVENANCE,
        value=boot.point,
        interval=(boot.low, boot.high),
        level=level,
        method=method,
    )
