"""Settings shapes (CMP-19; contracts.md O-1, ADR-0019).

Responsibility: the typed, frozen form of the merged non-secret settings, the
secret holder, and the reference-data bundle. Validates shape and the
cross-cutting rules of configuration.md §3 (lifetime cap within the ceiling,
run cap within the lifetime cap). Knows no policy: ``pipeline`` sections are
passed through untouched and validated by wiring against each policy's own
config type (configuration.md §3 rule 5).
Called by: settings.loader (builds), wiring (reads).
Privacy: no field holds content. Secrets live only in ``Secrets`` and never
enter the config hash, ``repr``, or a dump.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, SecretBytes, SecretStr, model_validator

from metis_auto.contracts import (
    ContractModel,
    ModelCatalogue,
    Name,
    PriceTable,
    Sourced,
    Version,
)


class PathSettings(ContractModel):
    """Machine-local locations (runtime configuration). Relative paths are
    resolved against the repository root by the loader. Excluded from the
    config hash: moving a directory does not change a result."""

    run_dir: str = "runs"
    spend_ledger: str = "data/spend/ledger.jsonl"
    recorded_dir: str = "data/recorded"


class LoggingSettings(ContractModel):
    """Operator logs (observability §6). Excluded from the config hash."""

    level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")


class LiveSettings(ContractModel):
    """Runtime permission for live calls on this machine (ADR-0003, ADR-0018).
    The second key of the "two keys" rule; set only by runtime layers."""

    enabled: bool = False


class BudgetSettings(ContractModel):
    """Spending caps for live calls (ADR-0018). Amounts are decimals in
    ``currency``. ``lifetime_ceiling`` may be set only in ``config/defaults.toml``
    (the loader enforces it), so no local file can raise the 20 USD limit."""

    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    lifetime_ceiling: Decimal = Field(default=Decimal("20"), gt=0)
    lifetime_cap: Decimal | None = Field(default=Decimal("20"), gt=0)
    run_cap: Decimal | None = Field(default=Decimal("1"), gt=0)
    warn_at: tuple[float, ...] = (0.5, 0.8)

    @model_validator(mode="after")
    def _check(self) -> BudgetSettings:
        if self.lifetime_cap is not None and self.lifetime_cap > self.lifetime_ceiling:
            raise ValueError(
                f"budget.lifetime_cap {self.lifetime_cap} exceeds the ceiling "
                f"{self.lifetime_ceiling} (ADR-0018)"
            )
        if (
            self.run_cap is not None
            and self.lifetime_cap is not None
            and self.run_cap > self.lifetime_cap
        ):
            raise ValueError("budget.run_cap may not exceed budget.lifetime_cap")
        if any(not 0 < f < 1 for f in self.warn_at):
            raise ValueError("budget.warn_at fractions must be between 0 and 1")
        return self

    @property
    def capped(self) -> bool:
        """Both caps set: the condition for any live call (ADR-0018)."""
        return self.lifetime_cap is not None and self.run_cap is not None


class ReferenceSettings(ContractModel):
    """Reference-data files, relative to the config directory. Represented in
    the config hash by each file's version ID, not by its path."""

    catalogue: str = "reference/catalogue-metis-test.toml"
    prices: str = "reference/prices-metis-2026-10-18.toml"
    endpoints: str | None = "reference/endpoints-metis.toml"
    baselines: str | None = "reference/baselines.toml"


class CounterfactualSource(StrEnum):
    """Where answers come from (ADR-0014). ``live`` is the first key of the
    "two keys" rule; ``live.enabled`` is the second."""

    FAKE = "fake"
    LOGGED_MATCH = "logged_match"
    RECORDED = "recorded"
    LIVE = "live"
    PROXY = "proxy"


class ExperimentSettings(ContractModel):
    """What a run asks for. Experiment config files set these (Stage 8 adds
    strategy loading)."""

    name: str = "default"
    counterfactual_source: CounterfactualSource = CounterfactualSource.FAKE
    seed: int = 0


class EmbeddingSettings(ContractModel):
    """Semantic-tier embedder choice (Stage 8). ``fake`` is offline."""

    backend: Name = "fake"
    model: str | None = None


class DatabaseSettings(ContractModel):
    """Future PostgreSQL (deployment_and_data.md; Stage 9). Nothing reads it
    yet. The password is a secret (``METIS_DB_PASSWORD``)."""

    enabled: bool = False
    host: str = "localhost"
    port: int = Field(default=5432, gt=0, lt=65536)
    name: str = "metis"
    user: str = "metis"


class DevSettings(ContractModel):
    """Local-development conveniences."""

    ephemeral_fingerprint_key: bool = True
    """Without ``METIS_FINGERPRINT_KEY``, use a random key for this process
    (A-44: fingerprints then don't compare across runs). False = refuse."""


