"""Configuration of the paid routing benchmark P-1..P-3
(``config/evaluation/benchmark.toml``; final plan "Paid branch").

Every owner decision is optional and defaults to **unset**; ``require`` turns an
unset value into ``OwnerValueUnset`` ("set by owner: <key>"), never a guess.
Unknown keys are refused. Pure. Traces: FR-EVAL-04, FR-EVAL-05, QA-COST,
ADR-0053. Status: provisional.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from metis_auto.contracts import ContractModel
from metis_auto.evaluation.judging.calibration import GateConfig


class OwnerValueUnset(Exception):
    """A value only an owner may set is missing; nothing was done."""

    def __init__(self, key: str) -> None:
        super().__init__(f"set by owner: {key}")
        self.key = key


class SetConfig(ContractModel):
    dataset_id: str
    reference_run_id: str
    reference_model: str
    shareable_ids: str
    tenant_cap: float = Field(gt=0, le=1)
    pooled_cohorts: tuple[str, ...] = ()


class PilotConfig(ContractModel):
    size: int = Field(gt=0)
    seed: str


class ArmsConfig(ContractModel):
    requested: tuple[str, ...]
    not_callable: Mapping[str, str] = {}


class GatesConfig(ContractModel):
    metis_allows_samples: bool = False
    metis_answer_ref: str | None = None

    @model_validator(mode="after")
    def _check(self) -> GatesConfig:
        if self.metis_allows_samples and not (self.metis_answer_ref or "").strip():
            raise ValueError("metis_allows_samples needs metis_answer_ref")
        return self


class SpendShareConfig(ContractModel):
    summaries_dir: str
    expected_machines: tuple[str, ...] | None = None
    max_age_hours: float | None = Field(default=None, gt=0)


class RunLimits(ContractModel):
    hard_cap_usd: Decimal | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    order_seed: str | None = None


class JudgeConfig(ContractModel):
    models: tuple[str, ...] | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    instruction_language: str | None = None

    @model_validator(mode="after")
    def _check(self) -> JudgeConfig:
        if self.models is not None and (
            len(self.models) != 2 or len(set(self.models)) != 2
        ):
            raise ValueError("judges.models needs exactly two different models")
        if self.instruction_language not in (None, "en", "fa"):
            raise ValueError("judges.instruction_language must be 'en' or 'fa'")
        return self


class LabelConfig(ContractModel):
    acceptable_score: float | None = Field(default=None, ge=0, le=1)
    cheap_arms: tuple[str, ...] | None = None


class SpotCheckConfig(ContractModel):
    size: int = Field(gt=0)
    seed: str


class BenchmarkConfig(ContractModel):
    version: str
    set: SetConfig
    pilot: PilotConfig
    arms: ArmsConfig
    gates: GatesConfig = GatesConfig()
    spend_share: SpendShareConfig
    run: RunLimits = RunLimits()
    judges: JudgeConfig = JudgeConfig()
    labels: LabelConfig = LabelConfig()
    gate: GateConfig = GateConfig()
    """The Persian gate for the judges (E5 ``GateConfig``), from the spot-check
    agreement. Unset: the label file says ``not_configured``; not an owner
    value the plan insists on."""
    spot_check: SpotCheckConfig

    def unset_owner_values(self) -> list[str]:
        """Every owner value still unset, in a stable order."""
        out = []
        for section, model in (
            ("spend_share", self.spend_share),
            ("run", self.run),
            ("judges", self.judges),
            ("labels", self.labels),
        ):
            for name in type(model).model_fields:
                if getattr(model, name) is None:
                    out.append(f"{section}.{name}")
        return out


def parse_config(raw: Mapping[str, Any]) -> BenchmarkConfig:
    return BenchmarkConfig.model_validate(dict(raw))


def require(value: Any, key: str) -> Any:
    if value is None:
        raise OwnerValueUnset(key)
    return value
