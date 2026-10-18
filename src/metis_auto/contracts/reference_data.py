"""Versioned reference data: model catalogue, price table, chat templates.

Stage 7 fixed the price schema (token_accounting.md §4, ADR-0020): token
types including cache writes, and context-length tiers selected by a call's
input tokens. The shape enforces the no-fabrication rule (MP§3.8): a
capability or limit counts only when verified with a source and check date,
a price may be unknown, and a chat template says how faithful it is.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from ._base import ContractModel, Name, NonNegInt, PosInt, Privacy, Version, field
from .accounting import Currency
from .tokens import Fidelity


class Sourced(ContractModel):
    """Where a fact came from and when it was checked."""

    source: str = field(Privacy.OPERATIONAL, "URL or document reference.", min_length=1)
    checked_on: date = field(Privacy.OPERATIONAL, "Date the source was read.")


class Capability(ContractModel):
    """A declared capability. Unverified means unsupported (FR-ROUTE-05)."""

    name: Name = field(
        Privacy.OPERATIONAL, "e.g. image_input, provider_prompt_caching."
    )
    verified: bool = field(Privacy.OPERATIONAL, "True only with a source.")
    evidence: Sourced | None = field(
        Privacy.OPERATIONAL, "Required when verified.", default=None
    )

    @model_validator(mode="after")
    def _check(self) -> Capability:
        if self.verified and self.evidence is None:
            raise ValueError("a verified capability needs evidence")
        return self


class Limit(ContractModel):
    """A numeric model limit. ``value`` None means unknown."""

    value: PosInt | None = field(Privacy.OPERATIONAL, "Limit in tokens.", default=None)
    evidence: Sourced | None = field(Privacy.OPERATIONAL, "Source.", default=None)

    @model_validator(mode="after")
    def _check(self) -> Limit:
        if self.value is not None and self.evidence is None:
            raise ValueError("a known limit needs evidence")
        return self


class CatalogueEntry(ContractModel):
    """One model Metis may route to."""

    model_id: Name = field(Privacy.OPERATIONAL, "Internal, stable ID.")
    provider: Name = field(Privacy.OPERATIONAL, "Provider family.")
    provider_model_name: str = field(Privacy.OPERATIONAL, "Name in the provider's API.")
    tier: NonNegInt = field(Privacy.OPERATIONAL, "Ordinal capability tier.")
    equivalence_group: Name = field(Privacy.OPERATIONAL, "Failover group (FR-FAIL-03).")
    context_window: Limit = field(Privacy.OPERATIONAL, "Context window.")
    max_output_tokens: Limit = field(Privacy.OPERATIONAL, "Output limit.")
    capabilities: tuple[Capability, ...] = field(
        Privacy.OPERATIONAL, "Declared capabilities.", default=()
    )
    tokenizer_ref: Name | None = field(
        Privacy.OPERATIONAL, "Tokenizer backend for this model.", default=None
    )
    price_ref: Name | None = field(
        Privacy.OPERATIONAL, "Price-table key; None = price unknown.", default=None
    )
    enabled: bool = field(Privacy.OPERATIONAL, "Disabled models are ineligible.")


class ModelCatalogue(ContractModel):
    version: Version = field(Privacy.OPERATIONAL, "Catalogue version ID.")
    entries: tuple[CatalogueEntry, ...] = field(
        Privacy.OPERATIONAL, "Models, in order."
    )

    @model_validator(mode="after")
    def _unique(self) -> ModelCatalogue:
        ids = [e.model_id for e in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("model_id values must be unique")
        return self


class TokenType(StrEnum):
    INPUT = "input"
    OUTPUT = "output"
    CACHED_INPUT = "cached_input"
    CACHE_WRITE = "cache_write"
    REASONING = "reasoning"
    """Only if a provider prices reasoning apart from output (none configured:
    reasoning is billed as output, token_accounting.md §3)."""


class PriceEntry(ContractModel):
    """Price of one token type for one model, optionally for one context tier.

    ``amount`` None = unknown, which makes dependent costs "not computed"
    (FR-ACCT-02). A tier applies when the call's **input** tokens lie within
    ``[min_input_tokens, max_input_tokens]`` (inclusive; open where None), and
    then prices every token type of that call ("full session" rule,
    token_accounting.md §4).
    """

    price_ref: Name = field(Privacy.OPERATIONAL, "Key used by catalogue entries.")
    token_type: TokenType = field(Privacy.OPERATIONAL, "Which tokens.")
    amount: Decimal | None = field(
        Privacy.OPERATIONAL, "Price per ``per_tokens`` tokens.", default=None, ge=0
    )
    per_tokens: PosInt = field(Privacy.OPERATIONAL, "Unit, e.g. 1000000.")
    currency: Currency = field(Privacy.OPERATIONAL, "ISO 4217.")
    effective_from: date | None = field(
        Privacy.OPERATIONAL, "First day the price applies.", default=None
    )
    evidence: Sourced | None = field(
        Privacy.OPERATIONAL, "Required when amount is set.", default=None
    )
    tier: Name | None = field(
        Privacy.OPERATIONAL, "Context tier name, e.g. standard, long.", default=None
    )
    min_input_tokens: NonNegInt | None = field(
        Privacy.OPERATIONAL, "Tier applies from this many input tokens.", default=None
    )
    max_input_tokens: PosInt | None = field(
        Privacy.OPERATIONAL, "Tier applies up to this many input tokens.", default=None
    )
    max_input_tokens_uncertain_up_to: PosInt | None = field(
        Privacy.OPERATIONAL,
        "The source's bound may really be this high (e.g. 270K read as 1,024s); "
        "inputs between the two bounds get a cost caveat.",
        default=None,
    )
    cache_ttl: Name | None = field(
        Privacy.OPERATIONAL,
        "Cache-write variant, e.g. ttl-5m; cache_write prices only.",
        default=None,
    )

    @model_validator(mode="after")
    def _check(self) -> PriceEntry:
        if self.amount is not None and self.evidence is None:
            raise ValueError("a price needs evidence (source and check date)")
        bounded = self.min_input_tokens is not None or self.max_input_tokens is not None
        if bounded and self.tier is None:
            raise ValueError("input-token bounds need a tier name")
        low, high = self.min_input_tokens, self.max_input_tokens
        if low is not None and high is not None and low > high:
            raise ValueError("min_input_tokens exceeds max_input_tokens")
        uncertain = self.max_input_tokens_uncertain_up_to
        if uncertain is not None and (high is None or uncertain <= high):
            raise ValueError("max_input_tokens_uncertain_up_to must exceed the bound")
        if self.cache_ttl is not None and self.token_type != TokenType.CACHE_WRITE:
            raise ValueError("cache_ttl applies to cache_write prices only")
        return self

    def covers(self, input_tokens: int) -> bool:
        """Whether this row's tier applies to a call with ``input_tokens``."""
        low = self.min_input_tokens or 0
        high = self.max_input_tokens
        return input_tokens >= low and (high is None or input_tokens <= high)


