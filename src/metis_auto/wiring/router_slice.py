"""Build, verify and report the routing dev slice (ADR-XXXX (system-one-decision-router)
point 10).

Composition only: reads with ``data_access.full``, labels with golden-v1's
``analysis`` feature builder (same definitions as ``eval.request``), selects
and reports with ``evaluation.router_slice``.

Two passes over the dataset, one Parquet file at a time:
1. **Structure** (no text kept): message order, golden-v1 pairing and
   eligibility from lengths computed in Arrow, exclusions (workflow bots,
   platform-default instructions, golden records, sessions and families),
   cohorts, recorded billing and RAG counts → a seeded pool of candidates,
   at most one per session.
2. **Targeted**: full rows of the pool's sessions (and the golden targets, to
   exclude their duplicate families) → the golden feature row per target →
   the final seeded draw under soft quotas and hard caps → records.

Outputs: the record file and manifest under ``data/derived/`` (content;
git-ignored), the content-free reports under ``reports/routing/<slug>/``,
the local review sheet under ``runs/routing/<slug>/``. Nothing is printed but
counts, durations and memory. Traces: FR-DATA-02/04/06, FR-EVAL-04/06,
QA-PRIV, QA-REPRO.
"""

from __future__ import annotations

import csv
import io
import json
import math
import platform
import secrets
import sys
import time
import tomllib
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import metis_auto.evaluation.router_slice.reports as rep
from metis_auto.adapters.system.resources import peak_rss_mb
from metis_auto.analysis import session_config as sc
from metis_auto.analysis.pairing import CONVERSATIONAL, pair_ordered
from metis_auto.analysis.request_features import (
    BotContext,
    Vocabulary,
    family_ids,
    session_requests,
)
from metis_auto.application.measurement import Fingerprinter
from metis_auto.data_access.full import reader
from metis_auto.data_access.full.records import read_records, write_records
from metis_auto.data_access.full.source import check_source, read_pins, resolve_root
from metis_auto.evaluation.grouping import TextItem, duplicate_groups
from metis_auto.evaluation.router_slice.config import (
    POOL_FLAGS,
    SliceConfig,
    load_config,
)
from metis_auto.evaluation.router_slice.records import build_record
from metis_auto.evaluation.router_slice.select import (
    Candidate,
    Caps,
    Targets,
    allocate,
    scaled,
    select,
    split_by_session,
)
from metis_auto.evaluation.router_slice.strata import (
    PassOneTarget,
    final_candidate,
    instructions_class,
    pass_one_candidate,
)
from metis_auto.evaluation.router_slice.weights import (
    traffic_weights,
    uncovered_share,
)

DEFAULT_CONFIG = "config/evaluation/router_dev_slice_v1.toml"
DUPLICATE_TREATMENT = "persian_fold_v1"
"""Cross-bot duplicate groups (``evaluation.grouping``; ADR-0025 treatment)."""
FEATURE_VERSION_KEY = ("dataset", "feature_version")

Log = Callable[[str], None]


