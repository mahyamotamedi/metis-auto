"""Experiment wiring (CMP-20 for CMP-24; docs/experiments/framework.md).

Responsibility: turn an experiment config file (layer 3, ADR-0019) into a
ready ``ExperimentRunner`` and its cases:
- settings: ``load_settings(experiment=path)``;
- the **candidate-loading mechanism** (A-26, repository_structure §6.2):
  ``[experiment.strategy]`` names either a ``builtin`` component of
  ``metis_auto`` or a ``file`` + ``object`` inside the experiment's folder.
  A file must resolve under ``<repo>/experiments/`` and is loaded with
  ``importlib`` under a private module name; nothing in ``metis_auto``
  imports it, and the loader refuses ``[experiment.strategy]`` in every layer
  but the experiment file, so production defaults can never load it;
- data: the sample loader (opaque refs from the keyed fingerprinter) and the
  replay-case builder; the data hash is the sha256 of the file read;
- the counterfactual client for pipeline runs (``fake``, ``logged_match``,
  ``recorded``, ``proxy``; ``live`` is refused here: live experiment runs
  need their own owner approval and go through ``wiring.live``);
- the ``RunManifest`` (code version from git, hardware) and the run folder
  ``runs/<EXP-ID>/<run-id>/``.
Called by: scripts/run_experiment.py, tests. Calls: settings, data_access,
adapters, evaluation, wiring.pipeline / from_settings.
"""

from __future__ import annotations

import hashlib
import importlib.util
import platform
import secrets
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from metis_auto.adapters.providers import (
    FakeModelClient,
    ProxyModelClient,
    ReplayModelClient,
)
from metis_auto.adapters.sinks import JsonLinesEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.adapters.system import SequentialIdSource, SystemClock
from metis_auto.adapters.tokenizers import ApproxCharsTokenizer
from metis_auto.application.measurement import Fingerprinter, MeasurementService
from metis_auto.contracts import (
    CodeVersion,
    CounterfactualSource,
    ExclusionCount,
    PairingFlag,
    ReplayCase,
    RunManifest,
    RunMode,
)
from metis_auto.data_access.replay_cases.builder import build_all
from metis_auto.data_access.sample.loader import SampleDataSource
from metis_auto.evaluation.cache_candidates import BUILTIN_INDEXES
from metis_auto.evaluation.runner import ExperimentRunner, RunSetup
from metis_auto.ports import EventSink, IdSource, ModelClient
from metis_auto.settings import (
    ExperimentKind,
    LoadedSettings,
    StrategySettings,
    StrategySlot,
    load_settings,
    repo_root,
)

from .from_settings import (
    build_accounting_service,
    build_pipeline_from_settings,
    fingerprint_key,
    pipeline_config,
)
from .pipeline import versions_for

SAMPLE_PATH = Path("data/sample_data/raw/data.json")


class ExperimentError(ValueError):
    """An experiment config or candidate cannot be used."""


# --- candidate loading -------------------------------------------------------


def load_candidate(
    spec: StrategySettings, experiment_dir: Path, experiments_root: Path
) -> Any:
    """The object a strategy names: a built-in, or ``object`` from ``file``
    under ``experiments_root`` (never anywhere else)."""
    if spec.builtin is not None:
        if (
            spec.slot == StrategySlot.CANDIDATE_INDEX
            and spec.builtin in BUILTIN_INDEXES
        ):
            return BUILTIN_INDEXES[spec.builtin]
        raise ExperimentError(
            f"no built-in {spec.slot.value} {spec.builtin!r}; promoted routing and "
            "context components are chosen in [pipeline.*], not here"
        )
    assert spec.file is not None and spec.object is not None
    path = (experiment_dir / spec.file).resolve()
    root = experiments_root.resolve()
    if not path.is_relative_to(root) or path.suffix != ".py" or not path.is_file():
        raise ExperimentError(
            f"candidate file must be an existing .py file under {root}: {spec.file}"
        )
    name = "metis_experiment_" + hashlib.sha256(str(path).encode()).hexdigest()[:12]
    module_spec = importlib.util.spec_from_file_location(name, path)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    if not hasattr(module, spec.object):
        raise ExperimentError(f"{spec.file} has no {spec.object!r}")
    return getattr(module, spec.object)


