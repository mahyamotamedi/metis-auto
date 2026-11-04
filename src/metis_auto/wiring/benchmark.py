"""Compose the paid routing benchmark P-1..P-3 (final plan "Paid branch";
ADR-0053). No decisions here: the rules are in
``evaluation.benchmark``, ``evaluation.sampling`` (E4) and
``evaluation.judging`` (E5).

What it builds:
- **the set**: golden-v2's pilot IDs (from the committed ID-only export, no
  database), and each record's request (``GoldenStore``: the local PostgreSQL
  database holding golden-v2 and the gpt-5.5 answers; LOCAL ONLY);
- **the plan**: arms (callable or why not), records, generation and judge
  calls, cost bounds against the caps and the shared team total, the gates
  and the unset owner values. No client is built and no call is made;
- **the live clients for the E4 harness** (``live_clients``): per model,
  ``ReplayFirstClient(recorded answers, SpendGuardedClient(recording(live)))``:
  an answer already recorded is replayed (a rerun costs nothing); only a new
  input goes live, under the spend guard over the shared ledger, and is
  recorded (``data/recorded/``). ``build_live_client`` refuses unless both
  keys (``live.enabled`` and ``METIS_API_KEY``) and the caps are set;
- **generation, judging, labels and the spot-check export**, each refusing,
  with every reason, until its gates and owner values are set.

Text stays in the database, ``data/recorded/`` and ``runs/`` (git-ignored);
everything returned or printed is content-free.
Called by: scripts/benchmark.py, tests.
"""

from __future__ import annotations

import csv
import json
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from metis_auto.adapters.providers import ReplayModelClient
from metis_auto.adapters.providers.recording import read_records
from metis_auto.adapters.providers.replay_first import ReplayFirstClient
from metis_auto.adapters.system import FileSpendLedger, SystemClock
from metis_auto.adapters.system.shared_spend import (
    LedgerSummary,
    SharedSpendError,
    SharedSpendLedger,
    summarise_ledger,
)
from metis_auto.application.pipeline.spend_guard import SpendGuard
from metis_auto.contracts import (
    AnswerSource,
    AttemptKind,
    CatalogueEntry,
    Cost,
    CostBasis,
    CostEstimate,
    ErrorClass,
    InputPart,
    ModelError,
    ModelInvocation,
    ModelResponse,
    ModelResult,
    Money,
    TokenUsage,
)
from metis_auto.domain.accounting.cost import cost_of, pre_call_estimate
from metis_auto.domain.accounting.overhead import template_overhead, with_overhead
from metis_auto.domain.accounting.tokens import sum_counts
from metis_auto.evaluation.benchmark import agreement as ag
from metis_auto.evaluation.benchmark import framework_report as fr
from metis_auto.evaluation.benchmark import labels as lb
from metis_auto.evaluation.benchmark import plan as pl
from metis_auto.evaluation.benchmark import spot_check as sc
from metis_auto.evaluation.benchmark.arms import ArmStatus, callable_arms, check_arms
from metis_auto.evaluation.benchmark.config import (
    BenchmarkConfig,
    OwnerValueUnset,
    parse_config,
    require,
)
from metis_auto.evaluation.benchmark.judge import (
    LlmPairwiseJudge,
    judge_all,
    render_request,
    require_two_families,
    view_from_parts,
)
from metis_auto.evaluation.benchmark.pilot import Candidate, select_pilot
from metis_auto.evaluation.benchmark.tenant import TenantCheck, check_tenant_cap
from metis_auto.evaluation.golden_answers.request import build_request
from metis_auto.evaluation.judging.pairwise import JudgeRun
from metis_auto.evaluation.judging.types import JudgeRequestView, PairItem
from metis_auto.evaluation.sampling.allocation import SamplingUnit
from metis_auto.evaluation.sampling.config import LiveApproval, RunConfig
from metis_auto.evaluation.sampling.runner import (
    RunResult,
    execute,
    plan_calls,
)
from metis_auto.ports import Clock, ModelClient
from metis_auto.settings import ApiFormat, EndpointStatus, LoadedSettings, load_settings
from metis_auto.settings.loader import repo_root

from .from_settings import live_permission, model_templates
from .live import build_live_client, live_overrides
from .tokenizers import build_tokenizers

CONFIG_PATH = "config/evaluation/benchmark.toml"
GOLDEN_ANSWERS_CONFIG = "config/evaluation/golden_answers.toml"
RUNS_DIR = "runs/benchmark"
AGREEMENT_FILE = "agreement.json"
KEY_FILE = "key_LOCAL_ONLY.csv"


