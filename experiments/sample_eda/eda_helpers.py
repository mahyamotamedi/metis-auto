"""Reusable, privacy-conscious helpers for the Metis sample EDA.

The raw export is read-only. Functions return new Python objects/DataFrames and
never write transformed records or message text to disk.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


DEFAULT_DATA_PATH = Path("data/sample_data/raw/data.json")
PERSIAN_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
LATIN_RE = re.compile(r"[A-Za-z]")
WORD_RE = re.compile(r"\b[\w]+\b", flags=re.UNICODE)
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
CODE_RE = re.compile(
    r"(?:```|\b(?:def|class|function|const|let|var|import|SELECT|FROM)\b|=>|</?[A-Za-z][^>]*>)",
    re.IGNORECASE,
)
MARKDOWN_RE = re.compile(r"(?:^\s{0,3}#{1,6}\s|\*\*|__|\[[^\]]+\]\([^)]*\)|^\s*[-*+]\s)", re.MULTILINE)
INSTRUCTION_RE = re.compile(
    r"\b(?:please|must|should|first|then|finally|step\s*\d+|1\.|2\.)\b|(?:لطفا|ابتدا|سپس|در نهایت|مرحله)",
    re.IGNORECASE,
)


def load_sessions(path: str | Path = DEFAULT_DATA_PATH) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load category buckets and return (category objects, flattened sessions).

    The category label is retained as an opaque stratum. No mutation is made to
    parsed records; downstream helpers build separate tabular representations.
    """
    with Path(path).open(encoding="utf-8") as file:
        categories = json.load(file)
    if not isinstance(categories, list):
        raise ValueError("Expected the JSON root to be a list of category objects")
    sessions = []
    for category_index, category in enumerate(categories):
        if not isinstance(category, dict):
            raise ValueError(f"Expected category {category_index} to be an object")
        label = category.get("category")
        category_sessions = category.get("sessions", [])
        if not isinstance(category_sessions, list):
            raise ValueError(f"Expected sessions in category {category_index} to be a list")
        for session_index, session in enumerate(category_sessions):
            if not isinstance(session, dict):
                raise ValueError(
                    f"Expected session {session_index} in category {category_index} to be an object"
                )
            messages = session.get("messages", [])
            if not isinstance(messages, list) or any(not isinstance(message, dict) for message in messages):
                raise ValueError(
                    f"Expected messages in session {session_index} of category {category_index} to be a list of objects"
                )
            sessions.append({"category": label, "session": session})
    return categories, sessions


