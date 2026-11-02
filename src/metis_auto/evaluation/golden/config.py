"""The sampling configuration, validated (pure). Every margin must sum to the total."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MARGINS = (
    "primary_intent",
    "complexity_proxy",
    "language_group",
    "target_length",
    "position",
    "bot_class",
    "cohort",
)
SOFT_MARGINS = (
    "complexity_proxy",
    "language_group",
    "target_length",
    "position",
    "bot_class",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class GoldenConfig:
    raw: Mapping[str, Any]
    sha256: str

    @property
    def total(self) -> int:
        return self.raw["dataset"]["total"]

    @property
    def seed(self) -> int:
        return self.raw["dataset"]["seed"]

    @property
    def dataset_id(self) -> str:
        return self.raw["dataset"]["dataset_id"]

    def quotas(self, margin: str) -> dict[str, int]:
        return dict(self.raw["quotas"][margin])


def config_sha256(data: bytes) -> str:
    """Hash of the file with line endings normalised, the same on every computer."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def parse_config(raw: Mapping[str, Any], sha256: str) -> GoldenConfig:
    total = raw["dataset"]["total"]
    for margin in MARGINS:
        got = sum(raw["quotas"][margin].values())
        if got != total:
            raise ConfigError(f"margin {margin} sums to {got}, not {total}")
    floor = raw["minimums"]["primary_intent_floor"]
    exempt = set(raw["minimums"]["primary_intent_floor_exempt"])
    for key, quota in raw["quotas"]["primary_intent"].items():
        if key not in exempt and quota < floor:
            raise ConfigError(f"{key}: quota {quota} is below the floor {floor}")
    if raw["cohorts"]["remaining"] not in raw["quotas"]["cohort"]:
        raise ConfigError("the remaining-accounts cohort has no quota")
    if "derive" in raw:
        _check_derive(raw["derive"], raw["coverage"])
    return GoldenConfig(raw=raw, sha256=sha256)


DERIVE_KEYS = {"base_dataset", "base_fingerprint", "exclude"}
DERIVE_RULES = {"attachments"}


def _check_derive(derive: Mapping[str, Any], coverage: Mapping[str, Any]) -> None:
    if set(derive) != DERIVE_KEYS:
        raise ConfigError(f"[derive] needs exactly {sorted(DERIVE_KEYS)}")
    if derive["exclude"] not in DERIVE_RULES:
        raise ConfigError(f"[derive] exclude must be one of {sorted(DERIVE_RULES)}")
    if derive["exclude"] == "attachments" and "attachment_dependent" in coverage:
        raise ConfigError(
            "a dataset without attachment records cannot require attachment_dependent"
        )


def percentile(sorted_values: list[int], q: float) -> int:
    """Nearest-rank percentile: exact and identical on every platform."""
    if not sorted_values:
        raise ValueError("no values")
    rank = max(1, -(-len(sorted_values) * int(q * 1000) // 100000))
    return sorted_values[rank - 1]


def length_edges(sorted_chars: list[int], percentiles: list[int]) -> list[int]:
    return [percentile(sorted_chars, p) for p in percentiles]


def length_bucket(chars: int, edges: list[int], labels: list[str]) -> str:
    """A value equal to an edge falls in the lower band (≤ p25 is very short)."""
    for edge, label in zip(edges, labels, strict=False):
        if chars <= edge:
            return label
    return labels[-1]


def position_bucket(turn_index: int, middle_max: int) -> str:
    if turn_index <= 1:
        return "first"
    return "middle" if turn_index <= middle_max else "late"
