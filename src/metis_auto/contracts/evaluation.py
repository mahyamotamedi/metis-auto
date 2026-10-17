"""Evaluation results and run manifests (CMP-23, CMP-24; ADR-0006, ADR-0014).

ADR-0006 rules enforced here: quality signals are separate metrics, hit rate
never appears without hit correctness, cost carries its fidelity and price
version, and "unmeasured" and "not computed" are explicit states.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

from ._base import (
    SCHEMA_VERSION,
    ContractModel,
    Identifier,
    Name,
    NonNegInt,
    Privacy,
    UtcDatetime,
    Version,
    Versions,
    field,
)
from .accounting import Cost, Money
from .replay import PairingFlag
from .tokens import Fidelity


class CounterfactualSource(StrEnum):
    """ADR-0014. Declared by every run."""

    FAKE = "fake"
    LOGGED_MATCH = "logged_match"
    RECORDED = "recorded"
    LIVE = "live"
    PROXY = "proxy"


class MetricName(StrEnum):
    """Known metrics. Quality is three separate metrics, never one score."""

    AGREEMENT = "agreement"
    JUDGE_SCORE = "judge_score"
    NON_INFERIORITY = "non_inferiority"
    CANDIDATE_HIT_RATE = "candidate_hit_rate"
    HIT_RATE = "hit_rate"
    HIT_CORRECTNESS = "hit_correctness"
    FALSE_HIT_RATE = "false_hit_rate"
    COST_PER_REQUEST = "cost_per_request"
    TOTAL_COST = "total_cost"
    SAVINGS = "savings"
    OVERHEAD_LATENCY_P50 = "overhead_latency_p50"
    OVERHEAD_LATENCY_P95 = "overhead_latency_p95"
    MODEL_LATENCY = "model_latency"
    END_TO_END_LATENCY = "end_to_end_latency"
    ESCALATION_RATE = "escalation_rate"
    FAILOVER_RATE = "failover_rate"
    RETRY_RATE = "retry_rate"
    ROUTER_OVERHEAD = "router_overhead"
    COVERAGE = "coverage"


HIT_RATES = frozenset({MetricName.HIT_RATE, MetricName.CANDIDATE_HIT_RATE})
HIT_CORRECTNESS = frozenset({MetricName.HIT_CORRECTNESS, MetricName.FALSE_HIT_RATE})
COST_METRICS = frozenset(
    {MetricName.COST_PER_REQUEST, MetricName.TOTAL_COST, MetricName.SAVINGS}
)


class MetricState(StrEnum):
    MEASURED = "measured"
    UNMEASURED = "unmeasured"
    """The data or source cannot produce it (e.g. latency offline)."""
    NOT_COMPUTED = "not_computed"
    """An input is unknown (e.g. a price, an unset baseline)."""


class Interval(ContractModel):
    low: float = field(Privacy.DERIVED, "Lower bound.")
    high: float = field(Privacy.DERIVED, "Upper bound.")
    level: float = field(Privacy.OPERATIONAL, "e.g. 0.95.", gt=0, lt=1)
    method: Name = field(Privacy.OPERATIONAL, "e.g. bootstrap_percentile.")


class MetricValue(ContractModel):
    """One metric, with its sample size and qualifiers."""

    name: MetricName = field(Privacy.OPERATIONAL, "Metric.")
    state: MetricState = field(Privacy.OPERATIONAL, "Measured or why not.")
    value: float | None = field(Privacy.DERIVED, "Set iff measured.", default=None)
    unit: Name | None = field(Privacy.OPERATIONAL, "e.g. ratio, ms, usd.", default=None)
    n: NonNegInt = field(Privacy.DERIVED, "Cases the value is computed over.")
    interval: Interval | None = field(Privacy.DERIVED, "Uncertainty.", default=None)
    reason: Name | None = field(
        Privacy.OPERATIONAL, "Why unmeasured or not computed.", default=None
    )
    baseline: Name | None = field(
        Privacy.OPERATIONAL, "Baseline compared against, if any.", default=None
    )
    key_variant: Name | None = field(
        Privacy.OPERATIONAL, "Cache key variant (cache metrics).", default=None
    )
    scope: Name | None = field(
        Privacy.OPERATIONAL, "Cache scope measured (cache metrics).", default=None
    )
    judge: Version | None = field(
        Privacy.OPERATIONAL, "Judge ID@version.", default=None
    )
    token_fidelity: Fidelity | None = field(
        Privacy.OPERATIONAL, "Worst fidelity (cost metrics).", default=None
    )
    price_table_version: Version | None = field(
        Privacy.OPERATIONAL, "Price table (cost metrics).", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> MetricValue:
        measured = self.state == MetricState.MEASURED
        if measured != (self.value is not None):
            raise ValueError("value is set exactly when measured")
        if not measured and self.reason is None:
            raise ValueError("an unmeasured or not-computed metric needs a reason")
        if (
            measured
            and self.name in COST_METRICS
            and (self.token_fidelity is None or self.price_table_version is None)
        ):
            raise ValueError("a cost metric carries token fidelity and price version")
        if measured and self.name == MetricName.JUDGE_SCORE and self.judge is None:
            raise ValueError("a judge score names its judge")
        return self


class JudgeScore(ContractModel):
    """One judge's score for one answer (``Judge`` port output, CMP-15).

    Evaluation cost when used offline; request overhead when used as a runtime
    detector (evaluation.md §6).
    """

    judge: Version = field(Privacy.OPERATIONAL, "Judge ID@version.")
    rubric: Name = field(Privacy.OPERATIONAL, "Rubric ID.")
    state: MetricState = field(Privacy.OPERATIONAL, "Measured or why not.")
    score: float | None = field(Privacy.DERIVED, "Set iff measured.", default=None)
    reason: Name | None = field(Privacy.OPERATIONAL, "Why not measured.", default=None)
    cost: Cost | None = field(
        Privacy.OPERATIONAL, "Cost of the judge call.", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> JudgeScore:
        measured = self.state == MetricState.MEASURED
        if measured != (self.score is not None):
            raise ValueError("score is set exactly when measured")
        if not measured and self.reason is None:
            raise ValueError("an unmeasured score needs a reason")
        return self


class StratumKey(ContractModel):
    dimension: Name = field(Privacy.OPERATIONAL, "e.g. category, language, turn_depth.")
    value: Identifier = field(Privacy.REFERENCE, "Stratum value (opaque for category).")


class StratumResult(ContractModel):
    """Metrics for one stratum. An empty ``stratum`` means overall."""

    stratum: tuple[StratumKey, ...] = field(Privacy.REFERENCE, "Stratum; () = overall.")
    n_cases: NonNegInt = field(Privacy.DERIVED, "Cases in the stratum.")
    metrics: tuple[MetricValue, ...] = field(Privacy.DERIVED, "Metrics.")

    @model_validator(mode="after")
    def _hit_rate_needs_correctness(self) -> StratumResult:
        names = {m.name for m in self.metrics}
        if names & HIT_RATES and not names & HIT_CORRECTNESS:
            raise ValueError(
                "hit rate needs hit correctness or false-hit rate, "
                "even if unmeasured (ADR-0006)"
            )
        return self


class ExclusionCount(ContractModel):
    reason: Name = field(Privacy.OPERATIONAL, "e.g. a pairing flag, unknown_metadata.")
    count: NonNegInt = field(Privacy.DERIVED, "Records excluded or flagged.")


class EvaluationResult(ContractModel):
    """Results of one run (FR-EVAL-03, 06, 08, 09)."""

    schema_version: Version = field(
        Privacy.OPERATIONAL, "Contract version.", default=SCHEMA_VERSION
    )
    run_id: Identifier = field(Privacy.REFERENCE, "Run.")
    experiment_id: Name = field(Privacy.OPERATIONAL, "EXP ID (Stage 8).")
    counterfactual_source: CounterfactualSource = field(
        Privacy.OPERATIONAL, "ADR-0014."
    )
    cases_total: NonNegInt = field(Privacy.DERIVED, "Cases offered.")
    cases_covered: NonNegInt = field(
        Privacy.DERIVED, "Cases the source answered; quality uses only these."
    )
    baselines: tuple[Name, ...] = field(Privacy.OPERATIONAL, "Baselines reported.")
    results: tuple[StratumResult, ...] = field(Privacy.DERIVED, "Overall first.")
    exclusions: tuple[ExclusionCount, ...] = field(
        Privacy.DERIVED, "Excluded or flagged records.", default=()
    )

    @model_validator(mode="after")
    def _check(self) -> EvaluationResult:
        if self.cases_covered > self.cases_total:
            raise ValueError("cases_covered cannot exceed cases_total")
        if "as_logged" not in self.baselines:
            raise ValueError("every run reports the as-logged baseline (ADR-0002)")
        if not self.results or self.results[0].stratum:
            raise ValueError("results start with the overall stratum")
        return self


class CodeVersion(ContractModel):
    commit: str | None = field(
        Privacy.OPERATIONAL, "Git commit, if known.", default=None
    )
    dirty: bool | None = field(
        Privacy.OPERATIONAL, "Uncommitted changes.", default=None
    )


class RunManifest(ContractModel):
    """Everything needed to reproduce and compare a run (FR-EVAL-07)."""

    schema_version: Version = field(
        Privacy.OPERATIONAL, "Contract version.", default=SCHEMA_VERSION
    )
    run_id: Identifier = field(Privacy.REFERENCE, "Run.")
    experiment_id: Name = field(Privacy.OPERATIONAL, "EXP ID.")
    started_at: UtcDatetime = field(Privacy.OPERATIONAL, "Start time.")
    code: CodeVersion = field(Privacy.OPERATIONAL, "Code version.")
    dataset: Name = field(Privacy.OPERATIONAL, "Dataset ID.")
    data_hash: str | None = field(
        Privacy.OPERATIONAL, "Hash of the dataset file(s).", default=None
    )
    seed: int | None = field(Privacy.OPERATIONAL, "Seed.", default=None)
    versions: Versions = field(Privacy.OPERATIONAL, "Config hash, key ID, versions.")
    counterfactual_source: CounterfactualSource = field(
        Privacy.OPERATIONAL, "ADR-0014."
    )
    prompt_composition_assumption: Name = field(
        Privacy.OPERATIONAL, "Assumed composition ID (context_construction.md §4)."
    )
    history_mode: Name = field(
        Privacy.OPERATIONAL, "e.g. logged_history (A-30, ADR-0014 point 5)."
    )
    ordering_rule: Name = field(Privacy.OPERATIONAL, "Case ordering (A-31).")
    pairing_flags_included: tuple[PairingFlag, ...] = field(
        Privacy.OPERATIONAL, "Flags admitted to the run."
    )
    live_calls: bool = field(Privacy.OPERATIONAL, "Whether live calls were enabled.")
    spend_cap: Money | None = field(Privacy.OPERATIONAL, "Cap, if live.", default=None)
    hardware: str | None = field(
        Privacy.OPERATIONAL, "Machine description (A-22).", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> RunManifest:
        if self.live_calls and self.spend_cap is None:
            raise ValueError("live calls need a spending cap (ADR-0003)")
        if (
            self.counterfactual_source == CounterfactualSource.LIVE
            and not self.live_calls
        ):
            raise ValueError(
                "a live source needs live calls enabled (configuration §3)"
            )
        if PairingFlag.NO_PRECEDING_USER in self.pairing_flags_included:
            raise ValueError("no_preceding_user records are never cases")
        return self
