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
from typing import Any, Literal

from pydantic import Field, SecretBytes, SecretStr, field_validator, model_validator

from metis_auto.contracts import (
    ChatTemplate,
    ContractModel,
    Fidelity,
    MetricName,
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
    tokenizer_assets: str = "data/tokenizers"
    """Tokenizer files fetched once by scripts/fetch_tokenizer_assets.py
    (git-ignored; token_accounting.md §2)."""
    compressor_assets: str = "data/compressors"
    """Context-compressor model files (LLMLingua-2) fetched once by
    scripts/fetch_compressor_assets.py (git-ignored; Demo milestone)."""


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
    prices: str = "reference/prices-metis-2026-10-18-g55.toml"
    endpoints: str | None = "reference/endpoints-metis.toml"
    baselines: str | None = "reference/baselines.toml"
    tokenizers: str | None = "reference/tokenizers.toml"
    label_mapping: str | None = "reference/label-mapping-sample-v1.toml"
    """Logged model label → catalogue model, for the as-logged baseline
    (Stage 8; contracts.md O-3)."""
    compressors: str | None = "reference/compressors.toml"
    """Pinned context-compressor models (Demo milestone, experimental)."""


class CounterfactualSource(StrEnum):
    """Where answers come from (ADR-0014). ``live`` is the first key of the
    "two keys" rule; ``live.enabled`` is the second."""

    FAKE = "fake"
    LOGGED_MATCH = "logged_match"
    RECORDED = "recorded"
    LIVE = "live"
    PROXY = "proxy"


EXPERIMENT_ID = r"^exp-(cache|route|ctx|cost|eval)-[0-9]{3}$"
"""EXP-ID naming (docs/experiments/framework.md §2): area code + number,
lower case, e.g. ``exp-cache-001``. Folder ``experiments/<area>/<id>-<slug>/``."""


class ExperimentKind(StrEnum):
    """Which runner a run uses (docs/experiments/framework.md §3)."""

    PIPELINE_REPLAY = "pipeline_replay"
    """Cases through the real ``RequestPipeline`` (routing, context, serving
    cache); metrics from its events."""
    CACHE_CANDIDATES = "cache_candidates"
    """Cases through a ``CandidateIndex`` under many key variants and scopes
    at once (caching.md §4); metrics from ``cache_lookup`` events."""


class StrategySlot(StrEnum):
    """Interfaces a candidate strategy can implement (framework.md §4)."""

    ROUTING_POLICY = "routing_policy"
    """``domain.routing.RoutingPolicy``, injected into the candidate pipeline."""
    CONTEXT_STRATEGY = "context_strategy"
    """``domain.context.ContextStrategy``, injected into the candidate pipeline."""
    CANDIDATE_INDEX = "candidate_index"
    """``evaluation.cache_candidates.CandidateIndex`` factory."""


class StrategySettings(ContractModel):
    """The candidate under test. Only an experiment file may set it (the
    loader refuses it in every other layer), so production defaults can never
    load unpromoted code (repository_structure §6.2)."""

    slot: StrategySlot
    builtin: Name | None = None
    """A component already in ``metis_auto`` (promoted or reference)."""
    file: str | None = None
    """Candidate code, relative to the experiment file's folder; must lie
    under ``experiments/`` (wiring.experiments)."""
    object: str | None = None
    """Class or factory name inside ``file``."""
    version: str = "0"
    params: dict[str, Any] = {}
    """Opaque here; validated by the strategy's own config type."""

    @model_validator(mode="after")
    def _one_source(self) -> StrategySettings:
        if (self.builtin is None) == (self.file is None):
            raise ValueError("experiment.strategy needs exactly one of builtin, file")
        if self.file is not None and not self.object:
            raise ValueError("experiment.strategy.file needs object")
        return self


class DataSliceSettings(ContractModel):
    """Which cases a run uses (framework.md §1)."""

    dataset: Literal["sample_v1"] = "sample_v1"
    """Only the sample loader exists (synthetic and full datasets: Stage 9)."""
    missing_key: Literal["unknown", "absent"] = "absent"
    """Sample loader: an optional key missing from a message is absent
    (default: the export lists these keys only when present; Q-37, A-61) or
    unknown (reason ``key_missing``, the conservative alternative run).
    Nulls are unknown either way (``not_in_log``, Q-25)."""
    pairing_flags: tuple[str, ...] = (
        "clean",
        "multiple_answers",
        "skipped_consecutive_user",
        "unanswered",
    )
    """Admitted pairing flags (FR-EVAL-08); the others become exclusions."""
    ordering: Literal["logged_time", "session_order"] = "logged_time"
    """Case order (A-31): naive logged time, ties by session and turn; or
    session by session in log order."""
    max_sessions: int | None = Field(default=None, gt=0)
    """Use only the first N sessions (smoke runs)."""

    @field_validator("pairing_flags")
    @classmethod
    def _flags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if "no_preceding_user" in value:
            raise ValueError("no_preceding_user records are never cases")
        return value


class ExperimentSettings(ContractModel):
    """What a run asks for (layer 3: experiment files; framework.md §1)."""

    id: str | None = Field(default=None, pattern=EXPERIMENT_ID)
    """EXP-ID; required by the experiment runner, None for ad-hoc runs."""
    name: str = "default"
    kind: ExperimentKind = ExperimentKind.PIPELINE_REPLAY
    counterfactual_source: CounterfactualSource = CounterfactualSource.FAKE
    seed: int = 0
    hypotheses: tuple[str, ...] = ()
    """H-n IDs the experiment tests (context.md §5.2)."""
    baselines: tuple[Name, ...] = ("as_logged", "premium")
    """Baselines to report; ``as_logged`` is mandatory (ADR-0002)."""
    metrics: tuple[MetricName, ...] = ()
    """Metrics the plan relies on; each appears in the results, measured or
    with the reason it is not."""
    prompt_composition: Name = "logged_full"
    """Assumed prompt composition (context_construction.md §4): logged
    instructions as instructions, full logged history, logged retrieved
    context, the message."""
    data: DataSliceSettings = DataSliceSettings()
    strategy: StrategySettings | None = None

    @field_validator("baselines")
    @classmethod
    def _as_logged(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if "as_logged" not in value:
            raise ValueError("every experiment reports the as_logged baseline")
        return value


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


class ThinkingMode(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class ModelRequestOptions(ContractModel):
    """Provider request options for one catalogue model (Stage 7.5, Q-34).
    Unset = the provider's default: nothing is sent. Part of the config hash,
    since an option can change answers and costs. An experiment file may set
    them (Stage 8 compares them); the endpoint must allow each option."""

    thinking: ThinkingMode | None = None
    """``thinking: {"type": ...}`` as documented by DeepSeek and Xiaomi MiMo
    (both default to enabled). The chat templates in ``tokenizers.toml`` are
    for each provider's default; with the other mode the counted framing is
    off by a few tokens (DeepSeek: over, MiMo: under; ADR-0021)."""


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
    model_options: dict[str, ModelRequestOptions] = {}
    """Per catalogue model ID, e.g. ``[model_options."deepseek-v4-flash"]``."""
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


class MaxTokensParam(StrEnum):
    """Request field that carries the generation limit (Stage 7.5)."""

    MAX_COMPLETION_TOKENS = "max_completion_tokens"
    """OpenAI: includes reasoning tokens; ``max_tokens`` is deprecated and not
    compatible with reasoning models (openai SDK 3.24.0 docstrings)."""
    MAX_TOKENS = "max_tokens"


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
    max_tokens_param: MaxTokensParam | None = None
    """Required for an enabled ``openai_chat_completions`` endpoint: the live
    adapter always sends a generation limit (cost control)."""
    request_options: tuple[str, ...] = ()
    """``ModelRequestOptions`` fields this family documents (e.g. thinking);
    an option for a model of another family is a configuration error."""

    @model_validator(mode="after")
    def _check(self) -> ProviderEndpoint:
        live_ready = (
            self.status == EndpointStatus.ENABLED
            and self.api_format == ApiFormat.OPENAI_CHAT_COMPLETIONS
        )
        if live_ready and self.max_tokens_param is None:
            raise ValueError(f"endpoint {self.family}: set max_tokens_param")
        return self


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


class LabelFidelity(StrEnum):
    """How well a logged label identifies a priced catalogue model (FR-ACCT-07)."""

    EXACT_ID = "exact_id"
    """The label equals a catalogue model ID. The snapshot or version served
    at log time is still unknown (A-07)."""
    ALIAS = "alias"
    """A documented alias of a catalogue model (e.g. a legacy name the
    provider redirects); whether the alias applied at log time is unknown."""


class UnmappedReason(StrEnum):
    NOT_IN_CATALOGUE = "not_in_catalogue"
    """A real model with no catalogue row or price."""
    NOT_A_MODEL = "not_a_model"
    """A label that names no model (e.g. a workflow), A-16."""


class LabelMappingEntry(ContractModel):
    label: str = Field(min_length=1)
    model_id: Name | None = None
    fidelity: LabelFidelity | None = None
    unmapped: UnmappedReason | None = None
    evidence: Sourced | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check(self) -> LabelMappingEntry:
        mapped = self.model_id is not None
        if mapped != (self.fidelity is not None) or mapped == (
            self.unmapped is not None
        ):
            raise ValueError(
                f"label {self.label!r}: a mapped label has model_id and fidelity; "
                "an unmapped one has only unmapped"
            )
        if self.fidelity == LabelFidelity.ALIAS and self.evidence is None:
            raise ValueError(f"label {self.label!r}: an alias needs evidence")
        return self


class LabelMapping(ContractModel):
    """Logged model labels of one dataset → catalogue models (contracts.md
    §4; the as-logged baseline, evaluation.md §5). A label not listed is
    unmapped (``not_listed``)."""

    version: Version
    dataset: Name
    labels: tuple[LabelMappingEntry, ...]

    def get(self, label: str) -> LabelMappingEntry | None:
        return next((e for e in self.labels if e.label == label), None)

    def model_ids(self) -> dict[str, str]:
        """Mapped label → model ID (for the replay client)."""
        return {e.label: e.model_id for e in self.labels if e.model_id is not None}


class TokenizerBackend(StrEnum):
    TIKTOKEN = "tiktoken"
    """OpenAI's tiktoken with a named encoding (adapters.tokenizers)."""
    HF_TOKENIZERS = "hf_tokenizers"
    """A Hugging Face ``tokenizer.json`` read with the ``tokenizers`` library."""
    APPROX_CHARS = "approx_chars"
    """Characters ÷ ``chars_per_token``: a labelled approximation."""


class TokenizerAsset(ContractModel):
    """A tokenizer file fetched once (scripts/fetch_tokenizer_assets.py) and
    checked by sha256 before every load. Never downloaded at run time."""

    path: str
    """Relative to ``paths.tokenizer_assets``."""
    url: str = Field(pattern=r"^https://")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, gt=0)


class TokenizerSpec(ContractModel):
    """How to count tokens for one tokenizer family (catalogue
    ``tokenizer_ref``), with its fidelity and evidence (MP§3.8)."""

    ref: Name
    backend: TokenizerBackend
    fidelity: Fidelity
    """``exact_local`` only with an official or vendor-published tokenizer."""
    evidence: Sourced
    encoding: str | None = None
    """tiktoken encoding name (backend ``tiktoken``)."""
    asset: TokenizerAsset | None = None
    library: str | None = None
    """Library and version the asset was checked with, e.g. tiktoken==0.14.0."""
    chars_per_token: int | None = Field(default=None, gt=0)
    """Backend ``approx_chars`` only."""
    template: ChatTemplate | None = None
    """Chat-template overhead; None = not modelled (not added)."""
    mode_templates: dict[Name, ChatTemplate] = {}
    """Framing for a non-default provider mode, keyed by mode name, e.g.
    ``thinking_disabled`` (Demo milestone, Q-34). Wiring uses it for a model
    whose ``[model_options]`` select that mode; otherwise ``template``."""

    @model_validator(mode="after")
    def _check(self) -> TokenizerSpec:
        exact = self.backend != TokenizerBackend.APPROX_CHARS
        if exact and self.asset is None:
            raise ValueError(f"tokenizer {self.ref}: backend needs an asset")
        if self.backend == TokenizerBackend.TIKTOKEN and not self.encoding:
            raise ValueError(f"tokenizer {self.ref}: tiktoken needs an encoding")
        if not exact and self.fidelity != Fidelity.APPROXIMATION:
            raise ValueError(f"tokenizer {self.ref}: approx_chars is an approximation")
        if not exact and self.chars_per_token is None:
            raise ValueError(
                f"tokenizer {self.ref}: approx_chars needs chars_per_token"
            )
        if self.template is not None and self.template.tokenizer_ref != self.ref:
            raise ValueError(f"tokenizer {self.ref}: template is for another ref")
        if any(t.tokenizer_ref != self.ref for t in self.mode_templates.values()):
            raise ValueError(f"tokenizer {self.ref}: mode template for another ref")
        return self


class TokenizerTable(ContractModel):
    version: Version
    tokenizers: tuple[TokenizerSpec, ...]

    def get(self, ref: str) -> TokenizerSpec | None:
        return next((t for t in self.tokenizers if t.ref == ref), None)


class CompressorBackend(StrEnum):
    LLMLINGUA2 = "llmlingua2"
    """LLMLingua-2 token classification (``llmlingua`` package, extra
    ``compress``)."""


class CompressorAsset(ContractModel):
    """One model file, fetched once (scripts/fetch_compressor_assets.py) and
    checked by sha256 before every load. Never downloaded at run time."""

    name: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    """File name inside the compressor's directory."""
    url: str = Field(pattern=r"^https://")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, gt=0)


class CompressorSpec(ContractModel):
    """A pinned context-compression model (Demo milestone; context plan X3).
    Experimental: unpromoted, needs ablation evidence (FR-CTX-03)."""

    ref: Name
    backend: CompressorBackend
    model: str
    """Hugging Face repository ID, for the record (the files are local)."""
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    licence: str
    library: str
    """Library and version it was checked with, e.g. llmlingua==0.2.2."""
    evidence: Sourced
    files: tuple[CompressorAsset, ...] = Field(min_length=1)

    @property
    def directory(self) -> str:
        """Relative to ``paths.compressor_assets``."""
        return f"{self.ref}/{self.revision}"


class CompressorTable(ContractModel):
    version: Version
    compressors: tuple[CompressorSpec, ...]

    def get(self, ref: str) -> CompressorSpec | None:
        return next((c for c in self.compressors if c.ref == ref), None)


@dataclass(frozen=True)
class ReferenceData:
    """Reference data loaded from ``config/`` (configuration.md §1)."""

    catalogue: ModelCatalogue
    prices: PriceTable
    endpoints: EndpointTable | None = None
    baselines: BaselineTable | None = None
    tokenizers: TokenizerTable | None = None
    label_mapping: LabelMapping | None = None
    compressors: CompressorTable | None = None

    def versions(self) -> dict[str, str]:
        found = {"catalogue": self.catalogue.version, "prices": self.prices.version}
        if self.endpoints is not None:
            found["endpoints"] = self.endpoints.version
        if self.baselines is not None:
            found["baselines"] = self.baselines.version
        if self.tokenizers is not None:
            found["tokenizers"] = self.tokenizers.version
        if self.label_mapping is not None:
            found["label_mapping"] = self.label_mapping.version
        if self.compressors is not None:
            found["compressors"] = self.compressors.version
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
