"""Compare lever results within a step and a baseline (S-2; FR-ACCT-05, FR-EVAL-02,
FR-EVAL-06, FR-EVAL-09, FR-REQ-04, QA-COST).

``compare`` turns lever results into one content-free table for one baseline;
``to_markdown`` writes the four baselines as separate sections. The rules:

- **Rank only like with like.** Versions are ranked by saving inside a *group*:
  one step, one data scope (``n_requests`` and ``manifest.data_revision``), one
  price version (``manifest.price_version``) and one evidence class. Different
  groups are listed, never ranked against each other.
- **One baseline at a time.** A result under another baseline is never compared.
- **A version is ``(step, version)``**, the same across baselines. ``lever_id``
  names one result file (ADR-0032) and may carry a baseline suffix (Pipeline B:
  ``rb1.retrieval-cache.ttl-1d.user.tune.as_logged``), so it never identifies a
  version. A version with a result under some baseline but not under the chosen
  one gets one row with status ``baseline missing``, a blank ``lever_id`` and the
  baselines it does have in ``notes``; nothing is invented for it. Two results
  with the same ``(step, version)`` in one group under one baseline are never
  merged: both get status ``duplicate version``, no rank, and each other's
  ``lever_id`` in ``notes``. So a ``version`` label must be unique within a step
  for each baseline and group; the same version on another data scope (a tune
  run and a report run) is in another group and is not a duplicate.
- **Four baselines** (``BASELINES``): premium ``gpt-5.5`` (estimate only),
  as-logged recorded cost, today's logged models, best single cheap model. Only
  as-logged is in recorded cost units; the others are repriced. They are never
  mixed, because a table never holds two baselines.
- **Insufficient evidence is never a winner**: no saving, no interval (missing or
  NaN), no eligible request, or ``n_eligible`` below the result's own ``min_n``
  (an optional attribute) gives status ``insufficient evidence`` and no rank.
- **Unknown stays unknown** (FR-REQ-04): a missing or non-finite amount is
  ``None`` in the frame and "unknown" in Markdown, never 0. Money is ``Decimal``
  and is not rounded before the share is computed.
- **Correctness** is displayed as stored: ``unmeasured`` is shown as unmeasured,
  never as zero errors. A state outside the three agreed forms is "unknown".
- **Tenant share**: the largest ``tenant_rank:<n>`` slice share above
  ``max_tenant_share`` is flagged; no tenant slice is "unknown", not "ok". The
  cap is a required argument: callers pass ``[sample] tenant_cap`` from
  ``config/evaluation/sprint.toml`` (0.35, plan decision rule); ``analysis`` reads
  no config file.

INTERIM SHAPES (docs/experiments/pipeline_b_interim_contracts.md): the shared
``LeverResult`` (S-1, ``analysis/lever_result.py``) does not exist yet. Results
are read through ``LeverResultLike``, a protocol naming the plan's fields; the
real pydantic model must satisfy it unchanged. The key names inside the mappings
(``TOTAL_KEY``, ``SAVING_SHARE_KEY``, ``TENANT_SHARE_KEY``), the baseline keys
are assumptions to confirm with S-1 and S-3.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import pandas as pd

# Mapping keys (interim; to confirm with the LeverResult and baseline owners).
TOTAL_KEY = "total"  # saving / baseline_cost total; else the sum of the blocks
SAVING_SHARE_KEY = "saving_share"  # inside the llm_only / traffic_weighted slices
TENANT_SHARE_KEY = "share"  # inside each tenant_rank:<n> slice
TENANT_PREFIX = "tenant_rank:"
LLM_ONLY = "llm_only"
TRAFFIC_WEIGHTED = "traffic_weighted"
STEP_ORDER = ("cache", "context", "routing")

RANKED = "ranked"
INSUFFICIENT = "insufficient evidence"
MISSING = "baseline missing"
DUPLICATE = "duplicate version"

_SAMPLED = re.compile(r"sampled:(\d+)")


class ManifestLike(Protocol):
    @property
    def price_version(self) -> str: ...
    @property
    def data_revision(self) -> str: ...


class LeverResultLike(Protocol):
    """The fields of the plan's ``LeverResult`` that the comparison reads."""

    @property
    def lever_id(self) -> str: ...
    @property
    def step(self) -> str: ...
    @property
    def version(self) -> str: ...
    @property
    def n_requests(self) -> int: ...
    @property
    def n_eligible(self) -> int: ...
    @property
    def baseline(self) -> str: ...
    @property
    def baseline_cost(self) -> Mapping[str, Decimal]: ...
    @property
    def saving(self) -> Mapping[str, Decimal]: ...
    @property
    def ci_low(self) -> float | None: ...
    @property
    def ci_high(self) -> float | None: ...
    @property
    def slices(self) -> Mapping[str, Mapping[str, Decimal]]: ...
    @property
    def evidence_class(self) -> str: ...
    @property
    def correctness_state(self) -> str: ...
    @property
    def assumptions(self) -> Sequence[str]: ...
    @property
    def overhead_ms_p50(self) -> float | None: ...
    @property
    def overhead_ms_p95(self) -> float | None: ...
    @property
    def manifest(self) -> ManifestLike: ...


