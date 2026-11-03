"""Decision-router infrastructure settings (``[router]``, ``[data]``;
ADR-XXXX (system-one-decision-router)).

Responsibility: the typed form of the router's *infrastructure* settings:
mode, deadline, backends and their chains, the router-result cache, the
circuit breaker, the confidence gate, and the runtime-only approval flags.
The routing *policy* knobs (gate rules, mapping thresholds, dynamic criteria,
hysteresis, state truncation, safe tier) are policy configuration under
``[pipeline.routing.decision_router]``, validated by the domain policy's own
config type (configuration.md §3 rule 5), not here.

Also ``DevSliceSettings`` (``[data]``): where the full dataset lives on this
machine. Machine-specific, so it belongs in the git-ignored
``config/local.toml`` or ``METIS__DATA__FULL_DATA_ROOT``, never in committed
configuration; it is left out of the config hash.

Called by: settings.model (fields of ``Settings``), wiring.routers (R4+).
Traces: FR-FEAT-02, FR-ROUTE-03/04, FR-FAIL-04/05, FR-ACCT-03, QA-LAT,
QA-PRIV, ADR-0018, ADR-0019.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from metis_auto.contracts import ContractModel, Name, QuestionLanguage, Version


class RouterMode(StrEnum):
    """Which decision backends the cascade may use (routing.md §7)."""

    OFF = "off"
    """No decision router is built; routing is unchanged (serving default)."""
    HOSTED = "hosted"
    LOCAL = "local"
    HYBRID_LOCAL_FIRST = "hybrid_local_first"
    HYBRID_HOSTED_FIRST = "hybrid_hosted_first"


HOSTED_TYPES = frozenset({"jev_metis", "llm_system_one"})
LOCAL_TYPES = frozenset({"thx01", "systemone_http", "fake"})
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class _Backend(ContractModel):
    enabled: bool = False
    timeout_ms: float = Field(gt=0)
    """Per-call deadline; the cascade further limits it to the time left."""


class JevMetisBackendSettings(_Backend):
    """Mode 1: Jev (TypeSafe) through the Metis wrapper. Shadow and labelling
    only by owner decision (2026-11-02): never required inline."""

    type: Literal["jev_metis"] = "jev_metis"
    base_url: str = "https://api.metisai.ir/typesafe"
    """The TypeSafe wrapper; the backend posts to ``<base_url>/v1/systemone``
    (Metis page, saved 2026-11-02). Not an ``endpoints-metis.toml`` row: those
    describe OpenAI-compatible chat endpoints, and Jev is neither (J-1, J-2;
    the plan adds an endpoint row only for an OpenAI-compatible model)."""
    model: str = Field(default="jev-latest", min_length=1)
    """The Metis page offers only ``jev-latest`` (checked 2026-11-02)."""
    price_ref: Name | None = None
    """Row in the router price table (``reference.router_prices``). Unset means
    the price is unknown: calls are not computed and refused unless
    ``allow_unpriced``. Default config: ``metis-jev-latest`` (Metis pricing
    page, checked by the owner 2026-11-02)."""
    state_format: Literal["text", "json"] = "text"
    timeout_ms: float = Field(default=1500, gt=0)

    @field_validator("base_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if urlsplit(value).scheme != "https":
            raise ValueError("jev_metis.base_url must be https")
        return value.rstrip("/")


class LlmSystemOneBackendSettings(_Backend):
    """Mode 1 backup: a tier-0 chat model asked for a JSON answer through the
    Metis OpenAI wrapper. Uncalibrated."""

    type: Literal["llm_system_one"] = "llm_system_one"
    model_id: Name = "gpt-4o-mini"
    """A catalogue model ID; its price and endpoint come from the catalogue.
    ``gpt-4o-mini`` since 2026-11-03: Metis answered ``gpt-4.1-nano`` with
    HTTP 404 model_not_found in the live check (TODO-17)."""
    max_output_tokens: int = Field(default=300, gt=0)
    state_format: Literal["text", "json"] = "text"
    timeout_ms: float = Field(default=2000, gt=0)


class Thx01BackendSettings(_Backend):
    """Mode 2 default: THX-01 in-process (the repository's root checkpoint, a
    multilingual mmBERT model), offline."""

    type: Literal["thx01"] = "thx01"
    asset: Name = "thx01"
    """Row in ``config/reference/routers.toml`` (revision and sha256 pins)."""
    runtime: Literal["torch", "onnx"] = "torch"
    """``onnx`` (int8) is the fallback if torch misses the latency budget
    (ADR-XXXX (system-one-decision-router) point 4); not built until the R5 benchmark
    asks for it."""
    threads: int = Field(default=4, ge=1, le=64)
    state_format: Literal["text", "json"] = "text"
    """How the state is rendered for the model (``text`` is shorter)."""
    timeout_ms: float = Field(default=60, gt=0)


class SystemOneHttpBackendSettings(_Backend):
    """Mode 2 via a local ``/v1/systemone`` server the owner starts (Mizan on
    llama-server, or THX-01's own server). Loopback only: dataset text may be
    sent to it because it never leaves the machine."""

    type: Literal["systemone_http"] = "systemone_http"
    base_url: str = "http://127.0.0.1:8080"
    model: str = Field(default="mizan-1.5-4b-q4_k_m", min_length=1)
    health_path: str = Field(default="/health", pattern=r"^/[A-Za-z0-9_./\-]*$")
    """llama-server and THX-01's own server answer ``GET /health``."""
    health_timeout_ms: float = Field(default=200, gt=0)
    state_format: Literal["text", "json"] = "text"
    timeout_ms: float = Field(default=400, gt=0)

    @field_validator("base_url")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or parts.hostname not in (
            LOOPBACK_HOSTS
        ):
            raise ValueError(
                "systemone_http serves local models only: base_url must be "
                "http(s) on 127.0.0.1, localhost or ::1"
            )
        return value.rstrip("/")


class FakeBackendSettings(_Backend):
    """Scripted, deterministic answers (tests, demos without weights)."""

    type: Literal["fake"] = "fake"
    profile: Literal["neutral", "cheap", "complex"] = "neutral"
    latency_ms: float = Field(default=0.0, ge=0)
    timeout_ms: float = Field(default=60, gt=0)


BackendSettings = Annotated[
    JevMetisBackendSettings
    | LlmSystemOneBackendSettings
    | Thx01BackendSettings
    | SystemOneHttpBackendSettings
    | FakeBackendSettings,
    Field(discriminator="type"),
]


def backend_kind(settings: BackendSettings) -> Literal["hosted", "local"]:
    return "hosted" if settings.type in HOSTED_TYPES else "local"


class RouterCacheSettings(ContractModel):
    """In-process router-result cache, keyed by a keyed fingerprint of the
    normalised state plus question set, backend and model revision."""

    enabled: bool = True
    max_entries: int = Field(default=10_000, gt=0)
    ttl_s: float = Field(default=86_400, gt=0)
    normalisation: Name = "persian_fold_v1"
    """An ADR-0025 treatment, by name."""


class RouterCircuitSettings(ContractModel):
    """Per-backend circuit breaker (the router's own health tracker, FR-FAIL-05)."""

    failure_threshold: int = Field(default=3, ge=1)
    window_s: float = Field(default=60, gt=0)
    cooldown_s: float = Field(default=30, gt=0)


DEFAULT_CHAINS: dict[str, tuple[str, ...]] = {
    "local": ("thx01",),
    "hosted": ("jev_metis",),
    "hybrid_local_first": ("thx01", "jev_metis"),
    "hybrid_hosted_first": ("jev_metis", "thx01"),
}


def _default_backends() -> dict[str, BackendSettings]:
    return {
        "jev_metis": JevMetisBackendSettings(),
        "llm_system_one": LlmSystemOneBackendSettings(),
        "thx01": Thx01BackendSettings(),
        "mizan_http": SystemOneHttpBackendSettings(),
    }


class RouterSettings(ContractModel):
    """``[router]``: decision-router infrastructure. Every value is a
    placeholder until the routing experiment (exp-route-013) gives evidence."""

    mode: RouterMode = RouterMode.OFF
    """Serving default stays ``off`` (ADR-0023 rules; owner decision)."""
    deadline_ms: float = Field(default=60, gt=0)
    """Budget for the whole decision step: the local router's own 60 ms p95
    inside the 100 ms overall overhead (Q-14; owner decision 2026-11-02)."""
    deadline_grace_ms: float = Field(default=10, ge=0)
    """An in-process call may overrun by this much before it is reported."""
    reserved_pipeline_ms: float = Field(default=0, ge=0)
    """Time kept back for the rest of the pipeline when a request deadline is set."""
    min_confidence: float = Field(default=0.6, ge=0, le=1)
    """Below this, an answered decision becomes ``failed(low_confidence)``."""
    keep_soft_signals: bool = False
    """Keep low-confidence answers on the outcome as soft signals."""
    escalate_on_low_confidence: bool = False
    """A low-confidence answer passes to the next backend of the chain while
    time and budget remain (true), or ends the chain (false, default; A-103,
    owner 2026-11-02). R8 compares both."""
    confidence_questions: Literal["mapping", "all"] = "mapping"
    """Which answers the confidence gate looks at (Q-61, owner 2026-11-03):
    ``mapping`` (default) = the lowest confidence among the questions the
    tier mapping uses (complexity, needs_reasoning, cheap_model_ok); ``all`` =
    every answer, including the 10-option intent question."""
    confidence_statistic: Literal["reported", "probability"] = "reported"
    """What the gate reads per answer: ``reported`` = the backend's own
    ``confidence`` (THX-01: normalised entropy); ``probability`` = the top
    option's or level's probability, ``max(p, 1 - p)`` for yes/no. Chosen by
    the R8 shadow evaluation on the tune split (provisional)."""
    question_set: Version = "routing_qs_v1"
    question_language: QuestionLanguage = QuestionLanguage.ENGLISH
    real_data_approved: bool = False
    """Runtime layer only. Lets a hosted backend receive a dataset-derived
    state for this run. Owner decision 2026-11-02: stays false until Metis
    confirms in writing (licence §4)."""
    allow_unpriced: bool = False
    """Runtime layer only. Lets a hosted backend with no configured price be
    called; its cost is then recorded as not computed, never as zero."""
    cache: RouterCacheSettings = RouterCacheSettings()
    circuit: RouterCircuitSettings = RouterCircuitSettings()
    backends: dict[Name, BackendSettings] = Field(default_factory=_default_backends)
    chains: dict[str, tuple[Name, ...]] = Field(
        default_factory=lambda: dict(DEFAULT_CHAINS)
    )

    @model_validator(mode="after")
    def _check_chains(self) -> RouterSettings:
        modes = {m.value for m in RouterMode} - {RouterMode.OFF.value}
        unknown_modes = set(self.chains) - modes
        if unknown_modes:
            raise ValueError(f"router.chains: unknown modes {sorted(unknown_modes)}")
        for mode, chain in self.chains.items():
            missing = [name for name in chain if name not in self.backends]
            if missing:
                raise ValueError(f"router.chains.{mode}: unknown backends {missing}")
            if len(set(chain)) != len(chain):
                raise ValueError(f"router.chains.{mode}: a backend appears twice")
        if self.mode == RouterMode.OFF:
            return self
        chain = self.chains.get(self.mode.value, ())
        if not chain:
            raise ValueError(f"router.mode = {self.mode.value!r} needs a chain")
        disabled = [name for name in chain if not self.backends[name].enabled]
        if disabled:
            raise ValueError(
                f"router.mode = {self.mode.value!r}: chain backends not enabled: "
                f"{disabled} (enable them under [router.backends.<name>])"
            )
        kinds = [backend_kind(self.backends[name]) for name in chain]
        if self.mode == RouterMode.LOCAL and "hosted" in kinds:
            raise ValueError("router.mode = 'local' may use local backends only")
        if self.mode == RouterMode.HOSTED and "local" in kinds:
            raise ValueError(
                "router.mode = 'hosted' may use hosted backends only "
                "(use hybrid_hosted_first for a local safety net)"
            )
        first = {"hybrid_local_first": "local", "hybrid_hosted_first": "hosted"}
        expected = first.get(self.mode.value)
        if expected is not None and kinds[0] != expected:
            raise ValueError(
                f"router.mode = {self.mode.value!r}: the chain must start with a "
                f"{expected} backend"
            )
        return self

    def active_chain(self) -> tuple[str, ...]:
        """Backend names the cascade tries, in order; empty when off."""
        if self.mode == RouterMode.OFF:
            return ()
        return self.chains[self.mode.value]


class DevSliceSettings(ContractModel):
    """``[data]``: where the full dataset is on this machine (machine-local)."""

    full_data_root: str = Field(default="data/full_data/raw", min_length=1)
    """Relative to the repository root, or absolute. Resolved with pathlib
    (``Path.resolve()`` follows the NTFS junction on Windows)."""