class BenchmarkRefused(RuntimeError):
    """A paid step that may not start; ``reasons`` lists every reason."""

    def __init__(self, reasons: Sequence[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = tuple(reasons)


class GoldenStore(Protocol):
    """Golden-v2 request inputs and the reference answers (LOCAL ONLY)."""

    def request_inputs(self, dataset_id: str) -> list[dict[str, Any]]: ...

    def answers(self, run_id: str, record_ids: Iterable[str]) -> dict[str, str]: ...


class DbGoldenStore:
    """``GoldenStore`` over the local PostgreSQL database (extra ``db``)."""

    def __init__(self, engine: Any | None = None) -> None:
        if engine is None:
            from .database import engine_from_settings  # noqa: PLC0415

            engine = engine_from_settings()
        self._engine = engine

    def request_inputs(self, dataset_id: str) -> list[dict[str, Any]]:
        from metis_auto.data_access.postgres import golden_answers as db  # noqa: PLC0415

        with self._engine.connect() as conn:
            return db.request_inputs(conn, dataset_id)

    def answers(self, run_id: str, record_ids: Iterable[str]) -> dict[str, str]:
        from metis_auto.data_access.postgres import golden_answers as db  # noqa: PLC0415

        with self._engine.connect() as conn:
            return db.answers_for(conn, run_id, record_ids)


# --------------------------------------------------------------------- clients
class SpendGuardedClient:
    """``ports.ModelClient``: a live call only if its pre-call estimate fits
    what is left (the spend guard over the shared ledger); then the actual
    cost is charged. A refused call returns a ``ModelError``
    (``spend_guard_refused``), so the E4 run records it and goes on.

    A **transient** provider error (``connection``, ``timeout`` or an
    intermittent ``http_404:model_not_found``: no usage is
    reported, so the actual cost is unknown) charges the pre-call estimate,
    never zero, and does **not** stop the run; the run is stopped after
    ``max_consecutive_transient`` of them in a row (an outage). Any other
    uncomputable cost still stops it (ADR-0021; ADR-0053 amendment 2)."""

    TRANSIENT = frozenset({ErrorClass.CONNECTION, ErrorClass.TIMEOUT})
    TRANSIENT_CODES = frozenset({"http_404:model_not_found"})
    """Observed 2026-11-04 (ADR-0053 amendment 5): the wrapper answered
    ``model_not_found`` for ``deepseek-v4-flash`` twice in about 60 calls, on
    different records, while the same model answered the calls around them. A
    model that is really gone fails every call, so the streak limit stops the
    run after ``max_consecutive_transient`` of them in a row."""

    def _is_transient(self, result: ModelResult) -> bool:
        return isinstance(result, ModelError) and (
            result.error_class in self.TRANSIENT
            or result.provider_error_code in self.TRANSIENT_CODES
        )

    def __init__(
        self,
        inner: ModelClient,
        guard: SpendGuard,
        *,
        estimate: Callable[[ModelInvocation], CostEstimate],
        actual: Callable[[ModelInvocation, ModelResult], Cost | None],
        max_consecutive_transient: int = 5,
    ) -> None:
        self._inner = inner
        self._guard = guard
        self._estimate = estimate
        self._actual = actual
        self.max_consecutive_transient = max_consecutive_transient
        self._streak = 0

    @property
    def source(self) -> AnswerSource:
        return self._inner.source

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        estimate = self._estimate(invocation)
        if not self._guard.allows(estimate):
            return ModelError(
                error_class=ErrorClass.UNKNOWN,
                retryable=False,
                provider_error_code="spend_guard_refused",
                source=self._inner.source,
            )
        result = self._inner.invoke(invocation)
        if isinstance(result, ModelError) and self._is_transient(result):
            assert estimate.cost.amount is not None  # allows() checked it
            self._guard.charge_amount(estimate.cost.amount)
            self._streak += 1
            if self._streak >= self.max_consecutive_transient:
                self._guard.stop(
                    f"{self._streak} consecutive transient errors "
                    f"({result.provider_error_code or result.error_class.value})"
                )
            return result
        self._streak = 0
        self._guard.charge(self._actual(invocation, result), estimate)
        return result


def _usage(result: ModelResult) -> TokenUsage | None:
    return result.usage if isinstance(result, ModelResponse) else None


# ------------------------------------------------------------------- benchmark
class Benchmark:
    def __init__(
        self,
        *,
        root: Path | None = None,
        config_path: str = CONFIG_PATH,
        loaded: LoadedSettings | None = None,
        load: Callable[[dict[str, Any]], LoadedSettings] | None = None,
        store: GoldenStore | None = None,
        clock: Clock | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = root or repo_root()
        raw = tomllib.loads((self.root / config_path).read_text(encoding="utf-8"))
        self.config: BenchmarkConfig = parse_config(raw)
        self._loaded = loaded
        self._load = load or (lambda overrides: load_settings(overrides=overrides))
        self._store = store
        self._clock = clock or SystemClock()
        self._now = now or (lambda: datetime.now(UTC))
        ga = tomllib.loads((self.root / GOLDEN_ANSWERS_CONFIG).read_text("utf-8"))
        self.layout: str = ga["run"]["layout"]
        """The reference run's prompt layout: every arm gets the same prompt."""

    # ------------------------------------------------------------ settings
    def loaded(self, *, live: bool = False) -> LoadedSettings:
        reference = self.config.reference.overrides()
        if live:
            return self._load(live_overrides() | reference)
        if self._loaded is None:
            self._loaded = self._load(dict(reference))
        return self._loaded

    def catalogue(
        self, loaded: LoadedSettings | None = None
    ) -> dict[str, CatalogueEntry]:
        loaded = loaded or self.loaded()
        return {e.model_id: e for e in loaded.reference.catalogue.entries}

    @staticmethod
    def enabled_families(loaded: LoadedSettings) -> set[str]:
        endpoints = loaded.reference.endpoints
        if endpoints is None:
            return set()
        return {
            e.family
            for e in endpoints.endpoints
            if e.status == EndpointStatus.ENABLED
            and e.api_format == ApiFormat.OPENAI_CHAT_COMPLETIONS
        }

    def arms(self, loaded: LoadedSettings | None = None) -> tuple[ArmStatus, ...]:
        loaded = loaded or self.loaded()
        return check_arms(
            self.config.arms.requested,
            catalogue=loaded.reference.catalogue.entries,
            prices=loaded.reference.prices,
            enabled_families=self.enabled_families(loaded),
            not_callable=self.config.arms.not_callable,
        )

    # ------------------------------------------------------- set (no DB)
    def shareable(self) -> pd.DataFrame:
        """golden-v2's committed ID-only export: record, cohort, language, key."""
        frame = pd.read_parquet(self.root / self.config.set.shareable_ids)
        language = frame["stratum"].map(lambda s: json.loads(s)["language_group"])
        return pd.DataFrame(
            {
                "record_id": frame["record_id"],
                "tenant": frame["owner_cohort"],
                "language_group": language,
                "user_message_id": frame["target_message_id"],
            }
        )

    def tenant_check(self, record_ids: Sequence[str] | None = None) -> TenantCheck:
        frame = self.shareable()
        if record_ids is not None:
            frame = frame[frame["record_id"].isin(record_ids)]
        return check_tenant_cap(
            frame["tenant"].tolist(),
            cap=self.config.set.tenant_cap,
            pooled=self.config.set.pooled_cohorts,
        )

    def pilot_ids(self) -> tuple[str, ...]:
        frame = self.shareable()
        candidates = [
            Candidate(r.record_id, r.tenant, r.language_group)
            for r in frame.itertuples(index=False)
        ]
        return select_pilot(
            candidates,
            size=self.config.pilot.size,
            seed=self.config.pilot.seed,
            cap=self.config.set.tenant_cap,
        )

    def record_ids(self, scope: str = "pilot") -> tuple[str, ...]:
        """``pilot``: the seeded pilot (20). ``main``: every golden-v2 record
        (the 300-request run, after the pilot; the pilot's recorded answers
        replay at no cost). Anything else is refused."""
        if scope == "pilot":
            return self.pilot_ids()
        if scope == "main":
            return tuple(sorted(self.shareable()["record_id"]))
        raise BenchmarkRefused([f"scope must be 'pilot' or 'main', not {scope!r}"])

    # ------------------------------------------------------ requests (DB)
    def store(self) -> GoldenStore:
        if self._store is None:
            self._store = DbGoldenStore()
        return self._store

    def requests(self, record_ids: Sequence[str]) -> dict[str, tuple[InputPart, ...]]:
        """Each record's prompt, built as for the gpt-5.5 reference
        (``build_request`` with the reference run's layout). LOCAL ONLY."""
        wanted = set(record_ids)
        out: dict[str, tuple[InputPart, ...]] = {}
        for item in self.store().request_inputs(self.config.set.dataset_id):
            if item["record_id"] in wanted:
                out[item["record_id"]] = build_request(
                    item["rows"], item["kinds"], self.layout
                ).parts
        return out

    def input_tokens(
        self,
        parts: Mapping[str, Sequence[InputPart]],
        models: Sequence[str],
        loaded: LoadedSettings | None = None,
    ) -> dict[tuple[str, str], int]:
        """Counted input per (record, model), template overhead included."""
        loaded = loaded or self.loaded()
        catalogue = self.catalogue(loaded)
        tokens = build_tokenizers(loaded)
        templates = model_templates(loaded, tokens)
        out: dict[tuple[str, str], int] = {}
        for model in models:
            entry = catalogue[model]
            tokenizer = tokens.tokenizers[entry.tokenizer_ref]
            template = templates.get(entry.model_id) or templates.get(
                entry.tokenizer_ref
            )
            for record, ps in parts.items():
                content = sum_counts(tokenizer.count(p.text) for p in ps)
                assert content is not None
                overhead = template_overhead(template, [p.role for p in ps])
                out[(record, model)] = with_overhead(content, overhead).tokens
        return out

    def judge_input_tokens(
        self,
        parts: Mapping[str, Sequence[InputPart]],
        references: Mapping[str, str],
        judges: Sequence[str],
        loaded: LoadedSettings | None = None,
    ) -> dict[tuple[str, str], int]:
        """Judge prompt + request view + reference answer per (record, judge),
        with an empty candidate (the generation limit bounds it)."""
        loaded = loaded or self.loaded()
        lang = self.config.judges.instruction_language or "en"
        prompts: dict[str, tuple[InputPart, ...]] = {}
        for record, ps in parts.items():
            if record not in references:
                continue
            probe = LlmPairwiseJudge(
                _NoClient(),
                model_id=judges[0],
                instruction_language=lang,
                max_output_tokens=1,
                price=lambda u: None,
                clock=self._clock,
                run_id="plan",
            )
            prompts[record] = probe.invocation(
                view_from_parts(ps), references[record], ""
            ).parts
        return self.input_tokens(prompts, judges, loaded)

    # ------------------------------------------------------------ budget
    def ledger_summary(
        self, machine: str, loaded: LoadedSettings | None = None
    ) -> LedgerSummary:
        loaded = loaded or self.loaded()
        return summarise_ledger(
            loaded.path(loaded.settings.paths.spend_ledger),
            machine=machine,
            currency=loaded.settings.budget.currency,
            created_at=self._now(),
        )

    def other_summaries(self, machine: str) -> list[LedgerSummary]:
        folder = self.root / self.config.spend_share.summaries_dir
        out = []
        for path in sorted(folder.glob("*.json")) if folder.exists() else []:
            summary = LedgerSummary.from_json(json.loads(path.read_text("utf-8")))
            if summary.machine != machine:
                out.append(summary)
        return out

    def summary_status(self) -> dict[str, Any]:
        """Which machines' ledger summaries exist in the summaries folder and
        which expected ones are missing (labels only; reads file names)."""
        folder = self.root / self.config.spend_share.summaries_dir
        present = (
            sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []
        )
        expected = self.config.spend_share.expected_machines
        return {
            "folder": self.config.spend_share.summaries_dir,
            "folder_exists": folder.exists(),
            "present": present,
            "missing": (
                sorted(set(expected) - set(present))
                if expected is not None
                else "set by owner: spend_share.expected_machines"
            ),
            "note": "a paid run refuses until every expected machine has exported "
            "its summary (scripts/spend_share.py export --machine <label>)",
        }

    def budget(
        self, machine: str | None, loaded: LoadedSettings | None = None
    ) -> dict[str, Any]:
        loaded = loaded or self.loaded()
        b = loaded.settings.budget
        out: dict[str, Any] = {
            "ledger_summaries": self.summary_status(),
            "currency": b.currency,
            "lifetime_ceiling": _s(b.lifetime_ceiling),
            "local_lifetime_cap": _s(b.lifetime_cap),
            "local_run_cap": _s(b.run_cap),
        }
        if machine is None:
            out["this_machine"] = "pass --machine to include this machine's ledger"
            return out
        local = self.ledger_summary(machine, loaded)
        others = self.other_summaries(machine)
        out["this_machine_spent"] = _s(local.total)
        out["other_machines"] = {s.machine: _s(s.total) for s in others}
        expected = self.config.spend_share.expected_machines
        missing = (
            sorted(set(expected) - {machine} - {s.machine for s in others})
            if expected is not None
            else None
        )
        out["missing_summaries"] = (
            missing
            if missing is not None
            else ("set by owner: spend_share.expected_machines")
        )
        team = local.total + sum((s.total for s in others), Decimal(0))
        out["team_total_known"] = _s(team)
        if b.lifetime_ceiling is not None:
            out["left_under_ceiling"] = _s(b.lifetime_ceiling - team)
        return out

    def shared_ledger(
        self, machine: str, run_id: str, loaded: LoadedSettings
    ) -> SharedSpendLedger:
        """This machine's file ledger, bounded by the team total (decision 7)."""
        b = loaded.settings.budget
        cfg = self.config.spend_share
        expected = require(cfg.expected_machines, "spend_share.expected_machines")
        max_age = require(cfg.max_age_hours, "spend_share.max_age_hours")
        if b.lifetime_cap is None or b.run_cap is None or b.lifetime_ceiling is None:
            raise BenchmarkRefused(["budget caps are not all set (ADR-0018)"])
        local = FileSpendLedger(
            loaded.path(loaded.settings.paths.spend_ledger),
            run_id=run_id,
            lifetime_cap=Money(amount=b.lifetime_cap, currency=b.currency),
            run_cap=Money(amount=b.run_cap, currency=b.currency),
            warn_at=b.warn_at,
        )
        return SharedSpendLedger(
            local,
            machine=machine,
            others=self.other_summaries(machine),
            expected_machines=expected,
            ceiling=Money(amount=b.lifetime_ceiling, currency=b.currency),
            now=self._now(),
            max_age=timedelta(hours=max_age),
        )

    # -------------------------------------------------------------- plan
    def plan(
        self,
        *,
        with_db: bool,
        machine: str | None = None,
        estimate: bool = False,
        scope: str = "pilot",
    ) -> dict[str, Any]:
        """Everything a pilot would do and cost, with no call (content-free).

        ``estimate=True`` is the strict mode: it refuses, listing every reason,
        while an owner value is unset or input sizes are not counted from the
        database, and otherwise adds the computed ``estimate`` (Gap 1)."""
        if estimate:
            reasons = [f"set by owner: {k}" for k in pl.estimate_gaps(self.config)]
            if not with_db:
                reasons.append("input sizes need the golden-v2 database: add --with-db")
            if reasons:
                raise BenchmarkRefused(reasons)
        loaded = self.loaded()
        arms = self.arms(loaded)
        callable_ = list(callable_arms(arms))
        records = list(self.record_ids(scope))
        catalogue = self.catalogue(loaded)
        prices = loaded.reference.prices
        judges = self.config.judges.models
        if with_db:
            parts = self.requests(records)
            missing = sorted(set(records) - set(parts))
            records = [r for r in records if r in parts]
            tokens = self.input_tokens(parts, callable_, loaded)
            refs = self.store().answers(self.config.set.reference_run_id, records)
            judge_tokens = (
                self.judge_input_tokens(parts, refs, judges, loaded) if judges else None
            )
        else:
            missing, tokens, judge_tokens, refs = [], {}, None, {}
        generation = pl.generation_estimate(
            records,
            callable_,
            input_tokens=tokens,
            catalogue=catalogue,
            prices=prices,
            max_output_tokens=self.config.run.max_output_tokens,
        )
        if not with_db:
            generation["reasons"] = {
                **generation["reasons"],  # type: ignore[dict-item]
                "input_sizes": "need the golden-v2 database (run with --with-db)",
            }
        judging = pl.judge_estimate(
            records,
            callable_,
            judges=judges,
            judge_input_tokens=judge_tokens,
            candidate_max_tokens=self.config.run.max_output_tokens,
            judge_max_output=self.config.judges.max_output_tokens,
            catalogue=catalogue,
            prices=prices,
        )
        tenant = self.tenant_check()
        pilot_tenant = self.tenant_check(records)
        result = pl.build_plan(
            self.config,
            arms=arms,
            records=records,
            generation=generation,
            judging=judging,
            budget=self.budget(machine, loaded),
            gate_list=pl.gates(
                amendment_committed=True,
                samples_allowed=self.config.gates.metis_allows_samples,
            ),
            tenant={
                "golden_v2": asdict(tenant),
                "pilot": asdict(pilot_tenant),
            },
        )
        result["with_db"] = with_db
        if estimate:
            result["estimate"] = pl.total_estimate(
                generation,
                judging,
                hard_cap=self.config.run.hard_cap_usd,  # type: ignore[arg-type]
            )
        if with_db:
            result["records_missing_in_db"] = len(missing)
            result["reference_answers_found"] = len(refs)
        return result

    # ------------------------------------------------------- live clients
    def live_clients(
        self,
        *,
        loaded: LoadedSettings,
        run_id: str,
        ledger: Any,
        http_client_factory: Callable[[], Any] | None = None,
    ) -> Callable[[str, str | None], ModelClient]:
        """``client_for(model, effort)`` for the E4 harness and the judges:
        replay-first over the spend-guarded, recording live client. Built
        once per run; one guard over the shared ledger for every model."""
        live = build_live_client(
            loaded, run_id, http_client_factory=http_client_factory
        )
        guard = SpendGuard(ledger)
        catalogue = self.catalogue(loaded)
        prices = loaded.reference.prices
        tokens = build_tokenizers(loaded)
        templates = model_templates(loaded, tokens)

        def estimate(inv: ModelInvocation) -> CostEstimate:
            entry = catalogue[inv.model_id]
            tokenizer = tokens.tokenizers[entry.tokenizer_ref]
            content = sum_counts(tokenizer.count(p.text) for p in inv.parts)
            assert content is not None
            template = templates.get(entry.model_id) or templates.get(
                entry.tokenizer_ref
            )
            overhead = template_overhead(template, [p.role for p in inv.parts])
            if inv.max_output_tokens is None:
                raise BenchmarkRefused(["every paid call needs max_output_tokens"])
            return pre_call_estimate(
                entry, content, inv.max_output_tokens, prices, overhead
            )

        def actual(inv: ModelInvocation, result: ModelResult) -> Cost | None:
            return cost_of(
                _usage(result), catalogue[inv.model_id], prices, CostBasis.ACTUAL
            )

        guarded = SpendGuardedClient(live, guard, estimate=estimate, actual=actual)
        replay = ReplayModelClient.recorded_from(
            loaded.path(loaded.settings.paths.recorded_dir)
        )
        client = ReplayFirstClient(replay, guarded)
        self.last_client = client
        return lambda model, effort: client

    def build_invocation(
        self, parts: Mapping[str, Sequence[InputPart]], run_id: str
    ) -> Callable[[str, str], ModelInvocation]:
        def build(case_id: str, model_id: str) -> ModelInvocation:
            return ModelInvocation(
                request_id=f"{run_id}.{case_id}",
                attempt_id=f"{run_id}.{case_id}.{model_id}",
                attempt_kind=AttemptKind.PRIMARY,
                model_id=model_id,
                parts=tuple(parts[case_id]),
                case_id=case_id,
            )

        return build

    # ---------------------------------------------------------- gates
    def refusals(self, *, approval: LiveApproval | None, step: str) -> list[str]:
        """Every reason a paid step may not start (gates, owner values)."""
        reasons = []
        if not self.config.gates.metis_allows_samples:
            reasons.append(
                "gate: Metis has not allowed sending samples to model APIs (O-1)"
            )
        if approval is None:
            reasons.append(
                "gate: no owner approval for this run (--approved-by, --cap)"
            )
        elif not approval.sample_conversations_approved:
            reasons.append("gate: the approval does not cover dataset text")
        keys = ["spend_share.expected_machines", "spend_share.max_age_hours"]
        keys += {
            "generate": ["run.hard_cap_usd", "run.max_output_tokens", "run.order_seed"],
            "judge": [
                "judges.models",
                "judges.max_output_tokens",
                "judges.instruction_language",
            ],
        }[step]
        unset = set(self.config.unset_owner_values())
        reasons += [f"set by owner: {k}" for k in keys if k in unset]
        return reasons

    # ------------------------------------------------------- generation
    def generate(
        self,
        *,
        run_id: str,
        machine: str,
        approval: LiveApproval | None,
        http_client_factory: Callable[[], Any] | None = None,
        scope: str = "pilot",
        only_arm: str | None = None,
    ) -> RunResult:
        """The pilot's answers from the callable arms through E4 ``execute``.
        Refuses (every reason, no call) until the gates and owner values are
        set. ``only_arm`` answers with one callable arm only, so the arms can
        run as separate processes (each with its own run ID, hence its own
        recording file and cap; saved answers of every file replay free)."""
        reasons = self.refusals(approval=approval, step="generate")
        if reasons:
            raise BenchmarkRefused(reasons)
        assert approval is not None
        loaded = self.loaded(live=True)
        permission = live_permission(loaded)
        if not permission.allowed:
            raise BenchmarkRefused(list(permission.reasons))
        arms = list(callable_arms(self.arms(loaded)))
        if only_arm is not None:
            if only_arm not in arms:
                raise BenchmarkRefused([f"--arm {only_arm}: not a callable arm"])
            arms = [only_arm]
        records = list(self.record_ids(scope))
        parts = self.requests(records)
        records = [r for r in records if r in parts]
        config = RunConfig(
            models=tuple(arms),
            hard_cap_usd=self.config.run.hard_cap_usd,
            max_output_tokens=self.config.run.max_output_tokens,
            order_seed=self.config.run.order_seed,
        )
        units = {r: SamplingUnit(case_id=r, session_ref=r, strata={}) for r in records}
        calls = plan_calls(records, units, config)
        try:
            ledger = self.shared_ledger(machine, run_id, loaded)
        except (OwnerValueUnset, SharedSpendError) as exc:
            raise BenchmarkRefused([str(exc)]) from None
        return execute(
            calls,
            client_for=self.live_clients(
                loaded=loaded,
                run_id=run_id,
                ledger=ledger,
                http_client_factory=http_client_factory,
            ),
            build_invocation=self.build_invocation(parts, run_id),
            config=config,
            catalogue=self.catalogue(loaded),
            prices=loaded.reference.prices,
            input_tokens=self.input_tokens(parts, arms, loaded),
            clock=self._clock,
            uses_sample_conversations=True,
            approval=approval,
        )

    # --------------------------------------------------------- judging
    def judge(
        self,
        *,
        run_id: str,
        machine: str,
        approval: LiveApproval | None,
        http_client_factory: Callable[[], Any] | None = None,
        scope: str = "pilot",
        only_judge: str | None = None,
        only_arm: str | None = None,
    ) -> list[JudgeRun]:
        """Both judges on every (record, callable arm) pair against gpt-5.5,
        both orders; results written content-free under ``runs/benchmark/``.
        ``only_judge`` runs one of the configured judges (so the two can run as
        two processes); the two-family check still covers the configured pair.
        ``only_arm`` judges one arm's answers only, so the work can be split
        further; each process then needs its own run ID (its own output folder),
        and the per-arm files are concatenated afterwards."""
        reasons = self.refusals(approval=approval, step="judge")
        if reasons:
            raise BenchmarkRefused(reasons)
        loaded = self.loaded(live=True)
        permission = live_permission(loaded)
        if not permission.allowed:
            raise BenchmarkRefused(list(permission.reasons))
        catalogue = self.catalogue(loaded)
        judges = require(self.config.judges.models, "judges.models")
        require_two_families(judges, catalogue)
        arms = list(callable_arms(self.arms(loaded)))
        if only_arm is not None:
            if only_arm not in arms:
                raise BenchmarkRefused([f"--arm {only_arm}: not a callable arm"])
            arms = [only_arm]
        records = list(self.record_ids(scope))
        parts = self.requests(records)
        records = [r for r in records if r in parts]
        try:
            ledger = self.shared_ledger(machine, run_id, loaded)
        except (OwnerValueUnset, SharedSpendError) as exc:
            raise BenchmarkRefused([str(exc)]) from None
        client = self.live_clients(
            loaded=loaded,
            run_id=run_id,
            ledger=ledger,
            http_client_factory=http_client_factory,
        )(judges[0], None)
        content = _Content(
            parts,
            self.store().answers(self.config.set.reference_run_id, records),
            ReplayModelClient.recorded_from(
                loaded.path(loaded.settings.paths.recorded_dir)
            ),
            self.build_invocation(parts, run_id),
            reference=self.config.set.reference_model,
        )
        frame = self.shareable().set_index("record_id")
        reference = (self.config.set.reference_model, None)
        items = [
            PairItem(
                case_id=r,
                session_ref=r,
                language=str(frame.loc[r, "language_group"]),
                candidate=(arm, None),
                reference=reference,
            )
            for r in records
            for arm in arms
        ]
        prices = loaded.reference.prices
        out = []
        folder = self.root / RUNS_DIR / run_id / "judging"
        if only_judge is not None and only_judge not in judges:
            raise BenchmarkRefused([f"--judge {only_judge}: not in judges.models"])
        for model in judges:
            if only_judge is not None and model != only_judge:
                continue
            entry = catalogue[model]
            judge = LlmPairwiseJudge(
                client,
                model_id=model,
                instruction_language=require(
                    self.config.judges.instruction_language,
                    "judges.instruction_language",
                ),
                max_output_tokens=require(
                    self.config.judges.max_output_tokens, "judges.max_output_tokens"
                ),
                price=lambda u, e=entry: _amount(
                    cost_of(u, e, prices, CostBasis.ACTUAL)
                ),
                clock=self._clock,
                run_id=run_id,
            )
            run = judge_all(judge, items, content, vision_candidates=None)
            write_judging(folder, model, run, judge.records)
            out.append(run)
        return out

    # ---------------------------------------------------------- labels
    def labels(self, *, run_id: str, name: str) -> dict[str, Any]:
        """P-3: the two judges' files → the label file (local) and its
        content-free summary."""
        folder = self.root / RUNS_DIR / run_id / "judging"
        files = sorted(folder.glob("*.scores.jsonl"))
        if len(files) != 2:
            raise BenchmarkRefused([f"need the two judges' score files in {folder}"])
        judged_rows = [read_rows(f) for f in files]
        scores = [read_scores(f) for f in files]
        inconsistent = [
            {
                (r["case_id"], r["candidate"])
                for r in rows
                if r["state"] == "inconsistent"
            }
            for rows in judged_rows
        ]
        languages = {r["case_id"]: r["language"] for rows in judged_rows for r in rows}
        frame = self.shareable().set_index("record_id")
        records = sorted(
            {k[0] for s in scores for k in s} | {k[0] for g in inconsistent for k in g}
        )
        gate_file = self.root / RUNS_DIR / run_id / AGREEMENT_FILE
        report = (
            json.loads(gate_file.read_text(encoding="utf-8"))
            if gate_file.exists()
            else None
        )
        gate = ag.gate_by_language(
            report, self.config.gate, sorted(set(languages.values()))
        )
        catalogue = self.catalogue()
        arms = list(callable_arms(self.arms()))
        rows = lb.make_labels(
            scores,
            records={r: str(frame.loc[r, "user_message_id"]) for r in records},
            arms=arms,
            tiers={a: catalogue[a].tier for a in arms},
            acceptable_score=self.config.labels.acceptable_score,
            cheap_arms=self.config.labels.cheap_arms,
            name=name,
            inconsistent=inconsistent,
            languages=languages,
            gate=gate,
        )
        pairs = [
            (r["judge_id"], r["candidate"], r["state"])
            for rows in judged_rows
            for r in rows
        ]
        out = self.root / RUNS_DIR / run_id / "labels"
        out.mkdir(parents=True, exist_ok=True)
        lb.to_frame(rows, arms).to_parquet(out / f"{name}.labels.parquet", index=False)
        summary = lb.summary(rows, inconsistency=lb.inconsistency_summary(pairs))
        (out / f"{name}.summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        return summary

    # ------------------------------------------------- framework report
    def framework_report(self, *, run_id: str, scope: str = "pilot") -> dict[str, Any]:
        """The pilot through the evaluation framework: the answering run is
        rebuilt from the recordings and given to E4's ``comparison_table``,
        quality per judge from the judging files. Content-free; no call. The
        minimum n and the bootstrap are owner decisions and stay unset."""
        run = self.root / RUNS_DIR / run_id
        files = sorted((run / "judging").glob("*.scores.jsonl"))
        if not files:
            raise BenchmarkRefused([f"no judging results in {run / 'judging'}"])
        loaded = self.loaded()
        recorded = (
            loaded.path(loaded.settings.paths.recorded_dir) / f"live-{run_id}.jsonl"
        )
        if not recorded.exists():
            raise BenchmarkRefused([f"no recording {recorded.name}"])
        arms = list(callable_arms(self.arms(loaded)))
        catalogue = self.catalogue(loaded)
        records = list(self.record_ids(scope))
        # The main set contains the pilot's records: their answers were made
        # live under an earlier run ID and replay for free, so every live
        # recording in the folder is read (per case and arm the best wins).
        lines = [
            rec
            for f in sorted(recorded.parent.glob("live-*.jsonl"))
            for rec in read_records(f)
        ]
        answers = fr.recorded_run(
            lines,
            case_ids=records,
            arms=arms,
            catalogue=self.catalogue(loaded),
            prices=loaded.reference.prices,
        )
        rows = {f.name.removesuffix(".scores.jsonl"): read_rows(f) for f in files}
        scores = {judge: read_scores(f) for judge, f in zip(rows, files, strict=True)}
        languages = {r["case_id"]: r["language"] for rs in rows.values() for r in rs}
        gate_file = run / AGREEMENT_FILE
        by_group = ag.gate_by_language(
            json.loads(gate_file.read_text(encoding="utf-8"))
            if gate_file.exists()
            else None,
            self.config.gate,
            sorted(set(languages.values())),
        )
        gate: dict[str, str] = {}
        for group, state in by_group.items():
            code = fr.FRAMEWORK_LANGUAGE.get(group, group)
            gate[code] = state if gate.get(code) in (None, state) else "unvalidated"
        report = fr.framework_report(
            answers,
            scores,
            languages,
            min_n=None,
            bootstrap=None,
            gate=gate,
            run_id=run_id,
            families={e.model_id: e.provider for e in catalogue.values()},
            current_judges=self.config.judges.models,
        )
        (run / "framework_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        (run / "framework_report.md").write_text(
            fr.to_markdown(report), encoding="utf-8"
        )
        return report

    # -------------------------------------------------------- agreement
    def agreement(self, *, run_id: str) -> dict[str, Any]:
        """P-2: the filled spot-check sheet and the local key → agreement per
        judge and language, and the gate (E5). Content-free; local files only,
        no call."""
        run = self.root / RUNS_DIR / run_id
        sheet, key = run / "spot_check" / "sheet.csv", run / "spot_check" / KEY_FILE
        for path in (sheet, key):
            if not path.exists():
                raise BenchmarkRefused([f"missing {path.relative_to(self.root)}"])
        judge_rows: dict[str, list[dict[str, Any]]] = {}
        for f in sorted((run / "judging").glob("*.scores.jsonl")):
            for row in read_rows(f):
                judge_rows.setdefault(row["judge_id"], []).append(row)
        if not judge_rows:
            raise BenchmarkRefused([f"no judging results in {run / 'judging'}"])
        try:
            report = ag.agreement_report(
                run_id=run_id,
                sheet_text=sheet.read_text(encoding="utf-8-sig"),
                key_text=key.read_text(encoding="utf-8-sig"),
                judge_rows=judge_rows,
                gate=self.config.gate,
            )
        except ValueError as exc:
            raise BenchmarkRefused([str(exc)]) from exc
        (run / AGREEMENT_FILE).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        return report

    # ------------------------------------------------------- spot check
    def spot_check(self, *, run_id: str) -> dict[str, Any]:
        """The 60-item sheet (ID-only) and its local text and key files."""
        folder = self.root / RUNS_DIR / run_id / "judging"
        files = sorted(folder.glob("*.scores.jsonl"))
        if not files:
            raise BenchmarkRefused([f"no judging results in {folder}"])
        outcomes = read_outcomes(files[0])
        items = sc.select_items(
            outcomes, size=self.config.spot_check.size, seed=self.config.spot_check.seed
        )
        loaded = self.loaded()
        records = sorted({i.case_id for i in items})
        parts = self.requests(records)
        refs = self.store().answers(self.config.set.reference_run_id, records)
        content = _Content(
            parts,
            refs,
            ReplayModelClient.recorded_from(
                loaded.path(loaded.settings.paths.recorded_dir)
            ),
            self.build_invocation(parts, run_id),
            reference=self.config.set.reference_model,
        )
        out = self.root / RUNS_DIR / run_id / "spot_check"
        out.mkdir(parents=True, exist_ok=True)
        with (out / "sheet.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(sc.SHEET_COLUMNS))
            w.writeheader()
            w.writerows(sc.sheet_rows(items))
        texts, keys = [], []
        for item in items:
            outcome = next(o for o in outcomes if o.item.item_id == item.item_id)
            cand = content.answer(item.case_id, outcome.item.candidate) or ""
            ref = content.answer(item.case_id, outcome.item.reference) or ""
            a, b = (cand, ref) if item.candidate_first else (ref, cand)
            texts.append(
                f"## {item.spot_id}\n\n{render_request(content.request(item.case_id))}"
                f"\n\n### Answer A\n\n{a}\n\n### Answer B\n\n{b}\n"
            )
            keys.append(
                {
                    "spot_id": item.spot_id,
                    "item_id": item.item_id,
                    "candidate_is": "a" if item.candidate_first else "b",
                }
            )
        (out / "texts_LOCAL_ONLY.md").write_text("\n".join(texts), encoding="utf-8")
        with (out / "key_LOCAL_ONLY.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["spot_id", "item_id", "candidate_is"])
            w.writeheader()
            w.writerows(keys)
        return {"items": len(items), "folder": str(out.relative_to(self.root))}


# ------------------------------------------------------------ helpers
class _NoClient:
    source = AnswerSource.FAKE

    def invoke(self, invocation: ModelInvocation) -> ModelResult:  # pragma: no cover
        raise RuntimeError("the plan makes no call")


class _Content:
    """E5 ``ContentProvider``: the request view, the reference answers from
    the database, the candidates' answers from the recordings. LOCAL ONLY."""

    def __init__(
        self,
        parts: Mapping[str, Sequence[InputPart]],
        references: Mapping[str, str],
        recorded: ModelClient,
        build: Callable[[str, str], ModelInvocation],
        *,
        reference: str,
    ) -> None:
        self._parts, self._refs = parts, references
        self._recorded, self._build, self._reference = recorded, build, reference

    def request(self, case_id: str) -> JudgeRequestView:
        return view_from_parts(self._parts[case_id])

    def answer(self, case_id: str, variant: tuple[str, str | None]) -> str | None:
        if variant[0] == self._reference:
            return self._refs.get(case_id)
        result = self._recorded.invoke(self._build(case_id, variant[0]))
        return result.text if isinstance(result, ModelResponse) else None


def write_judging(
    folder: Path, model: str, run: JudgeRun, calls: Sequence[Any]
) -> None:
    """Content-free judging results: one score line per pair, one line per
    call (cost and latency, evaluation cost)."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{model}.scores.jsonl").open("w", encoding="utf-8") as f:
        for o in run.outcomes:
            f.write(
                json.dumps(
                    {
                        "judge_id": run.judge_id,
                        "case_id": o.item.case_id,
                        "language": o.item.language,
                        "candidate": o.item.candidate[0],
                        "reference": o.item.reference[0],
                        "state": o.state,
                        "reason": o.reason,
                        "score": o.score,
                        "swap_consistent": o.swap_consistent,
                        "first_position_picks": o.first_position_picks,
                        "cost_usd": None if o.cost_usd is None else str(o.cost_usd),
                    }
                )
                + "\n"
            )
    with (folder / f"{model}.calls.jsonl").open("w", encoding="utf-8") as f:
        for c in calls:
            row = asdict(c)
            row["cost_usd"] = None if row["cost_usd"] is None else str(row["cost_usd"])
            f.write(json.dumps(row) + "\n")


def read_rows(path: Path) -> list[dict[str, Any]]:
    """The score lines of one judge's file (``write_judging``)."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def read_scores(path: Path) -> dict[tuple[str, str], float]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["state"] == "judged" and row["score"] is not None:
            out[(row["case_id"], row["candidate"])] = float(row["score"])
    return out


def read_outcomes(path: Path):
    from metis_auto.evaluation.judging.pairwise import PairOutcome  # noqa: PLC0415

    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        item = PairItem(
            case_id=r["case_id"],
            session_ref=r["case_id"],
            language=r["language"],
            candidate=(r["candidate"], None),
            reference=(r["reference"], None),
        )
        out.append(
            PairOutcome(
                item,
                r["state"],
                r["reason"],
                r["score"],
                None,
                None,
                None,
                r["first_position_picks"],
                r["swap_consistent"],
                None,
                None,
                None,
            )
        )
    return out


def _amount(cost: Cost) -> Decimal | None:
    return cost.amount.amount if cost.amount is not None else None


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")
