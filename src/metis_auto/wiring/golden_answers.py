"""Compose the golden-answer run: records, request building, plan, approvals,
live client, spend guard, local backup, summary (ADR-0030). No decisions here;
the loop and the rules are in ``evaluation.golden_answers``.

Prompts and answers go only to the local database, ``runs/`` and
``data/recorded/`` (all git-ignored). The summary written under ``reports/`` holds
counts, rates and cost only.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from metis_auto.adapters.system import SystemClock
from metis_auto.analysis.request_features import language_group
from metis_auto.analysis.text_features import language_label
from metis_auto.application.pipeline.spend_guard import SpendGuard
from metis_auto.contracts import AnswerSource, CostEstimate, CostStatus
from metis_auto.data_access.postgres import golden_answers as db
from metis_auto.domain.accounting.cost import pre_call_estimate
from metis_auto.domain.accounting.overhead import template_overhead, with_overhead
from metis_auto.domain.accounting.tokens import sum_counts
from metis_auto.evaluation.golden.validation import fingerprint
from metis_auto.evaluation.golden_answers.config import (
    AnswerSettings,
    SettingsError,
    parse_settings,
)
from metis_auto.evaluation.golden_answers.request import (
    build_request,
    prompt_fingerprint,
)
from metis_auto.evaluation.golden_answers.runner import (
    AnswerRow,
    RunReport,
    Spend,
    Task,
    run_answers,
    select_pilot,
)
from metis_auto.evaluation.golden_answers.summary import STRATUM_KEYS, summarise
from metis_auto.ports import ModelClient
from metis_auto.settings import LoadedSettings, load_settings
from metis_auto.settings.loader import repo_root
from metis_auto.wiring.database import engine_from_settings
from metis_auto.wiring.db_ingest import git_sha
from metis_auto.wiring.from_settings import (
    live_permission,
    model_templates,
    spend_ledger,
)
from metis_auto.wiring.live import build_live_client, live_overrides
from metis_auto.wiring.tokenizers import build_tokenizers

CONFIG_PATH = "config/evaluation/golden_answers.toml"


class RunRefused(RuntimeError):
    """A live run that may not start; the message lists every reason."""


class DbStore:
    """``AnswerStore`` over the local database."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def terminal(self, run_id: str) -> Mapping[str, tuple[str, str | None]]:
        with self._engine.connect() as conn:
            return db.stored_status(conn, run_id)

    def save(self, row: AnswerRow) -> None:
        with self._engine.begin() as conn:
            db.save_answer(conn, _row_dict(row))


class LedgerSpend:
    """The spend guard and its file ledger, as the answer loop needs them."""

    def __init__(self, guard: SpendGuard, ledger: Any) -> None:
        self._guard, self._ledger = guard, ledger

    @property
    def stopped(self) -> str | None:
        return self._guard.stopped

    def allows(self, estimate: CostEstimate) -> bool:
        return self._guard.allows(estimate)

    def charge_actual(self, cost, estimate: CostEstimate) -> None:
        self._guard.charge(cost, estimate)

    def charge_estimate(self, estimate: CostEstimate) -> None:
        if estimate.cost.status == CostStatus.COMPUTED and estimate.cost.amount:
            self._ledger.charge(estimate.cost.amount)


class NoSpend:
    """A fake or replay client costs nothing: nothing is checked or charged, and
    the persistent ledger is never touched (ADR-0018)."""

    stopped = None

    def allows(self, estimate: CostEstimate) -> bool:
        return True

    def charge_actual(self, cost, estimate: CostEstimate) -> None:
        pass

    def charge_estimate(self, estimate: CostEstimate) -> None:
        pass


