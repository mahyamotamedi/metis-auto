"""Settings → components (CMP-20; configuration.md §2, ADR-0018, ADR-0019).

Responsibility: map ``LoadedSettings`` onto what ``build_pipeline`` needs:
the ``PipelineConfig`` (reference data plus each policy's typed config, where
the policies' own types validate the ``[pipeline.*]`` sections), the
fingerprint key (a secret, handed only to the measurement service), the
persistent spend ledger, and the live-call permission ("two keys", caps, and
the API key). Secrets leave the holder only here, and only as arguments.
Called by: scripts, ``wiring.walking_skeleton``, tests, (Stage 7.5) the live
adapter factory. Calls: wiring.pipeline, settings, adapters.system.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any

from metis_auto.adapters.system import FileSpendLedger, SystemClock
from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.accounting import AccountingService
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.application.pipeline import PipelineConfig, RequestPipeline
from metis_auto.contracts import AnswerSource, Identifier, Money, RunMode
from metis_auto.ports import CacheStore, Clock, EventSink, IdSource, ModelClient
from metis_auto.settings import CounterfactualSource, LoadedSettings, SettingsError

from .pipeline import build_pipeline
from .tokenizers import TokenizerSet, build_tokenizers

log = logging.getLogger(__name__)


def pipeline_config(loaded: LoadedSettings) -> PipelineConfig:
    """Reference data plus the ``[pipeline.*]`` sections, validated by each
    policy's config type (unknown keys are errors)."""
    try:
        return PipelineConfig.model_validate(
            {
                "catalogue": loaded.reference.catalogue,
                "prices": loaded.reference.prices,
                **loaded.settings.pipeline,
            }
        )
    except ValueError as exc:
        raise SettingsError(f"invalid [pipeline] settings: {exc}") from None


def fingerprint_key(loaded: LoadedSettings) -> bytes:
    """``METIS_FINGERPRINT_KEY``; otherwise a random per-process key when
    ``dev.ephemeral_fingerprint_key`` allows it (A-44), else an error."""
    if loaded.secrets.fingerprint_key is not None:
        return loaded.secrets.fingerprint_key.get_secret_value()
    if not loaded.settings.dev.ephemeral_fingerprint_key:
        raise SettingsError(
            "METIS_FINGERPRINT_KEY is not set and dev.ephemeral_fingerprint_key "
            "is false"
        )
    log.info("no METIS_FINGERPRINT_KEY: using a random key for this process")
    return secrets.token_bytes(32)


@dataclass(frozen=True)
class LivePermission:
    """Whether this run may make live calls, and every reason it may not."""

    allowed: bool
    reasons: tuple[str, ...]


def live_permission(loaded: LoadedSettings) -> LivePermission:
    """ADR-0018: the experiment asks for ``live`` **and** the runtime enables
    live calls **and** both caps are set **and** ``METIS_API_KEY`` is present."""
    s = loaded.settings
    reasons = []
    if s.experiment.counterfactual_source != CounterfactualSource.LIVE:
        reasons.append("experiment.counterfactual_source is not 'live'")
    if not s.live.enabled:
        reasons.append("live.enabled is false in the runtime configuration")
    if not s.budget.capped:
        reasons.append("budget.lifetime_cap and budget.run_cap must both be set")
    if loaded.secrets.metis_api_key is None:
        reasons.append("METIS_API_KEY is not set")
    return LivePermission(allowed=not reasons, reasons=tuple(reasons))


def spend_ledger(loaded: LoadedSettings, run_id: Identifier) -> FileSpendLedger:
    """The persistent, cumulative ledger at ``paths.spend_ledger``, with the
    lifetime and per-run caps from ``[budget]``."""
    budget = loaded.settings.budget
    if not budget.capped:
        raise SettingsError("a spend ledger needs both budget caps (ADR-0018)")
    assert budget.lifetime_cap is not None and budget.run_cap is not None
    return FileSpendLedger(
        loaded.path(loaded.settings.paths.spend_ledger),
        run_id=run_id,
        lifetime_cap=Money(amount=budget.lifetime_cap, currency=budget.currency),
        run_cap=Money(amount=budget.run_cap, currency=budget.currency),
        warn_at=budget.warn_at,
    )


def build_pipeline_from_settings(
    loaded: LoadedSettings,
    *,
    model_client: ModelClient,
    cache_store: CacheStore,
    sink: EventSink,
    run_id: Identifier,
    run_mode: RunMode,
    clock: Clock | None = None,
    ids: IdSource | None = None,
    tokenizers: TokenizerSet | None = None,
    **candidates: Any,
) -> RequestPipeline:
    """``build_pipeline`` from settings. ``candidates`` are passed through
    (``routing_policy``, ``context_strategy``, ``candidate_versions``). A
    live client is refused unless ``live_permission`` allows it; it then
    gets the file ledger. Tokenizers come from the tokenizer table (built
    here unless given)."""
    tokens = tokenizers or build_tokenizers(loaded)
    ledger = None
    if model_client.source == AnswerSource.LIVE:
        permission = live_permission(loaded)
        if not permission.allowed:
            raise SettingsError("live calls refused: " + "; ".join(permission.reasons))
        ledger = spend_ledger(loaded, run_id)
    return build_pipeline(
        pipeline_config(loaded),
        model_client=model_client,
        cache_store=cache_store,
        sink=sink,
        fingerprint_key=fingerprint_key(loaded),
        run_id=run_id,
        run_mode=run_mode,
        clock=clock,
        ids=ids,
        spend_ledger=ledger,
        tokenizers=tokens.tokenizers,
        templates=tokens.templates,
        config_hash=loaded.config_hash,
        **candidates,
    )


def build_accounting_service(
    loaded: LoadedSettings, tokenizers: TokenizerSet | None = None
) -> AccountingService:
    """Token and cost accounting over the configured catalogue, prices, and
    tokenizers, outside any pipeline (scripts, the Demo UI). Its measurement
    service fingerprints nothing that is kept, so it uses a random key."""
    tokens = tokenizers or build_tokenizers(loaded)
    measurement = MeasurementService(
        Fingerprinter(secrets.token_bytes(32)),
        SystemClock(),
        ApproxCharsTokenizer(),
        tokenizers=tokens.tokenizers,
        templates=tokens.templates,
    )
    return AccountingService(
        measurement, loaded.reference.catalogue, loaded.reference.prices
    )