class Settings(ContractModel):
    """The merged, validated, non-secret settings. Frozen for a run."""

    paths: PathSettings = PathSettings()
    logging: LoggingSettings = LoggingSettings()
    live: LiveSettings = LiveSettings()
    budget: BudgetSettings = BudgetSettings()
    reference: ReferenceSettings = ReferenceSettings()
    experiment: ExperimentSettings = ExperimentSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    database: DatabaseSettings = DatabaseSettings()
    dev: DevSettings = DevSettings()
    pipeline: dict[str, dict[str, Any]] = {}
    """Policy sections (``routing``, ``cache``, ``context``, ``attempts``,
    ``features``, ``accounting``), opaque here; wiring validates them."""


HASH_EXCLUDED_SECTIONS = ("paths", "logging", "reference")
"""Sections left out of the config hash: machine-local or replaced by
reference version IDs (configuration.md §3 rule 6)."""


class Secrets(ContractModel):
    """Secret values from the environment or ``.env`` only (configuration.md
    §3 rule 7). pydantic's secret types hide the value in ``repr``, ``str``,
    and dumps; call ``get_secret_value()`` only where a secret is handed to
    the one component that needs it (wiring)."""

    metis_api_key: SecretStr | None = None
    fingerprint_key: SecretBytes | None = None
    database_password: SecretStr | None = None

    def presence(self) -> dict[str, bool]:
        """Which secrets are set: safe to log and record (never the values)."""
        return {
            name: getattr(self, name) is not None for name in type(self).model_fields
        }


class ApiFormat(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    GOOGLE_GENAI = "google_genai"


class EndpointStatus(StrEnum):
    ENABLED = "enabled"
    DEFERRED = "deferred"


class ProviderEndpoint(ContractModel):
    """How to reach one model family through the Metis wrapper. Config, not
    a secret: the credential is named by ``secret``, never stored here."""

    family: Name
    base_url: str = Field(pattern=r"^https://")
    api_format: ApiFormat
    auth_header: str
    secret: str = "metis_api_key"
    status: EndpointStatus
    evidence: Sourced


class EndpointTable(ContractModel):
    version: Version
    endpoints: tuple[ProviderEndpoint, ...]

    def get(self, family: str) -> ProviderEndpoint | None:
        return next((e for e in self.endpoints if e.family == family), None)


class BaselineMethod(StrEnum):
    ESTIMATE_ONLY = "estimate_only"
    """Never called: cost estimated from counted tokens (brief §5)."""
    PIPELINE_RUN = "pipeline_run"
    """A fixed_model pipeline run with the run's answer source (ADR-0014)."""
    FROM_REPLAY_CASES = "from_replay_cases"
    """Computed directly from replay cases, no model call (ADR-0014 point 4)."""


class BaselineDefinition(ContractModel):
    name: Name
    model_id: Name | None = None
    """None = unset placeholder: costs are "not computed" (ADR-0002)."""
    method: BaselineMethod


class BaselineTable(ContractModel):
    version: Version
    baselines: tuple[BaselineDefinition, ...]


class PendingPriceRow(ContractModel):
    """A price row the current ``PriceTable`` schema cannot represent yet
    (context-length tiers, cache writes). Parsed and validated, kept aside,
    never used for costs until Stage 7 extends the schema."""

    price_ref: Name
    context_tier: Name
    min_context_tokens: int | None = None
    max_context_tokens: int | None = None
    amounts: dict[str, Decimal]


@dataclass(frozen=True)
class ReferenceData:
    """Reference data loaded from ``config/`` (configuration.md §1)."""

    catalogue: ModelCatalogue
    prices: PriceTable
    endpoints: EndpointTable | None = None
    baselines: BaselineTable | None = None
    pending_prices: tuple[PendingPriceRow, ...] = ()

    def versions(self) -> dict[str, str]:
        found = {"catalogue": self.catalogue.version, "prices": self.prices.version}
        if self.endpoints is not None:
            found["endpoints"] = self.endpoints.version
        if self.baselines is not None:
            found["baselines"] = self.baselines.version
        return found


@dataclass(frozen=True)
class LoadedSettings:
    """What ``load_settings`` returns: settings, secrets, reference data, the
    config hash, and which layers contributed (for manifests and debugging)."""

    settings: Settings
    secrets: Secrets
    reference: ReferenceData
    config_hash: str
    layers: tuple[str, ...]
    root: Path
    """Directory relative settings paths resolve against (the config
    directory's parent: the checkout, or ``/app`` in the image)."""

    def path(self, value: str) -> Path:
        """A settings path made absolute against ``root``."""
        p = Path(value)
        return p if p.is_absolute() else self.root / p
