"""Configuration of the routing dev slice (router_dev_slice_v1.toml).

Committed, content-free, no machine paths. Every value is a placeholder chosen
for development, not evidence. The size is 100–200 records; anything above
``HARD_MAX`` is refused in code, whatever the file says (owner, 2026-11-02).
Traces: FR-DATA-06, FR-EVAL-04/06, ADR-XXXX (system-one-decision-router) point 10.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HARD_MAX = 200
HARD_MIN = 100

DIMENSIONS = (
    "language_group",
    "position",
    "bot_class",
    "cohort",
)
"""Single-valued strata with share targets."""
FLAGS = (
    "short_followup",
    "short_uncertain",
    "greeting",
    "coding",
    "long_message",
    "attachments",
    "high_input",
    "rag_on_answer",
)
"""Boolean strata with minimum counts."""
POOL_DIMENSIONS = ("position", "cohort", "instructions")
POOL_FLAGS = (
    "short_followup",
    "long_message",
    "attachments",
    "high_input",
    "rag_on_answer",
)
"""What pass 1 knows before any text is read."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SliceSection(_Model):
    slice_id: str = Field(min_length=1)
    record_prefix: str = Field(pattern=r"^[a-z][a-z0-9]*$")
    size: int
    seed: int
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    candidate_pool: int = Field(gt=0)
    pool_flag_oversample: float = Field(default=3.0, ge=1.0)

    @field_validator("size")
    @classmethod
    def _bounded(cls, value: int) -> int:
        if not HARD_MIN <= value <= HARD_MAX:
            raise ValueError(
                f"slice size must be {HARD_MIN}–{HARD_MAX} records (got {value}); "
                "the dev slice is never the whole dataset"
            )
        return value


class InputsSection(_Model):
    source_config: str
    """Pinned revision and sha256 of every file (repo-relative)."""
    features_config: str
    """Rules, language groups, intent map and cohort names shared with golden-v1."""
    label_mapping: str
    """Logged model label → catalogue model (reference side only)."""
    golden_exports: tuple[str, ...]
    """ID-only exports whose records are excluded (the held-out test sets)."""


class ExclusionsSection(_Model):
    workflow_provider_names: tuple[str, ...] = ("workflow",)
    workflow_provider_models: tuple[str, ...] = ("workflow", "default")
    exclude_platform_default_instructions: bool = True
    exclude_bot_classes: tuple[str, ...] = ("workflow_unknown_config",)
    exclude_golden_sessions: bool = True
    exclude_golden_families: bool = True


class CapsSection(_Model):
    per_session: int = Field(default=1, ge=1)
    per_bot: int = Field(default=10, ge=1)
    per_family: int = Field(default=1, ge=1)


class ThresholdsSection(_Model):
    short_followup_max_chars: int = Field(default=15, gt=0)
    long_message_min_chars: int = Field(default=400, gt=0)
    high_input_min_tokens: int = Field(default=8000, gt=0)


class SplitSection(_Model):
    tune_share: float = Field(default=0.7, gt=0, lt=1)


class RecordSection(_Model):
    history_max_turns: int = Field(default=20, ge=0)
    """Earlier turns kept per record (oldest dropped first)."""


