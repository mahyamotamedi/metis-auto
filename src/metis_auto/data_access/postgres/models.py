"""SQLAlchemy table definitions for schemas meta, src, eval and exp (ADR-0027).

Migrations in ``infra/db`` own the database; ``alembic check`` proves these
definitions and the migrations agree. Column comments carry the privacy class from
``contracts._base.Privacy``. ``info["source"]`` names the Parquet column a ``src``
column comes from. Views and triggers live in the migrations only.

``src`` mirrors the export and adds provenance. Source facts (``src``), deterministic
features (``eval.request``), inferred labels (``eval.annotation``) and the reference
answer (``eval.record_reference``) never share a table.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from metis_auto.contracts._base import Privacy

metadata = MetaData(
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
    }
)

SCHEMAS = ("meta", "src", "eval", "exp")
JSON_STATES = "('null','empty','malformed','ok')"

C = Privacy.CONTENT.value
R = Privacy.REFERENCE.value
F = Privacy.FINGERPRINT.value
O = Privacy.OPERATIONAL.value  # noqa: E741
D = Privacy.DERIVED.value


def col(name, type_, privacy, *args, source=None, **kw):
    info = {"source": source} if source else {}
    return Column(name, type_, *args, comment=f"privacy={privacy}", info=info, **kw)


def src_col(source, name, type_, privacy, *args, **kw):
    return col(name, type_, privacy, *args, source=source, **kw)


def _provenance():
    return (
        col(
            "_source_file_id",
            BigInteger,
            O,
            ForeignKey("meta.source_file.source_file_id"),
            nullable=False,
        ),
        col("_source_row", BigInteger, O, nullable=False),
    )


def _json_pair(source, name):
    """A JSON-text source column: parsed value plus its parse state."""
    return (
        src_col(source, name, JSONB, C),
        col(f"{name}_state", Text, O, nullable=False),
        CheckConstraint(f"{name}_state IN {JSON_STATES}", name=f"{name}_state"),
    )


# --------------------------------------------------------------------------- meta
ingest_run = Table(
    "ingest_run",
    metadata,
    col("run_id", BigInteger, O, primary_key=True, autoincrement=True),
    col("started_at", DateTime(timezone=True), O, nullable=False),
    col("finished_at", DateTime(timezone=True), O),
    col("git_sha", Text, O),
    col("dataset_repo", Text, R, nullable=False),
    col("dataset_revision", Text, R, nullable=False),
    col("tool_versions", JSONB, O, nullable=False),
    col("options", JSONB, O, nullable=False),
    col("status", Text, O, nullable=False),
    CheckConstraint("status IN ('running','ok','failed')", name="status"),
    schema="meta",
)
source_file = Table(
    "source_file",
    metadata,
    col("source_file_id", BigInteger, O, primary_key=True, autoincrement=True),
    col("run_id", BigInteger, O, ForeignKey("meta.ingest_run.run_id"), nullable=False),
    col("logical_table", Text, O, nullable=False),
    col("relative_path", Text, O, nullable=False),
    col("sha256", Text, F, nullable=False),
    col("bytes", BigInteger, O, nullable=False),
    col("parquet_rows", BigInteger, O, nullable=False),
    col("loaded_rows", BigInteger, O, nullable=False),
    col("schema_json", JSONB, O, nullable=False),
    col("status", Text, O, nullable=False),
    UniqueConstraint("relative_path", "sha256", name="uq_source_file_path_sha"),
    schema="meta",
)
reconciliation = Table(
    "reconciliation",
    metadata,
    col("run_id", BigInteger, O, ForeignKey("meta.ingest_run.run_id"), nullable=False),
    col("check_name", Text, O, nullable=False),
    col("expected", Text, O),
    col("actual", Text, O),
    col("ok", Boolean, O, nullable=False),
    PrimaryKeyConstraint("run_id", "check_name"),
    schema="meta",
)

# ---------------------------------------------------------------------------- src
users = Table(
    "users",
    metadata,
    src_col("user_id", "user_id", Text, R, primary_key=True),
    src_col("activated", "activated", Boolean, O),
    src_col("owner_user_id", "owner_user_id", Text, R),
    src_col("username_anon", "username_anon", Text, C),
    *_provenance(),
    schema="src",
)
chat_bot = Table(
    "chat_bot",
    metadata,
    src_col("bot_id", "bot_id", Text, R, primary_key=True),
    src_col("created_at", "created_at", DateTime, O),
    src_col("updated_at", "updated_at", DateTime, O),
    src_col("deleted_at", "deleted_at", DateTime, O),
    # No FK to users: the export has bot owners that are not in users (ADR-0027).
    src_col("user_id", "user_id", Text, R, nullable=False),
    src_col("instructions", "instructions", Text, C),
    col("instructions_sha256", Text, F),
    *_json_pair("provider_args", "provider_args"),
    *_json_pair("corpus_ids", "corpus_ids"),
    src_col("summarizer_provider_name", "summarizer_provider_name", Text, O),
    src_col("summarizer_provider_model", "summarizer_provider_model", Text, O),
    *_json_pair("summarizer_provider_args", "summarizer_provider_args"),
    *_json_pair("functions", "functions"),
    src_col("description", "description", Text, C),
    src_col("enabled", "enabled", Boolean, O),
    src_col("provider_name", "provider_name", Text, O),
    src_col("provider_model", "provider_model", Text, O),
    src_col("auto_generate_headline", "auto_generate_headline", Boolean, O),
    src_col("public", "public", Boolean, O),
    src_col("memory_enabled", "memory_enabled", Boolean, O),
    src_col("google_search_enabled", "google_search_enabled", Boolean, O),
    src_col("async_webhook", "async_webhook", Text, C),
    src_col("bot_type", "bot_type", Text, O),
    src_col("rag_top_k", "rag_top_k", BigInteger, O),
    src_col("rag_reranking", "rag_reranking", Text, O),
    src_col("independent_function_call", "independent_function_call", Boolean, O),
    src_col("summarizer_mode", "summarizer_mode", Text, O),
    src_col("rag_source_urls_enabled", "rag_source_urls_enabled", Boolean, O),
    *_provenance(),
    schema="src",
)
chat_session = Table(
    "chat_session",
    metadata,
    src_col("session_id", "session_id", Text, R, primary_key=True),
    src_col(
        "user_id", "user_id", Text, R, ForeignKey("src.users.user_id"), nullable=False
    ),
    src_col("created_at", "created_at", DateTime, O),
    src_col(
        "bot_id", "bot_id", Text, R, ForeignKey("src.chat_bot.bot_id"), nullable=False
    ),
    src_col("last_update_date", "last_update_date", DateTime, O),
    src_col("dialogue_length", "dialogue_length", BigInteger, O),
    src_col("headline", "headline", Text, C),
    *_provenance(),
    Index("ix_chat_session_bot_id", "bot_id"),
    Index("ix_chat_session_user_id", "user_id"),
    Index("ix_chat_session_created_at", "created_at"),
    schema="src",
)
chat_message = Table(
    "chat_message",
    metadata,
    src_col("message_id", "message_id", Text, R, primary_key=True),
    src_col(
        "session_id",
        "session_id",
        Text,
        R,
        ForeignKey("src.chat_session.session_id"),
        nullable=False,
    ),
    src_col("type", "type", Text, O, nullable=False),
    src_col("timestamp", "timestamp", DateTime, O),
    col("source_ordinal", BigInteger, O, nullable=False),
    src_col("content", "content", Text, C),
    src_col("finish_reason", "finish_reason", Text, O),
    *_json_pair("attachments", "attachments"),
    *_json_pair("citations", "citations"),
    *_json_pair("tool_calls", "tool_calls"),
    # Chunk text is replaced by its sha256 here and kept once, in src.rag_chunk;
    # the reconciliation check "rag_chunks_match_message_json" proves nothing is lost.
    *_json_pair("rag", "rag"),
    *_json_pair("billing", "billing"),
    *_json_pair("input", "input"),
    *_json_pair("actions", "actions"),
    src_col("google_search_query", "google_search_query", Text, C),
    *_provenance(),
    CheckConstraint("type IN ('USER','AI','SYSTEM','TOOL')", name="type"),
    Index("ix_chat_message_session_order", "session_id", "timestamp", "source_ordinal"),
    Index("ix_chat_message_type", "type"),
    schema="src",
)


def _derived(name, *columns, index=True):
    extras = [Index(f"ix_{name}_message_id", "message_id")] if index else []
    return Table(
        name,
        metadata,
        src_col(
            "message_id",
            "message_id",
            Text,
            R,
            ForeignKey("src.chat_message.message_id"),
            nullable=False,
        ),
        *columns,
        *_provenance(),
        PrimaryKeyConstraint("_source_file_id", "_source_row"),
        *extras,
        schema="src",
    )


rag_query = _derived("rag_query", src_col("query", "query", Text, C))
rag_chunk = _derived(
    "rag_chunk",
    src_col("chunk_id", "chunk_id", Text, R),
    src_col("content", "content", Text, C),
    col("content_sha256", Text, F),
    src_col("corpusId", "corpus_id", Text, R),
    src_col("reference", "reference", Double, O),
    src_col("relevancy", "relevancy", Double, O),
    src_col("reference.page", "reference_page", Double, O),
    src_col("reference.type", "reference_type", Text, O),
    src_col("reference.downloadUrl", "reference_download_url", Text, C),
    src_col("reference.url", "reference_url", Text, C),
    src_col("__index_level_0__", "source_index", BigInteger, O),
)
billing_item = _derived(
    "billing_item",
    *[
        src_col(s, n, t, O)
        for s, n, t in (
            ("callCount", "call_count", BigInteger),
            ("fixedCost", "fixed_cost", Double),
            ("totalCost", "total_cost", Double),
            ("usageCost", "usage_cost", Double),
            ("isNotEmpty", "is_not_empty", Boolean),
            ("fixedIncome", "fixed_income", Double),
            ("inputTokens", "input_tokens", BigInteger),
            ("totalIncome", "total_income", Double),
            ("usageIncome", "usage_income", Double),
            ("outputTokens", "output_tokens", BigInteger),
            ("webSearchCalls", "web_search_calls", Double),
            ("billableSeconds", "billable_seconds", Double),
            ("providerKeyName", "provider_key_name", Text),
            ("audioInputTokens", "audio_input_tokens", Double),
            ("audioOutputTokens", "audio_output_tokens", Double),
            ("cachedInputTokens", "cached_input_tokens", Double),
            ("groundingSearchQueries", "grounding_search_queries", Double),
            ("costBreakdown.input_tokens", "cost_input_tokens", Double),
            ("costBreakdown.output_tokens", "cost_output_tokens", Double),
            ("incomeBreakdown.input_tokens", "income_input_tokens", Double),
            ("incomeBreakdown.output_tokens", "income_output_tokens", Double),
            ("costBreakdown.per_call", "cost_per_call", Double),
            ("incomeBreakdown.per_call", "income_per_call", Double),
            ("costBreakdown.cached_input_tokens", "cost_cached_input_tokens", Double),
            (
                "incomeBreakdown.cached_input_tokens",
                "income_cached_input_tokens",
                Double,
            ),
            ("providerAccount", "provider_account", Text),
            ("cacheWriteTokens", "cache_write_tokens", Double),
            ("costBreakdown.cache_write_tokens", "cost_cache_write_tokens", Double),
            ("incomeBreakdown.cache_write_tokens", "income_cache_write_tokens", Double),
        )
    ],
)
input_item = _derived("input_item", *_json_pair("items", "items"))
tool_call = _derived(
    "tool_call",
    src_col("call.id", "call_id", Text, R),
    src_col("call.name", "call_name", Text, O),
    # Every other source column, under its source name (37 sparse columns).
    col("row_data", JSONB, C, nullable=False),
)
action = _derived(
    "action",
    src_col("type", "type", Text, O),
    src_col("reason", "reason", Text, O),
)

# --------------------------------------------------------------------------- eval
request = Table(
    "request",
    metadata,
    col(
        "request_id",
        Text,
        R,
        ForeignKey("src.chat_message.message_id"),
        primary_key=True,
    ),
    col(
        "session_id",
        Text,
        R,
        ForeignKey("src.chat_session.session_id"),
        nullable=False,
    ),
    col("bot_id", Text, R, ForeignKey("src.chat_bot.bot_id"), nullable=False),
    col("owner_cohort", Text, D, nullable=False),
    col("turn_index", Integer, D, nullable=False),
    col("answer_message_id", Text, R, ForeignKey("src.chat_message.message_id")),
    col("pair_flag", Text, D, nullable=False),
    col("eligible", Boolean, D, nullable=False),
    col("exclusion_reason", Text, D),
    col("language_label", Text, D, nullable=False),
    col("language_group", Text, D, nullable=False),
    col("language_method", Text, O, nullable=False),
    col("target_chars", Integer, D, nullable=False),
    col("target_words", Integer, D, nullable=False),
    col("n_prior_messages", Integer, D, nullable=False),
    col("history_chars", BigInteger, D, nullable=False),
    col("instruction_chars", BigInteger, D, nullable=False),
    col("rag_chunk_chars", BigInteger, D, nullable=False),
    col("bot_class", Text, D, nullable=False),
    col("instruction_evidence", Text, D, nullable=False),
    col("rag_config", Text, D, nullable=False),
    col("config_unknown", Boolean, D, nullable=False),
    col("attachment_count", Integer, D, nullable=False),
    col("attachment_types", JSONB, D, nullable=False),
    col("after_widget", Boolean, D, nullable=False),
    col("answer_finish_reason", Text, O),
    col("rag_observed_on_answer", Boolean, D, nullable=False),
    col("rule_intent", Text, D, nullable=False),
    col("rule_tags", JSONB, D, nullable=False),
    col("complexity_proxy", Text, D, nullable=False),
    # Local grouping hashes (analysis-time, ADR-0025 note in ADR-0028); never exported.
    col("exact_family_id", Text, F),
    col("near_family_id", Text, F),
    col("family_size", Integer, D),
    col("timestamp_is_null", Boolean, D, nullable=False),
    col("feature_version", Text, O, nullable=False),
    Index("ix_request_eligible_cell", "eligible", "rule_intent", "owner_cohort"),
    Index("ix_request_session_id", "session_id"),
    schema="eval",
)
rubric = Table(
    "rubric",
    metadata,
    col("rubric_version", Text, O, primary_key=True),
    col("document", Text, O, nullable=False),
    col("config_sha256", Text, F, nullable=False),
    schema="eval",
)
rubric_value = Table(
    "rubric_value",
    metadata,
    col(
        "rubric_version",
        Text,
        O,
        ForeignKey("eval.rubric.rubric_version"),
        nullable=False,
    ),
    col("dimension", Text, O, nullable=False),
    col("value", Text, O, nullable=False),
    col("definition_ref", Text, O, nullable=False),
    PrimaryKeyConstraint("rubric_version", "dimension", "value"),
    schema="eval",
)
dataset = Table(
    "dataset",
    metadata,
    col("dataset_id", Text, O, primary_key=True),
    col("name", Text, O, nullable=False),
    col("version", Text, O, nullable=False),
    col("status", Text, O, nullable=False),
    col("config_sha256", Text, F, nullable=False),
    col("created_at", DateTime(timezone=True), O, nullable=False),
    CheckConstraint(
        "status IN ('draft','annotated_provisional','validated','frozen')",
        name="status",
    ),
    schema="eval",
)
sampling_run = Table(
    "sampling_run",
    metadata,
    col("sampling_run_id", BigInteger, O, primary_key=True, autoincrement=True),
    col(
        "dataset_id",
        Text,
        O,
        ForeignKey("eval.dataset.dataset_id", ondelete="CASCADE"),
        nullable=False,
    ),
    col("seed", BigInteger, O, nullable=False),
    col("config", JSONB, O, nullable=False),
    col("code_git_sha", Text, O),
    col("population_snapshot", JSONB, O, nullable=False),
    col("status", Text, O, nullable=False),
    col("created_at", DateTime(timezone=True), O, nullable=False),
    schema="eval",
)
stratum_population = Table(
    "stratum_population",
    metadata,
    col(
        "sampling_run_id",
        BigInteger,
        O,
        ForeignKey("eval.sampling_run.sampling_run_id", ondelete="CASCADE"),
        nullable=False,
    ),
    col("margin", Text, O, nullable=False),
    col("key", Text, O, nullable=False),
    col("population_n", BigInteger, O, nullable=False),
    col("quota", Integer, O, nullable=False),
    col("achieved", Integer, O, nullable=False),
    col("shortfall", Integer, O, nullable=False),
    col("basis", Text, O, nullable=False),
    col("redistribution_note", Text, O),
    PrimaryKeyConstraint("sampling_run_id", "margin", "key"),
    schema="eval",
)
dataset_record = Table(
    "dataset_record",
    metadata,
    col("record_id", Text, R, primary_key=True),
    col(
        "dataset_id",
        Text,
        O,
        ForeignKey("eval.dataset.dataset_id", ondelete="CASCADE"),
        nullable=False,
    ),
    col("request_id", Text, R, ForeignKey("eval.request.request_id"), nullable=False),
    col("session_id", Text, R, nullable=False),
    col("stratum", JSONB, O, nullable=False),
    col("population_weight", Double, O, nullable=False),
    col("weight_basis", Text, O, nullable=False),
    col("selection_rank", Integer, O, nullable=False),
    col("selection_rationale", Text, O, nullable=False),
    UniqueConstraint("dataset_id", "request_id", name="uq_dataset_record_request"),
    UniqueConstraint("dataset_id", "session_id", name="uq_dataset_record_session"),
    schema="eval",
)
dataset_reserve = Table(
    "dataset_reserve",
    metadata,
    col(
        "dataset_id",
        Text,
        O,
        ForeignKey("eval.dataset.dataset_id", ondelete="CASCADE"),
        nullable=False,
    ),
    col("request_id", Text, R, ForeignKey("eval.request.request_id"), nullable=False),
    col("session_id", Text, R, nullable=False),
    col("cell", Text, O, nullable=False),
    col("reserve_rank", Integer, O, nullable=False),
    col("stratum", JSONB, O, nullable=False),
    PrimaryKeyConstraint("dataset_id", "request_id"),
    schema="eval",
)
record_input_component = Table(
    "record_input_component",
    metadata,
    col(
        "record_id",
        Text,
        R,
        ForeignKey("eval.dataset_record.record_id", ondelete="CASCADE"),
        nullable=False,
    ),
    col("position", Integer, O, nullable=False),
    col("kind", Text, O, nullable=False),
    col("role", Text, O),
    col("source_kind", Text, O, nullable=False),
    col("source_message_id", Text, R, ForeignKey("src.chat_message.message_id")),
    col("source_bot_id", Text, R, ForeignKey("src.chat_bot.bot_id")),
    col("source_chunk_file_id", BigInteger, O),
    col("source_chunk_row", BigInteger, O),
    col("availability_stage", Text, O, nullable=False),
    col("included_pre_retrieval", Boolean, O, nullable=False),
    col("included_post_retrieval", Boolean, O, nullable=False),
    col("transmitted_to_provider", Text, O, nullable=False),
    col("content_sha256", Text, F),
    col("metadata", JSONB, O),
    PrimaryKeyConstraint("record_id", "position"),
    ForeignKeyConstraint(
        ["source_chunk_file_id", "source_chunk_row"],
        ["src.rag_chunk._source_file_id", "src.rag_chunk._source_row"],
        name="fk_component_rag_chunk",
    ),
    CheckConstraint(
        "availability_stage IN ('request_arrival','configuration_snapshot',"
        "'retrieval_order_unknown')",
        name="stage",
    ),
    schema="eval",
)
record_reference = Table(
    "record_reference",
    metadata,
    col(
        "record_id",
        Text,
        R,
        ForeignKey("eval.dataset_record.record_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    col(
        "answer_message_id",
        Text,
        R,
        ForeignKey("src.chat_message.message_id"),
        nullable=False,
    ),
    col("reference_provider_label", Text, O),
    col("reference_model_label", Text, O),
    col("reference_model_source", Text, O, nullable=False),
    col("finish_reason", Text, O),
    col("billing_summary", JSONB, O, nullable=False),
    col(
        "availability_stage", Text, O, nullable=False, server_default="post_generation"
    ),
    schema="eval",
)
annotation = Table(
    "annotation",
    metadata,
    col("annotation_id", BigInteger, O, primary_key=True, autoincrement=True),
    col(
        "record_id",
        Text,
        R,
        ForeignKey("eval.dataset_record.record_id", ondelete="CASCADE"),
        nullable=False,
    ),
    col("dimension", Text, O, nullable=False),
    col("value", Text, O, nullable=False),
    col("method", Text, O, nullable=False),
    col("annotator_pseudonym", Text, O, nullable=False),
    col(
        "rubric_version",
        Text,
        O,
        ForeignKey("eval.rubric.rubric_version"),
        nullable=False,
    ),
    col("confidence", Double, O),
    col("review_status", Text, O, nullable=False),
    col("rationale_code", Text, O),
    col("supersedes_id", BigInteger, O, ForeignKey("eval.annotation.annotation_id")),
    col(
        "created_at",
        DateTime(timezone=True),
        O,
        nullable=False,
        server_default=text("now()"),
    ),
    CheckConstraint("method IN ('rule','human','llm_assisted')", name="method"),
    CheckConstraint(
        "review_status IN ('proposed','accepted','rejected')", name="review_status"
    ),
    Index("ix_annotation_record_dimension", "record_id", "dimension"),
    schema="eval",
)

# ---------------------------------------------------------------------------- exp
# Empty and ready for routing experiments. Files in runs/ stay the record
# (ADR-0022); these tables index imported summaries.
model = Table(
    "model",
    metadata,
    col("model_id", Text, O, primary_key=True),
    col("provider", Text, O, nullable=False),
    col("facts_source", Text, O, nullable=False),
    col("facts_checked_on", Text, O, nullable=False),
    col("price_table_version", Text, O),
    schema="exp",
)
experiment = Table(
    "experiment",
    metadata,
    col("experiment_id", Text, O, primary_key=True),
    col("area", Text, O, nullable=False),
    col("plan_ref", Text, O),
    schema="exp",
)
run = Table(
    "run",
    metadata,
    col("run_id", Text, O, primary_key=True),
    col(
        "experiment_id",
        Text,
        O,
        ForeignKey("exp.experiment.experiment_id"),
        nullable=False,
    ),
    col("dataset_id", Text, O, ForeignKey("eval.dataset.dataset_id")),
    col("manifest_sha256", Text, F, nullable=False),
    col("git_sha", Text, O),
    col("mode", Text, O, nullable=False),
    schema="exp",
)
attempt = Table(
    "attempt",
    metadata,
    col("attempt_id", BigInteger, O, primary_key=True, autoincrement=True),
    col("run_id", Text, O, ForeignKey("exp.run.run_id"), nullable=False),
    col(
        "record_id",
        Text,
        R,
        ForeignKey("eval.dataset_record.record_id"),
        nullable=False,
    ),
    col("attempt_index", Integer, O, nullable=False),
    col("attempt_kind", Text, O, nullable=False),
    col("model_id", Text, O, ForeignKey("exp.model.model_id"), nullable=False),
    col("input_tokens", BigInteger, O),
    col("cached_input_tokens", BigInteger, O),
    col("output_tokens", BigInteger, O),
    col("reasoning_tokens", BigInteger, O),
    col("cost", Text, O),
    col("cost_currency", Text, O),
    col("price_table_version", Text, O),
    col("token_count_fidelity", Text, O, nullable=False),
    col("latency_ms", Double, O),
    col("latency_state", Text, O, nullable=False),
    CheckConstraint("latency_state IN ('measured','unmeasured')", name="latency_state"),
    UniqueConstraint("run_id", "record_id", "attempt_index", name="uq_attempt_run"),
    schema="exp",
)
result = Table(
    "result",
    metadata,
    col("run_id", Text, O, ForeignKey("exp.run.run_id"), nullable=False),
    col(
        "record_id",
        Text,
        R,
        ForeignKey("eval.dataset_record.record_id"),
        nullable=False,
    ),
    col("outcome_state", Text, O, nullable=False),
    col("counterfactual_source", Text, O, nullable=False),
    PrimaryKeyConstraint("run_id", "record_id"),
    schema="exp",
)
judgement = Table(
    "judgement",
    metadata,
    col("judgement_id", BigInteger, O, primary_key=True, autoincrement=True),
    col("run_id", Text, O, ForeignKey("exp.run.run_id"), nullable=False),
    col(
        "record_id",
        Text,
        R,
        ForeignKey("eval.dataset_record.record_id"),
        nullable=False,
    ),
    # The three ADR-0006 quality signals stay separate.
    col("agreement_with_as_logged", Double, O),
    col("judge_score", Double, O),
    col("non_inferior", Boolean, O),
    col("judge_identity", Text, O),
    col("judge_version", Text, O),
    col("human_agreement", Double, O),
    schema="exp",
)
