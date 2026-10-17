"""Token counts, each labelled with how it was obtained (FR-ACCT-01, H-7)."""

from __future__ import annotations

from enum import StrEnum

from ._base import ContractModel, Name, NonNegInt, Privacy, Version, field


class Fidelity(StrEnum):
    """How a token count was obtained, best first (GLOSSARY: Fidelity)."""

    PROVIDER_REPORTED = "provider_reported"
    EXACT_LOCAL = "exact_local"
    COUNTING_API = "counting_api"
    APPROXIMATION = "approximation"


FIDELITY_ORDER: tuple[Fidelity, ...] = tuple(Fidelity)
"""Best to worst. A total's fidelity is the worst of its parts."""


class TokenCount(ContractModel):
    """One token count and its provenance."""

    tokens: NonNegInt = field(Privacy.DERIVED, "Number of tokens.")
    fidelity: Fidelity = field(Privacy.OPERATIONAL, "How the count was obtained.")
    method: Version = field(
        Privacy.OPERATIONAL,
        "Tokenizer or approximation ID@version, or the provider usage field.",
    )


class TokenUsage(ContractModel):
    """Token usage of one model call, or an estimate of it.

    Counts not reported or not estimated are None, never zero.
    """

    model_id: Name = field(Privacy.OPERATIONAL, "Catalogue model the counts are for.")
    input: TokenCount = field(Privacy.DERIVED, "Input tokens.")
    output: TokenCount | None = field(Privacy.DERIVED, "Output tokens.", default=None)
    total: TokenCount | None = field(
        Privacy.DERIVED, "Total, as reported or summed by accounting.", default=None
    )
    cached_input: TokenCount | None = field(
        Privacy.DERIVED, "Input tokens billed as cached, if reported.", default=None
    )
    reasoning: TokenCount | None = field(
        Privacy.DERIVED, "Reasoning tokens, if reported.", default=None
    )
