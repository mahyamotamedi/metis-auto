"""Pipeline configuration: reference data plus each policy's typed config.

Built by wiring from settings (TODO(Stage 6): from layered config files; the
walking skeleton builds it in code). Frozen for the run (configuration §3).
Traces: P-4, configuration.md.
"""

from __future__ import annotations

from metis_auto.contracts import ContractModel, ModelCatalogue, PriceTable
from metis_auto.domain.accounting import AccountingConfig
from metis_auto.domain.attempts import AttemptPolicyConfig
from metis_auto.domain.caching import CachePolicyConfig
from metis_auto.domain.context import ContextConfig
from metis_auto.domain.features import FeatureConfig
from metis_auto.domain.routing import RoutingConfig


class PipelineConfig(ContractModel):
    catalogue: ModelCatalogue
    prices: PriceTable
    features: FeatureConfig = FeatureConfig()
    routing: RoutingConfig = RoutingConfig()
    cache: CachePolicyConfig = CachePolicyConfig()
    context: ContextConfig = ContextConfig()
    attempts: AttemptPolicyConfig = AttemptPolicyConfig()
    accounting: AccountingConfig = AccountingConfig()
    default_deadline_ms: int | None = None
    attempt_timeout_ms: int | None = None
