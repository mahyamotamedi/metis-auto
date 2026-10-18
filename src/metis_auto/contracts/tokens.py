"""Token counts, each labelled with how it was obtained (FR-ACCT-01, H-7)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import model_validator

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

    Counts not reported or not estimated are None, never zero. **Inclusion
    rules** (token_accounting.md §3): ``input`` is every billed input token,
    so it *includes* ``cached_input``, ``cache_write``, and
    ``template_overhead``; ``output`` includes ``reasoning`` (hidden reasoning
    is billed as output). Adapters map provider usage fields onto these rules.
    """

    model_id: Name = field(Privacy.OPERATIONAL, "Catalogue model the counts are for.")
    input: TokenCount = field(Privacy.DERIVED, "Input tokens (all billed input).")
    output: TokenCount | None = field(
        Privacy.DERIVED, "Output tokens, including reasoning.", default=None
    )
    total: TokenCount | None = field(
        Privacy.DERIVED, "Total, as reported or summed by accounting.", default=None
    )
    cached_input: TokenCount | None = field(
        Privacy.DERIVED,
        "Part of input billed as cached (provider cache hit), if reported.",
        default=None,
    )
    reasoning: TokenCount | None = field(
        Privacy.DERIVED,
        "Part of output that is hidden reasoning, if reported.",
        default=None,
    )
    cache_write: TokenCount | None = field(
        Privacy.DERIVED,
        "Part of input billed as a provider cache write, if reported.",
        default=None,
    )
    cache_write_ttl: Name | None = field(
        Privacy.OPERATIONAL,
        "Cache-write variant when the price depends on it, e.g. ttl-5m.",
        default=None,
    )
    template_overhead: TokenCount | None = field(
        Privacy.DERIVED,
        "Part of a counted input added by the chat template (message framing).",
        default=None,
    )

    @model_validator(mode="after")
    def _check_parts(self) -> TokenUsage:
        provider_parts = sum(
            c.tokens for c in (self.cached_input, self.cache_write) if c is not None
        )
        if provider_parts > self.input.tokens:
            raise ValueError("cached_input + cache_write exceed input")
        overhead = self.template_overhead
        if overhead is not None and overhead.tokens > self.input.tokens:
            raise ValueError("template_overhead exceeds input")
        if self.reasoning is not None and (
            self.output is None or self.reasoning.tokens > self.output.tokens
        ):
            raise ValueError("reasoning is part of output and cannot exceed it")
        if self.cache_write_ttl is not None and self.cache_write is None:
            raise ValueError("cache_write_ttl needs cache_write")
        return self