@dataclass(frozen=True)
class Baseline:
    key: str
    label: str
    recorded: bool  # True: recorded cost units; False: repriced


BASELINES: tuple[Baseline, ...] = (
    Baseline("premium_gpt_5_5", "Premium gpt-5.5 (estimate only)", recorded=False),
    Baseline("as_logged", "As-logged recorded cost", recorded=True),
    Baseline("todays_models", "Today's logged models", recorded=False),
    Baseline("best_single_cheap", "Best single cheap model", recorded=False),
)

COLUMNS = (
    "group",
    "rank",
    "status",
    "step",
    "lever_id",
    "version",
    "baseline",
    "cost_unit",
    "saving",
    "saving_share",
    "ci_low",
    "ci_high",
    "eligible",
    "n_eligible",
    "n_requests",
    "correctness",
    "evidence_class",
    "llm_only_share",
    "traffic_weighted_share",
    "max_tenant_share",
    "tenant_flag",
    "overhead",
    "assumptions",
    "notes",
    "price_version",
    "data_revision",
)


def compare(
    results: Sequence[LeverResultLike], *, baseline: str, max_tenant_share: Decimal
) -> pd.DataFrame:
    """One row per result under ``baseline``, plus one ``baseline missing`` row per
    version (``(step, version)``) that has results only under other baselines.
    Columns: ``COLUMNS``.

    ``max_tenant_share`` is the tenant cap (a ``Decimal`` share in (0, 1]); a
    larger top-tenant share is flagged.
    """
    chosen = _baseline(baseline)
    cap = _share_cap(max_tenant_share)
    chosen_results = [r for r in results if r.baseline == chosen.key]
    rows = [_row(r, chosen, cap) for r in chosen_results]
    _flag_duplicates(rows)
    present = {(r.step, r.version) for r in chosen_results}
    elsewhere: dict[tuple[str, str], set[str]] = {}
    for r in results:
        if (r.step, r.version) not in present:
            elsewhere.setdefault((r.step, r.version), set()).add(r.baseline)
    rows += [
        _missing_row(step, version, chosen, sorted(others))
        for (step, version), others in sorted(elsewhere.items())
    ]
    _rank(rows)
    rows.sort(key=_order)
    frame = pd.DataFrame(rows, columns=list(COLUMNS))
    frame["rank"] = pd.array([r["rank"] for r in rows], dtype="Int64")
    return frame


def to_markdown(
    results: Sequence[LeverResultLike],
    *,
    max_tenant_share: Decimal,
    note: str | None = None,
) -> str:
    """The comparison for all four baselines, one section each; content-free."""
    lines = ["# Lever comparison", ""]
    if note:
        lines += [f"> {note}", ""]
    lines += [
        "Ranks hold only inside one group (step, data scope, price version, evidence "
        "class) and one baseline. Insufficient evidence is never ranked. Unknown is "
        "shown as unknown, never 0. `unmeasured` correctness means not checked.",
        "",
    ]
    for b in BASELINES:
        frame = compare(results, baseline=b.key, max_tenant_share=max_tenant_share)
        unit = "recorded cost units" if b.recorded else "repriced (see each group)"
        lines += [f"## {b.label} (`{b.key}`)", "", f"Cost unit: {unit}.", ""]
        if not any(r.baseline == b.key for r in results):
            lines += [
                "**Missing.** No result uses this baseline; none is invented.",
                "",
            ]
        for group, part in frame.groupby("group", sort=False):
            lines += [f"### {group}", "", *_table(part), ""]
    known = {b.key for b in BASELINES}
    other = sum(r.baseline not in known for r in results)
    if other:
        lines += [
            f"{other} result(s) use a baseline that is not one of the four; "
            "they are not shown.",
            "",
        ]
    return "\n".join(lines)


