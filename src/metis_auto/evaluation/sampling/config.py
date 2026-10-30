"""Configuration of the shared sampling run (Stage E4; framework §0.2, §5).

Every field is optional and defaults to **unset**: no sample size, floor,
quota, cap, stop-rule threshold, or seed is chosen here. An unset value gives a
stated refusal or ``not_evaluated`` (never a guess), so the first run's numbers
are the owner's decisions, supplied in an experiment file. Parsed with
``parse_allocation_config`` / ``parse_run_config`` (unknown keys are refused).
Pure. Status: provisional (Stage E4).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from pydantic import model_validator

from metis_auto.contracts import ContractModel


class AllocationConfig(ContractModel):
    dimensions: tuple[str, ...] | None = None
    """Strata dimensions whose combinations are the cells (for example
    language, length_bucket, turn_depth, retrieved)."""
    total: int | None = None
    """Units to draw (a budget decision, not a statistical guarantee)."""
    floor_per_cell: int | None = None
    """Least units per cell (capped at the cell's population)."""
    pool_below_n: int | None = None
    """Cells with a smaller population are pooled with their siblings that
    share the first dimension's value."""
    quotas: Mapping[str, int] | None = None
    """Least units per ``language`` value (minority representation)."""
    seed: str | None = None

    @model_validator(mode="after")
    def _check(self) -> AllocationConfig:
        for name in ("total", "floor_per_cell", "pool_below_n"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must not be negative")
        if self.dimensions is not None and (
            not self.dimensions or len(set(self.dimensions)) != len(self.dimensions)
        ):
            raise ValueError("dimensions must be non-empty and unique")
        if self.quotas and any(q < 0 for q in self.quotas.values()):
            raise ValueError("quotas must not be negative")
        return self


class RunConfig(ContractModel):
    models: tuple[str, ...] = ()
    efforts: Mapping[str, tuple[str | None, ...]] = {}
    """Per model: effort labels to run (None = the provider default). A model
    not listed runs once at the default."""
    repeat_units: int | None = None
    repeat_count: int | None = None
    """The first ``repeat_units`` selected units are called ``repeat_count``
    more times, for within-model variance."""
    hard_cap_usd: Decimal | None = None
    max_output_tokens: int | None = None
    """Generation limit on every call; with it, a worst-case cost per call is
    computable, which is what the cap is checked against before a call."""
    order_seed: str | None = None
    """Seed of the call-order shuffle (so no model gets a time-of-day edge)."""
    output_tokens_assumption: Mapping[str, int] | None = None
    assumption_note: str | None = None
    """A documented assumption (billed output tokens per call, per model),
    used only for the assumed estimate; reported as simulated."""
    max_failure_share: float | None = None
    max_truncation_share: float | None = None
    stop_rule_min_calls: int | None = None
    overrun_factor: float | None = None
    overrun_check_at_progress: float | None = None

    @model_validator(mode="after")
    def _check(self) -> RunConfig:
        if self.hard_cap_usd is not None and self.hard_cap_usd <= 0:
            raise ValueError("hard_cap_usd must be positive")
        for name in ("max_output_tokens", "repeat_units", "repeat_count"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be at least 1")
        if (self.repeat_units is None) != (self.repeat_count is None):
            raise ValueError("repeat_units and repeat_count go together")
        for name in ("max_failure_share", "max_truncation_share"):
            value = getattr(self, name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.overrun_check_at_progress is not None and not (
            0 < self.overrun_check_at_progress <= 1
        ):
            raise ValueError("overrun_check_at_progress must be in (0, 1]")
        if self.overrun_factor is not None and self.overrun_factor <= 0:
            raise ValueError("overrun_factor must be positive")
        if self.output_tokens_assumption and not (self.assumption_note or "").strip():
            raise ValueError("output_tokens_assumption needs an assumption_note")
        return self


class LiveApproval(ContractModel):
    """The owner's explicit approval of one live run (ADR-0003, ADR-0018)."""

    approved_by: str
    run_id: str
    cap_usd: Decimal
    sample_conversations_approved: bool = False
    """Sample conversations need per-run approval (ADR-0018); only own or
    synthetic messages otherwise."""

    @model_validator(mode="after")
    def _check(self) -> LiveApproval:
        if not self.approved_by.strip() or not self.run_id.strip():
            raise ValueError("approved_by and run_id are required")
        if self.cap_usd <= 0:
            raise ValueError("cap_usd must be positive")
        return self


def parse_allocation_config(raw: Mapping[str, object]) -> AllocationConfig:
    return AllocationConfig.model_validate(dict(raw))


def parse_run_config(raw: Mapping[str, object]) -> RunConfig:
    return RunConfig.model_validate(dict(raw))