def flatten_messages(sessions: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Flatten session messages while retaining raw content only in memory."""
    rows = []
    for item in sessions:
        category, session = item["category"], item["session"]
        for index, message in enumerate(session.get("messages", [])):
            rag = message.get("rag") if isinstance(message.get("rag"), dict) else {}
            attachment_list = message.get("attachments")
            attachment_list = attachment_list if isinstance(attachment_list, list) else []
            input_config = message.get("input")
            input_items = input_config.get("items", []) if isinstance(input_config, dict) else []
            rows.append(
                {
                    "category": category,
                    "session_id": session.get("session_id"),
                    "session_created_at": session.get("created_at"),
                    "message_index": index,
                    "message_id": f"{hashlib.sha256(str(session.get('session_id')).encode()).hexdigest()[:10]}:{index}",
                    "role": message.get("role"),
                    "timestamp": message.get("timestamp"),
                    "content": message.get("content") if isinstance(message.get("content"), str) else "",
                    "model": message.get("model"),
                    "provider": message.get("provider"),
                    "instructions": message.get("instructions"),
                    "has_rag": "rag" in message and message.get("rag") is not None,
                    "rag_query": rag.get("query", ""),
                    "rag_context": rag.get("context", []),
                    "attachment_count": len(attachment_list),
                    "has_attachment": len(attachment_list) > 0,
                    "attachment_types": [a.get("contentType") for a in attachment_list if isinstance(a, dict)],
                    "has_input_config": "input" in message and message.get("input") is not None,
                    "input_item_count": len(input_items) if isinstance(input_items, list) else 0,
                }
            )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["timestamp_dt"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    return frame


def _context_as_text(value: Any) -> str:
    """Convert nested context to a text-only representation for length metrics."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_context_as_text(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_context_as_text(v) for v in value)
    return str(value)


def approximate_tokens(text: str) -> int:
    """Return a rough character-based token proxy (ceil(chars / 4)).

    This is not a tokenizer and must never be interpreted as billed tokens,
    particularly for Persian text, code, or mixed structured payloads.
    """
    if not text:
        return 0
    return int(math.ceil(len(text) / 4))


def detect_language(text: str) -> str:
    """Explainable script heuristic: Persian-script, Latin, mixed, or unknown."""
    persian = len(PERSIAN_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    letters = persian + latin
    if letters == 0:
        return "other/unknown"
    if persian / letters >= 0.30 and latin / letters >= 0.15:
        return "mixed Persian/English"
    if persian / letters >= 0.50:
        return "Persian-script"
    if latin / letters >= 0.70:
        return "English/Latin-script"
    if persian > 0:
        return "mixed/other"
    return "English/Latin-script"


def add_text_features(frame: pd.DataFrame, text_column: str = "content") -> pd.DataFrame:
    """Return a copy with readable, low-cost character/text features."""
    result = frame.copy()
    text = result[text_column].fillna("").astype(str)
    normalized = text.str.replace(r"\s+", " ", regex=True).str.strip()
    result["char_count"] = text.str.len()
    result["normalized_char_count"] = normalized.str.len()
    result["word_count"] = text.map(_word_count)
    result["line_count"] = text.map(_line_count)
    result["newline_count"] = text.str.count("\n")
    result["sentence_count_approx"] = text.map(_sentence_count)
    result["punctuation_count"] = text.map(_punctuation_count)
    result["digit_count"] = text.map(_digit_count)
    result["question_mark_count"] = text.str.count(r"\?") + text.str.count("؟")
    result["has_url"] = text.map(_contains_url)
    result["has_code_like_text"] = text.map(_contains_code)
    result["has_fenced_code"] = text.str.contains("```", regex=False)
    result["has_markdown_like_formatting"] = text.map(_contains_markdown)
    result["persian_char_count"] = text.map(_persian_character_count)
    result["latin_char_count"] = text.map(_latin_character_count)
    denominator = result["persian_char_count"] + result["latin_char_count"]
    result["persian_char_proportion"] = np.where(denominator > 0, result["persian_char_count"] / denominator, np.nan)
    result["latin_char_proportion"] = np.where(denominator > 0, result["latin_char_count"] / denominator, np.nan)
    result["language"] = text.map(detect_language)
    result["is_empty"] = text.str.strip().eq("")
    result["is_extremely_short"] = text.str.strip().str.len().between(1, 10)
    result["is_extremely_long"] = result["char_count"] >= 5000
    result["approx_tokens_char_div4"] = text.map(approximate_tokens)
    return result


def _word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def _line_count(text: str) -> int:
    return 0 if not text else text.count("\n") + 1


def _sentence_count(text: str) -> int:
    sentence_marks = (".", "!", "?", "؟", "۔")
    return sum(text.count(mark) for mark in sentence_marks) or int(bool(text.strip()))


def _punctuation_count(text: str) -> int:
    return sum(unicodedata.category(char).startswith("P") for char in text)


def _digit_count(text: str) -> int:
    return sum(char.isdigit() for char in text)


def _contains_url(text: str) -> bool:
    return bool(URL_RE.search(text))


def _contains_code(text: str) -> bool:
    return bool(CODE_RE.search(text))


def _contains_markdown(text: str) -> bool:
    return bool(MARKDOWN_RE.search(text))


def _persian_character_count(text: str) -> int:
    return len(PERSIAN_RE.findall(text))


def _latin_character_count(text: str) -> int:
    return len(LATIN_RE.findall(text))


def _short_hash(value: Any) -> str:
    """Return a short stable identifier without exposing the source value."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:10]


def percentile_90(values: pd.Series) -> float:
    """Return the 90th percentile for use in named pandas aggregations."""
    available = values.dropna()
    return float(available.quantile(0.90)) if not available.empty else float("nan")


def most_common_value(values: pd.Series, default: str = "other/unknown") -> str:
    """Return the first mode, or a stable fallback when no value is present."""
    modes = values.dropna().mode()
    return str(modes.iloc[0]) if not modes.empty else default


def pair_bot_responses_with_preceding_users(
    messages: pd.DataFrame,
    user_requests: pd.DataFrame,
) -> pd.DataFrame:
    """Attach each bot message to the latest earlier user message in its session.

    Matching uses message order rather than timestamps, which may be equal or
    timezone-naive. Bot responses without a preceding user message are retained
    with missing request features.
    """
    bots = messages.loc[messages["role"].eq("bot")].copy()
    users = user_requests.loc[user_requests["role"].eq("user")].copy()
    request_columns = [
        "session_id",
        "message_index",
        "message_id",
        "char_count",
        "language",
        "has_code_like_text",
        "exploratory_complexity_score",
    ]
    user_lookup = users[request_columns].rename(
        columns={
            "message_index": "request_message_index",
            "message_id": "request_message_id",
            "char_count": "request_char_count",
            "language": "request_language",
            "has_code_like_text": "request_has_code_like_text",
            "exploratory_complexity_score": "request_complexity_score",
        }
    )
    user_lookup = user_lookup.sort_values(["session_id", "request_message_index"])
    paired_groups = []
    for session_id, bot_group in bots.groupby("session_id", sort=False, dropna=False):
        bot_group = bot_group.copy()
        session_users = user_lookup.loc[user_lookup["session_id"].eq(session_id)]
        bot_group = bot_group.reset_index(drop=True)
        feature_columns = user_lookup.columns.drop("session_id")
        if session_users.empty:
            for column in feature_columns:
                bot_group[column] = np.nan
            paired_groups.append(bot_group)
            continue
        request_indices = session_users["request_message_index"].to_numpy()
        preceding_positions = np.searchsorted(
            request_indices,
            bot_group["message_index"].to_numpy(),
            side="left",
        ) - 1
        matched_users = session_users.iloc[np.maximum(preceding_positions, 0)].reset_index(drop=True)
        has_preceding_user = preceding_positions >= 0
        matched_users[feature_columns] = matched_users[feature_columns].astype(object)
        matched_users.loc[~has_preceding_user, feature_columns] = np.nan
        for column in feature_columns:
            bot_group[column] = matched_users[column].to_numpy()
        paired_groups.append(bot_group)
    if not paired_groups:
        return bots.assign(
            request_message_id=pd.Series(dtype="object"),
            request_char_count=pd.Series(dtype="float64"),
            request_language=pd.Series(dtype="object"),
            request_has_code_like_text=pd.Series(dtype="object"),
            request_complexity_score=pd.Series(dtype="float64"),
        )
    return pd.concat(paired_groups, ignore_index=True)


def _categorical_group_ids(values: pd.Series, prefix: str) -> pd.Series:
    """Create stable-in-order opaque labels for normalized nonempty strings."""
    normalized = values.fillna("").astype(str)
    present = normalized.str.strip().ne("")
    codes, _ = pd.factorize(normalized[present], sort=False)
    result = pd.Series(pd.NA, index=values.index, dtype="object")
    result.loc[present] = [f"{prefix}{code + 1:04d}" for code in codes]
    return result


def build_response_level_analysis(
    messages: pd.DataFrame,
    user_requests: pd.DataFrame,
) -> pd.DataFrame:
    """Build privacy-safe bot rows joined to their inferred preceding request.

    Matching follows :func:`pair_bot_responses_with_preceding_users`: each bot
    is linked to the latest earlier user message in array order. This is an
    association convention, not an explicit request/response key.

    The returned frame includes features and opaque IDs only; raw request,
    instruction, retrieval-context, and response text are used in memory but
    omitted from the output. Hypothetical input components assume all earlier
    message content, the matched current request, the logged instruction, and
    logged RAG context were supplied together. It is not actual provider input.
    """
    pairs = pair_bot_responses_with_preceding_users(messages, user_requests)
    bots = messages.loc[messages["role"].eq("bot")].copy()
    request_columns = [
        "message_id",
        "message_index",
        "char_count",
        "normalized_char_count",
        "word_count",
        "line_count",
        "sentence_count_approx",
        "punctuation_count",
        "digit_count",
        "question_mark_count",
        "has_url",
        "has_code_like_text",
        "has_fenced_code",
        "has_markdown_like_formatting",
        "persian_char_proportion",
        "latin_char_proportion",
        "language",
        "is_empty",
        "is_extremely_short",
        "is_extremely_long",
        "approx_tokens_char_div4",
        "attachment_count",
        "has_attachment",
        "has_input_config",
        "input_item_count",
        "exploratory_complexity_score",
        "complexity_band",
    ]
    heuristic_columns = [column for column in user_requests if column.startswith("heuristic_")]
    request_columns += heuristic_columns
    request_lookup = user_requests.loc[user_requests["role"].eq("user"), request_columns].copy()
    request_lookup = request_lookup.rename(
        columns={
            column: f"request_{column}"
            for column in request_columns
            if column not in {"message_id", "message_index"}
        }
        | {"message_id": "request_message_id", "message_index": "request_message_index"}
    )
    paired = pairs.drop(
        columns=[
            column
            for column in [
                "request_char_count",
                "request_language",
                "request_has_code_like_text",
                "request_complexity_score",
                "request_message_index",
            ]
            if column in pairs
        ]
    ).merge(request_lookup, on="request_message_id", how="left", validate="many_to_one")

    # An instruction value is analyzed separately from request content. Group
    # identity uses conservative normalization; the text is never returned.
    instruction_text = paired["instructions"].fillna("").astype(str)
    instruction_norm = instruction_text.map(normalize_safe)
    paired["instruction_present"] = instruction_text.str.strip().ne("")
    paired["instruction_chars"] = instruction_text.str.len().where(paired["instruction_present"], 0)
    paired["instruction_words"] = instruction_text.map(lambda value: len(WORD_RE.findall(value))).where(
        paired["instruction_present"], 0
    )
    paired["instruction_approx_tokens_char_div4"] = instruction_text.map(approximate_tokens).where(
        paired["instruction_present"], 0
    )
    paired["instruction_group_id"] = _categorical_group_ids(instruction_norm, "ins_")

    request_text = user_requests.set_index("message_id")["content"]
    request_raw = paired["request_message_id"].map(request_text).fillna("")
    paired["request_literal_group_id"] = _categorical_group_ids(request_raw, "req_raw_")
    paired["request_whitespace_group_id"] = _categorical_group_ids(
        request_raw.map(normalize_exact), "req_ws_"
    )
    paired["request_safe_group_id"] = _categorical_group_ids(
        request_raw.map(normalize_safe), "req_safe_"
    )
    for column in [
        "request_literal_group_id",
        "request_whitespace_group_id",
        "request_safe_group_id",
    ]:
        paired.loc[paired["request_message_id"].isna(), column] = pd.NA

    # Accumulate all transcript content strictly before the matched request,
    # split by user/bot role. Never assume this is what was sent to the model.
    by_session = {key: group.sort_values("message_index") for key, group in messages.groupby("session_id")}
    history_rows = []
    for _, row in paired.iterrows():
        prior = by_session.get(row["session_id"])
        if prior is None or pd.isna(row.get("request_message_index")):
            prior = messages.iloc[0:0]
        else:
            prior = prior.loc[prior["message_index"].lt(row["request_message_index"])]
        prior_users = prior.loc[prior["role"].eq("user")]
        prior_bots = prior.loc[prior["role"].eq("bot")]
        history_rows.append(
            {
                "prior_history_message_count": len(prior),
                "prior_history_user_message_count": len(prior_users),
                "prior_history_bot_message_count": len(prior_bots),
                "prior_history_chars": int(prior["char_count"].sum()),
                "prior_history_user_chars": int(prior_users["char_count"].sum()),
                "prior_history_bot_chars": int(prior_bots["char_count"].sum()),
                "prior_history_approx_tokens_char_div4": int(prior["approx_tokens_char_div4"].sum()),
                "prior_history_user_approx_tokens": int(prior_users["approx_tokens_char_div4"].sum()),
                "prior_history_bot_approx_tokens": int(prior_bots["approx_tokens_char_div4"].sum()),
            }
        )
    history = pd.DataFrame(history_rows, index=paired.index)
    paired = pd.concat([paired, history], axis=1)
    paired["response_number_in_session"] = paired.groupby("session_id", sort=False).cumcount() + 1
    request_turns = user_requests.loc[user_requests["role"].eq("user")].sort_values(
        ["session_id", "message_index"]
    ).copy()
    request_turns["request_turn_number"] = request_turns.groupby("session_id", sort=False).cumcount() + 1
    paired = paired.merge(
        request_turns[["message_id", "request_turn_number"]].rename(
            columns={"message_id": "request_message_id"}
        ),
        on="request_message_id",
        how="left",
        validate="many_to_one",
    )

    contexts = context_features(messages)
    context_columns = [
        "message_id",
        "context_chars",
        "context_words",
        "context_approx_tokens_char_div4",
        "rag_query_chars",
        "context_to_query_char_ratio",
    ]
    paired = paired.merge(
        contexts[context_columns].rename(columns={"message_id": "message_id"}),
        on="message_id",
        how="left",
        validate="one_to_one",
    )
    # For scenario arithmetic, a missing logged component contributes zero to
    # the *logged-field scenario* only; presence remains separately visible.
    for column in ["context_chars", "context_approx_tokens_char_div4"]:
        paired[column] = paired[column].fillna(0)
    paired["instruction_present"] = paired["instruction_present"].fillna(False)
    paired["instruction_chars"] = paired["instruction_chars"].fillna(0)
    paired["instruction_approx_tokens_char_div4"] = paired[
        "instruction_approx_tokens_char_div4"
    ].fillna(0)
    paired["request_char_count"] = paired["request_char_count"].fillna(0)
    paired["request_approx_tokens_char_div4"] = paired[
        "request_approx_tokens_char_div4"
    ].fillna(0)
    paired["hypothetical_input_chars_proxy"] = (
        paired["prior_history_chars"]
        + paired["request_char_count"]
        + paired["instruction_chars"]
        + paired["context_chars"]
    )
    paired["hypothetical_input_tokens_char_div4"] = paired[
        "hypothetical_input_chars_proxy"
    ].map(lambda value: int(math.ceil(value / 4)) if value else 0)
    matched_request = paired["request_message_id"].notna()
    paired.loc[~matched_request, [
        "hypothetical_input_chars_proxy",
        "hypothetical_input_tokens_char_div4",
    ]] = np.nan
    denominator = paired["hypothetical_input_chars_proxy"].replace(0, np.nan)
    for component, column in [
        ("current_request", "request_char_count"),
        ("prior_history", "prior_history_chars"),
        ("instructions", "instruction_chars"),
        ("logged_rag_context", "context_chars"),
    ]:
        paired[f"hypothetical_{component}_char_share"] = paired[column] / denominator
        paired.loc[~matched_request, f"hypothetical_{component}_char_share"] = np.nan

    request_times = user_requests.set_index("message_id")["timestamp_dt"]
    paired["request_timestamp_dt"] = paired["request_message_id"].map(request_times)
    paired["observed_user_to_bot_gap_seconds"] = (
        paired["timestamp_dt"] - paired["request_timestamp_dt"]
    ).dt.total_seconds()
    paired["session_id_hash"] = paired["session_id"].map(_short_hash)

    # Keep a deliberately compact, privacy-safe response-level schema.
    keep = [
        "session_id_hash", "category", "message_id", "message_index", "response_number_in_session",
        "request_message_id", "request_message_index", "request_turn_number",
        "request_literal_group_id", "request_whitespace_group_id", "request_safe_group_id",
        "request_char_count", "request_normalized_char_count", "request_word_count",
        "request_sentence_count_approx", "request_language", "request_has_code_like_text",
        "request_has_url", "request_has_fenced_code", "request_has_markdown_like_formatting",
        "request_exploratory_complexity_score", "request_complexity_band",
        *[f"request_{column}" for column in heuristic_columns],
        "request_attachment_count", "request_has_attachment", "request_has_input_config",
        "request_input_item_count", "instruction_present", "instruction_chars",
        "instruction_words", "instruction_approx_tokens_char_div4", "instruction_group_id",
        "model", "provider", "has_rag", "context_chars", "context_words",
        "context_approx_tokens_char_div4", "rag_query_chars", "context_to_query_char_ratio",
        "has_attachment", "has_input_config", "input_item_count",
        "char_count", "normalized_char_count", "word_count", "line_count",
        "sentence_count_approx", "language", "has_code_like_text", "has_url",
        "approx_tokens_char_div4", "prior_history_message_count",
        "prior_history_user_message_count", "prior_history_bot_message_count",
        "prior_history_chars", "prior_history_user_chars", "prior_history_bot_chars",
        "prior_history_approx_tokens_char_div4", "prior_history_user_approx_tokens",
        "prior_history_bot_approx_tokens", "hypothetical_input_chars_proxy",
        "hypothetical_input_tokens_char_div4", "hypothetical_current_request_char_share",
        "hypothetical_prior_history_char_share", "hypothetical_instructions_char_share",
        "hypothetical_logged_rag_context_char_share", "observed_user_to_bot_gap_seconds",
    ]
    keep = list(dict.fromkeys(column for column in keep if column in paired.columns))
    return paired[keep].copy()


def instruction_group_summary(response_level: pd.DataFrame) -> pd.DataFrame:
    """Summarize normalized instruction reuse without returning instruction text."""
    present = response_level.loc[response_level["instruction_present"]].copy()
    if present.empty:
        return pd.DataFrame(
            columns=[
                "instruction_group_id", "bot_records", "distinct_sessions", "distinct_categories",
                "distinct_models", "distinct_providers", "distinct_request_groups",
            ]
        )
    return (
        present.groupby("instruction_group_id", dropna=False)
        .agg(
            bot_records=("message_id", "count"),
            distinct_sessions=("session_id_hash", "nunique"),
            distinct_categories=("category", "nunique"),
            distinct_models=("model", "nunique"),
            distinct_providers=("provider", "nunique"),
            distinct_request_groups=("request_safe_group_id", "nunique"),
            median_instruction_chars=("instruction_chars", "median"),
        )
        .reset_index()
        .sort_values("bot_records", ascending=False, ignore_index=True)
    )


def summarize_segments(
    frame: pd.DataFrame,
    segment_columns: Iterable[str],
    value_column: str,
    *,
    include_missing: bool = True,
) -> pd.DataFrame:
    """Return n, median, p90, and non-null rate for numeric values by segments."""
    available = [column for column in segment_columns if column in frame.columns]
    if not available or value_column not in frame.columns:
        return pd.DataFrame()
    result = (
        frame.groupby(available, dropna=not include_missing, observed=False)[value_column]
        .agg(
            n="count",
            median="median",
            p90=percentile_90,
            non_null_rate=lambda values: values.notna().mean(),
        )
        .reset_index()
    )
    return result


def paired_char_ngram_similarity(left_texts: Iterable[str], right_texts: Iterable[str]) -> np.ndarray:
    """Calculate in-memory paired char n-gram TF-IDF cosine scores.

    Text is not returned or logged. Values with no usable character n-grams get
    a zero similarity rather than raising an empty-vocabulary error.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    left = [normalize_safe(str(value or "")) for value in left_texts]
    right = [normalize_safe(str(value or "")) for value in right_texts]
    if len(left) != len(right):
        raise ValueError("left_texts and right_texts must have equal length")
    if not left:
        return np.array([], dtype=float)
    try:
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=1, norm="l2")
        matrix = vectorizer.fit_transform(left + right)
    except ValueError as error:
        if "empty vocabulary" not in str(error).lower():
            raise
        return np.zeros(len(left), dtype=float)
    size = len(left)
    return np.asarray(matrix[:size].multiply(matrix[size:]).sum(axis=1)).ravel()


def repeated_request_response_pairs(
    user_requests: pd.DataFrame,
    response_level: pd.DataFrame,
    messages: pd.DataFrame,
    response_similarity_threshold: float = 0.85,
) -> pd.DataFrame:
    """Compare response-level contexts for repeated normalized user requests.

    Each request event is represented by its first bot record under the
    existing latest-preceding-user association. Output contains only hashed
    IDs, features, flags, and similarities; prompt, instruction, context, and
    response text remain in memory. Candidate stages are screens, not cache
    hit rates or safety determinations.
    """
    users = user_requests.loc[user_requests["role"].eq("user")].copy()
    users = users.sort_values(["session_id", "message_index"]).reset_index(drop=True)
    users["_normalized_request"] = users["content"].map(normalize_safe)
    users["_request_group_id"] = _categorical_group_ids(users["_normalized_request"], "req_")
    first_responses = (
        response_level.loc[response_level["request_message_id"].notna()]
        .sort_values(["request_message_index", "message_index"])
        .drop_duplicates("request_message_id", keep="first")
        .copy()
    )
    response_columns = [
        "request_message_id", "message_id", "session_id_hash", "model", "provider",
        "instruction_present", "instruction_group_id", "has_rag", "context_chars",
        "has_attachment", "has_input_config", "prior_history_message_count",
        "prior_history_chars", "observed_user_to_bot_gap_seconds", "char_count",
    ]
    response_lookup = first_responses[response_columns].rename(
        columns={
            "message_id": "response_message_id",
            "char_count": "response_chars",
            "session_id_hash": "response_session_id_hash",
            "has_attachment": "response_has_attachment",
            "has_input_config": "response_has_input_config",
            "model": "associated_model",
            "provider": "associated_provider",
            "instruction_present": "associated_instruction_present",
            "instruction_group_id": "associated_instruction_group_id",
            "has_rag": "associated_has_rag",
            "context_chars": "associated_context_chars",
            "prior_history_message_count": "associated_prior_history_message_count",
            "prior_history_chars": "associated_prior_history_chars",
            "observed_user_to_bot_gap_seconds": "associated_observed_gap_seconds",
        }
    )
    events = users.merge(
        response_lookup,
        left_on="message_id",
        right_on="request_message_id",
        how="left",
        validate="one_to_one",
        suffixes=("", "_response"),
    )
    response_text = messages.set_index("message_id")["content"]
    context_rows = context_features(messages)
    context_text = context_rows.set_index("message_id")["context_text"]
    pairs = []
    for group_id, group in events.loc[events["_normalized_request"].ne("")].groupby(
        "_request_group_id", sort=False
    ):
        if len(group) < 2:
            continue
        records = group.to_dict("records")
        for left, right in combinations(records, 2):
            left_response = left.get("response_message_id")
            right_response = right.get("response_message_id")
            has_two_responses = pd.notna(left_response) and pd.notna(right_response)
            if has_two_responses:
                left_text = response_text.get(left_response, "")
                right_text = response_text.get(right_response, "")
                response_similarity = float(
                    paired_char_ngram_similarity([left_text], [right_text])[0]
                )
                same_response_exact = normalize_safe(left_text) == normalize_safe(right_text)
            else:
                response_similarity = np.nan
                same_response_exact = False
            same_instruction = bool(
                left.get("associated_instruction_present")
                and right.get("associated_instruction_present")
                and pd.notna(left.get("associated_instruction_group_id"))
                and left.get("associated_instruction_group_id")
                == right.get("associated_instruction_group_id")
            )
            left_has_rag = bool(left.get("associated_has_rag", False))
            right_has_rag = bool(right.get("associated_has_rag", False))
            both_no_logged_rag = bool(not left_has_rag and not right_has_rag)
            both_no_prior_history = bool(
                left.get("associated_prior_history_message_count") == 0
                and right.get("associated_prior_history_message_count") == 0
            )
            if left_has_rag and right_has_rag and pd.notna(left_response) and pd.notna(right_response):
                left_context = context_text.get(left_response, "")
                right_context = context_text.get(right_response, "")
                rag_context_similarity = float(
                    paired_char_ngram_similarity([left_context], [right_context])[0]
                )
                same_rag_context_exact = normalize_safe(left_context) == normalize_safe(right_context)
            else:
                rag_context_similarity = np.nan
                same_rag_context_exact = False
            left_model, right_model = left.get("associated_model"), right.get("associated_model")
            left_provider, right_provider = left.get("associated_provider"), right.get("associated_provider")
            response_similar = bool(
                has_two_responses and response_similarity >= response_similarity_threshold
            )
            pairs.append(
                {
                    "request_group_id": group_id,
                    "left_request_id": left["message_id"],
                    "right_request_id": right["message_id"],
                    "left_request_message_index": left["message_index"],
                    "right_request_message_index": right["message_index"],
                    "left_session_id_hash": _short_hash(left["session_id"]),
                    "right_session_id_hash": _short_hash(right["session_id"]),
                    "same_session": left["session_id"] == right["session_id"],
                    "left_category": left["category"],
                    "right_category": right["category"],
                    "same_category": left["category"] == right["category"],
                    "left_request_chars": left["char_count"],
                    "right_request_chars": right["char_count"],
                    "left_request_language": left.get("language"),
                    "right_request_language": right.get("language"),
                    "left_request_complexity_band": left.get("complexity_band"),
                    "right_request_complexity_band": right.get("complexity_band"),
                    "left_request_has_code": bool(left.get("has_code_like_text", False)),
                    "right_request_has_code": bool(right.get("has_code_like_text", False)),
                    "left_request_has_attachment": bool(left.get("has_attachment", False)),
                    "right_request_has_attachment": bool(right.get("has_attachment", False)),
                    "left_request_has_input_config": bool(left.get("has_input_config", False)),
                    "right_request_has_input_config": bool(right.get("has_input_config", False)),
                    "left_request_has_url": bool(left.get("has_url", False)),
                    "right_request_has_url": bool(right.get("has_url", False)),
                    "left_response_id": left_response,
                    "right_response_id": right_response,
                    "left_model": left_model,
                    "right_model": right_model,
                    "same_model": bool(pd.notna(left_model) and pd.notna(right_model) and left_model == right_model),
                    "left_provider": left_provider,
                    "right_provider": right_provider,
                    "same_provider": bool(pd.notna(left_provider) and pd.notna(right_provider) and left_provider == right_provider),
                    "left_instruction_group": left.get("associated_instruction_group_id"),
                    "right_instruction_group": right.get("associated_instruction_group_id"),
                    "same_instruction": same_instruction,
                    "left_instruction_present": bool(left.get("associated_instruction_present", False)),
                    "right_instruction_present": bool(right.get("associated_instruction_present", False)),
                    "left_has_logged_rag": left_has_rag,
                    "right_has_logged_rag": right_has_rag,
                    "both_no_logged_rag": both_no_logged_rag,
                    "left_context_chars": left.get("associated_context_chars"),
                    "right_context_chars": right.get("associated_context_chars"),
                    "rag_context_similarity": rag_context_similarity,
                    "same_rag_context_exact_normalized": bool(same_rag_context_exact),
                    "left_prior_history_messages": left.get("associated_prior_history_message_count"),
                    "right_prior_history_messages": right.get("associated_prior_history_message_count"),
                    "left_prior_history_chars": left.get("associated_prior_history_chars"),
                    "right_prior_history_chars": right.get("associated_prior_history_chars"),
                    "both_no_prior_history": both_no_prior_history,
                    "left_observed_user_to_bot_gap_seconds": left.get("associated_observed_gap_seconds"),
                    "right_observed_user_to_bot_gap_seconds": right.get("associated_observed_gap_seconds"),
                    "left_response_chars": left.get("response_chars"),
                    "right_response_chars": right.get("response_chars"),
                    "both_have_responses": bool(has_two_responses),
                    "response_similarity": response_similarity,
                    "same_response_exact_normalized": bool(same_response_exact),
                    "response_similar_threshold": response_similar,
                    "stage_1_same_normalized_request": True,
                    "stage_2_same_request_and_instruction": same_instruction,
                    "stage_3_same_instruction_and_no_logged_rag": same_instruction and both_no_logged_rag,
                    "stage_4_no_prior_history": same_instruction and both_no_logged_rag and both_no_prior_history,
                    "stage_5_similar_response": same_instruction and both_no_logged_rag and both_no_prior_history and response_similar,
                }
            )
    return pd.DataFrame(pairs)


def build_session_dataframe(sessions: Iterable[dict[str, Any]], messages: pd.DataFrame) -> pd.DataFrame:
    """Build session aggregates; gaps are timestamp differences, not latency."""
    records = []
    for item in sessions:
        category, session = item["category"], item["session"]
        group = messages[messages["session_id"] == session.get("session_id")].sort_values("message_index")
        user = group[group["role"] == "user"]
        bot = group[group["role"] == "bot"]
        valid_times = group["timestamp_dt"].dropna()
        duration = (valid_times.max() - valid_times.min()).total_seconds() if len(valid_times) > 1 else 0.0
        models = bot["model"].dropna().astype(str)
        providers = bot["provider"].dropna().astype(str)
        switches_model = int((models != models.shift()).sum() - (1 if len(models) else 0))
        switches_provider = int((providers != providers.shift()).sum() - (1 if len(providers) else 0))
        gaps = []
        for index, row in user.iterrows():
            following = group[(group["message_index"] > row["message_index"]) & (group["role"] == "bot")]
            if not following.empty and pd.notna(row["timestamp_dt"]):
                next_bot = following.iloc[0]
                if pd.notna(next_bot["timestamp_dt"]):
                    gap = (next_bot["timestamp_dt"] - row["timestamp_dt"]).total_seconds()
                    if gap >= 0:
                        gaps.append(gap)
        user_chars, bot_chars = int(user["char_count"].sum()), int(bot["char_count"].sum())
        records.append(
            {
                "session_id": session.get("session_id"),
                "category": category,
                "session_created_at": pd.to_datetime(session.get("created_at"), errors="coerce"),
                "declared_session_len": session.get("session_len"),
                "message_count": len(group),
                "user_turns": len(user),
                "bot_turns": len(bot),
                "unanswered_user_turns": max(0, len(user) - len(bot)),
                "user_chars": user_chars,
                "bot_chars": bot_chars,
                "user_approx_tokens": int(user["approx_tokens_char_div4"].sum()),
                "bot_approx_tokens": int(bot["approx_tokens_char_div4"].sum()),
                "user_to_bot_char_ratio": user_chars / bot_chars if bot_chars else np.nan,
                "duration_seconds": duration,
                "median_observed_user_to_next_bot_gap_seconds": float(np.median(gaps)) if gaps else np.nan,
                "model_count": models.nunique(),
                "provider_count": providers.nunique(),
                "model_switch_count": switches_model,
                "provider_switch_count": switches_provider,
                "has_retrieval": bool(group["has_rag"].any()),
                "has_attachment": bool(group["attachment_count"].gt(0).any()),
                "has_input_config_proxy": bool(group["has_input_config"].any()),
            }
        )
    return pd.DataFrame(records)


def summarize_missingness(frame: pd.DataFrame) -> pd.DataFrame:
    """Count null and blank values for each column."""
    return pd.DataFrame(
        {
            "column": frame.columns,
            "dtype": [str(frame[column].dtype) for column in frame.columns],
            "null_count": [int(frame[column].isna().sum()) for column in frame.columns],
            "null_pct": [float(frame[column].isna().mean() * 100) for column in frame.columns],
        }
    ).sort_values("null_count", ascending=False, ignore_index=True)


def numeric_summary(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Report count, center, spread, and tail percentiles for numeric variables."""
    rows = []
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if values.empty:
            continue
        rows.append(
            {
                "metric": column,
                "count": len(values),
                "mean": values.mean(),
                "median": values.median(),
                "std": values.std(),
                "min": values.min(),
                "p25": values.quantile(0.25),
                "p50": values.quantile(0.50),
                "p75": values.quantile(0.75),
                "p90": values.quantile(0.90),
                "p95": values.quantile(0.95),
                "p99": values.quantile(0.99),
                "max": values.max(),
            }
        )
    return pd.DataFrame(rows)


def summarize_values(frame: pd.DataFrame, column: str, include_missing: bool = True) -> pd.DataFrame:
    """Return count and percentage by value without expanding sensitive text."""
    values = frame[column].astype("object")
    counts = values.value_counts(dropna=not include_missing).rename_axis(column).reset_index(name="count")
    counts["percent"] = counts["count"] / len(frame) * 100 if len(frame) else 0
    return counts


def analyze_request_heuristics(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach reproducible, exploratory user-request labels and proxy score."""
    result = frame.copy()
    user_mask = result["role"].eq("user")
    text = result["content"].fillna("")
    # Keywords are intentionally broad and multilingual-light; overlap is possible.
    patterns = {
        "coding": r"\b(?:code|python|javascript|sql|bug|function|api|html|css)\b|کد|برنامه نویسی|خطا",
        "math": r"\b(?:math|calculate|equation|sum|integral|probability)\b|ریاضی|حساب کن|محاسبه",
        "translation": r"\b(?:translate|translation)\b|ترجمه",
        "rewrite_edit": r"\b(?:rewrite|edit|proofread|improve this text)\b|بازنویسی|ویرایش|اصلاح متن",
        "summarization": r"\b(?:summarize|summary|tl;dr)\b|خلاصه|خلاصه کن",
        "structured_output": r"\b(?:json|yaml|xml|csv|table|schema)\b|خروجی ساختاریافته",
        "long_form_generation": r"\b(?:write an article|essay|long form|detailed report)\b|مقاله بنویس|گزارش مفصل",
    }
    for label, pattern in patterns.items():
        result[f"heuristic_{label}"] = user_mask & text.str.contains(pattern, case=False, regex=True, na=False)
    complexity = (
        result["char_count"].ge(500).astype(int)
        + result["sentence_count_approx"].ge(3).astype(int)
        + result["has_code_like_text"].astype(int)
        + text.map(_has_multiple_instruction_markers).astype(int)
    )
    result["exploratory_complexity_score"] = np.where(user_mask, complexity, np.nan)
    result["complexity_band"] = pd.cut(
        result["exploratory_complexity_score"], bins=[-1, 1, 2, 5], labels=["low (0-1)", "medium (2)", "high (3+)"]
    ).astype("object")
    result.loc[~user_mask, "complexity_band"] = np.nan
    return result


def _has_multiple_instruction_markers(text: str) -> bool:
    return len(INSTRUCTION_RE.findall(text)) >= 2


def normalize_exact(text: str) -> str:
    """Whitespace-only normalization: trim and collapse runs, preserving case."""
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_safe(text: str) -> str:
    """Conservative normalization: Unicode NFKC, casefold, collapsed whitespace."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").casefold()).strip()


def duplicate_groups(
    frame: pd.DataFrame,
    normalized_column: str,
    role: str = "user",
) -> pd.DataFrame:
    """Summarize duplicate messages of a selected role without exposing text."""
    users = frame[(frame["role"] == role) & frame[normalized_column].astype(str).str.strip().ne("")].copy()
    rows = []
    for normalized, group in users.groupby(normalized_column, sort=False):
        if len(group) < 2:
            continue
        rows.append(
            {
                "duplicate_group": f"dup_{len(rows) + 1:03d}",
                "occurrences": len(group),
                "distinct_sessions": group["session_id"].nunique(),
                "within_session_repeats": int(len(group) - group["session_id"].nunique()),
                "message_ids": ";".join(group["message_id"].astype(str)),
                "median_chars": group["char_count"].median(),
            }
        )
    return pd.DataFrame(rows).sort_values("occurrences", ascending=False, ignore_index=True) if rows else pd.DataFrame(
        columns=["duplicate_group", "occurrences", "distinct_sessions", "within_session_repeats", "message_ids", "median_chars"]
    )


def near_duplicate_pairs(
    frame: pd.DataFrame,
    minimum_similarity: float = 0.55,
    role: str = "user",
) -> tuple[pd.DataFrame, np.ndarray]:
    """Use local character n-gram TF-IDF cosine similarity on one message role.

    Returns candidate pairs with IDs/lengths only (no raw text) and flattened
    pairwise scores for describing the full similarity distribution.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    users = frame[(frame["role"] == role) & frame["content"].astype(str).str.strip().ne("")].copy().reset_index(drop=True)
    if len(users) < 2:
        return pd.DataFrame(), np.array([])
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, norm="l2", max_features=100_000)
    matrix = vectorizer.fit_transform(users["content"].map(normalize_safe))
    similarity = cosine_similarity(matrix, dense_output=True)
    upper_i, upper_j = np.triu_indices(len(users), k=1)
    scores = similarity[upper_i, upper_j]
    normalized_values = users["content"].map(normalize_safe).to_numpy()
    exact_normalized = normalized_values[upper_i] == normalized_values[upper_j]
    select = scores >= minimum_similarity
    session_hashes = users["session_id"].map(_short_hash).to_numpy()
    pairs = pd.DataFrame(
        {
            "left_message_id": users.loc[upper_i[select], "message_id"].to_numpy(),
            "right_message_id": users.loc[upper_j[select], "message_id"].to_numpy(),
            "left_session_id_hash": session_hashes[upper_i[select]],
            "right_session_id_hash": session_hashes[upper_j[select]],
            "similarity": scores[select],
            "is_normalized_exact_match": exact_normalized[select],
            "left_chars": users.loc[upper_i[select], "char_count"].to_numpy(),
            "right_chars": users.loc[upper_j[select], "char_count"].to_numpy(),
            "same_session": users.loc[upper_i[select], "session_id"].to_numpy()
            == users.loc[upper_j[select], "session_id"].to_numpy(),
        }
    ).sort_values("similarity", ascending=False, ignore_index=True)
    return pairs, scores


def context_features(messages: pd.DataFrame) -> pd.DataFrame:
    """Return retrieval rows with context/query size proxies and categoricals."""
    retrieval = messages[messages["has_rag"]].copy()
    retrieval["context_text"] = retrieval["rag_context"].map(_context_as_text)
    retrieval["context_chars"] = retrieval["context_text"].str.len()
    retrieval["context_words"] = retrieval["context_text"].map(_word_count)
    retrieval["context_approx_tokens_char_div4"] = retrieval["context_text"].map(approximate_tokens)
    retrieval["rag_query_chars"] = retrieval["rag_query"].fillna("").astype(str).str.len()
    retrieval["context_to_query_char_ratio"] = np.where(
        retrieval["rag_query_chars"] > 0, retrieval["context_chars"] / retrieval["rag_query_chars"], np.nan
    )
    return retrieval


def data_dictionary(categories: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a data-driven dictionary for the fields present in raw records."""
    descriptions = {
        "category": ("category bucket", "Opaque stratum; meaning intentionally undocumented"),
        "session_id": ("session", "Session identifier; uniqueness is checked separately"),
        "created_at": ("session", "Naive timestamp; timezone semantics are unknown"),
        "session_len": ("session", "Declared message count; compared with parsed messages"),
        "user_turns": ("session", "Declared user-message count; checked against roles"),
        "bot_turns": ("session", "Declared bot-message count; checked against roles"),
        "role": ("message", "Observed message role"),
        "content": ("message", "Text payload; potentially sensitive and kept in memory"),
        "timestamp": ("message", "Naive message timestamp; not an API latency guarantee"),
        "model": ("bot message", "Logged model label; default/workflow labels are retained"),
        "provider": ("bot message", "Logged provider label; not verified billing identity"),
        "instructions": ("bot message", "Unverified metadata, separate from message content"),
        "rag": ("bot message", "Retrieval metadata; absence does not prove retrieval was unused"),
        "attachments": ("message", "Attachment metadata; payloads/URLs excluded from outputs"),
        "input": ("bot message", "Items-based proxy; configuration semantics are uncertain"),
    }
    records_by_level = {
        "category": [(record, "category") for record in categories],
        "session": [
            (session, "session")
            for category in categories
            for session in category.get("sessions", [])
        ],
        "message": [
            (message, "message")
            for category in categories
            for session in category.get("sessions", [])
            for message in session.get("messages", [])
        ],
    }
    rows = []
    for records in records_by_level.values():
        fields = sorted({key for record, _ in records for key in record})
        for field in fields:
            values = [record[field] for record, _ in records if field in record]
            non_null = [value for value in values if value is not None]
            types = sorted({_python_type_name(value) for value in non_null})
            null_count = len(values) - len(non_null)
            description = descriptions.get(field, ("unverified", "Meaning not documented"))
            rows.append(
                {
                    "field": field,
                    "observed_type": "/".join(types) if types else "unknown",
                    "grain": description[0],
                    "observed_presence_or_missingness": (
                        f"{len(values)}/{len(records)} have field; {null_count} null values"
                    ),
                    "meaning_and_uncertainty": description[1],
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "field",
            "observed_type",
            "grain",
            "observed_presence_or_missingness",
            "meaning_and_uncertainty",
        ],
    )


def _python_type_name(value: Any) -> str:
    """Return a concise type label for values in the raw JSON schema."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def schema_summary(categories: list[dict[str, Any]]) -> pd.DataFrame:
    """Summarize the top-level and nested record shapes without exposing values."""
    rows = []
    for level, records in (
        ("category", categories),
        ("session", [s for c in categories for s in c.get("sessions", [])]),
        ("message", [m for c in categories for s in c.get("sessions", []) for m in s.get("messages", [])]),
    ):
        key_counts = Counter(key for record in records if isinstance(record, dict) for key in record)
        for key, count in sorted(key_counts.items()):
            rows.append({"record_level": level, "field": key, "records_with_field": count, "records": len(records), "pct_present": count / len(records) * 100 if records else np.nan})
    return pd.DataFrame(rows)


def integrity_checks(categories: list[dict[str, Any]], sessions: list[dict[str, Any]], messages: pd.DataFrame) -> pd.DataFrame:
    """Run deterministic checks for IDs, role counts, declared counts, and time."""
    raw_sessions = [item["session"] for item in sessions]
    session_ids = [s.get("session_id") for s in raw_sessions]
    mismatch_count = 0
    for session in raw_sessions:
        actual = session.get("messages", [])
        mismatch_count += int(session.get("session_len") != len(actual))
        mismatch_count += int(session.get("user_turns") != sum(m.get("role") == "user" for m in actual))
        mismatch_count += int(session.get("bot_turns") != sum(m.get("role") == "bot" for m in actual))
    within_session_decreases = 0
    timestamp_parse_failures = int(messages["timestamp_dt"].isna().sum())
    for _, group in messages.groupby("session_id"):
        times = group.sort_values("message_index")["timestamp_dt"].dropna()
        within_session_decreases += int((times.diff().dt.total_seconds().dropna() < 0).sum())
    checks = [
        ("duplicate session ID occurrences", len(session_ids) - len(set(session_ids)), "Expect 0"),
        ("declared session counter mismatches", mismatch_count, "Expect 0 across three counters per session"),
        ("unexpected message roles", int((~messages["role"].isin(["user", "bot"])).sum()), "Expect 0 if role vocabulary is stable"),
        ("unparseable message timestamps", timestamp_parse_failures, "Expect 0; naive timestamps remain timezone-ambiguous"),
        ("within-session timestamp decreases", within_session_decreases, "May indicate ordering or export issues; equal timestamps allowed"),
        ("empty message content", int(messages["content"].fillna("").str.strip().eq("").sum()), "Inspect as structural edge cases"),
    ]
    return pd.DataFrame(checks, columns=["check", "count", "interpretation"])


def safe_text_excerpt(text: str, limit: int = 160) -> str:
    """Create a conservative excerpt by suppressing URLs, emails, and long digits.

    This is a convenience, not a complete privacy guarantee. Prefer displaying
    aggregate outputs and do not print excerpts by default.
    """
    excerpt = URL_RE.sub("[URL]", text or "")
    excerpt = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", excerpt)
    excerpt = re.sub(r"(?<!\w)\d{5,}(?!\w)", "[NUMBER]", excerpt)
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    return excerpt[:limit] + ("…" if len(excerpt) > limit else "")
