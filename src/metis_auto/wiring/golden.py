"""Compose the evaluation dataset: requests, selection, records, labels, exports,
validation, fingerprint (ADR-0028). No decisions here; each step calls pure code in
``analysis`` or ``evaluation.golden`` and SQL in ``data_access.postgres``.

Content-bearing output goes only to git-ignored ``runs/`` and ``data/derived/``.
"""

from __future__ import annotations

import csv
import json
import tomllib
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from metis_auto.analysis import session_config as sc
from metis_auto.analysis.request_features import (
    BotContext,
    Vocabulary,
    bigrams,
    jaccard,
    session_requests,
)
from metis_auto.data_access.postgres import repository as repo
from metis_auto.data_access.postgres.exports import write_rows
from metis_auto.evaluation.golden.annotations import (
    RUBRIC,
    LabelRow,
    double_annotation_ids,
    label_errors,
    percent_agreement,
    rule_annotations,
    weighted_kappa,
)
from metis_auto.evaluation.golden.config import (
    SOFT_MARGINS,
    GoldenConfig,
    config_sha256,
    length_bucket,
    length_edges,
    parse_config,
    position_bucket,
)
from metis_auto.evaluation.golden.manifest import GOLDEN_V1_SCHEMA_VERSION
from metis_auto.evaluation.golden.mapping import build_mapping, carry_labels
from metis_auto.evaluation.golden.records import billing_summary, build_components
from metis_auto.evaluation.golden.report import (
    context_dependency,
    cross_tab,
    mandatory_checks,
    margin_report,
    markdown_table,
    small_n_cells,
)
from metis_auto.evaluation.golden.selection import (
    Candidate,
    derive_without,
    design_weights,
    plan_swaps,
    seeded_rank,
    select,
)
from metis_auto.evaluation.golden.validation import (
    fingerprint,
    fingerprint_diff,
    markdown,
    run_checks,
    scan_for_content,
)
from metis_auto.settings.loader import repo_root
from metis_auto.wiring.database import engine_from_settings
from metis_auto.wiring.db_ingest import git_sha, source_config

CONFIG_PATH = "config/evaluation/golden_v1.toml"
HISTORY_IN_SHEET = 6


