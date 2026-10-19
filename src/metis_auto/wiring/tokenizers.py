"""Tokenizers from settings (CMP-20; token_accounting.md §2, ADR-0020).

Responsibility: build one ``Tokenizer`` per row of the tokenizer table, and
collect each row's chat template. An exact backend whose library (extra
``tokenizers``) or asset (scripts/fetch_tokenizer_assets.py) is missing is
**replaced by the labelled chars/4 approximation** for that ref, with a
warning; its counts then say ``approximation``, never ``exact_local``.
Called by: wiring.from_settings, scripts. Calls: adapters.tokenizers, settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from metis_auto.adapters.tokenizers import (
    ApproxCharsTokenizer,
    HuggingFaceTokenizer,
    TiktokenTokenizer,
    TokenizerUnavailable,
)
from metis_auto.contracts import ChatTemplate
from metis_auto.ports import Tokenizer
from metis_auto.settings import (
    LoadedSettings,
    TokenizerBackend,
    TokenizerSpec,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TokenizerStatus:
    """What a ref is counted with in this process (for scripts and logs)."""

    ref: str
    configured: str
    loaded: str
    fidelity: str
    reason: str | None = None


@dataclass(frozen=True)
class TokenizerSet:
    tokenizers: dict[str, Tokenizer]
    templates: dict[str, ChatTemplate]
    status: tuple[TokenizerStatus, ...]


def _build(spec: TokenizerSpec, loaded: LoadedSettings) -> Tokenizer:
    if spec.backend == TokenizerBackend.APPROX_CHARS:
        assert spec.chars_per_token is not None
        return ApproxCharsTokenizer(spec.ref, spec.chars_per_token)
    assert spec.asset is not None
    path = loaded.path(loaded.settings.paths.tokenizer_assets) / spec.asset.path
    if spec.backend == TokenizerBackend.TIKTOKEN:
        assert spec.encoding is not None
        return TiktokenTokenizer(
            spec.ref, spec.encoding, path, spec.asset.sha256, spec.fidelity
        )
    return HuggingFaceTokenizer(spec.ref, path, spec.asset.sha256, spec.fidelity)


def build_tokenizers(loaded: LoadedSettings) -> TokenizerSet:
    table = loaded.reference.tokenizers
    tokenizers: dict[str, Tokenizer] = {}
    templates: dict[str, ChatTemplate] = {}
    status = []
    for spec in table.tokenizers if table else ():
        try:
            tokenizer = _build(spec, loaded)
            reason = None
        except TokenizerUnavailable as exc:
            log.warning("tokenizer %s falls back to chars/4: %s", spec.ref, exc)
            tokenizer = ApproxCharsTokenizer(spec.ref)
            reason = str(exc)
        tokenizers[spec.ref] = tokenizer
        if spec.template is not None:
            templates[spec.ref] = spec.template
        probe = tokenizer.count("x")
        status.append(
            TokenizerStatus(
                ref=spec.ref,
                configured=spec.backend.value,
                loaded=probe.method,
                fidelity=probe.fidelity.value,
                reason=reason,
            )
        )
    return TokenizerSet(tokenizers, templates, tuple(status))
