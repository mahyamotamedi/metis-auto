"""``rule_based`` routing policy (routing.md §1 step 4; routing plan R1).

Responsibility: ordered rules over cheap features (code, coding intent, attachments,
language, length bucket, turn depth, retrieved context, instructions) choose
a **tier**; the model is the eligible model in that tier with the lowest
**effective** cost per answer, where hidden reasoning tokens count (routing
plan §3: the nominal price is misleading for gpt-5-nano, DeepSeek, and MiMo).
The escalation chain is the cheapest eligible model of each higher tier.
Pure. Called by: domain.routing.policy.route (built by wiring), and by the
sticky policy. Calls: domain.accounting (pricing), contracts.
Config: ``RuleBasedConfig`` (rules, tiers, and the cost model are
**placeholders**, A-43 style: not tuned, no quality evidence; routing plan
R1 decides them on the full dataset).
Status: demo component (Demo milestone, ADR-0023). Traces: FR-ROUTE-01…03,
H-5, routing_plan §3–§5.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from metis_auto.contracts import (
    CatalogueEntry,
    ComponentState,
    ContractModel,
    CostStatus,
    Fidelity,
    Language,
    ModelCatalogue,
    Name,
    PolicyRef,
    PriceTable,
    RequestFeatures,
    TokenCount,
    TokenUsage,
)

from ..accounting import bills_hidden_reasoning, cost_of
from .base import PolicyChoice

_METHOD = "routing-cost-model@1"


class RuleCondition(ContractModel):
    """All set conditions must hold; None = not checked. An unknown feature
    never satisfies a condition (P-6)."""

    language: tuple[Language, ...] | None = None
    has_code: bool | None = None
    has_coding_intent: bool | None = None
    has_attachments: bool | None = None
    length_bucket_min: int | None = None
    length_bucket_max: int | None = None
    turn_depth_min: int | None = None
    retrieved_present: bool | None = None
    instructions_present: bool | None = None

    def holds(self, f: RequestFeatures) -> bool:
        checks: list[bool] = []
        if self.language is not None:
            checks.append(f.language in self.language)
        if self.has_code is not None:
            checks.append(f.has_code is not None and f.has_code == self.has_code)
        if self.has_coding_intent is not None:
            intent = f.has_coding_intent
            checks.append(intent is not None and intent == self.has_coding_intent)
        if self.has_attachments is not None:
            count = f.attachment_count
            checks.append(count is not None and (count > 0) == self.has_attachments)
        if self.length_bucket_min is not None:
            b = f.length_bucket
            checks.append(b is not None and b >= self.length_bucket_min)
        if self.length_bucket_max is not None:
            b = f.length_bucket
            checks.append(b is not None and b <= self.length_bucket_max)
        if self.turn_depth_min is not None:
            d = f.turn_depth
            checks.append(d is not None and d >= self.turn_depth_min)
        if self.retrieved_present is not None:
            checks.append(
                f.retrieved_state != ComponentState.UNKNOWN
                and (f.retrieved_state == ComponentState.PRESENT)
                == self.retrieved_present
            )
        if self.instructions_present is not None:
            checks.append(
                f.instructions_state != ComponentState.UNKNOWN
                and (f.instructions_state == ComponentState.PRESENT)
                == self.instructions_present
            )
        return all(checks)

    def feature_names(self) -> tuple[str, ...]:
        names = {
            "language": self.language,
            "has_code": self.has_code,
            "has_coding_intent": self.has_coding_intent,
            "attachment_count": self.has_attachments,
            "length_bucket": self.length_bucket_min
            if self.length_bucket_min is not None
            else self.length_bucket_max,
            "turn_depth": self.turn_depth_min,
            "retrieved_state": self.retrieved_present,
            "instructions_state": self.instructions_present,
        }
        return tuple(k for k, v in names.items() if v is not None)


class Rule(ContractModel):
    id: Name
    when: RuleCondition = RuleCondition()
    tier: int = Field(ge=0)


class CostModel(ContractModel):
    """Effective cost per answer used to rank models inside a tier: the
    request's estimated input, plus ``assumed_output_tokens`` visible output,
    plus each model's expected hidden reasoning tokens (billed as output).
    Placeholders from one tiny live check each (live_check.md): they set the
    order, not a prediction of any bill."""

    assumed_output_tokens: int = Field(default=300, ge=0)
    expected_reasoning_tokens: dict[Name, int] = {}
    """Per model; wiring sets 0 for a model whose thinking is disabled."""
    default_reasoning_tokens: int = Field(default=256, ge=0)
    """For a model that bills hidden reasoning (verified capability) but has
    no configured expectation: never assume zero."""


class RuleBasedConfig(ContractModel):
    version: str = "0.1.0"
    rules: tuple[Rule, ...] = ()
    default_tier: int = Field(default=0, ge=0)
    cost_model: CostModel = CostModel()


def effective_cost(
    entry: CatalogueEntry,
    prices: PriceTable,
    input_tokens: int,
    model: CostModel,
) -> Decimal | None:
    """Expected cost of one answer on ``entry``, hidden reasoning included;
    None if its price is unknown."""
    reasoning = model.expected_reasoning_tokens.get(entry.model_id)
    if reasoning is None:
        reasoning = (
            model.default_reasoning_tokens if bills_hidden_reasoning(entry) else 0
        )
    output = model.assumed_output_tokens + reasoning

    def count(n: int) -> TokenCount:
        return TokenCount(tokens=n, fidelity=Fidelity.APPROXIMATION, method=_METHOD)

    usage = TokenUsage(
        model_id=entry.model_id,
        input=count(input_tokens),
        output=count(output),
        reasoning=count(reasoning),
    )
    cost = cost_of(usage, entry, prices)
    if cost.status != CostStatus.COMPUTED or cost.amount is None:
        return None
    return cost.amount.amount


def rank_by_cost(
    entries: tuple[CatalogueEntry, ...] | list[CatalogueEntry],
    prices: PriceTable,
    input_tokens: int,
    model: CostModel,
) -> list[CatalogueEntry]:
    """Cheapest effective first; unknown prices last; ties by catalogue order."""
    costs = [
        (effective_cost(e, prices, input_tokens, model), i, e)
        for i, e in enumerate(entries)
    ]
    known = sorted((c, i, e) for c, i, e in costs if c is not None)
    unknown = [(i, e) for c, i, e in costs if c is None]
    return [e for _, _, e in known] + [e for _, e in unknown]


class RuleBasedPolicy:
    """Rules → tier → cheapest effective eligible model in it."""

    def __init__(
        self, config: RuleBasedConfig, catalogue: ModelCatalogue, prices: PriceTable
    ) -> None:
        self._config = config
        self._catalogue = catalogue
        self._prices = prices

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(name="rule_based", version=self._config.version)

    @property
    def config(self) -> RuleBasedConfig:
        return self._config

    def input_tokens(self, features: RequestFeatures) -> int:
        known = features.known_input_tokens
        return known.tokens if known is not None else 0

    def tier_for(self, features: RequestFeatures) -> tuple[str, int, tuple[str, ...]]:
        """(rule ID or ``default``, tier, features read)."""
        for rule in self._config.rules:
            if rule.when.holds(features):
                return rule.id, rule.tier, rule.when.feature_names()
        return "default", self._config.default_tier, ()

    def cheapest(
        self, features: RequestFeatures, candidates: tuple[CatalogueEntry, ...]
    ) -> CatalogueEntry | None:
        ranked = rank_by_cost(
            candidates,
            self._prices,
            self.input_tokens(features),
            self._config.cost_model,
        )
        return ranked[0] if ranked else None

    def chain_above(
        self,
        features: RequestFeatures,
        eligible: tuple[CatalogueEntry, ...],
        tier: int,
    ) -> tuple[str, ...]:
        """The cheapest eligible model of each tier above ``tier``, ascending."""
        tiers = sorted({e.tier for e in eligible if e.tier > tier})
        chain = []
        for t in tiers:
            best = self.cheapest(features, tuple(e for e in eligible if e.tier == t))
            if best is not None:
                chain.append(best.model_id)
        return tuple(chain)

    def choose(
        self, features: RequestFeatures, eligible: tuple[CatalogueEntry, ...]
    ) -> PolicyChoice | None:
        rule_id, tier, used = self.tier_for(features)
        return self.choose_in_tier(features, eligible, tier, f"rule.{rule_id}", used)

    def choose_in_tier(
        self,
        features: RequestFeatures,
        eligible: tuple[CatalogueEntry, ...],
        tier: int,
        reason: str,
        used: tuple[str, ...] = (),
    ) -> PolicyChoice | None:
        """Cheapest effective model in ``tier``; if the tier has no eligible
        model, the nearest tier above, then below (``.tier_fallback``)."""
        available = sorted({e.tier for e in eligible})
        if not available:
            return None
        order = [t for t in available if t >= tier] + sorted(
            (t for t in available if t < tier), reverse=True
        )
        chosen_tier = order[0]
        target = self.cheapest(
            features, tuple(e for e in eligible if e.tier == chosen_tier)
        )
        if target is None:
            return None
        if chosen_tier != tier:
            reason = f"{reason}.tier_fallback"
        return PolicyChoice(
            reason_code=reason,
            model_id=target.model_id,
            features_used=(*used, "known_input_tokens"),
            chain=self.chain_above(features, eligible, chosen_tier),
        )