class Golden:
    """One dataset's build steps, sharing a config and an engine."""

    def __init__(
        self,
        engine: Engine | None = None,
        root: Path | None = None,
        config_path: str = CONFIG_PATH,
        log=print,
    ):
        self.root = root or repo_root()
        self.engine = engine or engine_from_settings()
        data = (self.root / config_path).read_bytes()
        self.cfg: GoldenConfig = parse_config(
            tomllib.loads(data.decode("utf-8")), config_sha256(data)
        )
        self.log = log
        slug = self.cfg.dataset_id.replace("-", "_")
        self.slug = slug
        self.report_dir = f"reports/evaluation/{slug}"
        self.local_review = f"runs/evaluation/{slug}/review_local"
        self.local_export = f"data/derived/eval_datasets/{slug}"

    @property
    def derived(self) -> Mapping[str, Any] | None:
        """The ``[derive]`` section of a dataset built from another (ADR-0029)."""
        return self.cfg.raw.get("derive")

    # ------------------------------------------------------------------ requests
    def build_requests(self, force: bool = False) -> int:
        raw = self.cfg.raw
        version = raw["dataset"]["feature_version"]
        with self.engine.connect() as conn:
            if not force and repo.request_count(conn, version):
                n = repo.request_count(conn, version)
                self.log(f"eval.request already built: {n} rows. Nothing to do.")
                return n
            state = repo.dataset_state(conn, self.cfg.dataset_id)
            if state and (state["status"] == "frozen" or state["human_labels"]):
                raise SystemExit(
                    "Refused: the dataset is frozen or holds human labels, and it "
                    "depends on eval.request. Nothing was changed."
                )
            rag = repo.rag_stats(conn)
            owners = repo.owners_by_user_turns(conn)
            sessions = repo.session_owner_map(conn)
            bots = repo.bots_for_features(conn)
            rules = raw["rules"]
            thresholds = {
                "complex_chars": repo.user_char_percentile(
                    conn, rules["complex_min_chars_percentile"] / 100
                ),
                "average_chars": repo.user_char_percentile(
                    conn, rules["average_min_chars_percentile"] / 100
                ),
                "complex_history": rules["complex_min_history_chars"],
                "distant_history_min_turn": raw["buckets"]["distant_history_min_turn"],
            }
        ranked = raw["cohorts"]["ranked"]
        cohort_of = dict(zip(owners, ranked, strict=False))
        defaults = sc.platform_default_hashes(
            ((b["instructions"], b["user_id"], b["provider_name"]) for b in bots),
            "workflow",
            5,
        )
        contexts = {
            b["bot_id"]: BotContext(
                bot_id=b["bot_id"],
                instruction_evidence=sc.instruction_evidence(
                    b["instructions"], defaults
                ),
                rag_config=sc.rag_config_evidence(b["corpus_ids"]),
                instruction_chars=len(b["instructions"] or ""),
            )
            for b in bots
        }
        vocab = Vocabulary(rules)
        groups = raw["language_groups"]
        intents = raw["intent_map"]
        remaining = raw["cohorts"]["remaining"]

        def rows():
            for session_id, messages in repo.iter_session_messages(self.engine):
                bot_id, user_id = sessions[session_id]
                for msg in messages:
                    msg.update(rag.get(msg["message_id"], {}))
                yield from session_requests(
                    messages,
                    bot=contexts[bot_id],
                    cohort=cohort_of.get(user_id, remaining),
                    vocab=vocab,
                    groups=groups,
                    intent_map=intents,
                    thresholds=thresholds,
                    feature_version=version,
                )

        self.log("Building eval.request. Safe to interrupt: it is one transaction.")
        with self.engine.begin() as conn:
            repo.delete_dataset(conn, self.cfg.dataset_id)
        n = repo.replace_requests(self.engine, rows())
        self.log(f"eval.request: {n} rows.")
        return n

    # ----------------------------------------------------------------- candidates
    def _candidates(self):
        raw = self.cfg.raw
        with self.engine.connect() as conn:
            rows = repo.eligible_requests(conn)
        chars = sorted(r["target_chars"] for r in rows)
        edges = length_edges(chars, raw["buckets"]["length_percentiles"])
        labels = raw["buckets"]["length_labels"]
        middle = raw["buckets"]["middle_max"]
        cands, strata = [], {}
        for r in rows:
            s = {
                "complexity_proxy": r["complexity_proxy"],
                "language_group": r["language_group"],
                "target_length": length_bucket(r["target_chars"], edges, labels),
                "position": position_bucket(r["turn_index"], middle),
                "bot_class": r["bot_class"],
            }
            tags = frozenset(
                k
                for k, v in r["rule_tags"].items()
                if k in raw["coverage"] and v is True
            )
            strata[r["request_id"]] = {
                **s,
                "primary_intent": r["rule_intent"],
                "cohort": r["owner_cohort"],
                "tags": r["rule_tags"],
                "context_dependency": context_dependency(r["rule_tags"]),
            }
            cands.append(
                Candidate(
                    request_id=r["request_id"],
                    session_id=r["session_id"],
                    bot_id=r["bot_id"],
                    intent=r["rule_intent"],
                    cohort=r["owner_cohort"],
                    strata=tuple((m, s[m]) for m in SOFT_MARGINS),
                    tags=tags,
                    family=r["exact_family_id"],
                    near_family=r["near_family_id"],
                )
            )
        return cands, strata, edges

    def _select_without_near_duplicates(self, cands):
        """Reselect until no two chosen texts are near duplicates (bigram Jaccard)."""
        raw = self.cfg.raw["selection"]
        threshold = raw["near_duplicate_bigram_jaccard"]
        excluded: set[str] = set()
        for round_no in range(raw["near_duplicate_rounds_max"]):
            sel = select(cands, self.cfg, frozenset(excluded))
            ids = [c.request_id for c, _ in sel.primary + sel.reserves]
            with self.engine.connect() as conn:
                texts = repo.texts_for(conn, ids)
            grams = {i: bigrams(texts[i]) for i in ids}
            drop = {
                b
                for x, a in enumerate(ids)
                for b in ids[x + 1 :]
                if jaccard(grams[a], grams[b]) >= threshold
            }
            self.log(f"Selection round {round_no + 1}: {len(drop)} near duplicates.")
            if not drop:
                return sel, len(excluded)
            excluded |= drop
        raise RuntimeError("near duplicates remain after the configured rounds")

    def _selection(self, cands):
        """A fresh selection, or the base dataset minus its attachment records."""
        if self.derived is None:
            return self._select_without_near_duplicates(cands)
        return self._derive_selection(cands)

    def _derive_selection(self, cands):
        """ADR-0029: drop the base's attachment records and replace each inside its
        cell (reserves first, then the pool), then re-check near duplicates for the
        new records only. Refuses unless the base is exactly the one pinned."""
        spec = self.derived
        base_id = spec["base_dataset"]
        with self.engine.connect() as conn:
            state = repo.dataset_state(conn, base_id)
            if state is None:
                raise SystemExit(
                    f"Refused: {base_id} is not built. Build it first with "
                    f"`build_eval_dataset.py all` and check it with `verify`."
                )
            base = repo.dataset_records(conn, base_id)
            reserves = repo.reserve_rows(conn, base_id)
            attachments = repo.attachment_request_ids(conn)
        got = fingerprint(
            [r["record_id"] for r in base], state["version"], state["config_sha256"]
        )
        if got != spec["base_fingerprint"]:
            raise SystemExit(
                f"Refused: {base_id} differs from the one this dataset derives "
                f"from (fingerprint {got[:12]}…). Run its `verify` first."
            )
        raw = self.cfg.raw["selection"]
        threshold = raw["near_duplicate_bigram_jaccard"]
        excluded: set[str] = set()
        for round_no in range(raw["near_duplicate_rounds_max"]):
            sel = derive_without(
                cands,
                self.cfg,
                base_primary=[
                    (r["request_id"], r["selection_rationale"]) for r in base
                ],
                base_reserves=[r["request_id"] for r in reserves],
                remove=frozenset(attachments),
                exclude=frozenset(excluded),
            )
            new = {m["replacement"] for m in sel.moves if "replacement" in m}
            ids = [c.request_id for c, _ in sel.primary + sel.reserves]
            with self.engine.connect() as conn:
                texts = repo.texts_for(conn, ids)
            grams = {i: bigrams(texts[i]) for i in ids}
            drop = {
                n
                for n in sorted(new)
                for o in ids
                if o != n and jaccard(grams[n], grams[o]) >= threshold
            }
            self.log(f"Derive round {round_no + 1}: {len(drop)} near duplicates.")
            if not drop:
                unfilled = sum("unfilled" in m for m in sel.moves)
                if unfilled:
                    self.log(
                        f"WARNING: {unfilled} removed records have no replacement."
                    )
                return sel, len(excluded)
            excluded |= drop
        raise RuntimeError("near duplicates remain after the configured rounds")

    def _stratum(self, stratum: Mapping[str, Any]) -> dict[str, Any]:
        """The record's stratum plus its caveats, when the config names any."""
        by_intent = self.cfg.raw.get("caveats", {}).get("by_intent")
        if not by_intent:
            return dict(stratum)
        caveat = by_intent.get(stratum["primary_intent"])
        return {**stratum, "caveats": [caveat] if caveat else []}

    # -------------------------------------------------------------------- dataset
    def build_dataset(self, *, force: bool = False) -> None:
        raw = self.cfg.raw
        ds = raw["dataset"]
        with self.engine.connect() as conn:
            state = repo.dataset_state(conn, ds["dataset_id"])
        if state:
            if state["status"] == "frozen":
                raise SystemExit("The dataset is frozen. Nothing was changed.")
            if state["human_labels"] and not force:
                raise SystemExit(
                    "The dataset holds human labels. Export them first, then pass "
                    "--force to rebuild."
                )
        cands, strata, edges = self._candidates()
        population: dict[str, Counter] = {
            m: Counter()
            for m in (*SOFT_MARGINS, "primary_intent", "cohort", "coverage")
        }
        eligible_cells: Counter = Counter()
        in_population = cands
        if self.derived is not None:
            with self.engine.connect() as conn:
                attachments = repo.attachment_request_ids(conn)
            in_population = [c for c in cands if c.request_id not in attachments]
        for c in in_population:
            s = strata[c.request_id]
            for margin in (*SOFT_MARGINS, "primary_intent", "cohort"):
                population[margin][s[margin]] += 1
            eligible_cells[c.cell] += 1
            for tag in c.tags:
                population["coverage"][tag] += 1
        sel, n_near = self._selection(cands)
        if len(sel.primary) != self.cfg.total:
            self.log(f"WARNING: selected {len(sel.primary)}, not {self.cfg.total}.")
        sampled = Counter(c.cell for c, _ in sel.primary)
        weights, uncovered = design_weights(eligible_cells, sampled)

        records, components, references, annotations = [], [], [], []
        prefix = ds["record_prefix"]
        ids = [c.request_id for c, _ in sel.primary]
        with self.engine.connect() as conn:
            requests = repo.request_rows(conn, ids)
            for rank, (cand, code) in enumerate(sel.primary):
                record_id = f"{prefix}-{cand.request_id}"
                req = requests[cand.request_id]
                session = repo.session_messages(conn, cand.session_id)
                target = next(m for m in session if m["message_id"] == cand.request_id)
                target = {**target, "attachment_types": req["attachment_types"]}
                earlier_ai = [m["message_id"] for m in session if m["type"] == "AI"]
                chunks = repo.chunks_for(conn, earlier_ai)
                answer_id = req["answer_message_id"]
                snap = repo.bot_snapshot(conn, cand.bot_id)
                snap_for_input = {**snap, "config_unknown": req["config_unknown"]}
                comps = build_components(
                    target=target,
                    session=session,
                    bot=snap_for_input,
                    answer_chunks=chunks.get(answer_id, ()),
                    earlier_chunks={k: v for k, v in chunks.items() if k != answer_id},
                )
                components += [{**c, "record_id": record_id} for c in comps]
                records.append(
                    {
                        "record_id": record_id,
                        "dataset_id": ds["dataset_id"],
                        "request_id": cand.request_id,
                        "session_id": cand.session_id,
                        "stratum": self._stratum(strata[cand.request_id]),
                        "population_weight": weights[cand.cell],
                        "weight_basis": "eligible_requests/primary_intent_x_cohort",
                        "selection_rank": rank,
                        "selection_rationale": code,
                    }
                )
                references.append(
                    {
                        "record_id": record_id,
                        "answer_message_id": answer_id,
                        "reference_provider_label": snap["provider_name"],
                        "reference_model_label": snap["provider_model"],
                        "reference_model_source": "bot_config_snapshot",
                        "finish_reason": req["answer_finish_reason"],
                        "billing_summary": billing_summary(
                            repo.billing_items(conn, answer_id)
                        ),
                        "availability_stage": "post_generation",
                    }
                )
                annotations += rule_annotations(record_id, req, ds["rubric_version"])

        report_rows = [
            {
                "stratum": r["stratum"],
                "bot_id": next(
                    c.bot_id for c, _ in sel.primary if c.request_id == r["request_id"]
                ),
                "rag_observed_on_answer": requests[r["request_id"]][
                    "rag_observed_on_answer"
                ],
            }
            for r in records
        ]
        margins = margin_report(
            report_rows,
            population,
            self.cfg,
            derived_note=(
                "golden-v2: attachment records replaced inside their cell (ADR-0029)"
                if self.derived
                else None
            ),
        )
        source = source_config(self.root)["source"]
        with self.engine.begin() as conn:
            repo.write_dataset(
                conn,
                dataset={
                    "dataset_id": ds["dataset_id"],
                    "name": ds["name"],
                    "version": ds["version"],
                    "status": "draft",
                    "config_sha256": self.cfg.sha256,
                },
                sampling={
                    "dataset_id": ds["dataset_id"],
                    "seed": self.cfg.seed,
                    "config": {
                        "config": raw,
                        "length_edges": edges,
                        "near_duplicates_excluded": n_near,
                        "moves": sel.moves,
                        **(
                            {"derived_from": dict(self.derived)} if self.derived else {}
                        ),
                        "uncovered_population_share": uncovered,
                        "joint": {
                            f"{a}|{b}": n for (a, b), n in sorted(sel.joint.items())
                        },
                    },
                    "code_git_sha": git_sha(self.root),
                    "population_snapshot": {
                        "dataset_revision": source["revision"],
                        "eligible_requests": len(in_population),
                        "pool_distinct": sel.pool_size,
                        "by_margin": {k: dict(v) for k, v in population.items()},
                    },
                    "status": "completed",
                },
                margins=margins,
                records=records,
                reserves=[
                    {
                        "dataset_id": ds["dataset_id"],
                        "request_id": c.request_id,
                        "session_id": c.session_id,
                        "cell": cell,
                        "reserve_rank": i,
                        "stratum": strata[c.request_id],
                    }
                    for i, (c, cell) in enumerate(sel.reserves)
                ],
                components=components,
                references=references,
                rubric={
                    "rubric_version": ds["rubric_version"],
                    "document": ds["rubric_document"],
                    "config_sha256": self.cfg.sha256,
                },
                rubric_values=[
                    {
                        "rubric_version": ds["rubric_version"],
                        "dimension": dim,
                        "value": value,
                        "definition_ref": f"{ds['rubric_document']}#{dim}",
                    }
                    for dim, values in sorted(RUBRIC.items())
                    for value in values
                ],
                annotations=annotations,
            )
            repo.set_status(conn, ds["dataset_id"], "annotated_provisional")
        self.log(
            f"Dataset {ds['dataset_id']}: {len(records)} records, "
            f"{len(sel.reserves)} reserves, status annotated_provisional."
        )

    # --------------------------------------------------------------- fingerprint
    def _fingerprint(self) -> dict[str, Any]:
        ds = self.cfg.raw["dataset"]
        with self.engine.connect() as conn:
            records = repo.dataset_records(conn, ds["dataset_id"])
        ids = sorted(r["record_id"] for r in records)
        return {
            "dataset_id": ds["dataset_id"],
            "version": ds["version"],
            "dataset_revision": source_config(self.root)["source"]["revision"],
            "config_sha256": self.cfg.sha256,
            "record_count": len(ids),
            "record_ids": ids,
            "fingerprint": fingerprint(ids, ds["version"], self.cfg.sha256),
        }

    def write_fingerprint(self) -> Path:
        path = self.root / self.report_dir / "fingerprint.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._fingerprint(), indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.log(f"Wrote {path.relative_to(self.root)}")
        return path

    def verify(self) -> bool:
        path = self.root / self.report_dir / "fingerprint.json"
        if not path.exists():
            self.log("FAIL: no committed fingerprint file.")
            return False
        problem = fingerprint_diff(
            json.loads(path.read_text(encoding="utf-8")), self._fingerprint()
        )
        self.log("PASS" if problem is None else f"FAIL: {problem}")
        return problem is None

    # -------------------------------------------------------------------- exports
    def _shareable_rows(self, conn) -> list[dict[str, Any]]:
        ds = self.cfg.raw["dataset"]
        labels: dict[str, list] = {}
        for lab in repo.labels_of(conn, ds["dataset_id"]):
            labels.setdefault(lab["record_id"], []).append(lab)
        source = source_config(self.root)["source"]
        rows = []
        for r in repo.dataset_records(conn, ds["dataset_id"]):
            rows.append(
                {
                    "schema_version": GOLDEN_V1_SCHEMA_VERSION,
                    "record_id": r["record_id"],
                    "session_id": r["session_id"],
                    "target_message_id": r["request_id"],
                    "reference_message_id": r["answer_message_id"],
                    "bot_id": r["bot_id"],
                    "owner_cohort": r["owner_cohort"],
                    "source_revision": source["revision"],
                    "target_timestamp_naive": r["target_timestamp"],
                    "reference_timestamp_naive": r["answer_timestamp"],
                    "seed": self.cfg.seed,
                    "stratum": r["stratum"],
                    "selection_rationale": r["selection_rationale"],
                    "population_weight": r["population_weight"],
                    "weight_basis": r["weight_basis"],
                    "pair_flag": r["pair_flag"],
                    "config_unknown": r["config_unknown"],
                    "labels": labels.get(r["record_id"], []),
                }
            )
        return rows

    def export(self) -> None:
        ds = self.cfg.raw["dataset"]
        with self.engine.connect() as conn:
            shareable = self._shareable_rows(conn)
            write_rows(
                shareable, self.root / self.report_dir / f"{self.slug}_shareable"
            )
            full = []
            for row in shareable:
                rid = row["record_id"]
                full.append(
                    {
                        **row,
                        "routing_input": {
                            p: repo.routing_input(conn, rid, p)
                            for p in ("pre_retrieval_v1", "post_retrieval_v1")
                        },
                        "reference": repo.reference_of(conn, rid),
                    }
                )
            write_rows(full, self.root / self.local_export / ds["dataset_id"])
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": f"{ds['dataset_id']} shareable record (no text)",
            "type": "object",
            "properties": {
                "schema_version": {"const": GOLDEN_V1_SCHEMA_VERSION},
                **{
                    k: {"type": "string"}
                    for k in (
                        "record_id",
                        "session_id",
                        "target_message_id",
                        "reference_message_id",
                        "bot_id",
                        "owner_cohort",
                        "source_revision",
                        "selection_rationale",
                        "weight_basis",
                        "pair_flag",
                    )
                },
                "target_timestamp_naive": {"type": ["string", "null"]},
                "reference_timestamp_naive": {"type": ["string", "null"]},
                "seed": {"type": "integer"},
                "stratum": {"type": "object"},
                "population_weight": {"type": "number"},
                "config_unknown": {"type": "boolean"},
                "labels": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["schema_version", "record_id", "target_message_id", "labels"],
            "additionalProperties": False,
        }
        path = self.root / self.report_dir / f"{self.slug}_manifest_schema.json"
        path.write_text(json.dumps(schema, indent=1) + "\n", encoding="utf-8")
        if self.derived is not None:
            self._write_mapping()
        self.log("Exports written (text only under data/derived/, which git ignores).")

    def _mapping_rows(self) -> list[dict[str, Any]]:
        spec = self.derived
        dsid = self.cfg.dataset_id
        with self.engine.connect() as conn:
            base = repo.dataset_records(conn, spec["base_dataset"])
            new = repo.dataset_records(conn, dsid)
            moves = repo.latest_sampling_run(conn, dsid)["config"]["moves"]
        return build_mapping(
            {r["request_id"]: r["record_id"] for r in base},
            {r["request_id"]: r["record_id"] for r in new},
            moves,
        )

    def _write_mapping(self) -> Path:
        """Record ids of the base and of this dataset, side by side. IDs only."""
        base_slug = self.derived["base_dataset"].replace("-", "_")
        path = self.root / self.report_dir / f"{base_slug}_to_{self.slug}_mapping.jsonl"
        rows = self._mapping_rows()
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
            encoding="utf-8",
        )
        self.log(f"Wrote {path.relative_to(self.root)} ({len(rows)} rows).")
        return path

    # --------------------------------------------------------------- review sheets
    def review_sheets(self) -> None:
        ds = self.cfg.raw["dataset"]
        dims = sorted(RUBRIC)
        with self.engine.connect() as conn:
            records = repo.dataset_records(conn, ds["dataset_id"])
            strata = {r["record_id"]: r["stratum"]["primary_intent"] for r in records}
            rank = {
                r["record_id"]: seeded_rank(self.cfg.seed, r["record_id"])
                for r in records
            }
            double = set(
                double_annotation_ids(
                    strata, self.cfg.raw["review"]["double_annotation_share"], rank
                )
            )
            id_rows, text_rows = [], []
            for r in records:
                rid = r["record_id"]
                base = {
                    "record_id": rid,
                    "double_annotate": rid in double,
                    "rule_intent": r["stratum"]["primary_intent"],
                    "language_group": r["stratum"]["language_group"],
                    "position": r["stratum"]["position"],
                    "bot_class": r["stratum"]["bot_class"],
                    "rubric": ds["rubric_document"],
                }
                blanks = dict.fromkeys(dims, "")
                id_rows.append({**base, **blanks})
                target, history, ins_chars, rag = repo.recent_history_text(
                    conn, rid, HISTORY_IN_SHEET
                )
                text_rows.append(
                    {
                        **base,
                        "target_text": target,
                        "recent_history": json.dumps(history, ensure_ascii=False),
                        "instruction_chars": ins_chars,
                        "rag_present": rag,
                        **blanks,
                    }
                )
        _write_csv(
            self.root / self.report_dir / "review" / "review_idonly.csv", id_rows
        )
        _write_csv(
            self.root / self.local_review / "review_with_text_LOCAL_ONLY.csv", text_rows
        )
        self.log(
            f"Review sheets written; {len(double)} records marked for two reviewers."
        )

    # ---------------------------------------------------------------- annotations
    def _known_records(self, conn) -> set[str]:
        ds = self.cfg.raw["dataset"]
        return {r["record_id"] for r in repo.dataset_records(conn, ds["dataset_id"])}

    def import_annotations(self, path: Path, annotator: str) -> int:
        """A completed review sheet: one column per dimension; blank means no label."""
        with path.open(encoding="utf-8", newline="") as fh:
            sheet = list(csv.DictReader(fh))
        rows = [
            LabelRow(row["record_id"], dim, row[dim].strip(), annotator)
            for row in sheet
            for dim in RUBRIC
            if (row.get(dim) or "").strip()
        ]
        return self._import(rows)

    def import_labels(self, path: Path) -> int:
        """Reviewed labels from a teammate: the ID-and-label file, no text."""
        lines = path.read_text(encoding="utf-8").splitlines()
        return self._import(_label_rows(json.loads(x) for x in lines if x.strip()))

    def carry_labels(self, path: Path) -> int:
        """Reviewed labels of the base dataset, re-keyed through the ID mapping.
        Only records that are unchanged carry over; the rest need new review."""
        if self.derived is None:
            raise SystemExit("carry-labels needs a dataset derived from another.")
        carried, dropped = carry_labels(
            path.read_text(encoding="utf-8").splitlines(), self._mapping_rows()
        )
        self.log(
            f"{len(carried)} labels carried over; {dropped} belong to removed records."
        )
        return self._import(_label_rows(carried))

    def _import(self, rows: list[LabelRow]) -> int:
        ds = self.cfg.raw["dataset"]
        with self.engine.begin() as conn:
            errors = label_errors(rows, self._known_records(conn))
            if errors:
                raise SystemExit(
                    f"Refused, nothing imported ({len(errors)} problems):\n  "
                    + "\n  ".join(errors[:20])
                )
            n = repo.add_annotations(
                conn,
                [
                    {
                        "record_id": r.record_id,
                        "dimension": r.dimension,
                        "value": r.value,
                        "method": r.method,
                        "annotator_pseudonym": r.annotator_pseudonym,
                        "rubric_version": ds["rubric_version"],
                        "confidence": r.confidence,
                        "review_status": "accepted",
                        "rationale_code": r.rationale_code,
                    }
                    for r in rows
                ],
            )
        self.log(f"Imported {n} new labels ({len(rows) - n} already present).")
        return n

    def export_labels(self) -> Path:
        ds = self.cfg.raw["dataset"]
        path = self.root / self.report_dir / "reviewed_labels.jsonl"
        with self.engine.connect() as conn:
            rows = [
                lab
                for lab in repo.labels_of(conn, ds["dataset_id"])
                if lab["method"] == "human"
            ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
            encoding="utf-8",
        )
        self.log(f"{len(rows)} reviewed labels in {path.relative_to(self.root)}")
        return path

    def plan_review_swaps(self) -> list[tuple[str, str]]:
        """Which records leave their intent cell on reviewed labels. Does not apply."""
        ds = self.cfg.raw["dataset"]
        with self.engine.connect() as conn:
            records = repo.dataset_records(conn, ds["dataset_id"])
            reviewed = {
                lab["record_id"]: lab["value"]
                for lab in repo.labels_of(conn, ds["dataset_id"])
                if lab["dimension"] == "primary_intent"
                and lab["method"] == "human"
                and lab["review_status"] == "accepted"
            }
            reserves = repo.reserve_rows(conn, ds["dataset_id"])
        return plan_swaps(
            reviewed,
            {r["record_id"]: r["stratum"]["primary_intent"] for r in records},
            [(r["request_id"], r["cell"].split("|")[0]) for r in reserves],
        )

    def freeze(self) -> None:
        ds = self.cfg.raw["dataset"]
        with self.engine.begin() as conn:
            state = repo.dataset_state(conn, ds["dataset_id"])
            if not state or state["status"] != "validated":
                raise SystemExit("Only a validated dataset can be frozen.")
            repo.set_status(conn, ds["dataset_id"], "frozen")
        self.log("Dataset frozen: its records, components and labels are immutable.")

    # ----------------------------------------------------------------- validation
    def validate(self, *, rebuild: bool = False) -> int:
        ds = self.cfg.raw["dataset"]
        dsid = ds["dataset_id"]
        rebuilt = None
        if rebuild:
            cands, _, _ = self._candidates()
            sel, _ = self._selection(cands)
            rebuilt = sorted(c.request_id for c, _ in sel.primary)
        with self.engine.connect() as conn:
            records = repo.dataset_records(conn, dsid)
            margins = repo.margin_rows(conn, dsid)
            labels = repo.labels_of(conn, dsid)
            reserves = repo.reserve_rows(conn, dsid)
            components = repo.components_of(conn, dsid)
            sessions = {
                r["session_id"]: repo.session_messages(conn, r["session_id"])
                for r in records
            }
            leaks = repo.view_leak_counts(conn, dsid)
            ownership = repo.ownership_errors(conn, dsid)
            recon = repo.latest_reconciliation(conn)
            ids = [r["request_id"] for r in records]
            answers = [r["answer_message_id"] for r in records]
            texts = repo.texts_for(conn, ids + answers)
        must = mandatory_checks(records, self.cfg)
        unmet = {m["key"] for m in must if not m["met"]}
        margin_view = [
            {
                "key": f"{m['margin']}:{m['key']}",
                "shortfall": m["shortfall"],
                "note": m["redistribution_note"],
                "mandatory_unmet": False,
            }
            for m in margins
        ] + [
            {
                "key": k,
                "shortfall": 1,
                "note": "see mandatory table",
                "mandatory_unmet": True,
            }
            for k in sorted(unmet)
        ]
        grams = {r["request_id"]: bigrams(texts[r["request_id"]]) for r in records}
        threshold = self.cfg.raw["selection"]["near_duplicate_bigram_jaccard"]
        pairs = sum(
            jaccard(grams[a], grams[b]) >= threshold
            for i, a in enumerate(ids)
            for b in ids[i + 1 :]
        )
        families = [r["exact_family_id"] for r in records]
        near = [r["near_family_id"] for r in records]
        duplicates = (
            pairs + (len(families) - len(set(families))) + (len(near) - len(set(near)))
        )
        overlap = self._eda_overlap(ids)
        scan_files = self._committed_files()
        hits = scan_for_content(scan_files, texts.values())
        results = run_checks(
            {
                "records": records,
                "reserve_request_ids": [r["request_id"] for r in reserves],
                "sessions": sessions,
                "components": components,
                "view_leaks": leaks["leaks"],
                "view_rows": leaks["rows"],
                "ownership_errors": ownership,
                "margins": margin_view,
                "duplicate_pairs": duplicates,
                "eda_overlap": overlap,
                "labels": labels,
                "content_hits": hits,
                "files_scanned": len(scan_files),
                "rebuild_ids": rebuilt,
            },
            self.cfg.total,
        )
        for name, reason in hits:
            self.log(f"content hit: {name}: {reason}")
        db = _database_lines(recon)
        out = self.root / self.report_dir / "validation.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            f"# {dsid} validation\n\nGenerated by `scripts/validate_eval_dataset.py`. "
            "No content. `pending` means a human step has not happened.\n\n"
            + markdown(results)
            + "\n## Mandatory minimums and caps\n\n"
            + markdown_table(("key", "value", "target", "met", "note"), must)
            + "\n## Database checks\n\n"
            + db
            + "\nD-05 (migrations from scratch and downgrade) is covered by "
            "`tests/integration/test_postgres.py` with `--run-postgres`.\n",
            encoding="utf-8",
        )
        for r in results:
            self.log(f"{r.status.upper():8} {r.check_id} {r.title} ({r.detail})")
        failed = [r for r in results if r.status == "fail"]
        if not failed and not any(r.status == "pending" for r in results):
            with self.engine.begin() as conn:
                if repo.dataset_state(conn, dsid)["status"] != "frozen":
                    repo.set_status(conn, dsid, "validated")
        return 1 if failed else 0

    def _eda_overlap(self, ids: list[str]) -> int:
        path = (
            self.root
            / "reports/full_eda/sessions/golden_candidates_proposed_idonly.csv"
        )
        if not path.exists():
            return 0
        with path.open(encoding="utf-8", newline="") as fh:
            old = {row["message_id"] for row in csv.DictReader(fh)}
        return len(old & set(ids))

    def _committed_files(self) -> dict[str, str]:
        out = {}
        for folder in (self.report_dir, "docs/evaluation"):
            base = self.root / folder
            if not base.exists():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file() and path.suffix in (
                    ".md",
                    ".csv",
                    ".json",
                    ".jsonl",
                    ".sql",
                ):
                    out[path.relative_to(self.root).as_posix()] = path.read_text(
                        encoding="utf-8"
                    )
        return out

    def _compromise_line(self, snapshot: Mapping[str, Any]) -> str:
        moves = snapshot["moves"]
        if self.derived is None:
            return (
                f"{len(moves)} cell moves for lack of supply; "
                f"{snapshot['near']} near duplicates excluded at selection.\n"
            )
        by_rule = Counter(m.get("rule", "unfilled") for m in moves)
        return (
            f"{len(moves)} records of {self.derived['base_dataset']} left the set "
            f"({self.derived['exclude']}); replaced from reserves: "
            f"{by_rule['reserve']}, from the pool: {by_rule['pool']}, unfilled: "
            f"{by_rule['unfilled']}. {snapshot['near']} near duplicates excluded.\n"
        )

    # ------------------------------------------------------------- quality report
    def quality_report(self) -> Path:
        ds = self.cfg.raw["dataset"]
        dsid = ds["dataset_id"]
        out_dir = self.root / self.report_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        with self.engine.connect() as conn:
            records = repo.dataset_records(conn, dsid)
            margins = repo.margin_rows(conn, dsid)
            labels = repo.labels_of(conn, dsid)
            totals = repo.request_totals(conn)
            exclusions = repo.exclusion_counts(conn)
            recon = repo.latest_reconciliation(conn)
            snapshot = _sampling_snapshot(conn, dsid)
        for r in records:
            r["stratum"]["rag_on_answer"] = r["rag_observed_on_answer"]
        _write_csv(out_dir / "margins.csv", margins)
        tabs = [
            ("primary_intent", "complexity_proxy"),
            ("primary_intent", "target_length"),
            ("complexity_proxy", "context_dependency"),
            ("bot_class", "rag_on_answer"),
            ("language_group", "primary_intent"),
            ("position", "context_dependency"),
        ]
        must = mandatory_checks(records, self.cfg)
        lines = [
            f"# {dsid} quality report\n",
            "Generated by `scripts/build_eval_dataset.py report`. No message text. Status "
            "`annotated_provisional`: every label below is a **rule proposal** until "
            "human review completes. This is a balanced challenge set; **no aggregate "
            "on it equals production performance**, and neither the balanced nor the "
            "traffic-weighted view does.\n",
            "## Source and population (verified from the database)\n",
            markdown_table(
                ("measure", "value"),
                [{"measure": k, "value": v} for k, v in totals.items()],
            ),
            "\nExclusions (unit: USER messages):\n",
            markdown_table(
                ("reason", "n"),
                [{"reason": k, "n": v} for k, v in sorted(exclusions.items())],
            ),
            f"\nEligible distinct pool: {snapshot['pool']}. Weights: N/n over eligible "
            "requests per primary intent × cohort cell. Population share in cells with "
            f"no sample: {snapshot['uncovered']:.4f}.\n",
            "\n## Population versus sample per margin (rule-derived)\n",
            markdown_table(
                (
                    "margin",
                    "key",
                    "population_n",
                    "quota",
                    "achieved",
                    "shortfall",
                    "basis",
                    "redistribution_note",
                ),
                margins,
            ),
            "\n## Mandatory minimums and caps\n",
            markdown_table(("key", "value", "target", "met", "note"), must),
            "\n## Compromises\n",
            self._compromise_line(snapshot),
            "\n## Labels and agreement\n",
            _label_section(labels, len(records), len(RUBRIC)),
            "\n## Missing fields in the set\n",
            markdown_table(
                ("field", "records"),
                [
                    {
                        "field": "config_unknown (no exported bot configuration)",
                        "records": sum(bool(r["config_unknown"]) for r in records),
                    },
                    {
                        "field": "no RAG observed on the answer",
                        "records": sum(
                            not r["rag_observed_on_answer"] for r in records
                        ),
                    },
                ],
            ),
            "\n## Cross-tabs (rule-derived; complexity is the selection proxy)\n",
        ]
        for row, col in tabs:
            columns, rows = cross_tab(records, row, col)
            _write_csv(out_dir / f"crosstab_{row}__{col}.csv", rows)
            small = small_n_cells(rows, columns)
            lines += [
                f"\n### {row} × {col}\n",
                f"Small-n warning: {small} non-empty cells below 5.\n\n",
                markdown_table(columns, rows),
            ]
        lines += [
            "\n## Validation\n",
            "See `validation.md`.\n\n",
            _database_lines(recon),
        ]
        path = out_dir / "quality_report.md"
        path.write_text(
            "".join(s if s.endswith("\n") else s + "\n" for s in lines),
            encoding="utf-8",
        )
        self.log(f"Wrote {path.relative_to(self.root)}")
        return path