# --- rows ---


def _baseline(key: str) -> Baseline:
    for b in BASELINES:
        if b.key == key:
            return b
    names = ", ".join(b.key for b in BASELINES)
    raise ValueError(f"{key!r} is not one of the four baselines ({names})")


def _share_cap(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError("max_tenant_share must be a Decimal, never float or text")
    if not value.is_finite() or not Decimal(0) < value <= Decimal(1):
        raise ValueError("max_tenant_share must be a share in (0, 1]")
    return value


def _row(r: LeverResultLike, b: Baseline, cap: Decimal) -> dict[str, object]:
    saving = _total(r.saving)
    cost = _total(r.baseline_cost)
    share = saving / cost if saving is not None and cost else None
    tenant = _max_tenant_share(r.slices)
    notes = _insufficient(r, saving)
    return {
        "group": _group(r),
        "rank": None,
        "status": INSUFFICIENT if notes else RANKED,
        "step": r.step,
        "lever_id": r.lever_id,
        "version": r.version,
        "baseline": b.key,
        "cost_unit": _cost_unit(b, r.manifest.price_version),
        "saving": saving,
        "saving_share": share,
        "ci_low": _finite_float(r.ci_low),
        "ci_high": _finite_float(r.ci_high),
        "eligible": f"{r.n_eligible} of {r.n_requests}",
        "n_eligible": r.n_eligible,
        "n_requests": r.n_requests,
        "correctness": _correctness(r.correctness_state),
        "evidence_class": r.evidence_class,
        "llm_only_share": _slice_share(r.slices, LLM_ONLY),
        "traffic_weighted_share": _slice_share(r.slices, TRAFFIC_WEIGHTED),
        "max_tenant_share": tenant,
        "tenant_flag": _tenant_flag(tenant, cap),
        "overhead": _overhead(r.overhead_ms_p50, r.overhead_ms_p95),
        "assumptions": "; ".join(r.assumptions),
        "notes": "; ".join(notes),
        "price_version": r.manifest.price_version,
        "data_revision": r.manifest.data_revision,
    }


def _flag_duplicates(rows: list[dict[str, object]]) -> None:
    """Mark rows that share ``(step, version)`` in one group under one baseline;
    never merge. Rows of different groups are never compared, so never twins."""
    by_version: dict[tuple[object, object, object], list[dict[str, object]]] = {}
    for row in rows:
        key = (row["group"], row["step"], row["version"])
        by_version.setdefault(key, []).append(row)
    for twins in by_version.values():
        if len(twins) < 2:
            continue
        for row in twins:
            others = sorted(str(t["lever_id"]) for t in twins if t is not row)
            note = f"same step and version as {', '.join(others)}; not ranked"
            row["status"] = DUPLICATE
            row["notes"] = "; ".join(n for n in (note, row["notes"]) if n)


def _missing_row(
    step: str, version: str, b: Baseline, others: Sequence[str]
) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(COLUMNS)
    row |= {
        "group": f"{step} | {MISSING}",
        "status": MISSING,
        "step": step,
        "lever_id": None,
        "version": version,
        "baseline": b.key,
        "tenant_flag": "unknown",
        "notes": (
            "no result under this baseline; none is invented; present under "
            f"{', '.join(others)} (lever IDs are baseline-qualified, so the "
            "version is matched by step and version)"
        ),
    }
    return row


def _group(r: LeverResultLike) -> str:
    m = r.manifest
    return (
        f"{r.step} | {r.n_requests} requests | data {m.data_revision} "
        f"| prices {m.price_version} | evidence {r.evidence_class}"
    )


def _insufficient(r: LeverResultLike, saving: Decimal | None) -> list[str]:
    notes = []
    if saving is None:
        notes.append("saving unknown")
    if _finite_float(r.ci_low) is None or _finite_float(r.ci_high) is None:
        notes.append("no interval")
    if r.n_eligible <= 0:
        notes.append("no eligible request")
    min_n = getattr(r, "min_n", None)  # optional: the result's own minimum
    if min_n is not None and r.n_eligible < min_n:
        notes.append(f"n_eligible {r.n_eligible} below min_n {min_n}")
    return notes


def _rank(rows: list[dict[str, object]]) -> None:
    groups: dict[object, list[dict[str, object]]] = {}
    for row in rows:
        if row["status"] == RANKED:
            groups.setdefault(row["group"], []).append(row)
    for members in groups.values():
        members.sort(key=lambda r: (-r["saving"], r["lever_id"], r["version"]))
        for i, row in enumerate(members, start=1):
            row["rank"] = i


def _order(row: dict[str, object]) -> tuple:
    step = row["step"]
    step_pos = STEP_ORDER.index(step) if step in STEP_ORDER else len(STEP_ORDER)
    rank = row["rank"]
    return (
        row["status"] == MISSING,
        step_pos,
        str(step),
        str(row["group"]),
        rank is None,
        rank if rank is not None else 0,
        str(row["lever_id"]),
        str(row["version"]),
    )


# --- values ---


def _money(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, Decimal | int):
        raise TypeError("money must be Decimal (or int), never float or text")
    d = Decimal(value)
    return d if d.is_finite() else None


def _total(amounts: Mapping[str, Decimal]) -> Decimal | None:
    if TOTAL_KEY in amounts:
        return _money(amounts[TOTAL_KEY])
    if not amounts:
        return None
    parts = [_money(v) for v in amounts.values()]
    return None if any(p is None for p in parts) else sum(parts, Decimal(0))


def _finite_float(value: float | None) -> float | None:
    if value is None:
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _slice_share(slices: Mapping[str, Mapping[str, Decimal]], name: str):
    value = slices.get(name, {}).get(SAVING_SHARE_KEY)
    return None if value is None else _money(value)


def _max_tenant_share(slices: Mapping[str, Mapping[str, Decimal]]) -> Decimal | None:
    shares = [
        _money(inner[TENANT_SHARE_KEY])
        for key, inner in slices.items()
        if key.startswith(TENANT_PREFIX) and TENANT_SHARE_KEY in inner
    ]
    known = [s for s in shares if s is not None]
    return max(known) if known else None


def _tenant_flag(share: Decimal | None, cap: Decimal) -> str:
    if share is None:
        return "unknown"
    return f"over {_percent(cap)}%" if share > cap else "ok"


def _percent(share: Decimal) -> str:
    """``0.35`` -> ``35``; ``0.355`` -> ``35.5`` (no trailing zeros, no exponent)."""
    text = f"{share * 100:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _correctness(state: str) -> str:
    if state == "unmeasured":
        return "unmeasured (not checked)"
    if state == "measured":
        return "measured"
    if match := _SAMPLED.fullmatch(state):
        return f"sampled (n={int(match.group(1))})"
    return "unknown (unrecognised state)"


def _cost_unit(b: Baseline, price_version: str) -> str:
    return "recorded cost units" if b.recorded else f"repriced (prices {price_version})"


def _overhead(p50: float | None, p95: float | None) -> str:
    if p50 is None and p95 is None:
        return "not measured"

    def ms(x: float | None) -> str:
        return "unknown" if x is None else f"{round(x, 3)} ms"

    return f"p50 {ms(p50)}, p95 {ms(p95)}"


# --- Markdown ---

_HEADER = (
    "rank",
    "status",
    "lever",
    "version",
    "saving",
    "saving share",
    "interval",
    "eligible",
    "correctness",
    "evidence",
    "LLM-only share",
    "traffic-weighted share",
    "max tenant share",
    "tenant",
    "overhead",
    "assumptions",
    "notes",
)


def _table(frame: pd.DataFrame) -> list[str]:
    lines = ["| " + " | ".join(_HEADER) + " |", "|" + "---|" * len(_HEADER)]
    for row in frame.to_dict("records"):
        interval = (
            f"[{row['ci_low']:.4g}, {row['ci_high']:.4g}]"
            if pd.notna(row["ci_low"]) and pd.notna(row["ci_high"])
            else "missing"
        )
        cells = (
            "—" if pd.isna(row["rank"]) else str(row["rank"]),
            row["status"],
            row["lever_id"],
            row["version"],
            row["saving"],
            row["saving_share"],
            interval if row["status"] != MISSING else "—",
            row["eligible"],
            row["correctness"],
            row["evidence_class"],
            row["llm_only_share"],
            row["traffic_weighted_share"],
            row["max_tenant_share"],
            row["tenant_flag"],
            row["overhead"],
            row["assumptions"],
            row["notes"],
        )
        if row["status"] == MISSING:  # not applicable, rather than unknown
            keep = {1, 3, len(cells) - 1}  # status, version, notes
            cells = tuple(c if i in keep else "—" for i, c in enumerate(cells))
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return lines


def _cell(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "unknown"
    return str(value).replace("|", "\\|").replace("\n", " ")