class PriceTable(ContractModel):
    version: Version = field(Privacy.OPERATIONAL, "Price-table version ID.")
    entries: tuple[PriceEntry, ...] = field(Privacy.OPERATIONAL, "Prices.")

    @model_validator(mode="after")
    def _tiers_disjoint(self) -> PriceTable:
        """Rows of one price_ref, token type, and cache variant may not
        overlap in input tokens, so at most one row ever applies."""
        groups: dict[tuple, list[PriceEntry]] = {}
        for e in self.entries:
            groups.setdefault((e.price_ref, e.token_type, e.cache_ttl), []).append(e)
        for key, rows in groups.items():
            spans = sorted(
                (r.min_input_tokens or 0, r.max_input_tokens or float("inf"))
                for r in rows
            )
            for (_, high), (low, _) in zip(spans, spans[1:], strict=False):
                if low <= high:
                    raise ValueError(f"overlapping price tiers for {key}")
        return self


class ChatTemplate(ContractModel):
    """Message-framing tokens a provider adds around the content (the chat
    template), for counting input that the provider reports none for.

    Overhead of a request = ``sequence_start`` + Σ per part (``prefix`` +
    ``suffix`` of its role) + ``reply_priming``. Roles are the generic
    ``PartRole`` values. ``fidelity`` is ``approximation`` unless the template
    is verified against provider-reported counts for this model.
    """

    tokenizer_ref: Name = field(Privacy.OPERATIONAL, "Tokenizer family it frames.")
    version: Version = field(Privacy.OPERATIONAL, "Template version ID.")
    sequence_start: NonNegInt = field(
        Privacy.OPERATIONAL, "Tokens once per request (e.g. BOS).", default=0
    )
    reply_priming: NonNegInt = field(
        Privacy.OPERATIONAL, "Tokens that open the model's reply.", default=0
    )
    role_prefix: dict[Name, NonNegInt] = field(
        Privacy.OPERATIONAL, "Tokens before each part, by role.", default_factory=dict
    )
    role_suffix: dict[Name, NonNegInt] = field(
        Privacy.OPERATIONAL, "Tokens after each part, by role.", default_factory=dict
    )
    fidelity: Fidelity = field(Privacy.OPERATIONAL, "How faithful the template is.")
    evidence: Sourced = field(Privacy.OPERATIONAL, "Where the framing comes from.")
