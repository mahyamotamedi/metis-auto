"""Versioned reference data: model catalogue and price table.

**Provisional:** Stage 7 fixes the schema (providers.md §4). The shape already
enforces the no-fabrication rule (MP§3.8): a capability or limit counts only
when verified with a source and check date, and a price may be unknown.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import model_validator

from ._base import ContractModel, Name, NonNegInt, PosInt, Privacy, Version, field
from .accounting import Currency


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
    REASONING = "reasoning"


class PriceEntry(ContractModel):
    """Price of one token type for one model. ``amount`` None = unknown, which
    makes dependent costs "not computed" (FR-ACCT-02)."""

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

    @model_validator(mode="after")
    def _check(self) -> PriceEntry:
        if self.amount is not None and self.evidence is None:
            raise ValueError("a price needs evidence (source and check date)")
        return self


class PriceTable(ContractModel):
    version: Version = field(Privacy.OPERATIONAL, "Price-table version ID.")
    entries: tuple[PriceEntry, ...] = field(Privacy.OPERATIONAL, "Prices.")
