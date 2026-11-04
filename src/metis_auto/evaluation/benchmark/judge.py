"""A real pairwise judge over a ``ModelClient`` (P-2; framework §4, E5).

``LlmPairwiseJudge`` implements E5's ``PairwiseJudge`` protocol
(``evaluation.judging.types``) unchanged: it shows the judge model the request
view and two answers in the given order and asks for **strict JSON**, exactly
``{"choice": "first" | "second" | "tie"}``. Strictness comes from the prompt
and the parser, not from the provider: Metis's OpenAI wrapper rejected
``response_format`` ``json_schema`` (HTTP 400, router live check 2026-11-03),
and JSON mode is not verified there, so neither is sent.

The parser refuses anything else (``JudgeOutputInvalid``): no guessing, no
keyword search in prose. The one tolerance is a single fenced block
(three backticks, optional ``json`` tag) around the object, which is unwrapped
deterministically. A provider error or a missing answer raises ``JudgeCallFailed``.
Each call's cost (from reported usage, priced by the injected function) and
latency are kept as content-free ``JudgeCallRecord``s: **evaluation cost**,
never request cost. The judge model is configuration (owner decision).

``judge_all`` runs E5's ``judge_items`` one pair at a time so a refused output
or a failed call becomes a ``not_evaluated`` outcome with its reason instead of
crashing the run; both answer orders, as E5 does. ``require_two_families``
checks the plan's "two judges from different families".
Calls: ports.ModelClient, evaluation.judging. Traces: FR-EVAL-05, ADR-0006,
ADR-0053. Status: provisional.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from metis_auto.contracts import (
    AttemptKind,
    CatalogueEntry,
    ComponentName,
    InputPart,
    ModelError,
    ModelInvocation,
    ModelNoAnswer,
    PartRole,
    TokenUsage,
)
from metis_auto.evaluation.judging.pairwise import JudgeRun, PairOutcome, judge_items
from metis_auto.evaluation.judging.types import (
    CHOICES,
    ContentProvider,
    JudgeRequestView,
    PairItem,
    PairwiseJudge,
    PairwiseVerdict,
)
from metis_auto.ports import Clock, ModelClient

PROMPT_VERSION = "pairwise-v1"

_INSTRUCTIONS = {
    "en": (
        "You compare two answers to the same request. The request may include "
        "the assistant's instructions, earlier turns and retrieved context. "
        "Judge which answer serves the user better: correct, follows the "
        "instructions and the context, answers in the user's language, and is "
        "complete without padding. Length alone is not quality. The order of "
        "the answers carries no information.\n"
        'Reply with exactly one JSON object and nothing else: {"choice": '
        '"first"} if the first answer is better, {"choice": "second"} if the '
        'second is better, or {"choice": "tie"} if they are equally good.'
    ),
    "fa": (
        "شما دو پاسخ به یک درخواست را مقایسه می‌کنید. درخواست ممکن است شامل "
        "دستورالعمل‌های دستیار، پیام‌های قبلی و متن بازیابی‌شده باشد. داوری کنید "
        "کدام پاسخ برای کاربر بهتر است: درست باشد، از دستورالعمل‌ها و متن پیروی "
        "کند، به زبان کاربر باشد و بدون حشو کامل باشد. طولانی‌تر بودن به‌تنهایی "
        "بهتر بودن نیست. ترتیب پاسخ‌ها هیچ اطلاعاتی ندارد.\n"
        "فقط یک شیء JSON و هیچ چیز دیگری بنویسید: "
        '{"choice": "first"} اگر پاسخ اول بهتر است، '
        '{"choice": "second"} اگر پاسخ دوم بهتر است، یا '
        '{"choice": "tie"} اگر هر دو به یک اندازه خوب‌اند.'
    ),
}

_FENCE = re.compile(r"\A```(?:json)?[ \t]*\n(?P<body>.*?)\n?```\Z", re.DOTALL)


class JudgeOutputInvalid(Exception):
    """The judge's reply is not the required JSON object; never guessed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class JudgeCallFailed(Exception):
    """The judge call returned an error or no answer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_choice(text: str | None) -> str:
    """``first``, ``second`` or ``tie``; raises ``JudgeOutputInvalid``."""
    if text is None or not text.strip():
        raise JudgeOutputInvalid("empty_output")
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group("body").strip()
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        raise JudgeOutputInvalid("not_json") from None
    if not isinstance(value, dict):
        raise JudgeOutputInvalid("not_an_object")
    if set(value) != {"choice"}:
        raise JudgeOutputInvalid("unexpected_keys")
    choice = value["choice"]
    if choice not in CHOICES:
        raise JudgeOutputInvalid("invalid_choice")
    return choice


def render_request(view: JudgeRequestView) -> str:
    """The request view as the judge sees it (transient; never stored)."""
    blocks = []
    if view.instructions:
        blocks.append(f"[Assistant instructions]\n{view.instructions}")
    if view.history:
        blocks.append("[Earlier turns]\n" + "\n---\n".join(view.history))
    if view.retrieved:
        blocks.append(f"[Retrieved context]\n{view.retrieved}")
    blocks.append(f"[User message]\n{view.message}")
    return "\n\n".join(blocks)


@dataclass(frozen=True)
class JudgeCallRecord:
    """Content-free record of one judge call (evaluation cost)."""

    judge_id: str
    model_id: str
    outcome: str
    """``verdict``, ``invalid_output:<reason>`` or ``failed:<reason>``."""
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    cost_kind: str = "evaluation"


class LlmPairwiseJudge:
    """E5 ``PairwiseJudge`` over a chat model."""

    def __init__(
        self,
        client: ModelClient,
        *,
        model_id: str,
        instruction_language: str,
        max_output_tokens: int,
        price: Callable[[TokenUsage | None], Decimal | None],
        clock: Clock,
        run_id: str,
    ) -> None:
        if instruction_language not in _INSTRUCTIONS:
            raise ValueError("instruction_language must be 'en' or 'fa'")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")
        self._client = client
        self._model = model_id
        self._lang = instruction_language
        self._max = max_output_tokens
        self._price = price
        self._clock = clock
        self._run_id = run_id
        self._n = 0
        self.records: list[JudgeCallRecord] = []

    @property
    def judge_id(self) -> str:
        return f"llm-pairwise:{self._model}@{PROMPT_VERSION}-{self._lang}"

    @property
    def instruction_language(self) -> str:
        return self._lang

    @property
    def supports_images(self) -> bool:
        return False

    def invocation(
        self, view: JudgeRequestView, first: str, second: str
    ) -> ModelInvocation:
        self._n += 1
        user = (
            f"{render_request(view)}\n\n[First answer]\n{first}\n\n"
            f"[Second answer]\n{second}"
        )
        return ModelInvocation(
            request_id=f"{self._run_id}.judge.{self._n}",
            attempt_id=f"{self._run_id}.judge.{self._n}.a0",
            attempt_kind=AttemptKind.PRIMARY,
            model_id=self._model,
            parts=(
                InputPart(
                    role=PartRole.INSTRUCTIONS,
                    text=_INSTRUCTIONS[self._lang],
                    component=ComponentName.INSTRUCTIONS,
                ),
                InputPart(
                    role=PartRole.USER, text=user, component=ComponentName.MESSAGE
                ),
            ),
            max_output_tokens=self._max,
        )

    def compare(
        self, view: JudgeRequestView, first: str, second: str
    ) -> PairwiseVerdict:
        invocation = self.invocation(view, first, second)
        started = self._clock.monotonic_ms()
        result = self._client.invoke(invocation)
        latency = self._clock.monotonic_ms() - started
        if isinstance(result, ModelError | ModelNoAnswer):
            reason = (
                f"error:{result.error_class.value}"
                if isinstance(result, ModelError)
                else f"no_answer:{result.reason.value}"
            )
            self._log(f"failed:{reason}", latency, None, None)
            raise JudgeCallFailed(reason)
        cost = self._price(result.usage)
        try:
            choice = parse_choice(result.text)
        except JudgeOutputInvalid as exc:
            self._log(f"invalid_output:{exc.reason}", latency, result.usage, cost)
            raise
        self._log("verdict", latency, result.usage, cost)
        return PairwiseVerdict(choice=choice, cost_usd=cost)

    def _log(
        self,
        outcome: str,
        latency: float,
        usage: TokenUsage | None,
        cost: Decimal | None,
    ) -> None:
        self.records.append(
            JudgeCallRecord(
                judge_id=self.judge_id,
                model_id=self._model,
                outcome=outcome,
                latency_ms=round(latency, 1),
                input_tokens=usage.input.tokens if usage else None,
                output_tokens=usage.output.tokens if usage and usage.output else None,
                cost_usd=cost,
            )
        )


def require_two_families(
    judges: Sequence[str], catalogue: Mapping[str, CatalogueEntry]
) -> None:
    """Plan P-2: exactly two judges, from different provider families."""
    if len(judges) != 2 or len(set(judges)) != 2:
        raise ValueError("two different judge models are required")
    families = []
    for model in judges:
        entry = catalogue.get(model)
        if entry is None:
            raise ValueError(f"judge model {model!r} is not in the catalogue")
        families.append(entry.provider)
    if families[0] == families[1]:
        raise ValueError(
            f"judges must come from different families (both are {families[0]!r})"
        )


def judge_all(
    judge: PairwiseJudge,
    items: Sequence[PairItem],
    content: ContentProvider,
    *,
    vision_candidates: frozenset[str] | None,
) -> JudgeRun:
    """E5 ``judge_items`` per pair; a refused output or failed call becomes
    ``not_evaluated`` with ``judge_output_invalid:<reason>`` or
    ``judge_call_failed:<reason>``. Costs of failed pairs are not lost: they
    stay in the judge's ``records``. An interrupt (SIGINT) abandons the pair in
    flight and returns the pairs finished so far; the rest are simply absent."""
    outcomes: list[PairOutcome] = []
    total = Decimal(0)
    for item in items:
        try:
            run = judge_items(
                judge, [item], content, vision_candidates=vision_candidates
            )
        except JudgeOutputInvalid as exc:
            outcomes.append(_failed(item, f"judge_output_invalid:{exc.reason}"))
            continue
        except JudgeCallFailed as exc:
            outcomes.append(_failed(item, f"judge_call_failed:{exc.reason}"))
            continue
        except KeyboardInterrupt:
            break  # stop here: the pairs finished so far are kept and written
        outcomes.extend(run.outcomes)
        total += run.cost_usd_total
    excluded = Counter(o.reason for o in outcomes if o.state != "judged" and o.reason)
    return JudgeRun(
        judge_id=judge.judge_id,
        instruction_language=judge.instruction_language,
        outcomes=tuple(outcomes),
        cost_usd_total=total,
        cost_kind="evaluation",
        excluded_by_reason=dict(excluded),
    )


def _failed(item: PairItem, reason: str) -> PairOutcome:
    return PairOutcome(
        item,
        "not_evaluated",
        reason,
        None,
        None,
        None,
        None,
        0,
        None,
        None,
        None,
        None,
    )


def view_from_parts(parts: Sequence[InputPart]) -> JudgeRequestView:
    """The judge's view of a request built by golden answers' ``build_request``:
    the target message, the instructions, the earlier turns and the retrieved
    context, in their order."""
    message = [p.text for p in parts if p.component == ComponentName.MESSAGE]
    if len(message) != 1:
        raise ValueError("a request needs exactly one target message part")
    instructions = [p.text for p in parts if p.role == PartRole.INSTRUCTIONS]
    history = tuple(
        f"{p.role.value}: {p.text}"
        for p in parts
        if p.component == ComponentName.HISTORY
    )
    retrieved = [p.text for p in parts if p.role == PartRole.RETRIEVED]
    return JudgeRequestView(
        message=message[0],
        instructions="\n\n".join(instructions) or None,
        history=history,
        retrieved="\n\n".join(retrieved) or None,
    )
