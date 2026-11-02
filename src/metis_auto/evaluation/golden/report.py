"""Margin reports and the content-free quality report (pure)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from metis_auto.evaluation.golden.config import SOFT_MARGINS, GoldenConfig

SMALL_N = 5
PROXY_BASIS = {"primary_intent": "rule_proposal", "complexity_proxy": "rule_proxy"}


def margin_report(
    records: Sequence[Mapping[str, Any]],
    population: Mapping[str, Counter],
    cfg: GoldenConfig,
    derived_note: str | None = None,
) -> list[dict[str, Any]]:
    """One row per margin key and coverage constraint. Each shortfall gets a cause.
    ``derived_note`` names the cause of any difference in a derived dataset."""
    rows = []
    for margin in ("primary_intent", "cohort", *SOFT_MARGINS):
        achieved = Counter(r["stratum"][margin] for r in records)
        for key, quota in sorted(cfg.quotas(margin).items()):
            got = achieved[key]
            pop = population[margin][key]
            short = max(0, quota - got)
            rows.append(
                {
                    "margin": margin,
                    "key": key,
                    "population_n": pop,
                    "quota": quota,
                    "achieved": got,
                    "shortfall": short,
                    "basis": PROXY_BASIS.get(margin, "deterministic"),
                    "redistribution_note": derived_note
                    if derived_note and got != quota
                    else _note(quota, got, pop),
                }
            )
    for tag, spec in sorted(cfg.raw["coverage"].items()):
        got = sum(bool(r["stratum"]["tags"].get(tag)) for r in records)
        need = spec["minimum"]
        pop = population["coverage"][tag]
        rows.append(
            {
                "margin": "coverage",
                "key": tag,
                "population_n": pop,
                "quota": need,
                "achieved": got,
                "shortfall": max(0, need - got),
                "basis": "rule_proposal",
                "redistribution_note": _note(need, got, pop)
                if got < need
                else "minimum met",
            }
        )
    return rows


def _note(quota: int, got: int, population: int) -> str | None:
    if got == quota:
        return None
    if got > quota:
        return "above quota: absorbed units other margins could not place"
    if population < quota:
        return f"supply: only {population} eligible distinct requests"
    return "compromise: joint constraints across margins; supply was sufficient"


def mandatory_checks(
    records: Sequence[Mapping[str, Any]], cfg: GoldenConfig
) -> list[dict[str, Any]]:
    """Hard minimums and caps of the design; ``unmet`` is a reported failure."""
    raw = cfg.raw
    mins, caps = raw["minimums"], raw["caps"]
    count = Counter()
    bots = Counter()
    for r in records:
        s = r["stratum"]
        for margin in (
            "primary_intent",
            "complexity_proxy",
            "language_group",
            "position",
        ):
            count[margin, s[margin]] += 1
        count["bot_class", s["bot_class"]] += 1
        count["cohort", s["cohort"]] += 1
        bots[r["bot_id"]] += 1
    out = []

    def check(key, value, target, sense=">=", note=""):
        met = value >= target if sense == ">=" else value <= target
        out.append(
            {
                "key": key,
                "value": value,
                "target": f"{sense} {target}",
                "met": met,
                "note": note,
            }
        )

    exempt = set(mins["primary_intent_floor_exempt"])
    for key in cfg.quotas("primary_intent"):
        if key not in exempt:
            check(
                f"intent_floor:{key}",
                count["primary_intent", key],
                mins["primary_intent_floor"],
            )
    for key in cfg.quotas("complexity_proxy"):
        check(
            f"complexity_proxy_min:{key}",
            count["complexity_proxy", key],
            mins["complexity_proxy"],
            note="proxy; reviewed labels decide",
        )
    check("english_min", count["language_group", "english"], mins["english"])
    check("mixed_min", count["language_group", "mixed"], mins["mixed"])
    check("first_turn_min", count["position", "first"], mins["first_turn"])
    check(
        "instruction_rag_with_retrieval_min",
        sum(
            r["stratum"]["bot_class"] == "instruction_rag"
            and r["rag_observed_on_answer"]
            for r in records
        ),
        mins["instruction_rag_with_retrieval"],
    )
    check(
        "workflow_unknown_config_min",
        count["bot_class", "workflow_unknown_config"],
        mins["workflow_unknown_config"],
    )
    check("distinct_bots_min", len(bots), mins["distinct_bots"])
    remaining = raw["cohorts"]["remaining"]
    for key in cfg.quotas("cohort"):
        if key != remaining:
            check(
                f"cohort_cap:{key}",
                count["cohort", key],
                caps["single_account_cohort_max"],
                "<=",
            )
    for tag, spec in sorted(raw["coverage"].items()):
        if spec["mandatory"]:
            check(
                f"coverage:{tag}",
                sum(bool(r["stratum"]["tags"].get(tag)) for r in records),
                spec["minimum"],
            )
    return out


def cross_tab(
    records: Sequence[Mapping[str, Any]], row: str, col: str
) -> tuple[list[str], list[dict[str, Any]]]:
    """Counts of ``row`` × ``col`` (keys in the stratum), with a total column."""
    rows = sorted({str(r["stratum"][row]) for r in records})
    cols = sorted({str(r["stratum"][col]) for r in records})
    c = Counter((str(r["stratum"][row]), str(r["stratum"][col])) for r in records)
    out = [
        {row: a, **{b: c[a, b] for b in cols}, "total": sum(c[a, b] for b in cols)}
        for a in rows
    ]
    return [row, *cols, "total"], out


def context_dependency(tags: Mapping[str, Any]) -> str:
    """Rule proposal of the context-dependency label for cross-tabs."""
    active = [
        name
        for name, tag in (
            ("instruction", "instruction_dependent"),
            ("rag", "rag_dependent"),
            ("distant_history", "history_distant"),
            ("recent_history", "history_recent"),
        )
        if tags.get(tag)
    ]
    if not active:
        return "self_contained"
    return active[0] if len(active) == 1 else "multiple"


def markdown_table(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> str:
    head = "| " + " | ".join(columns) + " |\n|" + "---|" * len(columns) + "\n"
    body = "".join(
        "| " + " | ".join(str(r.get(c, "")) for c in columns) + " |\n" for r in rows
    )
    return head + body


def small_n_cells(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> int:
    return sum(
        1
        for r in rows
        for c in columns[1:-1]
        if isinstance(r.get(c), int) and 0 < r[c] < SMALL_N
    )
