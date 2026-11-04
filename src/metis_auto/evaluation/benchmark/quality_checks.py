"""Cut-first item (d): the inputs and the estimate of the two paid quality
checks, with **no call** (sprint close; sprint_decisions "Quality evaluation
plan").

- *Answer-cache hit judging* (decides "answer error <= 1% over about 300
  reviewed hits"): each hit pairs the stored answer against the hit's own logged
  answer, judged by two judges in both orders. No new answer is generated.
- *Context ablation* (decides "loss - win within noise + 3 points"): per record,
  one answer from the original context and one per context version, from the
  same arm, then judged pairwise (version against original).

``build_*_items`` make the E5 ``PairItem``s (and for the ablation the E4
``PlannedCall``s); ``MappingContent`` serves transient text from injected
mappings; ``*_plan`` counts calls and, only when the caller supplies counted
input sizes, bounds the cost with the same E4/P-2 arithmetic as the benchmark.
``readiness_reasons`` is the Gap 1 gate: every unset owner value and the Metis
written answer (O-1) each refuse. Nothing here calls a model or reads a
database. Pure. Traces: H-1, H-3, FR-EVAL-04, FR-EVAL-06, QA-COST, ADR-0053.
Status: provisional; never run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from metis_auto.contracts import CatalogueEntry, PriceTable
from metis_auto.evaluation.judging.types import JudgeRequestView, PairItem, Variant
from metis_auto.evaluation.sampling.runner import PlannedCall

from .config import BenchmarkConfig
from .plan import JUDGE_ORDERS, estimate_gaps, generation_estimate, judge_estimate

STORED: Variant = ("cache-stored", None)
LOGGED: Variant = ("hit-logged", None)
ORIGINAL = "original"


class QualityCheckRefused(Exception):
    """A paid quality check that may not start; lists every reason."""

    def __init__(self, reasons: Sequence[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = tuple(reasons)


def readiness_reasons(config: BenchmarkConfig) -> list[str]:
    """The same gates as the P-1 benchmark: owner values and the O-1 answer."""
    reasons = [f"set by owner: {k}" for k in estimate_gaps(config)]
    if not config.gates.metis_allows_samples:
        reasons.append(
            "gate missing: Metis has not answered in writing that samples may be "
            "sent to model APIs (O-1); gates.metis_allows_samples is false"
        )
    return reasons


def build_hit_items(hits: Sequence[tuple[str, str, str]]) -> list[PairItem]:
    """``hits``: (hit_id, session_ref, language). Candidate = the stored answer,
    reference = the hit's own logged answer."""
    _unique([h[0] for h in hits], "hit_id")
    return [PairItem(hit, session, lang, STORED, LOGGED) for hit, session, lang in hits]


def ablation_case_id(record_id: str, version: str) -> str:
    return f"{record_id}#{version}"


def build_ablation_items(
    records: Sequence[tuple[str, str, str]], versions: Sequence[str], arm: str
) -> tuple[list[PairItem], list[PlannedCall]]:
    """``records``: (record_id, session_ref, language). Returns the pairs
    (version answer against original answer, same arm) and the generation
    calls (original once per record, each version once)."""
    if not arm.strip():
        raise ValueError("an answering arm is required")
    if not versions or ORIGINAL in versions:
        raise ValueError("versions must be non-empty and must not include 'original'")
    _unique(list(versions), "version")
    _unique([r[0] for r in records], "record_id")
    items, calls = [], []
    for record, session, lang in records:
        calls.append(PlannedCall(record, session, arm, None, 0))
        for version in versions:
            case = ablation_case_id(record, version)
            calls.append(PlannedCall(case, session, arm, None, 0))
            items.append(
                PairItem(
                    record,
                    session,
                    lang,
                    (f"{arm}+{version}", None),
                    (f"{arm}+{ORIGINAL}", None),
                )
            )
    return items, calls


