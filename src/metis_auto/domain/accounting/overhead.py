"""Chat-template overhead: the framing tokens a provider adds around content
(token_accounting.md §3).

Responsibility: count a request's message-framing tokens from a configured
``ChatTemplate`` and the ordered part roles, and add them to a content count.
Pure. Called by: application.measurement, application.accounting.
Traces: FR-ACCT-01, MP Stage 7 ("chat-template/message overhead"), ADR-0020.
"""

from __future__ import annotations

from collections.abc import Sequence

from metis_auto.contracts import ChatTemplate, TokenCount

from .tokens import sum_counts


def template_overhead(
    template: ChatTemplate | None, roles: Sequence[str]
) -> TokenCount | None:
    """Framing tokens for parts with these roles, in order; None without a
    template (the overhead is then not modelled, and not added)."""
    if template is None:
        return None
    missing = sorted(
        {r for r in roles if r not in template.role_prefix}
        | {r for r in roles if r not in template.role_suffix}
    )
    if missing:
        raise ValueError(f"chat template {template.version} lacks roles {missing}")
    tokens = (
        template.sequence_start
        + template.reply_priming
        + sum(template.role_prefix[r] + template.role_suffix[r] for r in roles)
    )
    return TokenCount(
        tokens=tokens, fidelity=template.fidelity, method=f"template:{template.version}"
    )


def with_overhead(content: TokenCount, overhead: TokenCount | None) -> TokenCount:
    """Billed input: content plus framing. Fidelity is the worse of the two."""
    total = sum_counts(c for c in (content, overhead) if c is not None)
    assert total is not None
    return total
