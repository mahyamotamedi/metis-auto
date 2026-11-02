"""Content-free result of one lever, with its reproducibility manifest.

``LeverResult`` is the one format that the comparison, the savings waterfall and
the demo read (final plan S-1, E-2; QA-REPRO, QA-PRIV). Callers write it to
``reports/levers/<lever_id>.json`` using ``to_json``. Every field declares a
privacy class (ADR-0017); none can hold message text, instructions, IDs or
hashes of content. ``assumptions`` holds short authored statements, not data.

Determinism: ``to_json`` sorts keys and prints money in fixed notation, and the
manifest's ``created_at`` is passed in, so identical inputs give identical bytes.
A script passes the real UTC time; tests fix it.

Evidence labels: a result is one of *observed*, *metadata-derived*, *heuristic*,
*hypothetical reconstruction* or *simulation*. A cache hit is a candidate hit.
Recorded cost (unstated units) is never mixed with repriced cost.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import Field, PlainSerializer, StringConstraints, model_validator

from metis_auto.analysis.levers import ReplayContext
from metis_auto.contracts import ContractModel, Name, Privacy, UtcDatetime
from metis_auto.contracts._base import NonNegInt, field

DATA_REVISION = "30f578f283b903cdbd06cd1b5f7f962f76452ded"
"""Pinned dataset revision for the sprint (final plan, Global Constraints)."""

REQUIRED_SLICES = ("all", "llm_only")

Amount = Annotated[
    Decimal,
    Field(allow_inf_nan=False),
    PlainSerializer(lambda d: format(d, "f"), return_type=str, when_used="json"),
]
"""A recorded cost or a count, as a finite Decimal printed in fixed notation."""

LeverId = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_.+\-]*$"
    ),
]
"""File-name safe: ``route.per_bot+jev`` is valid, a path is not."""

ShortVersion = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.+\-]*$"
    ),
]

Assumption = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class Manifest(ContractModel):
    """What is needed to reproduce a result (QA-REPRO, FR-EVAL-07).

    Fields are pattern-constrained, so a path or a user name cannot be stored.
    """

    data_revision: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")] = field(
        Privacy.OPERATIONAL, "Dataset revision (40-hex git hash)."
    )
    code_commit: Annotated[
        str, StringConstraints(pattern=r"^([0-9a-f]{7,40}|unknown)$")
    ] = field(Privacy.OPERATIONAL, "Code commit, or 'unknown' (never guessed).")
    config_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = field(
        Privacy.OPERATIONAL, "SHA-256 of the canonical replay settings."
    )
    seed: int = field(Privacy.OPERATIONAL, "Random seed of the replay.")
    price_version: ShortVersion = field(
        Privacy.OPERATIONAL, "Version of the price table used."
    )
    python_version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")] = (
        field(Privacy.OPERATIONAL, "Python version that produced the result.")
    )
    created_at: UtcDatetime = field(Privacy.OPERATIONAL, "UTC time, passed in.")


def _canonical(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, set | frozenset):
        return sorted(value, key=str)
    raise TypeError(f"config holds a non-plain value: {type(value).__name__}")


def config_hash(config: Mapping[str, object], ctx: ReplayContext) -> str:
    """SHA-256 over the settings that change a result: ``config``, ``min_n`` and
    the period bounds. Key order does not matter."""
    payload = {
        "config": config,
        "min_n": ctx.min_n,
        "period_bounds": {k: list(v) for k, v in ctx.period_bounds.items()},
    }
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=_canonical
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_manifest(
    config: Mapping[str, object],
    ctx: ReplayContext,
    *,
    code_commit: str,
    python_version: str,
    created_at: datetime,
    data_revision: str = DATA_REVISION,
) -> Manifest:
    """Fill a ``Manifest``. No git call and no clock here: analysis stays pure.

    A script gets ``code_commit`` from ``wiring.experiments.code_version`` and
    ``python_version`` from ``platform.python_version()``. The price version is
    the ``version`` key of ``ctx.price_table``; without one this raises.
    """
    table = ctx.price_table
    version = table.get("version") if isinstance(table, Mapping) else None
    if not isinstance(version, str):
        raise ValueError("ctx.price_table needs a 'version' key to build a manifest")
    return Manifest(
        data_revision=data_revision,
        code_commit=code_commit,
        config_hash=config_hash(config, ctx),
        seed=ctx.seed,
        price_version=version,
        python_version=python_version,
        created_at=created_at,
    )


class LeverResult(ContractModel):
    """One step version's saving against one baseline (simulation unless stated)."""

    lever_id: LeverId = field(Privacy.OPERATIONAL, "Result name; the file name.")
    step: Literal["cache", "context", "routing"] = field(
        Privacy.OPERATIONAL, "Which step the version belongs to."
    )
    version: ShortVersion = field(Privacy.OPERATIONAL, "Version label of the step.")
    n_requests: NonNegInt = field(Privacy.DERIVED, "Requests in the replay.")
    n_eligible: NonNegInt = field(
        Privacy.DERIVED, "LLM requests the version could act on."
    )
    baseline: Name = field(
        Privacy.OPERATIONAL, "Baseline the saving is measured against."
    )
    baseline_cost: dict[Name, Amount] = field(
        Privacy.OPERATIONAL, "Baseline cost per block, recorded units."
    )
    saving: dict[Name, Amount] = field(
        Privacy.OPERATIONAL, "Saving per block, same units as the baseline."
    )
    ci_low: float | None = field(
        Privacy.DERIVED,
        "Session-clustered interval, low; None if not computed.",
        default=None,
    )
    ci_high: float | None = field(
        Privacy.DERIVED,
        "Session-clustered interval, high; None if not computed.",
        default=None,
    )
    slices: dict[Name, dict[Name, Amount]] = field(
        Privacy.OPERATIONAL,
        "Counts, costs and rates per slice; 'all' and 'llm_only' are required.",
    )
    evidence_class: Literal[
        "observed",
        "metadata-derived",
        "heuristic",
        "hypothetical reconstruction",
        "simulation",
    ] = field(Privacy.OPERATIONAL, "Evidence label of the result.")
    correctness_state: Annotated[
        str, StringConstraints(pattern=r"^(unmeasured|measured|sampled:[0-9]+)$")
    ] = field(Privacy.OPERATIONAL, "unmeasured, sampled:<n> or measured.")
    assumptions: tuple[Assumption, ...] = field(
        Privacy.OPERATIONAL, "Short authored assumptions; never data.", default=()
    )
    overhead_ms_p50: float | None = field(
        Privacy.DERIVED, "Offline per-request overhead, median (ms).", default=None
    )
    overhead_ms_p95: float | None = field(
        Privacy.DERIVED, "Offline per-request overhead, p95 (ms).", default=None
    )
    manifest: Manifest = field(Privacy.OPERATIONAL, "How to reproduce the result.")

    @model_validator(mode="after")
    def _check(self) -> Self:
        missing = [s for s in REQUIRED_SLICES if s not in self.slices]
        if missing:
            raise ValueError(
                f"slices must include {REQUIRED_SLICES}; missing {missing}"
            )
        if self.ci_low is not None and self.ci_high is not None:
            if self.ci_low > self.ci_high:
                raise ValueError("ci_low must not exceed ci_high")
        return self

    def to_json(self) -> str:
        """Sorted keys, fixed money notation, trailing newline."""
        data = self.model_dump(mode="json")
        return json.dumps(data, sort_keys=True, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> Self:
        return cls.model_validate_json(text)
