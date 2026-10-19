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
    ) -> None:
        self._config = config
        self._rules = RuleBasedPolicy(rules, catalogue, prices)
        self._tiers = {e.model_id: e.tier for e in catalogue.entries}

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(
            name="sticky",
            version=f"{self._config.version}+{self._config.mode.value}"
            f"+rules-{self._rules.config.version}",
        )

    def choose(
        self, features: RequestFeatures, eligible: tuple[CatalogueEntry, ...]
    ) -> PolicyChoice | None:
        if self._config.mode == StickyMode.PER_REQUEST:
            choice = self._rules.choose(features, eligible)
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
            choice = self._rules.choose(features, eligible)
            return _prefixed(choice, "sticky.first_substantive")

        anchor_id = anchor.model_id
        why = difference(_profile_of_request(features), anchor.profile, self._config)
        if why is not None:
            choice = self._rules.choose(features, eligible)
            return _prefixed(choice, f"sticky.reroute.{why}", anchor_id)

        target = next((e for e in eligible if e.model_id == anchor_id), None)
        if target is None:
            choice = self._rules.choose(features, eligible)
            return _prefixed(choice, "sticky.reroute.anchor_ineligible", anchor_id)
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
