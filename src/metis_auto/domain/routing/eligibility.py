"""Shared eligibility filter (routing.md §1 step 3).

Responsibility: remove catalogue models that cannot serve the request, with a
reason for each. Shared by every policy, so no candidate strategy can bypass
capability safety. Pure.
Called by: domain.routing.policy.route. Calls: contracts only.
Config: ``EligibilityConfig``. Traces: FR-ROUTE-05, FR-CTX-05, FR-FAIL-03.

Status: reference implementation (modality, context fit, enabled, minimum
window). Provider health (FR-FAIL-05) is future.
"""

from __future__ import annotations

from metis_auto.contracts import (
    CatalogueEntry,
    ContractModel,
    Exclusion,
    ExclusionReason,
    Modality,
    ModelCatalogue,
    RequestFeatures,
)


class EligibilityConfig(ContractModel):
    """Provisional defaults; the margin is configuration (routing.md §5)."""

    context_safety_margin: float = 0.1
    """Fraction of the estimated input added before the context-fit check."""
    reserved_output_tokens: int = 0
    """Output tokens reserved in the fit check (TODO(Stage 7): per model)."""


def capability_for(modality: Modality) -> str:
    """Catalogue capability name a modality needs, e.g. ``image_input``."""
    return f"{modality.value}_input"


def filter_eligible(
    features: RequestFeatures,
    catalogue: ModelCatalogue,
    config: EligibilityConfig,
    min_context_window: int | None = None,
) -> tuple[tuple[CatalogueEntry, ...], tuple[Exclusion, ...]]:
    """(eligible entries in catalogue order, exclusions with reasons)."""
    eligible: list[CatalogueEntry] = []
    exclusions: list[Exclusion] = []
    for entry in catalogue.entries:
        reason = _exclusion(entry, features, config, min_context_window)
        if reason is None:
            eligible.append(entry)
        else:
            exclusions.append(Exclusion(model_id=entry.model_id, reason=reason))
    return tuple(eligible), tuple(exclusions)


def _exclusion(
    entry: CatalogueEntry,
    features: RequestFeatures,
    config: EligibilityConfig,
    min_window: int | None,
) -> ExclusionReason | None:
    if not entry.enabled:
        return ExclusionReason.DISABLED
    declared = {c.name: c for c in entry.capabilities}
    for modality in features.attachment_modalities:
        capability = declared.get(capability_for(modality))
        if capability is None:
            return ExclusionReason.MODALITY_UNSUPPORTED
        if not capability.verified:
            return ExclusionReason.CAPABILITY_UNVERIFIED  # unverified = unsupported
    window = entry.context_window.value
    if window is None:
        return ExclusionReason.CONTEXT_LIMIT_UNKNOWN
    if min_window is not None and window < min_window:
        return ExclusionReason.BELOW_MIN_WINDOW
    estimate = features.known_input_tokens
    if estimate is not None:
        needed = estimate.tokens * (1 + config.context_safety_margin)
        if needed + config.reserved_output_tokens > window:
            return ExclusionReason.CONTEXT_TOO_SMALL
    return None
