"""``sticky`` routing policy: sticky routing v1 (owner brief §7; routing
plan §5, R8), with a ``per_request`` mode (R1, no stickiness).

Responsibility, mode ``sticky_v1``:
- a greeting or small talk (configured phrase list) never anchors: in an
  **unanchored** session it goes to the **cheapest** eligible model; in an
  **anchored** session it **stays on the anchor** (owner decision Q-41,
  2026-10-19: keeps the provider's prefix cache warm, and a greeting costs
  almost nothing on any model);
- the session's anchor is reconstructed from the request alone (stateless,
  P-8): each earlier user turn, with the producer of the turn that answered it
  (``Turn.producer``, A-64). Turns answered from cache, greetings, and turns
  with an unknown producer never anchor. The first substantive turn anchors
  on its producer. A later turn that is **very different** from the anchoring
  turn re-anchors on its producer. A producer in a **higher tier** than the
  anchor (an escalation) raises the anchor: only up, never down;
- no anchor yet → initial routing by the rules (``rule_based``), and this
  message anchors the session;
- anchored and similar → stay on the anchor (if still eligible);
- anchored and very different → re-route by the rules (and re-anchor).
"Very different" uses cheap feature changes only: code appears or
disappears, a coding intent appears (a request for code with no code in it;
A-71: only appearing counts, so a follow-up without the intent stays), an
attachment appears, the language switches, or the length bucket jumps by at
least ``length_bucket_jump``.
Escalation itself happens in the attempt loop (ADR-0013) along the chain
that the rules give (the cheapest model of each higher tier); the next
request sees the stronger producer and stays on it.

Mode ``per_request``: the rules on every message, no anchor, no greeting rule.

**Inner router** (``inner``, ADR-XXXX (system-one-decision-router)): ``rule_based``
(default, unchanged) or ``decision_router``, which routes first and re-routed messages
and adds **hysteresis** on anchored, similar messages (stateless, P-8):
- the decision's tier is above the anchor's → re-route up now (``upgrade``);
- below it → stay when the message depends on the earlier conversation
  (``depends_on_history ≥ tau_hist``); go down only when the last
  ``downgrade_after_n`` user turns were all low-complexity by proxy (no code,
  no coding intent, short) and the model or gate decided the low tier
  (``downgrade``); otherwise stay (``stay.hysteresis``);
- a fallback decision (rules or safe tier after a failed or missing
  decision) never moves an anchored session.
Greetings never anchor (Q-41 unchanged).

Pure. Called by: domain.routing.policy.route (built by wiring).
Config: ``StickyConfig`` (placeholders, A-43 style).
Status: demo component (Demo milestone, ADR-0023); unpromoted strategy until
the routing-plan experiment (exp-route-010) gives evidence.
Known limit: earlier turns carry no attachments in ``Turn``, so "an
attachment appears" is judged on the current message only.
Traces: FR-ROUTE-01…03, H-5, routing_plan §5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import Field

from metis_auto.contracts import (
    CACHE_PRODUCER,
    CatalogueEntry,
    ComponentState,
    ContractModel,
    Language,
    ModelCatalogue,
    PolicyRef,
    PriceTable,
    RequestFeatures,
    TurnFeatures,
)

from .base import PolicyChoice
from .decision_policy import (
    DecisionRouterPolicy,
    HysteresisConfig,
    TierDecision,
    dependent_on_history,
)
from .rule_based import RuleBasedConfig, RuleBasedPolicy


class StickyMode(StrEnum):
    STICKY_V1 = "sticky_v1"
    PER_REQUEST = "per_request"


class StickyConfig(ContractModel):
    version: str = "0.1.0"
    mode: StickyMode = StickyMode.STICKY_V1
    length_bucket_jump: int = Field(default=2, ge=1)
    """A length-bucket change of at least this many buckets is a jump."""
    language_switch: bool = True
    """A change between determined languages (fa, en, mixed, other) counts."""
    inner: Literal["rule_based", "decision_router"] = "rule_based"
    """Router for first and re-routed messages
    (ADR-XXXX (system-one-decision-router))."""


@dataclass(frozen=True)
class _Profile:
    """The cheap features compared to decide "very different"."""

    language: Language
    has_code: bool | None
    length_bucket: int | None
    has_attachment: bool
    has_coding_intent: bool | None = None


@dataclass(frozen=True)
class Anchor:
    model_id: str
    profile: _Profile
    escalated: bool
    """The anchor was raised by an escalation."""


def _profile_of_turn(t: TurnFeatures) -> _Profile:
    # Earlier turns carry no attachments (Turn has none): never "appears".
    return _Profile(t.language, t.has_code, t.length_bucket, False, t.has_coding_intent)


def _profile_of_request(f: RequestFeatures) -> _Profile:
    return _Profile(
        f.language,
        f.has_code,
        f.length_bucket,
        bool(f.attachment_count or 0),
        f.has_coding_intent,
    )


_UNDETERMINED = {Language.UNDETERMINED}


def difference(current: _Profile, anchor: _Profile, config: StickyConfig) -> str | None:
    """Why ``current`` is very different from the anchoring turn, or None."""
    if current.has_code is not None and anchor.has_code is not None:
        if current.has_code and not anchor.has_code:
            return "code_appeared"
        if anchor.has_code and not current.has_code:
            return "code_disappeared"
    if (
        current.has_coding_intent
        and anchor.has_coding_intent is not None
        and not anchor.has_coding_intent
        and not anchor.has_code
    ):
        # Appearing only (A-71). An anchor with code already is code-related.
        return "coding_intent_appeared"
    if current.has_attachment and not anchor.has_attachment:
        return "attachment"
    if (
        config.language_switch
        and current.language not in _UNDETERMINED
        and anchor.language not in _UNDETERMINED
        and current.language != anchor.language
    ):
        return "language_switch"
    if (
        current.length_bucket is not None
        and anchor.length_bucket is not None
        and abs(current.length_bucket - anchor.length_bucket)
        >= config.length_bucket_jump
    ):
        return "length_jump"
    return None


def reconstruct_anchor(
    turns: tuple[TurnFeatures, ...],
    tiers: dict[str, int],
    config: StickyConfig,
) -> Anchor | None:
    """The session's anchor after ``turns`` (oldest first), from producers only.
    ``tiers`` maps catalogue model IDs to tiers; unknown producers are skipped."""
    anchor: Anchor | None = None
    for t in turns:
        if t.producer_state != ComponentState.PRESENT or t.producer is None:
            continue
        if t.producer == CACHE_PRODUCER or t.is_greeting or t.producer not in tiers:
            continue
        profile = _profile_of_turn(t)
        if anchor is None or difference(profile, anchor.profile, config) is not None:
            anchor = Anchor(t.producer, profile, escalated=False)
        elif tiers[t.producer] > tiers[anchor.model_id]:
            anchor = Anchor(t.producer, anchor.profile, escalated=True)
    return anchor


class StickyPolicy:
    def __init__(
        self,
        config: StickyConfig,
        rules: RuleBasedConfig,
        catalogue: ModelCatalogue,
        prices: PriceTable,
        decision_router: DecisionRouterPolicy | None = None,
    ) -> None:
        self._config = config
        self._rules = RuleBasedPolicy(rules, catalogue, prices)
        self._tiers = {e.model_id: e.tier for e in catalogue.entries}
        if config.inner == "decision_router" and decision_router is None:
            raise ValueError("sticky.inner = decision_router needs the policy")
        self._decision = decision_router if config.inner == "decision_router" else None
        self._inner: RuleBasedPolicy | DecisionRouterPolicy = (
            self._decision if self._decision is not None else self._rules
        )

    @property
    def ref(self) -> PolicyRef:
        inner = (
            f"+dr-{self._decision.config.version}" if self._decision is not None else ""
        )
        return PolicyRef(
            name="sticky",
            version=f"{self._config.version}+{self._config.mode.value}"
            f"+rules-{self._rules.config.version}{inner}",
        )

    def choose(
        self, features: RequestFeatures, eligible: tuple[CatalogueEntry, ...]
    ) -> PolicyChoice | None:
        if self._config.mode == StickyMode.PER_REQUEST:
            choice = self._inner.choose(features, eligible)
            return _prefixed(choice, "per_request")

        anchor = reconstruct_anchor(features.history_turns, self._tiers, self._config)
        if features.is_greeting:
            # Anchored (Q-41, owner 2026-10-19): stay on the anchor, which keeps
            # the provider's prefix cache warm; a greeting costs almost nothing
            # anywhere. Unanchored, or the anchor ineligible: the cheapest model.
            # Either way the greeting itself never anchors.
            target = (
                next((e for e in eligible if e.model_id == anchor.model_id), None)
                if anchor is not None
                else None
            )
            if target is not None:
                return PolicyChoice(
                    reason_code="sticky.greeting.stay",
                    model_id=target.model_id,
                    features_used=("is_greeting", "history_turns"),
                    chain=self._rules.chain_above(features, eligible, target.tier),
                    anchor_model_id=anchor.model_id,
                )
            cheapest = self._rules.cheapest(features, eligible)
            if cheapest is None:
                return None
            return PolicyChoice(
                reason_code="sticky.greeting",
                model_id=cheapest.model_id,
                features_used=("is_greeting", "known_input_tokens"),
                chain=self._rules.chain_above(features, eligible, cheapest.tier),
                anchor_model_id=anchor.model_id if anchor else None,
            )
        if anchor is None:
            choice = self._inner.choose(features, eligible)
            return _prefixed(choice, "sticky.first_substantive")

        anchor_id = anchor.model_id
        why = difference(_profile_of_request(features), anchor.profile, self._config)
        if why is not None:
            choice = self._inner.choose(features, eligible)
            return _prefixed(choice, f"sticky.reroute.{why}", anchor_id)

        target = next((e for e in eligible if e.model_id == anchor_id), None)
        if target is None:
            choice = self._inner.choose(features, eligible)
            return _prefixed(choice, "sticky.reroute.anchor_ineligible", anchor_id)
        if self._decision is not None:
            moved = self._hysteresis(features, eligible, target, anchor)
            if moved is not None:
                return moved
        return PolicyChoice(
            reason_code="sticky.stay.escalated" if anchor.escalated else "sticky.stay",
            model_id=target.model_id,
            features_used=(
                "history_turns",
                "language",
                "has_code",
                "has_coding_intent",
                "length_bucket",
                "attachment_count",
            ),
            chain=self._rules.chain_above(features, eligible, target.tier),
            anchor_model_id=anchor_id,
        )

    def _hysteresis(
        self,
        features: RequestFeatures,
        eligible: tuple[CatalogueEntry, ...],
        target: CatalogueEntry,
        anchor: Anchor,
    ) -> PolicyChoice | None:
        """A move away from the anchor, or None to stay on it (decision inner only)."""
        policy = self._decision
        assert policy is not None
        h = policy.config.hysteresis
        decided = policy.decide_tier(features)
        if decided.path.value not in _DECIDED_PATHS or decided.tier == target.tier:
            return None
        if decided.tier > target.tier:
            choice = policy.choose_for(
                features, eligible, decided, reason_prefix="sticky.upgrade"
            )
            if choice is None:
                return None
            return _with_summary(choice, "hysteresis.upgrade", decided, anchor.model_id)
        if dependent_on_history(decided.answers, h.tau_hist):
            return self._stay(features, eligible, target, anchor, "sticky.stay.history")
        recent = features.history_turns[-h.downgrade_after_n :]
        if len(recent) == h.downgrade_after_n and all(
            low_complexity_turn(t, h) for t in recent
        ):
            choice = policy.choose_for(
                features, eligible, decided, reason_prefix="sticky.downgrade"
            )
            if choice is None:
                return None
            return _with_summary(
                choice, "hysteresis.downgrade", decided, anchor.model_id
            )
        return self._stay(features, eligible, target, anchor, "sticky.stay.hysteresis")

    def _stay(
        self,
        features: RequestFeatures,
        eligible: tuple[CatalogueEntry, ...],
        target: CatalogueEntry,
        anchor: Anchor,
        reason: str,
    ) -> PolicyChoice:
        return PolicyChoice(
            reason_code=reason,
            model_id=target.model_id,
            features_used=("history_turns", "decision"),
            chain=self._rules.chain_above(features, eligible, target.tier),
            anchor_model_id=anchor.model_id,
        )


_DECIDED_PATHS = frozenset({"fast_rules", "fast_cache", "slow_local", "slow_hosted"})


def low_complexity_turn(t: TurnFeatures, h: HysteresisConfig) -> bool:
    """Proxy for an earlier turn (no answers are kept per turn): known and low."""
    return (
        t.has_code is False
        and not t.has_coding_intent
        and t.length_bucket is not None
        and t.length_bucket <= h.low_turn_max_length_bucket
    )


def _with_summary(
    choice: PolicyChoice, reason: str, decided: TierDecision, anchor: str
) -> PolicyChoice:
    summary = choice.router_summary
    if summary is not None:
        summary = summary.model_copy(
            update={"thresholds_fired": (*summary.thresholds_fired, reason)}
        )
    return PolicyChoice(
        reason_code=choice.reason_code,
        model_id=choice.model_id,
        tier=choice.tier,
        features_used=("history_turns", *choice.features_used),
        chain=choice.chain,
        anchor_model_id=anchor,
        router_summary=summary,
    )


def _prefixed(
    choice: PolicyChoice | None, prefix: str, anchor: str | None = None
) -> PolicyChoice | None:
    if choice is None:
        return None
    return PolicyChoice(
        reason_code=f"{prefix}.{choice.reason_code}",
        model_id=choice.model_id,
        tier=choice.tier,
        features_used=("history_turns", *choice.features_used)
        if prefix.startswith("sticky")
        else choice.features_used,
        chain=choice.chain,
        anchor_model_id=anchor,
    )
