"""Cache-candidate harness (CMP-23 support; caching.md §4, ADR-0007,
ADR-0011, ADR-0012; docs/experiments/caching_plan.md stage C1).

Responsibility: replay cases once, in the run's order, and evaluate **every
key variant and every scope in one pass**, outside the serving path. For each
case and variant it decides eligibility, asks the variant's
``CandidateIndex`` for an earlier matching case (session scope: same session
only; global scope: any earlier case), emits one ``cache_lookup`` event per
scope, and stores the case when it has a logged answer to serve. Matches are
**candidate hits**, not safe hits: nothing checks the answer would have been
right (hit correctness is unmeasured until a judge or agreement metric runs).

Key variants (``KeyVariantSpec``): a base composition × a message treatment
(``literal`` / ``whitespace`` / ``nfkc_casefold_ws``) × an unknown treatment
(``strict``: unknown never matches, P-6; ``wildcard``: measurement only).
Eligibility, per variant: attachments present → ``attachments`` (A-19); in
strict mode, a variant component (or the logged model) that is unknown →
``unknown_component``. Attachments unknown are ``unknown_component`` in strict
mode and allowed in wildcard mode (an upper bound). The time-sensitivity
check is a no-op reported as not evaluated (TODO-07).

The logged model label stands in for the target group (``full`` variant):
replay serves what the logged model answered. Scopes: ``session``; ``global``
(any earlier case). The sample has no user reference, so same-user and
cross-user scopes are **unmeasured**; "cross-session" = a global hit with no
same-session match (an upper bound mixing same-user and cross-user reuse).

Also (investigation signals, not metrics, never exported per case):
lexical repeat groups per message treatment, and how many candidate hits
had an identical logged answer (NFKC + casefold + whitespace) to the matched
case's, a crude lexical signal that is **not** hit correctness.

Called by: evaluation.runner. Calls: application.measurement (fingerprints),
application.events (recorder), domain.caching (normalisation).
Privacy: requests and answers stay in memory; events hold fingerprints and
codes only; signal digests are unkeyed sha256 in memory, never written.
Status: implemented (Stage 8).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from metis_auto.application.events import EventRecorder
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.contracts import (
    CacheKeyDraft,
    CacheLookupResult,
    CacheScope,
    CacheTier,
    ComponentName,
    ComponentState,
    IneligibleReason,
    KeyComponent,
    LookupOutcome,
    ReplayCase,
    ScopeKind,
)
from metis_auto.contracts.events import CacheLookedUp
from metis_auto.domain.caching import TREATMENTS, normalise

from .index import CandidateIndex, CandidateItem, IndexFactory

KEY_SCHEMA = "ks-1"
NOT_EVALUATED = ("time_sensitivity",)
SCOPES = (ScopeKind.SESSION, ScopeKind.GLOBAL)
SHORT = {"literal": "lit", "whitespace": "ws", "nfkc_casefold_ws": "nfkc"}

BASES: dict[str, tuple[tuple[ComponentName, ...], bool]] = {
    "msg_only": ((ComponentName.MESSAGE,), False),
    "msg_instr": ((ComponentName.MESSAGE, ComponentName.INSTRUCTIONS), False),
    "msg_instr_ctx": (
        (
            ComponentName.MESSAGE,
            ComponentName.INSTRUCTIONS,
            ComponentName.RETRIEVED,
            ComponentName.STRUCTURED_INPUT,
        ),
        False,
    ),
    "full_no_model": (
        (
            ComponentName.MESSAGE,
            ComponentName.INSTRUCTIONS,
            ComponentName.HISTORY,
            ComponentName.RETRIEVED,
            ComponentName.STRUCTURED_INPUT,
        ),
        False,
    ),
    "full": (
        (
            ComponentName.MESSAGE,
            ComponentName.INSTRUCTIONS,
            ComponentName.HISTORY,
            ComponentName.RETRIEVED,
            ComponentName.STRUCTURED_INPUT,
        ),
        True,
    ),
}
"""Base compositions, narrowest first. ``full`` is the serving composition
(caching.md §1) with the logged model in place of the target group."""
_LABEL = re.compile(r"^[a-z0-9][a-z0-9_.:\-]*$")


@dataclass(frozen=True)
class KeyVariantSpec:
    base: str
    message_treatment: str
    unknown_mode: Literal["strict", "wildcard"]

    @property
    def components(self) -> tuple[ComponentName, ...]:
        return BASES[self.base][0]

    @property
    def include_model(self) -> bool:
        return BASES[self.base][1]

    @property
    def name(self) -> str:
        return f"{self.base}.{SHORT[self.message_treatment]}.{self.unknown_mode}"


def variants(params: Mapping[str, Any]) -> tuple[KeyVariantSpec, ...]:
    """Every combination named by the strategy parameters (default: all)."""
    bases = params.get("bases", list(BASES))
    treatments = params.get("message_treatments", list(TREATMENTS))
    modes = params.get("unknown_modes", ["strict", "wildcard"])
    for b in bases:
        if b not in BASES:
            raise ValueError(f"unknown base composition {b!r}; known: {list(BASES)}")
    for t in treatments:
        if t not in TREATMENTS:
            raise ValueError(f"unknown treatment {t!r}; known: {TREATMENTS}")
    for m in modes:
        if m not in ("strict", "wildcard"):
            raise ValueError("unknown_modes are strict and wildcard")
    return tuple(
        KeyVariantSpec(b, t, m) for b in bases for t in treatments for m in modes
    )


@dataclass(frozen=True)
class CandidateRun:
    """What the harness hands back besides the events: content-free counts."""

    variants: tuple[str, ...]
    repeats: dict[str, dict[str, int]]
    lexical_answer_match: dict[str, dict[str, int]]


def order_cases(cases: Sequence[ReplayCase], ordering: str) -> list[ReplayCase]:
    """``logged_time``: naive logged time, ties by session and turn; cases
    without a time last (A-31). ``session_order``: as given."""
    if ordering == "session_order":
        return list(cases)
    return sorted(
        cases,
        key=lambda c: (
            c.logged_timestamp is None,
            c.logged_timestamp or datetime.min,
            c.session_ref,
            c.turn_index,
        ),
    )


def _answer_digest(case: ReplayCase) -> str | None:
    if not case.references:
        return None
    text = normalise(case.references[0].text, "nfkc_casefold_ws")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CandidateHarness:
    def __init__(
        self,
        fingerprinter: Fingerprinter,
        measurement: MeasurementService,
        recorder: EventRecorder,
        index_factory: IndexFactory,
        params: Mapping[str, Any] | None = None,
    ) -> None:
        self._fp = fingerprinter
        self._measure = measurement
        self._recorder = recorder
        self._factory = index_factory
        self._params = dict(params or {})
        self._variants = variants(self._params)

    @property
    def variant_names(self) -> tuple[str, ...]:
        return tuple(v.name for v in self._variants)

    def run(self, cases: Iterable[ReplayCase]) -> CandidateRun:
        ordered = list(cases)
        indexes: dict[str, CandidateIndex] = {
            v.name: self._factory(v, self._params) for v in self._variants
        }
        digests = {c.case_id: _answer_digest(c) for c in ordered}
        lexical: dict[str, Counter[str]] = defaultdict(Counter)
        for case in ordered:
            base = self._base_components(case)
            for v in self._variants:
                self._one(case, v, base, indexes[v.name], digests, lexical[v.name])
        return CandidateRun(
            variants=self.variant_names,
            repeats=self._repeats(ordered),
            lexical_answer_match={k: dict(c) for k, c in lexical.items()},
        )

    # --- per case ---------------------------------------------------------

    def _base_components(self, case: ReplayCase) -> dict[ComponentName, KeyComponent]:
        measured = {
            m.component: m for m in self._measure.measure(case.request).components
        }
        return {
            name: KeyComponent(
                component=name,
                state=m.state,
                fingerprint=m.fingerprint
                if m.state == ComponentState.PRESENT
                else None,
                treatment="full",
            )
            for name, m in measured.items()
            if name != ComponentName.ATTACHMENTS  # not a key component (A-19)
        }

    def _message(self, case: ReplayCase, treatment: str) -> KeyComponent:
        text = case.request.message
        if not text.strip():
            return KeyComponent(
                component=ComponentName.MESSAGE,
                state=ComponentState.ABSENT,
                treatment=treatment,
            )
        return KeyComponent(
            component=ComponentName.MESSAGE,
            state=ComponentState.PRESENT,
            fingerprint=self._fp.fingerprint("message", normalise(text, treatment)),
            treatment=treatment,
        )

    @staticmethod
    def _model(case: ReplayCase) -> tuple[ComponentState, str | None]:
        if not case.references:
            return (ComponentState.UNKNOWN, None)
        label = case.references[0].model_label
        if label.state != ComponentState.PRESENT:
            return (ComponentState.UNKNOWN, None)
        return (ComponentState.PRESENT, label.value)

    def _eligibility(
        self,
        case: ReplayCase,
        v: KeyVariantSpec,
        components: tuple[KeyComponent, ...],
        model: tuple[ComponentState, str | None],
    ) -> IneligibleReason | None:
        attachments = case.request.attachments.state
        if attachments == ComponentState.PRESENT:
            return IneligibleReason.ATTACHMENTS
        if v.unknown_mode == "wildcard":
            return None
        unknown = attachments == ComponentState.UNKNOWN or any(
            c.state == ComponentState.UNKNOWN for c in components
        )
        if unknown or (v.include_model and model[0] == ComponentState.UNKNOWN):
            return IneligibleReason.UNKNOWN_COMPONENT
        return None

    def _seal(
        self,
        v: KeyVariantSpec,
        components: tuple[KeyComponent, ...],
        model: tuple[ComponentState, str | None],
    ) -> str:
        group = None
        if v.include_model and model[1] is not None:
            label = model[1]
            group = (
                label
                if _LABEL.fullmatch(label)
                else "label-" + self._fp.fingerprint("model_label", label)[4:20]
            )
        draft = CacheKeyDraft(
            key_schema_version=KEY_SCHEMA,
            variant=v.name,
            serving_allowed=False,
            components=components,
            target_group=group,
            scope=CacheScope(kind=ScopeKind.GLOBAL),
        )
        return self._fp.seal(draft).key

    def _one(
        self,
        case: ReplayCase,
        v: KeyVariantSpec,
        base: dict[ComponentName, KeyComponent],
        index: CandidateIndex,
        digests: Mapping[str, str | None],
        lexical: Counter[str],
    ) -> None:
        components = tuple(
            self._message(case, v.message_treatment)
            if name == ComponentName.MESSAGE
            else base[name]
            for name in v.components
        )
        model = self._model(case) if v.include_model else (ComponentState.ABSENT, None)
        reason = self._eligibility(case, v, components, model)
        key = None
        if reason is None and v.unknown_mode == "strict":
            key = self._seal(v, components, model)
        item = CandidateItem(
            case_id=case.case_id,
            session_ref=case.session_ref,
            components=components,
            model=model,
            key=key,
            request=case.request,
        )
        for scope in SCOPES:
            if reason is not None:
                result = CacheLookupResult(
                    tier=CacheTier.EXACT,
                    outcome=LookupOutcome.INELIGIBLE,
                    ineligible_reason=reason,
                    key_variant=v.name,
                    scope=scope,
                    not_evaluated=NOT_EVALUATED,
                )
            else:
                ref = case.session_ref if scope == ScopeKind.SESSION else None
                match = index.lookup(item, session_ref=ref)
                result = CacheLookupResult(
                    tier=CacheTier.EXACT,
                    outcome=LookupOutcome.HIT if match else LookupOutcome.MISS,
                    key_variant=v.name,
                    key=key,
                    scope=scope,
                    entry_id=f"entry:{match}" if match else None,
                    not_evaluated=NOT_EVALUATED,
                )
                if match:
                    same = digests.get(case.case_id) is not None and digests.get(
                        case.case_id
                    ) == digests.get(match)
                    lexical[f"{scope.value}_hits"] += 1
                    lexical[f"{scope.value}_identical_answer"] += int(same)
            self._recorder.emit(
                CacheLookedUp(result=result),
                request_id=f"req:{case.case_id}",
                session_ref=case.session_ref,
                case_id=case.case_id,
                logged_timestamp=case.logged_timestamp,
            )
        if reason is None and case.references:
            index.add(item)

    # --- lexical repeats ----------------------------------------------------

    def _repeats(self, cases: Sequence[ReplayCase]) -> dict[str, dict[str, int]]:
        """Groups of identical messages per treatment (content-free counts)."""
        out: dict[str, dict[str, int]] = {}
        for t in TREATMENTS:
            groups: dict[str, set[tuple[str, str]]] = defaultdict(set)
            for c in cases:
                if c.request.message.strip():
                    fp = self._fp.fingerprint(
                        "message", normalise(c.request.message, t)
                    )
                    groups[fp].add((c.session_ref, c.case_id))
            repeated = [g for g in groups.values() if len(g) > 1]
            out[t] = {
                "messages": sum(len(g) for g in groups.values()),
                "repeat_groups": len(repeated),
                "messages_in_repeat_groups": sum(len(g) for g in repeated),
                "groups_crossing_sessions": sum(
                    1 for g in repeated if len({s for s, _ in g}) > 1
                ),
                "largest_group": max((len(g) for g in groups.values()), default=0),
            }
        return out