# --- data ----------------------------------------------------------------------


@dataclass(frozen=True)
class CaseSet:
    cases: tuple[ReplayCase, ...]
    exclusions: tuple[ExclusionCount, ...]
    dataset: str
    data_hash: str


def sample_cases(
    loaded: LoadedSettings, fingerprinter: Fingerprinter, path: Path | None = None
) -> CaseSet:
    """Cases from the sample file (read-only), or from ``path`` (tests:
    synthetic files in the sample's shape)."""
    data = loaded.settings.experiment.data
    path = path or loaded.root / SAMPLE_PATH
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    def opaque(purpose: str, raw: str) -> str:
        return fingerprinter.fingerprint(purpose, raw)

    source = SampleDataSource(path, opaque, missing_key=data.missing_key)
    sessions = list(source.sessions())
    if data.max_sessions is not None:
        sessions = sessions[: data.max_sessions]
    cases, exclusions = build_all(sessions)
    return CaseSet(cases, exclusions, source.dataset, "sha256:" + digest)


# --- manifest ------------------------------------------------------------------


def code_version(root: Path) -> CodeVersion:
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, check=True
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return out.stdout.strip()

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return CodeVersion(commit=commit, dirty=None if status is None else bool(status))


def hardware() -> str:
    return (
        f"{platform.machine()} {platform.system()} {platform.release()}; "
        f"{platform.python_implementation()} {platform.python_version()}"
    )