class GoldenAnswers:
    def __init__(
        self,
        engine: Engine | None = None,
        root: Path | None = None,
        config_path: str = CONFIG_PATH,
        loaded: LoadedSettings | None = None,
        log: Callable[[str], None] = print,
        report_dir: Path | None = None,
    ) -> None:
        self.root = root or repo_root()
        self._report_dir = report_dir
        self.engine = engine or engine_from_settings()
        raw = tomllib.loads((self.root / config_path).read_text(encoding="utf-8"))
        self.raw = raw
        self.settings: AnswerSettings = parse_settings(raw)
        self._loaded = loaded
        self.log = log
        dataset = tomllib.loads(
            (self.root / raw["run"]["dataset_config"]).read_bytes().decode()
        )
        self._groups: Mapping[str, str] = dataset["language_groups"]
        self._dataset_cfg = dataset

    # ------------------------------------------------------------------ settings
    def loaded(self, *, live: bool = False) -> LoadedSettings:
        if live:
            return load_settings(overrides=live_overrides())
        if self._loaded is None:
            self._loaded = load_settings()
        return self._loaded

    def _entry(self, loaded: LoadedSettings):
        for e in loaded.reference.catalogue.entries:
            if e.model_id == self.settings.model_id:
                return e
        raise SettingsError(f"{self.settings.model_id} is not in the catalogue")

    def classify(self, text: str) -> str:
        return language_group(text, language_label(text), self._groups)

    # --------------------------------------------------------------------- tasks
    def tasks(self, loaded: LoadedSettings | None = None) -> list[Task]:
        loaded = loaded or self.loaded()
        entry = self._entry(loaded)
        tokens = build_tokenizers(loaded)
        tokenizer = tokens.tokenizers[entry.tokenizer_ref]
        templates = model_templates(loaded, tokens)
        template = templates.get(entry.model_id) or templates.get(entry.tokenizer_ref)
        with self.engine.connect() as conn:
            inputs = db.request_inputs(conn, self.settings.dataset_id)
        out = []
        for item in inputs:
            built = build_request(item["rows"], item["kinds"])
            content = sum_counts(tokenizer.count(p.text) for p in built.parts)
            assert content is not None
            overhead = template_overhead(template, [p.role for p in built.parts])
            stratum = item["stratum"]
            out.append(
                Task(
                    record_id=item["record_id"],
                    parts=built.parts,
                    caveats=tuple(
                        dict.fromkeys((*built.caveats, *stratum.get("caveats", ())))
                    ),
                    fingerprint=prompt_fingerprint(built.parts),
                    input_tokens=with_overhead(content, overhead),
                    strata={
                        k: stratum[k]
                        for k in STRATUM_KEYS
                        if isinstance(stratum.get(k), str)
                    },
                )
            )
        return out

    def pilot(self, tasks: list[Task]) -> list[Task]:
        pilot = self.raw["pilot"]
        return select_pilot(tasks, pilot["size"], pilot["seed"])

    # ---------------------------------------------------------------------- plan
    def plan(self) -> dict[str, Any]:
        """What a run would do, with no call and no content: counts, IDs, cost
        bounds and the settings the owner must change."""
        loaded = self.loaded()
        entry = self._entry(loaded)
        tasks = self.tasks(loaded)
        s = self.settings
        prices = loaded.reference.prices
        over = [
            t.record_id
            for t in tasks
            if t.input_tokens.tokens + s.max_output_tokens > s.context_window
        ]
        pilot = self.pilot(tasks)

        def bounds(subset):
            lower = ceiling = Decimal(0)
            unpriced = 0
            for t in subset:
                low = pre_call_estimate(entry, t.input_tokens, 0, prices).cost
                high = pre_call_estimate(
                    entry, t.input_tokens, s.max_output_tokens, prices
                ).cost
                if low.amount is None or high.amount is None:
                    unpriced += 1
                    continue
                lower += low.amount.amount
                ceiling += high.amount.amount
            return lower, ceiling, unpriced

        lower, ceiling, unpriced = bounds(tasks)
        p_lower, p_ceiling, _ = bounds(pilot)
        sizes = sorted(t.input_tokens.tokens for t in tasks)
        permission = live_permission(self.loaded(live=True))
        budget = loaded.settings.budget
        return {
            "settings": s.manifest(),
            "records": len(tasks),
            "input_tokens": {
                "total": sum(sizes),
                "median": sizes[len(sizes) // 2] if sizes else None,
                "max": sizes[-1] if sizes else None,
                "fidelity": sorted({t.input_tokens.fidelity.value for t in tasks}),
            },
            "over_context_window_ids": over,
            "cost_usd": {
                "lower_bound_input_only": str(lower),
                "ceiling_every_call_at_max_output": str(ceiling),
                "unpriced_records": unpriced,
                "pilot_lower_bound_input_only": str(p_lower),
                "pilot_ceiling_every_call_at_max_output": str(p_ceiling),
            },
            "caveats": _count(c for t in tasks for c in t.caveats),
            "pilot_ids": [t.record_id for t in pilot],
            "approvals": {
                "golden_answers.real_data_approved": (
                    loaded.settings.golden_answers.real_data_approved
                ),
                "live_permission_reasons": list(permission.reasons),
                "budget_run_cap": str(budget.run_cap),
                "budget_lifetime_cap": str(budget.lifetime_cap),
            },
        }

    # ----------------------------------------------------------------- live run
    def check_live(self, loaded: LoadedSettings) -> None:
        """Every reason a live run may not start (ADR-0018, ADR-0030)."""
        reasons = []
        if not loaded.settings.golden_answers.real_data_approved:
            reasons.append(
                "golden_answers.real_data_approved is false: sending real "
                "conversations to a provider needs the owner's approval"
            )
        reasons += list(live_permission(loaded).reasons)
        if not reasons and not self._dataset_verified():
            reasons.append(f"{self.settings.dataset_id}: verify did not pass")
        if reasons:
            raise RunRefused("live run refused: " + "; ".join(reasons))

    def _dataset_verified(self) -> bool:
        from metis_auto.wiring.golden import Golden

        quiet = Golden(
            engine=self.engine,
            root=self.root,
            config_path=self.raw["run"]["dataset_config"],
            log=lambda _m: None,
        )
        return quiet.verify()

    def run(
        self,
        run_id: str,
        *,
        scope: str,
        client: ModelClient | None = None,
        loaded: LoadedSettings | None = None,
    ) -> RunReport:
        """``scope``: ``pilot`` answers the pilot records only; ``full`` answers
        every record not yet answered in this run. ``client`` is for tests; a
        live run builds the recording live client after ``check_live``."""
        if scope not in ("pilot", "full"):
            raise ValueError("scope is 'pilot' or 'full'")
        live = client is None
        loaded = loaded or self.loaded(live=live)
        if live:
            self.check_live(loaded)
        entry = self._entry(loaded)
        tasks = self.tasks(loaded)
        first = self.pilot(tasks)
        if scope == "pilot":
            ordered, limit = first, None
        else:
            ids = {t.record_id for t in first}
            ordered = [*first, *(t for t in tasks if t.record_id not in ids)]
            limit = None
        if client is None:
            client = build_live_client(
                loaded, run_id, model_options=self._model_options(loaded, entry)
            )
        spend: Spend
        if client.source == AnswerSource.LIVE:
            ledger = spend_ledger(loaded, run_id)
            spend = LedgerSpend(SpendGuard(ledger), ledger)
        else:
            spend = NoSpend()
        store = DbStore(self.engine)
        backup_path = (
            self.root / loaded.settings.paths.run_dir / "golden_answers" / run_id
        )
        backup_path.mkdir(parents=True, exist_ok=True)
        backup_file = backup_path / "answers.jsonl"
        self._write_manifest(backup_path / "manifest.json", run_id, scope, tasks, first)
        self._restore(store, backup_file, run_id)

        def backup(row: AnswerRow) -> None:
            with backup_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(_row_json(row), ensure_ascii=False) + "\n")
                fh.flush()

        report = run_answers(
            ordered,
            run_id=run_id,
            client=client,
            entry=entry,
            prices=loaded.reference.prices,
            settings=self.settings,
            store=store,
            spend=spend,
            clock=SystemClock(),
            classify_language=self.classify,
            backup=backup,
            limit=limit,
            halt_after_failed_records=self.raw["retry"]["halt_after_failed_records"],
        )
        self.summary(run_id, planned=len(ordered))
        return report

    def _model_options(
        self, loaded: LoadedSettings, entry
    ) -> dict[str, dict[str, Any]]:
        effort = self.settings.reasoning_effort
        if effort is None:
            return {}
        endpoint = loaded.reference.endpoints.get(entry.provider)
        if endpoint is None or "reasoning_effort" not in endpoint.request_options:
            raise SettingsError(
                f"the {entry.provider!r} endpoint does not allow reasoning_effort"
            )
        return {entry.model_id: {"reasoning_effort": effort}}

    def _restore(self, store: DbStore, path: Path, run_id: str) -> int:
        """Rows in the local backup that the database lacks (a crash between the
        two writes): inserted, never re-bought."""
        if not path.exists():
            return 0
        have = store.terminal(run_id)
        restored = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = _row_from_json(json.loads(line))
            known = have.get(row.record_id)
            if known is None or (known[0] != "answered" and row.status == "answered"):
                store.save(row)
                restored += 1
        if restored:
            self.log(f"Restored {restored} rows from {path.name} into the database.")
        return restored

    def _write_manifest(self, path: Path, run_id, scope, tasks, pilot) -> None:
        with self.engine.connect() as conn:
            from metis_auto.data_access.postgres import repository as repo

            state = repo.dataset_state(conn, self.settings.dataset_id)
            records = repo.dataset_records(conn, self.settings.dataset_id)
        manifest = {
            "run_id": run_id,
            "scope": scope,
            "settings": self.settings.manifest(),
            "code_git_sha": git_sha(self.root),
            "dataset": {
                "dataset_id": self.settings.dataset_id,
                "status": state["status"] if state else None,
                "config_sha256": state["config_sha256"] if state else None,
                "fingerprint": fingerprint(
                    [r["record_id"] for r in records],
                    state["version"],
                    state["config_sha256"],
                )
                if state
                else None,
            },
            "records": len(tasks),
            "pilot_ids": [t.record_id for t in pilot],
            "independence": {
                "one_fresh_call_per_record": True,
                "cache": False,
                "routing": False,
                "compression": False,
                "escalation": False,
                "extra_system_prompt": False,
            },
            "notes": [
                "history is sent in full; whether Metis transmitted it is unknown",
                "bot configuration (temperature and similar) is not sent",
                "attachments are never sent",
            ],
        }
        path.write_text(
            json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )

    # ------------------------------------------------------------------- summary
    def summary(self, run_id: str, *, planned: int | None = None) -> Path:
        with self.engine.connect() as conn:
            rows = db.summary_rows(conn, run_id)
        manifest = self.settings.manifest()
        body = summarise(
            rows,
            run_id=run_id,
            manifest=manifest,
            planned=planned if planned is not None else len(rows),
        )
        slug = self.settings.dataset_id.replace("-", "_")
        folder = self._report_dir or self.root / "reports" / "evaluation" / slug
        path = folder / f"answers_{run_id}_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        shown = path.relative_to(self.root) if path.is_relative_to(self.root) else path
        self.log(f"Wrote {shown}")
        return path


def _count(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return dict(sorted(out.items()))


def _row_dict(row: AnswerRow) -> dict[str, Any]:
    d = dict(vars(row))
    d["status"] = row.status
    return d


def _row_json(row: AnswerRow) -> dict[str, Any]:
    d = _row_dict(row)
    d["cost_usd"] = None if row.cost_usd is None else str(row.cost_usd)
    d["caveats"] = list(row.caveats)
    return d


def _row_from_json(d: Mapping[str, Any]) -> AnswerRow:
    cost = d.get("cost_usd")
    return AnswerRow(
        **{
            **d,
            "cost_usd": None if cost is None else Decimal(cost),
            "caveats": tuple(d.get("caveats", ())),
        }
    )