class ReviewSection(_Model):
    reviewers: tuple[str, ...] = ("R1", "R2")
    double_share: float = Field(default=0.2, ge=0.2, le=1)
    """At least 20% double-annotated (owner, 2026-11-02)."""
    message_max_chars: int = Field(default=1500, gt=0)
    context_max_chars: int = Field(default=300, gt=0)
    instructions_max_chars: int = Field(default=500, ge=0)

    @field_validator("reviewers")
    @classmethod
    def _two_or_more(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2 or len(set(value)) != len(value):
            raise ValueError("at least two distinct reviewers")
        return value


TRAFFIC_BASES = ("eligible_targets", "user_messages")


class WeightsSection(_Model):
    """Per-record traffic weights (owner, 2026-11-02): ``weight = cohort
    traffic share / cohort slice share``, so traffic-weighted metrics can be
    reported next to the balanced ones (R8). By cohort only: the one stratum
    known for all traffic before any text is read."""

    traffic_basis: str = "eligible_targets"
    """``eligible_targets``: the targets the slice is drawn from (after pass-1
    exclusions); ``user_messages``: every USER message of the dataset."""

    @field_validator("traffic_basis")
    @classmethod
    def _basis(cls, value: str) -> str:
        if value not in TRAFFIC_BASES:
            raise ValueError(f"traffic_basis must be one of {TRAFFIC_BASES}")
        return value


class CohortsSection(_Model):
    """Per-cohort record targets with a hard ceiling (owner, 2026-11-02): the
    golden allocation (session_config_report.md §8, floor plus square root of
    traffic), scaled to the slice. Replaces a ``[quotas.cohort]`` share."""

    targets: dict[str, int]
    """Cohort pseudonym → records; must sum to the slice size."""
    tolerance: int = Field(default=2, ge=0)
    """Hard ceiling per cohort = target + tolerance (a ``[ceilings.cohort]``
    share, if lower, still wins)."""
    pool_min_multiple: float = Field(default=5.0, ge=1.0)
    """The candidate pool is drawn per cohort, in proportion to the targets;
    each cohort gets at least this multiple of its target, or all its eligible
    sessions if fewer (checked and reported)."""
    waive_per_bot_if_cohort_bots_at_most: int = Field(default=2, ge=0)
    """A cohort with this few eligible bots has no per-bot cap (golden-v1's
    rule): its target could not otherwise be met."""

    @field_validator("targets")
    @classmethod
    def _positive(cls, value: dict[str, int]) -> dict[str, int]:
        if not value or any(n <= 0 for n in value.values()):
            raise ValueError("cohorts.targets: every target must be above 0")
        return value


class SliceConfig(_Model):
    slice: SliceSection
    inputs: InputsSection
    exclusions: ExclusionsSection = ExclusionsSection()
    caps: CapsSection = CapsSection()
    thresholds: ThresholdsSection = ThresholdsSection()
    split: SplitSection = SplitSection()
    record: RecordSection = RecordSection()
    review: ReviewSection = ReviewSection()
    weights: WeightsSection = WeightsSection()
    cohorts: CohortsSection | None = None
    quotas: dict[str, dict[str, float]] = {}
    """Dimension → value → target share of the slice (soft floor)."""
    ceilings: dict[str, dict[str, float]] = {}
    """Dimension → value → maximum share of the slice (hard: a candidate that
    would pass it is skipped)."""
    minimums: dict[str, int] = {}
    """Flag → minimum record count (soft)."""

    @model_validator(mode="after")
    def _check(self) -> SliceConfig:
        unknown = set(self.quotas) - set(DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown quota dimensions {sorted(unknown)}")
        for dim, shares in self.quotas.items():
            if any(not 0 < v <= 1 for v in shares.values()):
                raise ValueError(f"quotas.{dim}: shares must be in (0, 1]")
            if sum(shares.values()) > 1.0 + 1e-9:
                raise ValueError(f"quotas.{dim}: shares sum above 1")
        if self.cohorts is not None:
            if "cohort" in self.quotas:
                raise ValueError(
                    "set cohort targets in [cohorts] or [quotas.cohort], not both"
                )
            total = sum(self.cohorts.targets.values())
            if total != self.slice.size:
                raise ValueError(
                    f"cohorts.targets sum to {total}, not the slice size "
                    f"{self.slice.size}"
                )
            multiple = self.slice.candidate_pool / self.slice.size
            if multiple + 1e-9 < self.cohorts.pool_min_multiple:
                raise ValueError(
                    "candidate_pool is below cohorts.pool_min_multiple × size"
                )
        unknown = set(self.ceilings) - set(DIMENSIONS)
        if unknown:
            raise ValueError(f"unknown ceiling dimensions {sorted(unknown)}")
        floors = self.share_targets(self.slice.size)
        for dim, shares in self.ceilings.items():
            if any(not 0 < v <= 1 for v in shares.values()):
                raise ValueError(f"ceilings.{dim}: shares must be in (0, 1]")
        for dim, values in self.ceiling_counts(self.slice.size).items():
            for value, cap in values.items():
                floor = floors.get(dim, {}).get(value, 0)
                if cap < floor:
                    raise ValueError(
                        f"ceilings.{dim}.{value}: {cap} records is below the "
                        f"quota floor of {floor}"
                    )
        unknown = set(self.minimums) - set(FLAGS)
        if unknown:
            raise ValueError(f"unknown minimum flags {sorted(unknown)}")
        if any(v < 0 or v > self.slice.size for v in self.minimums.values()):
            raise ValueError("minimums must be between 0 and the slice size")
        if self.slice.candidate_pool < self.slice.size:
            raise ValueError("candidate_pool must be at least the slice size")
        return self

    def share_targets(self, size: int) -> dict[str, dict[str, int]]:
        """Soft floors in records; cohort targets come from ``[cohorts]``."""
        out = {
            dim: {v: max(1, round(share * size)) for v, share in values.items()}
            for dim, values in self.quotas.items()
        }
        if self.cohorts is not None:
            out["cohort"] = dict(self.cohorts.targets)
        return out

    def ceiling_counts(self, size: int) -> dict[str, dict[str, int]]:
        """Hard maxima in records. A share is rounded down, so it is never
        exceeded (0.30 × 150 = 45); a cohort target adds its tolerance; the
        lower of the two wins."""
        out = {
            dim: {v: math.floor(share * size + 1e-9) for v, share in values.items()}
            for dim, values in self.ceilings.items()
        }
        if self.cohorts is not None:
            caps = out.setdefault("cohort", {})
            for cohort, target in self.cohorts.targets.items():
                limit = target + self.cohorts.tolerance
                caps[cohort] = min(caps.get(cohort, limit), limit)
        return out


def load_config(path: Path) -> tuple[SliceConfig, str]:
    """The config and its hash (sha256 of the canonical parsed TOML, so line
    endings and comments do not change it)."""
    with path.open("rb") as handle:
        raw: dict[str, Any] = tomllib.load(handle)
    canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return SliceConfig.model_validate(raw), digest