def read_full_label_map(path: Path) -> dict[str, tuple[str | None, str | None]]:
    """``label → (model_id, fidelity or unmapped reason)`` from the full-dataset
    mapping (``label-mapping-full-v1.toml``). That file carries extra counts and
    a dataset reference the sample-format ``settings`` reader does not accept,
    so only these three fields are read."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    out: dict[str, tuple[str | None, str | None]] = {}
    for row in raw.get("labels", []):
        out[row["label"]] = (
            row.get("model_id"),
            row.get("fidelity") or row.get("unmapped"),
        )
    return out


class SliceRefused(RuntimeError):
    """The build or check cannot proceed; the message says why (no content)."""


@dataclass(frozen=True)
class SlicePaths:
    root: Path
    slug: str

    @property
    def records(self) -> Path:
        return (
            self.root / "data" / "derived" / "routing" / self.slug / "records.parquet"
        )

    @property
    def manifest(self) -> Path:
        return self.root / "data" / "derived" / "routing" / self.slug / "manifest.json"

    @property
    def reports(self) -> Path:
        return self.root / "reports" / "routing" / self.slug

    @property
    def review_local(self) -> Path:
        return self.root / "runs" / "routing" / self.slug / "review_LOCAL_ONLY.csv"


def slug_of(cfg: SliceConfig) -> str:
    return cfg.slice.slice_id.removeprefix("router-").replace("-", "_")


def percentile_disc(sorted_values: list[int], q: float) -> int:
    """PostgreSQL ``percentile_disc``: the first value whose cumulative share
    reaches ``q`` (the golden pipeline's threshold rule)."""
    if not sorted_values:
        return 0
    index = max(0, math.ceil(q * len(sorted_values)) - 1)
    return sorted_values[min(index, len(sorted_values) - 1)]


def _encoded(table: Any, column: str) -> tuple[list[int | None], list[Any]]:
    """(codes, values) of a dictionary-encoded column; a null stays None."""
    encoded = table.column(column).combine_chunks().dictionary_encode()
    return encoded.indices.to_pylist(), encoded.dictionary.to_pylist()


def _write_text(path: Path, text: str, *, bom: bool = False) -> None:
    """Exact bytes on every platform: LF line ends, UTF-8 (BOM for Excel)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("﻿" if bom else "").encode("utf-8") + text.encode("utf-8"))


@dataclass
class _PassOne:
    targets: list[PassOneTarget] = field(default_factory=list)
    exclusions: Counter[str] = field(default_factory=Counter)
    totals: dict[str, int] = field(default_factory=dict)
    user_lengths: list[int] = field(default_factory=list)
    golden_sessions: set[str] = field(default_factory=set)
    golden_targets: dict[str, str] = field(default_factory=dict)
    """golden message_id → session_id."""
    cohort_user_messages: Counter[str] = field(default_factory=Counter)
    """Every USER message of the dataset by cohort (a traffic basis)."""


class RouterSlice:
    """One dev slice: its config, its dataset location, and its outputs."""

    def __init__(
        self,
        repo_root: Path,
        data_root: str,
        config_path: Path | None = None,
        *,
        log: Log = print,
    ) -> None:
        self.repo = repo_root
        self.config_path = config_path or repo_root / DEFAULT_CONFIG
        self.cfg, self.config_hash = load_config(self.config_path)
        self.paths = SlicePaths(repo_root, slug_of(self.cfg))
        self.data_root = resolve_root(data_root, repo_root)
        self.log = log
        self.last_audit: dict[str, Any] = {}
        self.pins = read_pins(repo_root / self.cfg.inputs.source_config)
        if self.pins.revision != self.cfg.slice.revision:
            raise SliceRefused(
                "the slice config's revision differs from source_config's pin"
            )
        with (repo_root / self.cfg.inputs.features_config).open("rb") as handle:
            self.features = tomllib.load(handle)
        if self.cfg.cohorts is not None:
            names = {*self.features["cohorts"]["ranked"]}
            names.add(self.features["cohorts"]["remaining"])
            if set(self.cfg.cohorts.targets) != names:
                raise SliceRefused(
                    "cohorts.targets must name exactly the cohorts of "
                    f"features_config: {sorted(names)}"
                )

    # ------------------------------------------------------------------ helpers
    def _check_source(self, *, hash_files: bool, allow_mismatch: bool) -> None:
        self.log(
            "Checking the dataset against the pins"
            + (" (sha256 of every file; about a minute)" if hash_files else "")
            + " ..."
        )
        check = check_source(self.data_root, self.pins, hash_files=hash_files)
        for problem in check.problems:
            self.log(f"  source problem: {problem}")
        if check.problems and not allow_mismatch:
            raise SliceRefused(
                f"{len(check.problems)} source problem(s); nothing was built. Re-run "
                "with --allow-source-mismatch only if you mean to (it is recorded)."
            )
        if not check.problems:
            self.log(
                f"  ok: revision {self.pins.revision[:12]}, {check.hashed} files hashed"
            )

    def _golden_ids(self) -> set[str]:
        ids: set[str] = set()
        for rel in self.cfg.inputs.golden_exports:
            path = self.repo / rel
            if not path.is_file():
                raise SliceRefused(f"golden export missing: {rel}")
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record_id = json.loads(line)["record_id"]
                    ids.add(record_id.split("-", 1)[1])
        return ids

    def _workflow_bots(self, bots: list[dict[str, Any]]) -> set[str]:
        ex = self.cfg.exclusions
        return {
            b["bot_id"]
            for b in bots
            if b.get("provider_name") in ex.workflow_provider_names
            or b.get("provider_model") in ex.workflow_provider_models
        }

    # ------------------------------------------------------------------- pass 1
    def _pass_one(
        self,
        *,
        with_text_lengths: bool,
        bots: list[dict[str, Any]],
        evidence: dict[str, str],
    ) -> tuple[_PassOne, dict[str, tuple[str, str]], dict[str, str]]:
        res = _PassOne()
        session_rows = reader.sessions(self.data_root).to_pylist()
        session_of = {
            r["session_id"]: (r["user_id"], r["bot_id"]) for r in session_rows
        }
        del session_rows
        workflow = self._workflow_bots(bots)
        golden = self._golden_ids()

        table = reader.light_messages(
            self.data_root, with_lengths=with_text_lengths, progress=self.log
        )
        order = table.sort_by(
            [
                ("session_id", "ascending"),
                ("timestamp", "ascending"),
                ("ordinal", "ascending"),
            ]
        )
        del table
        # Small ints and Arrow arrays instead of 710k Python strings per column.
        sid_codes, sid_values = _encoded(order, "session_id")
        type_codes, type_values = _encoded(order, "type")
        finish_codes, finish_values = _encoded(order, "finish_reason")
        mid_array = order.column("message_id").combine_chunks()
        ts_null = order.column("timestamp").is_null().to_pylist()
        if with_text_lengths:
            chars = order.column("content_chars").to_pylist()
            att = order.column("attachment_count").to_pylist()
        else:
            chars = [None] * order.num_rows
            att = [0] * order.num_rows
        res.totals = {"messages": order.num_rows}
        del order
        stop = finish_values.index("STOP") if "STOP" in finish_values else -2
        user = type_values.index("USER") if "USER" in type_values else -2
        conv_codes = {c for c, v in enumerate(type_values) if v in CONVERSATIONAL}

        def mid(k: int) -> str:
            return mid_array[k].as_py()

        rag_queries = reader.rag_query_counts(self.data_root)
        chunks = reader.chunk_counts(self.data_root, progress=self.log)
        input_tokens = reader.billing_input_tokens(self.data_root)

        owner_turns: Counter[str] = Counter()
        raw_targets: list[tuple[int, int, int, str]] = []
        i, n = 0, len(sid_codes)
        golden_k: set[int] = set()
        while i < n:
            j = i
            while j < n and sid_codes[j] == sid_codes[i]:
                j += 1
            sid = sid_values[sid_codes[i]]
            # The golden order: timestamp with nulls last, then source order.
            idx = sorted(range(i, j), key=lambda k: ts_null[k])
            conv = [k for k in idx if type_codes[k] in conv_codes]
            pairs = pair_ordered([type_values[type_codes[k]] for k in conv], conv)
            answer_of = {
                p.user_message_id: p for p in pairs if p.user_message_id is not None
            }
            owner = session_of.get(sid, ("", ""))[0]
            turn = 0
            for k in conv:
                if type_codes[k] != user:
                    continue
                turn += 1
                owner_turns[owner] += 1
                if chars[k] is not None:
                    res.user_lengths.append(chars[k])
                pair = answer_of.get(k)
                raw_targets.append(
                    (
                        k,
                        pair.ai_message_id if pair else -1,
                        turn,
                        pair.pair_flag if pair else "unanswered",
                    )
                )
                if golden:
                    message_id = mid(k)
                    if message_id in golden:
                        golden_k.add(k)
                        res.golden_sessions.add(sid)
                        res.golden_targets[message_id] = sid
            i = j

        res.user_lengths.sort()
        ranked = self.features["cohorts"]["ranked"]
        remaining = self.features["cohorts"]["remaining"]
        owners = sorted(owner_turns, key=lambda o: (-owner_turns[o], o))
        cohort_of = dict(zip(owners, ranked, strict=False))
        res.totals["user_messages"] = sum(owner_turns.values())
        for o, count in owner_turns.items():
            res.cohort_user_messages[cohort_of.get(o, remaining)] += count

        ex = self.cfg.exclusions
        for k, a, turn, flag in raw_targets:
            sid = sid_values[sid_codes[k]]
            owner, bot_id = session_of.get(sid, ("", ""))
            reason = None
            if with_text_lengths and not chars[k]:
                reason = "blank_target"
            elif ts_null[k]:
                reason = "null_target_timestamp"
            elif flag != "clean":
                reason = f"pair_{flag}"
            elif with_text_lengths and not chars[a]:
                reason = "blank_answer"
            elif ts_null[a]:
                reason = "null_answer_timestamp"
            elif finish_codes[a] != stop:
                reason = "answer_not_stop"
            elif bot_id in workflow:
                reason = "workflow_bot"
            elif (
                ex.exclude_platform_default_instructions
                and evidence.get(bot_id) == "platform_default"
            ):
                reason = "platform_default_instructions"
            elif k in golden_k:
                reason = "golden_record"
            elif ex.exclude_golden_sessions and sid in res.golden_sessions:
                reason = "golden_session"
            if reason is not None:
                res.exclusions[reason] += 1
                continue
            answer_id = mid(a)
            res.targets.append(
                PassOneTarget(
                    message_id=mid(k),
                    session_id=sid,
                    bot_id=bot_id,
                    turn_index=turn,
                    target_chars=chars[k] or 0,
                    attachment_count=att[k] or 0,
                    answer_message_id=answer_id,
                    answer_input_tokens=input_tokens.get(answer_id),
                    rag_on_answer=bool(
                        chunks.get(answer_id) or rag_queries.get(answer_id)
                    ),
                    cohort=cohort_of.get(owner, remaining),
                    instructions=instructions_class(evidence.get(bot_id, "unknown")),
                )
            )
        res.totals["eligible_targets"] = len(res.targets)
        return res, session_of, cohort_of

    def _pool_base(self, *, with_cohort: bool) -> Targets:
        """Pool targets in slice-size units: position, instructions present or
        absent (all pass 1 knows of the bot class), pass-1 flags; and the
        cohort shares when the pool is not drawn per cohort."""
        cfg = self.cfg
        final = cfg.share_targets(cfg.slice.size)
        shares: dict[str, dict[str, int]] = {}
        for dim in ("position", "cohort") if with_cohort else ("position",):
            if dim in final:
                shares[dim] = dict(final[dim])
        bot = cfg.quotas.get("bot_class", {})
        present = bot.get("instruction_rag", 0) + bot.get("instruction_only", 0)
        absent = bot.get("blank_no_config", 0) + bot.get("rag_only", 0)
        shares["instructions"] = {
            k: max(1, round(v * cfg.slice.size))
            for k, v in (("present", present), ("absent", absent))
            if v
        }
        minimums = {f: v for f, v in cfg.minimums.items() if f in POOL_FLAGS}
        return Targets(shares=shares, minimums=minimums)

    def _pool_per_bot(self) -> int:
        cfg = self.cfg
        return max(
            cfg.caps.per_bot,
            math.ceil(cfg.caps.per_bot * cfg.slice.candidate_pool / cfg.slice.size),
        )

    def _cohort_plan(
        self, targets: list[PassOneTarget]
    ) -> tuple[dict[str, dict[str, Any]], frozenset[str]]:
        """Per cohort: target, eligible sessions and bots, the planned pool
        (in proportion to the targets, capped by eligible sessions), the
        minimum the owner asked for, and whether the per-bot cap is waived.
        Also the bots exempt from the per-bot cap."""
        co = self.cfg.cohorts
        assert co is not None
        sessions: dict[str, set[str]] = defaultdict(set)
        bots: dict[str, set[str]] = defaultdict(set)
        for t in targets:
            sessions[t.cohort].add(t.session_id)
            bots[t.cohort].add(t.bot_id)
        capacity = {c: len(sessions[c]) for c in co.targets}
        planned = allocate(self.cfg.slice.candidate_pool, co.targets, capacity)
        exempt: set[str] = set()
        plan: dict[str, dict[str, Any]] = {}
        for cohort, target in sorted(co.targets.items()):
            waived = len(bots[cohort]) <= co.waive_per_bot_if_cohort_bots_at_most
            if waived:
                exempt |= bots[cohort]
            plan[cohort] = {
                "target": target,
                "eligible_sessions": capacity[cohort],
                "eligible_bots": len(bots[cohort]),
                "per_bot_cap_waived": waived,
                "pool_minimum": min(
                    math.ceil(co.pool_min_multiple * target), capacity[cohort]
                ),
                "pool_planned": planned[cohort],
            }
        return plan, frozenset(exempt)

    def _draw_pool(
        self, targets: list[PassOneTarget]
    ) -> tuple[list[Candidate], dict[str, dict[str, Any]], frozenset[str]]:
        """The candidate pool: per cohort when ``[cohorts]`` is set (each its
        planned share, its own seeded draw under the other pool targets scaled
        to it), else one draw under shares. Returns the candidates, the
        per-cohort plan with what was drawn, and the per-bot-exempt bots."""
        cfg = self.cfg
        factor = cfg.slice.candidate_pool / cfg.slice.size
        if cfg.cohorts is None:
            pool = select(
                (pass_one_candidate(t, cfg) for t in targets),
                cfg.slice.candidate_pool,
                scaled(
                    self._pool_base(with_cohort=True),
                    factor,
                    flag_factor=cfg.slice.pool_flag_oversample,
                ),
                Caps(per_session=1, per_bot=self._pool_per_bot(), per_family=10**9),
                seed=cfg.slice.seed,
                purpose="pool",
            )
            return pool.chosen, {}, frozenset()
        plan, exempt = self._cohort_plan(targets)
        by_cohort: dict[str, list[PassOneTarget]] = defaultdict(list)
        for t in targets:
            by_cohort[t.cohort].append(t)
        base = self._pool_base(with_cohort=False)
        chosen: list[Candidate] = []
        for cohort, row in plan.items():
            n = row["pool_planned"]
            drawn: list[Candidate] = []
            if n:
                drawn = select(
                    (pass_one_candidate(t, cfg) for t in by_cohort[cohort]),
                    n,
                    scaled(
                        base,
                        n / cfg.slice.size,
                        flag_factor=cfg.slice.pool_flag_oversample,
                    ),
                    Caps(
                        per_session=1,
                        per_bot=self._pool_per_bot(),
                        per_family=10**9,
                        per_bot_exempt=exempt,
                    ),
                    seed=cfg.slice.seed,
                    purpose=f"pool:{cohort}",
                ).chosen
            row["pool_drawn"] = len(drawn)
            row["pool_below_minimum"] = len(drawn) < row["pool_minimum"]
            chosen += drawn
        return chosen, plan, exempt

    # ------------------------------------------------------------------ plan
    def plan(self) -> dict[str, Any]:
        """Counts only: no text and no text length is read."""
        start = time.perf_counter()
        self._check_source(hash_files=False, allow_mismatch=True)
        bots = reader.bots(self.data_root, with_instructions=False)
        p1, _, _ = self._pass_one(with_text_lengths=False, bots=bots, evidence={})
        position = Counter(
            "first" if t.turn_index == 1 else "follow_up" for t in p1.targets
        )
        cohorts = Counter(t.cohort for t in p1.targets)
        rag = sum(t.rag_on_answer for t in p1.targets)
        high = sum(
            (t.answer_input_tokens or 0) > self.cfg.thresholds.high_input_min_tokens
            for t in p1.targets
        )
        sessions = len({t.session_id for t in p1.targets})
        cohort_plan = (
            self._cohort_plan(p1.targets)[0] if self.cfg.cohorts is not None else {}
        )
        return {
            "mode": "plan: no text read; blank-text, attachment and length checks "
            "wait for build",
            "totals": p1.totals,
            "exclusions": dict(sorted(p1.exclusions.items())),
            "eligible_targets": len(p1.targets),
            "eligible_sessions": sessions,
            "by_position": dict(sorted(position.items())),
            "by_cohort": dict(sorted(cohorts.items())),
            "pool_by_cohort": cohort_plan,
            "rag_on_answer": rag,
            "high_input_answers": high,
            "planned": {
                "size": self.cfg.slice.size,
                "candidate_pool": self.cfg.slice.candidate_pool,
                "split": {"tune_share": self.cfg.split.tune_share},
            },
            "duration_s": round(time.perf_counter() - start, 1),
            "peak_rss_mb": peak_rss_mb(),
        }

    # ----------------------------------------------------------------- build
    def build(self, *, allow_source_mismatch: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        cfg = self.cfg
        self._check_source(hash_files=True, allow_mismatch=allow_source_mismatch)

        bots = reader.bots(self.data_root, with_instructions=True)
        defaults = sc.platform_default_hashes(
            ((b["instructions"], b["user_id"], b["provider_name"]) for b in bots),
            "workflow",
            5,
        )
        evidence = {
            b["bot_id"]: sc.instruction_evidence(b["instructions"], defaults)
            for b in bots
        }
        bot_by_id = {b["bot_id"]: b for b in bots}

        p1, session_of, cohort_of = self._pass_one(
            with_text_lengths=True, bots=bots, evidence=evidence
        )
        self.log(f"pass 1: {len(p1.targets):,} eligible targets")

        pool_chosen, pool_plan, exempt_bots = self._draw_pool(p1.targets)
        pool_ids = {c.key for c in pool_chosen}
        by_id = {t.message_id: t for t in p1.targets if t.message_id in pool_ids}
        pool_sessions = {t.session_id for t in by_id.values()}
        golden_sessions = set(p1.golden_targets.values())
        traffic = (
            Counter(t.cohort for t in p1.targets)
            if cfg.weights.traffic_basis == "eligible_targets"
            else Counter(p1.cohort_user_messages)
        )
        self.log(
            f"pool: {len(pool_ids):,} candidates in {len(pool_sessions):,} sessions"
        )
        del p1.targets

        messages = reader.session_messages(
            self.data_root, pool_sessions | golden_sessions, progress=self.log
        )
        by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for m in messages:
            by_session[m["session_id"]].append(m)
        del messages
        for msgs in by_session.values():
            msgs.sort(
                key=lambda m: (
                    m["timestamp_is_null"],
                    m["timestamp"] or 0,
                    m["ordinal"],
                )
            )

        answer_ids = {t.answer_message_id for t in by_id.values()}
        all_ids = [
            m["message_id"] for s in pool_sessions for m in by_session.get(s, [])
        ]
        chunk_read = reader.chunks_for(
            self.data_root, all_ids, keep_text_for=answer_ids, progress=self.log
        )
        rag_queries = reader.rag_query_counts(self.data_root)
        billing = reader.billing_sums(self.data_root, only=answer_ids)

        rules = self.features["rules"]
        thresholds = {
            "complex_chars": percentile_disc(
                p1.user_lengths, rules["complex_min_chars_percentile"] / 100
            ),
            "average_chars": percentile_disc(
                p1.user_lengths, rules["average_min_chars_percentile"] / 100
            ),
            "complex_history": rules["complex_min_history_chars"],
            "distant_history_min_turn": self.features["buckets"][
                "distant_history_min_turn"
            ],
        }
        del p1.user_lengths
        vocab = Vocabulary(rules)
        groups = self.features["language_groups"]
        intents = self.features["intent_map"]
        feature_version = self.features["dataset"]["feature_version"]
        remaining = self.features["cohorts"]["remaining"]
        contexts = {
            bid: BotContext(
                bot_id=bid,
                instruction_evidence=evidence[bid],
                rag_config=sc.rag_config_evidence(b["corpus_ids"]),
                instruction_chars=len(b["instructions"] or ""),
            )
            for bid, b in bot_by_id.items()
        }

        def rows_of(session_id: str) -> list[dict[str, Any]]:
            msgs = by_session.get(session_id, [])
            for m in msgs:
                m.update(chunk_read.stats.get(m["message_id"], {}))
                m.setdefault("rag_n_chunks", 0)
                m.setdefault("rag_chunk_chars", 0)
                m["rag_n_queries"] = rag_queries.get(m["message_id"], 0)
            owner, bot_id = session_of[session_id]
            return session_requests(
                msgs,
                bot=contexts[bot_id],
                cohort=cohort_of.get(owner, remaining),
                vocab=vocab,
                groups=groups,
                intent_map=intents,
                thresholds=thresholds,
                feature_version=feature_version,
            )

        def text_of(session_id: str, message_id: str) -> str:
            return next(
                (
                    m["content"] or ""
                    for m in by_session.get(session_id, [])
                    if m["message_id"] == message_id
                ),
                "",
            )

        golden_families: set[str] = set()
        if cfg.exclusions.exclude_golden_families:
            for mid, sid in p1.golden_targets.items():
                for f in family_ids(session_of[sid][1], text_of(sid, mid)):
                    if f:
                        golden_families.add(f)
        # Cross-bot duplicate groups; the key lives only for this build, so
        # group IDs are never comparable outside it (and never written).
        grouper = Fingerprinter(secrets.token_bytes(32))
        items = [
            TextItem(
                item_id=t.message_id,
                session_ref=t.session_id,
                text=text_of(t.session_id, t.message_id),
            )
            for t in by_id.values()
        ] + [
            TextItem(item_id=f"golden:{mid}", session_ref=sid, text=text_of(sid, mid))
            for mid, sid in p1.golden_targets.items()
        ]
        dup_of = duplicate_groups(items, DUPLICATE_TREATMENT, grouper)
        golden_dups = {g for k, g in dup_of.items() if k.startswith("golden:")}

        pool_lost: Counter[str] = Counter()
        finals = []
        rows_by_id: dict[str, dict[str, Any]] = {}
        for sid in sorted(pool_sessions):
            for row in rows_of(sid):
                if row["request_id"] not in pool_ids:
                    continue
                if not row["eligible"]:
                    pool_lost[row["exclusion_reason"]] += 1
                    continue
                if row["bot_class"] in cfg.exclusions.exclude_bot_classes:
                    pool_lost[f"bot_class_{row['bot_class']}"] += 1
                    continue
                if {
                    row["exact_family_id"],
                    row["near_family_id"],
                } & golden_families or (
                    cfg.exclusions.exclude_golden_families
                    and dup_of.get(row["request_id"]) in golden_dups
                ):
                    pool_lost["golden_family"] += 1
                    continue
                answer_tokens = billing.get(row["answer_message_id"], {}).get(
                    "billing_input_tokens"
                )
                finals.append(
                    final_candidate(
                        row,
                        answer_tokens,
                        cfg,
                        duplicate_group=dup_of.get(row["request_id"]),
                    )
                )
                rows_by_id[row["request_id"]] = row

        final_targets = Targets(
            shares=cfg.share_targets(cfg.slice.size),
            minimums=dict(cfg.minimums),
            ceilings=cfg.ceiling_counts(cfg.slice.size),
        )
        chosen = select(
            finals,
            cfg.slice.size,
            final_targets,
            Caps(
                cfg.caps.per_session,
                cfg.caps.per_bot,
                cfg.caps.per_family,
                per_bot_exempt=exempt_bots,
            ),
            seed=cfg.slice.seed,
            purpose="final",
        )
        split_of = split_by_session(
            [c.session_id for c in chosen.chosen],
            cfg.split.tune_share,
            seed=cfg.slice.seed,
        )
        mapping = read_full_label_map(self.repo / cfg.inputs.label_mapping)
        weights = traffic_weights(
            Counter(c.strata["cohort"] for c in chosen.chosen), traffic
        )

        records = []
        for c in sorted(chosen.chosen, key=lambda c: c.key):
            row = rows_by_id[c.key]
            msgs = by_session[c.session_id]
            position = next(i for i, m in enumerate(msgs) if m["message_id"] == c.key)
            answer = next(
                m for m in msgs if m["message_id"] == row["answer_message_id"]
            )
            bot = bot_by_id[row["bot_id"]]
            mapped, fidelity = mapping.get(
                bot.get("provider_model") or "", (None, "not_listed")
            )
            records.append(
                build_record(
                    prefix=cfg.slice.record_prefix,
                    split=split_of[c.session_id],
                    row=row,
                    flags=sorted(c.flags),
                    history=msgs[:position],
                    target=msgs[position],
                    answer=answer,
                    bot=bot,
                    chunks=chunk_read.texts.get(row["answer_message_id"], []),
                    billing=billing.get(row["answer_message_id"]),
                    mapped_model_id=mapped,
                    mapping_fidelity=fidelity,
                    history_max_turns=cfg.record.history_max_turns,
                    cohort_traffic_share=round(
                        weights[row["owner_cohort"]].traffic_share, 6
                    ),
                    traffic_weight=weights[row["owner_cohort"]].weight,
                )
            )
        by_session.clear()  # drop the text before writing outputs
        chunk_read.texts.clear()
        write_records(self.paths.records, records)

        splits: dict[str, Counter[str]] = defaultdict(Counter)
        for r in records:
            splits[r["split"]][r["language_group"]] += 1
        stats = rep.selection_stats(chosen, final_targets, splits=splits)
        stats.update(
            exclusions=dict(sorted(p1.exclusions.items())),
            eligible_targets=p1.totals["eligible_targets"],
            pool_size=len(pool_ids),
            pool_lost=dict(sorted(pool_lost.items())),
            pool_by_cohort=pool_plan,
            traffic={
                "basis": cfg.weights.traffic_basis,
                "dimension": "cohort",
                "by_value": {
                    k: {
                        "traffic": w.traffic,
                        "traffic_share": round(w.traffic_share, 6),
                        "records": w.records,
                        "slice_share": round(w.slice_share, 6),
                        "weight": w.weight,
                    }
                    for k, w in weights.items()
                },
                "uncovered_share": round(uncovered_share(weights), 6),
                "user_messages_by_cohort": dict(
                    sorted(p1.cohort_user_messages.items())
                ),
            },
        )
        manifest = {
            "slice_id": cfg.slice.slice_id,
            "record_version": records[0]["record_version"] if records else None,
            "revision": cfg.slice.revision,
            "seed": cfg.slice.seed,
            "config_hash": self.config_hash,
            "source_override": allow_source_mismatch,
            "records": len(records),
            "stats": stats,
            "thresholds": thresholds,
            "build": {
                "duration_s": round(time.perf_counter() - start, 1),
                "peak_rss_mb": peak_rss_mb(),
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
        }
        _write_text(
            self.paths.manifest,
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        )
        self._write_reports(records, manifest)
        return {
            "records": len(records),
            "splits": {k: sum(v.values()) for k, v in sorted(splits.items())},
            "shortfalls": len(stats["shortfalls"]),
            "pool_size": len(pool_ids),
            "eligible_targets": p1.totals["eligible_targets"],
            **manifest["build"],
        }

    # ---------------------------------------------------------------- outputs
    def _write_reports(
        self, records: list[dict[str, Any]], manifest: dict[str, Any]
    ) -> None:
        ids = rep.id_rows(records)
        out = self.paths.reports
        _write_text(out / "ids.csv", rep.to_csv(ids, rep.ID_COLUMNS))
        _write_text(
            out / "composition.md",
            rep.composition_markdown(
                self.cfg, manifest["config_hash"], manifest["stats"]
            ),
        )
        fp = rep.fingerprint(self.cfg, manifest["config_hash"], self.pins.files, ids)
        _write_text(out / "fingerprint.json", json.dumps(fp, indent=2) + "\n")
        template = rep.review_template_rows(
            [r["slice_record_id"] for r in records], self.cfg
        )
        _write_text(
            out / "review_template.csv", rep.to_csv(template, rep.LABEL_COLUMNS)
        )
        review = rep.review_rows(records, self.cfg)
        _write_text(
            self.paths.review_local, rep.to_csv(review, rep.REVIEW_COLUMNS), bom=True
        )

    def report(self) -> dict[str, Any]:
        """Regenerate every output from the local record file and manifest."""
        records, manifest = self._local()
        if manifest["config_hash"] != self.config_hash:
            raise SliceRefused(
                "the config changed since the build; run build again (report "
                "never mixes a new config with old records)"
            )
        self._write_reports(records, manifest)
        return {
            "records": len(records),
            "reports": self.paths.reports.relative_to(self.repo).as_posix(),
        }

    def frozen_records(self) -> list[dict[str, Any]]:
        """The local records, only if they are the committed slice: the same
        config hash as ``fingerprint.json`` and the same IDs, strata and splits
        as ``ids.csv`` (cheap: the dataset is not read). For replays of the
        frozen slice (R4–R8); a mismatch is refused, never rebuilt here."""
        fp_path = self.paths.reports / "fingerprint.json"
        if not fp_path.is_file():
            raise SliceRefused("no committed fingerprint.json; build the slice first")
        expected = json.loads(fp_path.read_text(encoding="utf-8"))
        if expected.get("config_hash") != self.config_hash:
            raise SliceRefused("the slice config changed since the committed build")
        records, _ = self._local()
        committed = (self.paths.reports / "ids.csv").read_bytes().decode("utf-8")
        ids = rep.to_csv(rep.id_rows(records), rep.ID_COLUMNS)
        if committed.replace("\r\n", "\n") != ids:
            raise SliceRefused(
                "the local records differ from the committed ids.csv; the slice "
                "is frozen, so nothing is replayed"
            )
        return records

    def _local(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.paths.records.is_file() or not self.paths.manifest.is_file():
            raise SliceRefused("no local build found; run build first")
        manifest = json.loads(self.paths.manifest.read_text(encoding="utf-8"))
        return read_records(self.paths.records), manifest

    # ----------------------------------------------------------------- verify
    def verify(self, *, hash_files: bool = True) -> list[str]:
        """Problems, or an empty list: config unchanged since the committed
        fingerprint, source as pinned, local build identical to it."""
        problems: list[str] = []
        fp_path = self.paths.reports / "fingerprint.json"
        if not fp_path.is_file():
            return ["no committed fingerprint.json; build and report first"]
        expected = json.loads(fp_path.read_text(encoding="utf-8"))
        if expected.get("config_hash") != self.config_hash:
            problems.append("config changed since the committed fingerprint")
        check = check_source(self.data_root, self.pins, hash_files=hash_files)
        problems += [f"source: {p}" for p in check.problems]
        try:
            records, _ = self._local()
        except SliceRefused as exc:
            problems.append(str(exc))
            return problems
        ids = rep.id_rows(records)
        actual = rep.fingerprint(self.cfg, self.config_hash, self.pins.files, ids)
        problems += [
            f"fingerprint: {p}" for p in rep.compare_fingerprints(expected, actual)
        ]
        committed_ids = (self.paths.reports / "ids.csv").read_bytes().decode("utf-8")
        if committed_ids.replace("\r\n", "\n") != rep.to_csv(ids, rep.ID_COLUMNS):
            problems.append("ids.csv differs from the local build")
        self.last_audit = self.golden_audit(records)
        problems += self.last_audit["problems"]
        return problems

    def golden_audit(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Content-free check that no golden record and no golden session is in
        the slice, using the golden exports' own message and session IDs; and
        how many golden records sit on workflow bots (pass 1 counts those under
        ``workflow_bot``, which is checked before ``golden_record``)."""
        golden: dict[str, tuple[str, str]] = {}
        for rel in self.cfg.inputs.golden_exports:
            for line in (self.repo / rel).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    message_id = row["record_id"].split("-", 1)[1]
                    golden[message_id] = (row.get("session_id"), row.get("bot_id"))
        workflow = self._workflow_bots(
            reader.bots(self.data_root, with_instructions=False)
        )
        golden_sessions = {s for s, _ in golden.values() if s}
        in_slice = sum(r["message_id"] in golden for r in records)
        sessions_in_slice = sum(r["session_id"] in golden_sessions for r in records)
        problems = []
        if in_slice:
            problems.append(f"golden audit: {in_slice} golden record(s) in the slice")
        if sessions_in_slice:
            problems.append(
                f"golden audit: {sessions_in_slice} record(s) from golden sessions"
            )
        missing = sum(1 for s, _ in golden.values() if not s)
        if missing:
            problems.append(f"golden audit: {missing} export row(s) lack a session_id")
        return {
            "golden_records": len(golden),
            "golden_sessions": len(golden_sessions),
            "golden_on_workflow_bots": sum(b in workflow for _, b in golden.values()),
            "golden_records_in_slice": in_slice,
            "slice_records_from_golden_sessions": sessions_in_slice,
            "problems": problems,
        }

    # ----------------------------------------------------------------- labels
    def import_labels(self, path: Path) -> dict[str, Any]:
        records, _ = self._local()
        known = {r["slice_record_id"] for r in records}
        text = path.read_bytes().decode("utf-8-sig")
        result = rep.import_labels(
            csv.DictReader(io.StringIO(text)), known, self.cfg.review.reviewers
        )
        if result.problems:
            raise SliceRefused(
                f"{len(result.problems)} problem(s) in the label file; "
                "nothing imported:\n  " + "\n  ".join(result.problems[:20])
            )
        out = self.paths.reports
        _write_text(out / "labels_l3.csv", rep.to_csv(result.labels, rep.LABEL_COLUMNS))
        _write_text(
            out / "labels_l3_agreement.json",
            json.dumps(result.agreement, indent=2) + "\n",
        )
        return result.agreement