def _label_rows(dicts) -> list[LabelRow]:
    return [
        LabelRow(
            d["record_id"],
            d["dimension"],
            d["value"],
            d["annotator_pseudonym"],
            d.get("method", "human"),
            d.get("confidence"),
            d.get("rationale_code"),
        )
        for d in dicts
    ]


def _sampling_snapshot(conn, dataset_id: str) -> dict[str, Any]:
    r = repo.latest_sampling_run(conn, dataset_id)
    return {
        "pool": r["population_snapshot"]["pool_distinct"],
        "uncovered": r["config"]["uncovered_population_share"],
        "moves": r["config"]["moves"],
        "near": r["config"]["near_duplicates_excluded"],
    }


def _label_section(labels, n_records: int, n_dims: int) -> str:
    methods = Counter((lab["method"], lab["review_status"]) for lab in labels)
    lines = markdown_table(
        ("method", "review_status", "labels"),
        [
            {"method": a, "review_status": b, "labels": n}
            for (a, b), n in sorted(methods.items())
        ],
    )
    by_person: dict[tuple, dict[str, str]] = {}
    for lab in labels:
        if lab["method"] == "human":
            by_person.setdefault((lab["record_id"], lab["dimension"]), {})[
                lab["annotator_pseudonym"]
            ] = lab["value"]
    pairs: dict[str, list[tuple[str, str]]] = {}
    for (_, dim), people in by_person.items():
        if len(people) >= 2:
            first, second = sorted(people)[:2]
            pairs.setdefault(dim, []).append((people[first], people[second]))
    if not pairs:
        return lines + "\nAgreement: not evaluated; human review is pending.\n"
    rows = [
        {
            "dimension": dim,
            "pairs": len(p),
            "percent_agreement": percent_agreement(p),
            "weighted_kappa": weighted_kappa(p) if dim == "complexity" else "",
        }
        for dim, p in sorted(pairs.items())
    ]
    return (
        lines
        + "\n"
        + markdown_table(
            ("dimension", "pairs", "percent_agreement", "weighted_kappa"), rows
        )
    )


def _database_lines(recon: Mapping[str, Any]) -> str:
    checks = recon["checks"]
    failed = [c for c in checks if not c["ok"]]
    rows = [c for c in checks if c["check_name"].startswith("rows:")]
    lines = [
        f"- D-01 source row counts reconcile: "
        f"{'pass' if rows and all(c['ok'] for c in rows) else 'fail'} ({len(rows)} tables).",
        f"- D-02 no silent drops: {'pass' if rows and not failed else 'fail'} "
        f"({len(checks)} checks, {len(failed)} failed).",
        f"- D-03 re-ingest is a no-op: {'pass' if recon['noop_run'] else 'not yet run'}.",
        "- D-04 referential integrity: "
        f"{'pass' if rows and not failed else 'fail'} (FKs enforced; orphan checks).",
    ]
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        if rows:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
