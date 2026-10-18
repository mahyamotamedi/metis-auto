"""Configuration loading: secrets, runtime config, experiment config, defaults.

Reads files and environment, merges layers by precedence, validates shape,
and never logs secrets (Stage 6, ADR-0019). Knows no specific policy; wiring
maps settings onto components.

May import: contracts.
Traces: MP section 4 (configuration over code), ADR-0003, ADR-0018, ADR-0019.
"""

from .loader import (
    SECRET_ENV,
    SettingsError,
    config_hash,
    default_config_dir,
    load_settings,
    read_dotenv,
    read_secrets,
    repo_root,
)
from .model import (
    BaselineDefinition,
    BaselineMethod,
    BudgetSettings,
    CounterfactualSource,
    EndpointStatus,
    LoadedSettings,
    PendingPriceRow,
    ProviderEndpoint,
    ReferenceData,
    Secrets,
    Settings,
)
from .reference import ReferenceDataError, load_reference

__all__ = [
    "SECRET_ENV",
    "BaselineDefinition",
    "BaselineMethod",
    "BudgetSettings",
    "CounterfactualSource",
    "EndpointStatus",
    "LoadedSettings",
    "PendingPriceRow",
    "ProviderEndpoint",
    "ReferenceData",
    "ReferenceDataError",
    "Secrets",
    "Settings",
    "SettingsError",
    "config_hash",
    "default_config_dir",
    "load_reference",
    "load_settings",
    "read_dotenv",
    "read_secrets",
    "repo_root",
]
