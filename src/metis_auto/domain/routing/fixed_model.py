"""``fixed_model`` routing policy (routing.md §1 step 4).

Responsibility: always choose the configured model. Implements the premium
baseline (ADR-0002) and simple deployments. If the model is not eligible for
this request, there is no target: routing never falls back silently.
Called by: domain.routing.policy.route (built by wiring). Config:
``FixedModelConfig``. Status: decided (reference policy). Traces: FR-ROUTE-03.
"""

from __future__ import annotations

from metis_auto.contracts import (
    CatalogueEntry,
    ContractModel,
    Name,
    PolicyRef,
    RequestFeatures,
)

from .base import PolicyChoice


class FixedModelConfig(ContractModel):
    model_id: Name
    version: str = "1.0.0"


class FixedModelPolicy:
    def __init__(self, config: FixedModelConfig) -> None:
        self._config = config

    @property
    def ref(self) -> PolicyRef:
        return PolicyRef(name="fixed_model", version=self._config.version)

    def choose(
        self, features: RequestFeatures, eligible: tuple[CatalogueEntry, ...]
    ) -> PolicyChoice | None:
        if any(e.model_id == self._config.model_id for e in eligible):
            return PolicyChoice(
                reason_code="fixed_model", model_id=self._config.model_id
            )
        return None