def new_run_id(experiment_id: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{experiment_id}-{stamp}-{secrets.token_hex(3)}"


def run_mode(source: CounterfactualSource) -> RunMode:
    return (
        RunMode.SIMULATED if source == CounterfactualSource.FAKE else RunMode.REPLAYED
    )


# --- counterfactual client ------------------------------------------------------


def counterfactual_client(
    loaded: LoadedSettings, cases: tuple[ReplayCase, ...]
) -> ModelClient:
    source = loaded.settings.experiment.counterfactual_source.value
    if source == "fake":
        return FakeModelClient()
    if source == "proxy":
        return ProxyModelClient()
    if source == "recorded":
        return ReplayModelClient.recorded_from(
            loaded.path(loaded.settings.paths.recorded_dir)
        )
    if source == "logged_match":
        mapping = loaded.reference.label_mapping
        if mapping is None:
            raise ExperimentError("logged_match needs [reference] label_mapping")
        refs = {
            c.case_id: [
                (r.model_label.value if r.model_label.value else None, r.text)
                for r in c.references
            ]
            for c in cases
        }
        return ReplayModelClient.logged(refs, mapping.model_ids())
    raise ExperimentError(
        "live experiment runs are not wired in Stage 8: they need the owner's "
        "approval per run (ADR-0018) and go through wiring.live"
    )


# --- the run -------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedRun:
    runner: ExperimentRunner
    cases: CaseSet
    loaded: LoadedSettings
    run_dir: Path
    sink: JsonLinesEventSink


def prepare(
    config: Path,
    *,
    runtime: Path | str | None = None,
    environ: dict[str, str] | None = None,
    experiments_root: Path | None = None,
    run_root: Path | None = None,
    now: Callable[[], datetime] | None = None,
    overrides: dict[str, Any] | None = None,
    data_path: Path | None = None,
    dotenv: Path | str | None | object = ...,
) -> PreparedRun:
    """Load ``config`` and build the runner. ``runtime=None`` ignores
    ``config/local.toml`` (experiments are offline; the runtime layer only
    matters for live calls)."""
    extra = {} if dotenv is ... else {"dotenv": dotenv}
    loaded = load_settings(
        experiment=config,
        runtime=runtime,
        environ=environ,
        overrides=overrides,
        **extra,
    )
    exp = loaded.settings.experiment
    if exp.id is None:
        raise ExperimentError(f"{config}: [experiment] id is required")
    root = experiments_root or (repo_root() / "experiments")
    fp = Fingerprinter(fingerprint_key(loaded))
    cases = sample_cases(loaded, fp, data_path)
    source = CounterfactualSource(exp.counterfactual_source.value)
    if source == CounterfactualSource.LIVE:
        raise ExperimentError("live experiment runs are not wired in Stage 8")
    run_id = new_run_id(exp.id, now() if now else None)
    run_dir = (run_root or loaded.path(loaded.settings.paths.run_dir)) / exp.id / run_id
    ids: IdSource = SequentialIdSource(run_id)
    clock = SystemClock()

    config_obj = pipeline_config(loaded)
    versions = versions_for(config_obj, fp, loaded.config_hash)
    strategy = exp.strategy
    candidate = (
        load_candidate(strategy, Path(config).parent, root) if strategy else None
    )
    if strategy is not None:
        versions = versions.model_copy(
            update={
                "policies": {
                    **versions.policies,
                    _strategy_name(strategy): strategy.version,
                }
            }
        )
    manifest = RunManifest(
        run_id=run_id,
        experiment_id=exp.id,
        started_at=(now or (lambda: datetime.now(UTC)))(),
        code=code_version(loaded.root),
        dataset=cases.dataset,
        data_hash=cases.data_hash,
        seed=exp.seed,
        versions=versions,
        counterfactual_source=source,
        prompt_composition_assumption=exp.prompt_composition,
        history_mode="logged_history",
        ordering_rule=exp.data.ordering,
        pairing_flags_included=tuple(PairingFlag(f) for f in exp.data.pairing_flags),
        live_calls=False,
        hardware=hardware(),
    )
    baselines = loaded.reference.baselines
    premium = (
        next((b.model_id for b in baselines.baselines if b.name == "premium"), None)
        if baselines
        else None
    )
    mapping = loaded.reference.label_mapping
    if mapping is None:
        raise ExperimentError("the as-logged baseline needs [reference] label_mapping")

    pipeline_factory = None
    index_factory = None
    if exp.kind == ExperimentKind.CACHE_CANDIDATES:
        if strategy is None or strategy.slot != StrategySlot.CANDIDATE_INDEX:
            raise ExperimentError(
                "a cache_candidates run needs a candidate_index strategy"
            )
        index_factory = candidate
    else:
        client = counterfactual_client(loaded, cases.cases)
        inject: dict[str, Any] = {}
        if strategy is not None:
            if strategy.slot == StrategySlot.ROUTING_POLICY:
                inject["routing_policy"] = candidate(strategy.params)
            elif strategy.slot == StrategySlot.CONTEXT_STRATEGY:
                inject["context_strategy"] = candidate(strategy.params)
            else:
                raise ExperimentError(
                    "pipeline_replay takes a routing or context candidate"
                )
            inject["candidate_versions"] = {_strategy_name(strategy): strategy.version}

        def pipeline_factory(events: EventSink, run_ids: IdSource):
            return build_pipeline_from_settings(
                loaded,
                model_client=client,
                cache_store=InMemoryCacheStore(),
                sink=events,
                run_id=run_id,
                run_mode=run_mode(source),
                ids=run_ids,
                clock=clock,
                **inject,
            )

    sink = JsonLinesEventSink(run_dir / "events.jsonl")  # opened last
    setup = RunSetup(
        experiment=exp,
        manifest=manifest,
        run_dir=run_dir,
        sink=sink,
        clock=clock,
        ids=ids,
        versions=versions,
        run_mode=run_mode(source),
        accounting=build_accounting_service(loaded),
        prices=loaded.reference.prices,
        label_mapping=mapping,
        premium_model_id=premium,
        fingerprinter=fp,
        measurement=MeasurementService(fp, clock, ApproxCharsTokenizer()),
        pipeline_factory=pipeline_factory,
        index_factory=index_factory,
        strategy_params=dict(strategy.params) if strategy else {},
    )
    return PreparedRun(ExperimentRunner(setup), cases, loaded, run_dir, sink)


def _strategy_name(spec: StrategySettings) -> str:
    raw = spec.builtin or f"{Path(spec.file or '').stem}.{spec.object}"
    return "candidate:" + "".join(
        ch if ch.isalnum() or ch in "._-" else "-" for ch in raw.lower()
    )
