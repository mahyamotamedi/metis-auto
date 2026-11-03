"""``decision_router`` routing policy (pure; ADR-XXXX (system-one-decision-router);
routing plan R9).

The decision model answers questions; this policy maps the answers, the rule
features and dynamic criteria onto a **tier**, then the tier's cheapest
eligible model by **effective** cost (``rule_based``'s ranking, shared, not
copied), plus a reasoning-effort hint. Every path is recorded in the
``RouterSummary`` of the decision.

Order (first match wins; every threshold is a named placeholder, tuned on the
dev slice's ``tune`` split only):
1. **Gate** (fast path, ``fast_rules``): a decisive cheap-feature rule.
2. **Answers** (``slow_local`` / ``slow_hosted``, or ``fast_cache`` on a
   router-cache hit), when the decision was answered:
   a. ``complexity.score ≥ tau_complex`` or ``needs_reasoning ≥ tau_reason``
      → the high tier;
   b. ``cheap_model_ok ≥ tau_ok`` and the complexity answer's confidence
      ``≥ tau_conf`` → the low tier;
   c. ``intent ∈ high_tier_intents`` → the high tier.
3. **Fallback**: the rule-based tier when a rule (not the default) matches
   (``fallback_rules``); otherwise ``safe_tier`` (``fallback_safe_tier``).
   A failed, skipped or missing decision, or one whose answers fire nothing,
   lands here: unknown never satisfies a mapping rule (P-6).
Then the **criteria**: a long known input raises the tier; ``max_tier``
clamps it; a tight request deadline prefers models with a verified
``low_latency`` capability; an effective cost above the cap is flagged.

Called by: domain.routing.policy.route (built by wiring); the sticky policy
when ``inner = "decision_router"``. Calls: domain.routing.rule_based,
domain.routing.decision. Status: demo / placeholder component (ADR-0023
rules) until exp-route-013 gives evidence.
Traces: FR-FEAT-02, FR-ROUTE-01…03/05, H-5, routing_plan §3–§5.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pydantic import Field

from metis_auto.contracts import (
    BackendKind,
    CatalogueEntry,
    ContractModel,
    DecisionFailureReason,
    DecisionResult,
    DecisionStatus,
    ModelCatalogue,
    Name,
    PolicyRef,
    PriceTable,
    RequestFeatures,
    RouterPath,
    RouterSummary,
)

from .base import PolicyChoice
from .decision import Answers, GateConfig, QuestionIds, StateConfig, needs_decision
from .rule_based import CostModel, RuleBasedConfig, RuleBasedPolicy, effective_cost


class MappingConfig(ContractModel):
    tau_complex: float = Field(default=2.0, ge=0)
    tau_reason: float = Field(default=0.6, ge=0, le=1)
    tau_ok: float = Field(default=0.7, ge=0, le=1)
    tau_conf: float = Field(default=0.6, ge=0, le=1)
    high_tier_intents: tuple[Name, ...] = ("code", "math_reasoning", "analysis")
    low_tier: int = Field(default=0, ge=0)
    high_tier: int = Field(default=1, ge=0)
    use_soft_signals: bool = False
    """Map the answers kept on a low-confidence failure (``keep_soft_signals``).
    Off: a low-confidence decision falls back like any failure."""


class CriteriaConfig(ContractModel):
    long_context_tokens: int | None = Field(default=32_000, gt=0)
    long_context_min_tier: int = Field(default=1, ge=0)
    fast_model_deadline_ms: int | None = Field(default=None, gt=0)
    """A request deadline at or under this prefers ``low_latency_capability``
    models in the tier (verified only; unknown = not preferred). None = off."""
    low_latency_capability: Name = "low_latency"
    max_effective_cost_per_answer: Decimal | None = Field(default=None, gt=0)
    """Flag a target whose effective cost exceeds this (no cheaper model is
    forced: the chosen one is already the tier's cheapest). None = off."""
    max_tier: int | None = Field(default=None, ge=0)


class EffortConfig(ContractModel):
    """Reasoning-effort hint, only for models listed (where the endpoint takes
    ``reasoning_effort``); unknown needs_reasoning = no hint."""

    models: tuple[Name, ...] = ("gpt-5-nano",)
    low_below: float = Field(default=0.3, ge=0, le=1)
    low_effort: Name = "minimal"
    high_effort: Name | None = None
    """At or above ``tau_reason``; None = the model's default."""
    reasoning_tokens: dict[Name, dict[Name, int]] = {}
    """Expected hidden reasoning tokens per model and effort, for ranking."""


class HysteresisConfig(ContractModel):
    """Sticky interplay (``[pipeline.routing.sticky] inner = decision_router``)."""

    downgrade_after_n: int = Field(default=2, ge=1)
    tau_hist: float = Field(default=0.5, ge=0, le=1)
    low_turn_max_length_bucket: int = Field(default=1, ge=0)
    """Earlier turns carry no decision answers (stateless, P-8), so a turn
    counts as low-complexity by proxy: no code, no coding intent, and a length
    bucket at most this (all known)."""


class DecisionRouterConfig(ContractModel):
    version: str = "0.1.0"
    gate: GateConfig = GateConfig()
    state: StateConfig = StateConfig()
    questions: QuestionIds = QuestionIds()
    mapping: MappingConfig = MappingConfig()
    criteria: CriteriaConfig = CriteriaConfig()
    effort: EffortConfig = EffortConfig()
    hysteresis: HysteresisConfig = HysteresisConfig()
    safe_tier: int = Field(default=1, ge=0)
    undetermined: Literal["safe_tier", "rules_default"] = "safe_tier"
    """When no rule but the default matches: the safe tier (conservative) or
    the rules' default tier."""


@dataclass(frozen=True)
class TierDecision:
    tier: int
    path: RouterPath
    reason: str
    fired: tuple[str, ...]
    features_used: tuple[str, ...]
    backend: PolicyRef | None = None
    effort: str | None = None
    answers: Answers | None = None


def map_answers(
    a: Answers, m: MappingConfig
) -> tuple[int | None, str | None, tuple[str, ...]]:
    """(tier, reason, thresholds fired); (None, None, ()) when nothing fires."""
    fired = []
    if a.complexity is not None and a.complexity >= m.tau_complex:
        fired.append("tau_complex")
    if a.needs_reasoning is not None and a.needs_reasoning >= m.tau_reason:
        fired.append("tau_reason")
    if fired:
        reason = (
            "decision.tier1.needs_reasoning"
            if "tau_reason" in fired
            else "decision.tier1.complex"
        )
        return m.high_tier, reason, tuple(fired)
    if (
        a.cheap_model_ok is not None
        and a.cheap_model_ok >= m.tau_ok
        and a.complexity_confidence is not None
        and a.complexity_confidence >= m.tau_conf
    ):
        return m.low_tier, "decision.tier0.cheap_ok", ("tau_ok", "tau_conf")
    if a.intent is not None and a.intent in m.high_tier_intents:
        return m.high_tier, f"decision.tier1.intent.{a.intent}", ("high_tier_intents",)
    return None, None, ()


def effort_hint(a: Answers | None, config: DecisionRouterConfig) -> str | None:
    if a is None or a.needs_reasoning is None:
        return None
    if a.needs_reasoning < config.effort.low_below:
        return config.effort.low_effort
    if a.needs_reasoning >= config.mapping.tau_reason:
        return config.effort.high_effort
    return None


def _result_of(features: RequestFeatures, m: MappingConfig) -> DecisionResult | None:
    outcome = features.decision
    if outcome is None:
        return None
    if outcome.status == DecisionStatus.ANSWERED:
        return outcome.result
    if (
        m.use_soft_signals
        and outcome.failure_reason == DecisionFailureReason.LOW_CONFIDENCE
    ):
        return outcome.soft_result
    return None


class DecisionRouterPolicy:
    """Gate → answers → fallback → criteria → cheapest effective model."""

    def __init__(
        self,
        config: DecisionRouterConfig,
        rules: RuleBasedConfig,
        catalogue: ModelCatalogue,
        prices: PriceTable,
    ) -> None:
        self._config = config
        self._rules_config = rules
        self._rules = RuleBasedPolicy(rules, catalogue, prices)
        self._catalogue = catalogue
        self._prices = prices

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(
            name="decision_router",
            version=f"{self._config.version}+rules-{self._rules_config.version}",
        )

    @property
    def config(self) -> DecisionRouterConfig:
        return self._config

    # -- the tier ----------------------------------------------------------------
    def decide_tier(self, features: RequestFeatures) -> TierDecision:
        """The tier and the path that decided it, before criteria and eligibility."""
        cfg = self._config
        gate = needs_decision(features, cfg.gate)
        if gate is not None:
            return TierDecision(
                gate.tier,
                RouterPath.FAST_RULES,
                f"decision.{gate.rule_id}",
                (gate.rule_id,),
                gate.features_used,
            )
        result = _result_of(features, cfg.mapping)
        answers = Answers.of(result, cfg.questions) if result is not None else None
        backend = result.backend if result is not None else None
        effort = effort_hint(answers, cfg)
        if answers is not None and result is not None:
            tier, reason, fired = map_answers(answers, cfg.mapping)
            if tier is not None and reason is not None:
                if result.cache_hit:
                    path = RouterPath.FAST_CACHE
                elif result.backend_kind == BackendKind.LOCAL:
                    path = RouterPath.SLOW_LOCAL
                else:
                    path = RouterPath.SLOW_HOSTED
                return TierDecision(
                    tier, path, reason, fired, ("decision",), backend, effort, answers
                )
        rule_id, rule_tier, used = self._rules.tier_for(features)
        if rule_id != "default" or cfg.undetermined == "rules_default":
            return TierDecision(
                rule_tier,
                RouterPath.FALLBACK_RULES,
                f"decision.fallback.rules.{rule_id}",
                (f"rule.{rule_id}",),
                used,
                backend,
                effort,
                answers,
            )
        return TierDecision(
            cfg.safe_tier,
            RouterPath.FALLBACK_SAFE_TIER,
            "decision.fallback.safe_tier",
            ("safe_tier",),
            (),
            backend,
            effort,
            answers,
        )

    # -- criteria and the model --------------------------------------------------
    def _criteria(
        self, features: RequestFeatures, tier: int
    ) -> tuple[int, tuple[str, ...]]:
        c = self._config.criteria
        fired = []
        known = features.known_input_tokens
        if (
            c.long_context_tokens is not None
            and known is not None
            and known.tokens >= c.long_context_tokens
            and tier < c.long_context_min_tier
        ):
            tier = c.long_context_min_tier
            fired.append("criteria.long_context")
        if c.max_tier is not None and tier > c.max_tier:
            tier = c.max_tier
            fired.append("criteria.max_tier")
        return tier, tuple(fired)

    def _latency_filter(
        self,
        features: RequestFeatures,
        eligible: tuple[CatalogueEntry, ...],
        tier: int,
    ) -> tuple[tuple[CatalogueEntry, ...], tuple[str, ...]]:
        c = self._config.criteria
        deadline = features.deadline_ms
        if c.fast_model_deadline_ms is None or deadline is None:
            return eligible, ()
        if deadline > c.fast_model_deadline_ms:
            return eligible, ()
        fast = {
            e.model_id
            for e in eligible
            if e.tier == tier
            and any(
                cap.name == c.low_latency_capability and cap.verified
                for cap in e.capabilities
            )
        }
        if not fast:
            return eligible, ("criteria.low_latency_unavailable",)
        kept = tuple(e for e in eligible if e.tier != tier or e.model_id in fast)
        return kept, ("criteria.low_latency",)

    def _ranker(self, effort: str | None) -> RuleBasedPolicy:
        """The rule-based ranking, with expected reasoning tokens per effort for
        the models the hint applies to."""
        if effort is None:
            return self._rules
        per = {
            model: by_effort[effort]
            for model, by_effort in self._config.effort.reasoning_tokens.items()
            if effort in by_effort and model in self._config.effort.models
        }
        if not per:
            return self._rules
        base = self._rules_config.cost_model
        cost_model = CostModel(
            assumed_output_tokens=base.assumed_output_tokens,
            expected_reasoning_tokens={**base.expected_reasoning_tokens, **per},
            default_reasoning_tokens=base.default_reasoning_tokens,
        )
        rules = self._rules_config.model_copy(update={"cost_model": cost_model})
        return RuleBasedPolicy(rules, self._catalogue, self._prices)

    def choose(
        self, features: RequestFeatures, eligible: tuple[CatalogueEntry, ...]
    ) -> PolicyChoice | None:
        decided = self.decide_tier(features)
        return self.choose_for(features, eligible, decided)

    def choose_for(
        self,
        features: RequestFeatures,
        eligible: tuple[CatalogueEntry, ...],
        decided: TierDecision,
        *,
        reason_prefix: str | None = None,
    ) -> PolicyChoice | None:
        tier, criteria = self._criteria(features, decided.tier)
        candidates, latency = self._latency_filter(features, eligible, tier)
        ranker = self._ranker(decided.effort)
        reason = (
            f"{reason_prefix}.{decided.reason}" if reason_prefix else decided.reason
        )
        choice = ranker.choose_in_tier(
            features, candidates, tier, reason, decided.features_used
        )
        if choice is None:
            return None
        fired = [*decided.fired, *criteria, *latency]
        target = next(e for e in candidates if e.model_id == choice.model_id)
        cap = self._config.criteria.max_effective_cost_per_answer
        if cap is not None:
            known = features.known_input_tokens
            cost = effective_cost(
                target,
                self._prices,
                known.tokens if known is not None else 0,
                ranker.config.cost_model,
            )
            if cost is None or cost > cap:
                fired.append("criteria.cost_cap_exceeded")
        effort = (
            decided.effort
            if decided.effort is not None
            and target.model_id in self._config.effort.models
            else None
        )
        if decided.effort is not None and effort is not None:
            fired.append(f"effort.{effort}")
        return PolicyChoice(
            reason_code=choice.reason_code,
            model_id=choice.model_id,
            features_used=choice.features_used,
            chain=choice.chain,
            anchor_model_id=choice.anchor_model_id,
            router_summary=RouterSummary(
                path=decided.path,
                backend=decided.backend,
                mapped_tier=tier,
                thresholds_fired=tuple(fired),
                reasoning_effort=effort,
            ),
        )

    # -- the helpers the sticky policy needs (same as RuleBasedPolicy) -----------
    def cheapest(
        self, features: RequestFeatures, candidates: tuple[CatalogueEntry, ...]
    ) -> CatalogueEntry | None:
        return self._rules.cheapest(features, candidates)

    def chain_above(
        self,
        features: RequestFeatures,
        eligible: tuple[CatalogueEntry, ...],
        tier: int,
    ) -> tuple[str, ...]:
        return self._rules.chain_above(features, eligible, tier)


def dependent_on_history(answers: Answers | None, tau_hist: float) -> bool:
    """True only when the answer is known and at or above the threshold (P-6)."""
    return (
        answers is not None
        and answers.depends_on_history is not None
        and answers.depends_on_history >= tau_hist
    )