class MappingContent:
    """E5 ``ContentProvider`` over injected, in-memory text (transient)."""

    def __init__(
        self,
        requests: Mapping[str, JudgeRequestView],
        answers: Mapping[tuple[str, Variant], str],
    ) -> None:
        self._requests = requests
        self._answers = answers

    def request(self, case_id: str) -> JudgeRequestView:
        return self._requests[case_id]

    def answer(self, case_id: str, variant: Variant) -> str | None:
        return self._answers.get((case_id, variant))


def hit_judging_plan(
    config: BenchmarkConfig,
    items: Sequence[PairItem],
    *,
    judge_input_tokens: Mapping[tuple[str, str], int] | None,
    catalogue: Mapping[str, CatalogueEntry],
    prices: PriceTable,
    candidate_max_tokens: int | None = None,
) -> dict[str, object]:
    """Calls and cost bounds of hit judging; no answer is generated."""
    ids = [i.case_id for i in items]
    judging = judge_estimate(
        ids,
        [STORED[0]],
        judges=config.judges.models,
        judge_input_tokens=judge_input_tokens,
        candidate_max_tokens=candidate_max_tokens,
        judge_max_output=config.judges.max_output_tokens,
        catalogue=catalogue,
        prices=prices,
    )
    return {
        "check": "answer_cache_hit_judging",
        "hits": len(items),
        "generation_calls": 0,
        "judge_calls": len(items) * 2 * JUDGE_ORDERS,
        "judging": judging,
        "makes_calls": False,
    }


def ablation_plan(
    config: BenchmarkConfig,
    items: Sequence[PairItem],
    calls: Sequence[PlannedCall],
    *,
    input_tokens: Mapping[tuple[str, str], int],
    judge_input_tokens: Mapping[tuple[str, str], int] | None,
    catalogue: Mapping[str, CatalogueEntry],
    prices: PriceTable,
) -> dict[str, object]:
    """Calls and cost bounds of the context ablation (generation + judging)."""
    arm = calls[0].model_id if calls else ""
    generation = generation_estimate(
        [c.case_id for c in calls],
        [arm],
        input_tokens=input_tokens,
        catalogue=catalogue,
        prices=prices,
        max_output_tokens=config.run.max_output_tokens,
    )
    judging = judge_estimate(
        [i.case_id + "|" + i.candidate[0] for i in items],
        [arm],
        judges=config.judges.models,
        judge_input_tokens=judge_input_tokens,
        candidate_max_tokens=config.run.max_output_tokens,
        judge_max_output=config.judges.max_output_tokens,
        catalogue=catalogue,
        prices=prices,
    )
    return {
        "check": "context_ablation",
        "records": len({i.case_id for i in items}),
        "versions": sorted({i.candidate[0] for i in items}),
        "generation_calls": len(calls),
        "judge_calls": len(items) * 2 * JUDGE_ORDERS,
        "generation": generation,
        "judging": judging,
        "makes_calls": False,
    }


def count_preview(*, kind: str, n: int, versions: int = 0) -> dict[str, object]:
    """Call counts only (no sizes, no cost), for the refusal message."""
    if kind == "cache_hit":
        return {"hits": n, "generation_calls": 0, "judge_calls": n * 2 * JUDGE_ORDERS}
    return {
        "records": n,
        "versions": versions,
        "generation_calls": n * (1 + versions),
        "judge_calls": n * versions * 2 * JUDGE_ORDERS,
    }


def refuse_unless_ready(config: BenchmarkConfig, *, preview: Mapping[str, object]):
    reasons = readiness_reasons(config)
    if reasons:
        raise QualityCheckRefused([*reasons, f"preview (counts only): {dict(preview)}"])


def _unique(values: Sequence[str], what: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{what}s must be unique")


__all__ = [
    "LOGGED",
    "ORIGINAL",
    "STORED",
    "MappingContent",
    "QualityCheckRefused",
    "ablation_case_id",
    "ablation_plan",
    "build_ablation_items",
    "build_hit_items",
    "count_preview",
    "hit_judging_plan",
    "readiness_reasons",
    "refuse_unless_ready",
]
