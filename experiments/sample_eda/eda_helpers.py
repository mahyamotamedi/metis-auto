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
    for category in categories:
        label = category.get("category")
        for session in category.get("sessions", []):
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
    result["word_count"] = text.map(lambda x: len(WORD_RE.findall(x)))
    result["line_count"] = text.map(lambda x: 0 if not x else x.count("\n") + 1)
    result["newline_count"] = text.str.count("\n")
    result["sentence_count_approx"] = text.map(
        lambda x: sum(x.count(mark) for mark in (".", "!", "?", "؟", "۔")) or (1 if x.strip() else 0)
    )
    result["punctuation_count"] = text.map(lambda x: sum(unicodedata.category(ch).startswith("P") for ch in x))
    result["digit_count"] = text.map(lambda x: sum(ch.isdigit() for ch in x))
    result["question_mark_count"] = text.map(lambda x: x.count("?") + x.count("؟"))
    result["has_url"] = text.map(lambda x: bool(URL_RE.search(x)))
    result["has_code_like_text"] = text.map(lambda x: bool(CODE_RE.search(x)))
    result["has_fenced_code"] = text.str.contains("```", regex=False)
    result["has_markdown_like_formatting"] = text.map(lambda x: bool(MARKDOWN_RE.search(x)))
    result["persian_char_count"] = text.map(lambda x: len(PERSIAN_RE.findall(x)))
    result["latin_char_count"] = text.map(lambda x: len(LATIN_RE.findall(x)))
    denominator = result["persian_char_count"] + result["latin_char_count"]
    result["persian_char_proportion"] = np.where(denominator > 0, result["persian_char_count"] / denominator, np.nan)
    result["latin_char_proportion"] = np.where(denominator > 0, result["latin_char_count"] / denominator, np.nan)
    result["language"] = text.map(detect_language)
    result["is_empty"] = text.str.strip().eq("")
    result["is_extremely_short"] = text.str.strip().str.len().between(1, 10)
    result["is_extremely_long"] = result["char_count"] >= 5000
    result["approx_tokens_char_div4"] = text.map(approximate_tokens)
    return result


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
        "coding": r"\b(code|python|javascript|sql|bug|function|api|html|css)\b|کد|برنامه نویسی|خطا",
        "math": r"\b(math|calculate|equation|sum|integral|probability)\b|ریاضی|حساب کن|محاسبه",
        "translation": r"\b(translate|translation)\b|ترجمه",
        "rewrite_edit": r"\b(rewrite|edit|proofread|improve this text)\b|بازنویسی|ویرایش|اصلاح متن",
        "summarization": r"\b(summarize|summary|tl;dr)\b|خلاصه|خلاصه کن",
        "structured_output": r"\b(json|yaml|xml|csv|table|schema)\b|خروجی ساختاریافته",
        "long_form_generation": r"\b(write an article|essay|long form|detailed report)\b|مقاله بنویس|گزارش مفصل",
    }
    for label, pattern in patterns.items():
        result[f"heuristic_{label}"] = user_mask & text.str.contains(pattern, case=False, regex=True, na=False)
    complexity = (
        result["char_count"].ge(500).astype(int)
        + result["sentence_count_approx"].ge(3).astype(int)
        + result["has_code_like_text"].astype(int)
        + text.map(lambda value: len(INSTRUCTION_RE.findall(value)) >= 2).astype(int)
    )
    result["exploratory_complexity_score"] = np.where(user_mask, complexity, np.nan)
    result["complexity_band"] = pd.cut(
        result["exploratory_complexity_score"], bins=[-1, 1, 2, 5], labels=["low (0-1)", "medium (2)", "high (3+)"]
    ).astype("object")
    result.loc[~user_mask, "complexity_band"] = np.nan
    return result


def normalize_exact(text: str) -> str:
    """Whitespace-only normalization: trim and collapse runs, preserving case."""
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_safe(text: str) -> str:
    """Conservative normalization: Unicode NFKC, casefold, collapsed whitespace."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "").casefold()).strip()


def duplicate_groups(frame: pd.DataFrame, normalized_column: str) -> pd.DataFrame:
    """Summarize duplicate prompt groups with opaque labels, not prompt text."""
    users = frame[(frame["role"] == "user") & frame[normalized_column].astype(str).str.strip().ne("")].copy()
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


def near_duplicate_pairs(frame: pd.DataFrame, minimum_similarity: float = 0.55) -> tuple[pd.DataFrame, np.ndarray]:
    """Use local character n-gram TF-IDF cosine similarity on user prompts.

    Returns candidate pairs with IDs/lengths only (no raw text) and flattened
    pairwise scores for describing the full similarity distribution.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    users = frame[(frame["role"] == "user") & frame["content"].astype(str).str.strip().ne("")].copy().reset_index(drop=True)
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
    session_hashes = users["session_id"].map(
        lambda value: hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:10]
    ).to_numpy()
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
    retrieval["context_words"] = retrieval["context_text"].map(lambda value: len(WORD_RE.findall(value)))
    retrieval["context_approx_tokens_char_div4"] = retrieval["context_text"].map(approximate_tokens)
    retrieval["rag_query_chars"] = retrieval["rag_query"].fillna("").astype(str).str.len()
    retrieval["context_to_query_char_ratio"] = np.where(
        retrieval["rag_query_chars"] > 0, retrieval["context_chars"] / retrieval["rag_query_chars"], np.nan
    )
    return retrieval


def data_dictionary(categories: list[dict[str, Any]], messages: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Construct a concise dictionary from observed fields and known semantics."""
    rows = [
        ("category", "str", "category bucket", "4 buckets; 25 sessions each", "Opaque stratum; meaning intentionally undocumented"),
        ("session_id", "str", "session", "0 missing in parsed sample", "100 unique values observed"),
        ("created_at", "str/datetime", "session", "0 missing in parsed sample", "Naive ISO-like timestamp; timezone absent"),
        ("session_len", "int", "session", "0 missing in parsed sample", "Matches message array size in this sample"),
        ("user_turns", "int", "session", "0 missing in parsed sample", "Declared count matches parsed roles in sample"),
        ("bot_turns", "int", "session", "0 missing in parsed sample", "Declared count matches parsed roles in sample"),
        ("role", "str", "message", "0 missing in parsed sample", "Observed values: user, bot"),
        ("content", "str", "message", "0 missing in parsed sample", "May contain serialized payloads; sensitive text retained only in memory"),
        ("timestamp", "str/datetime", "message", "0 missing in parsed sample", "Naive ISO-like timestamp; not an API latency guarantee"),
        ("model", "str/null", "bot message", "27/442 bot values null", "'default' and workflow entries are not normalized away"),
        ("provider", "str/null", "bot message", "27/442 bot values null", "Provider labels are export values, not verified billing entities"),
        ("instructions", "str/null", "bot message", "27 null among 442 bot records", "Unverified metadata; analyzed separately from request/context totals"),
        ("rag", "dict", "bot message", "71/442 bot records", "Contains query and context; absence does not prove retrieval was unused"),
        ("attachments", "list", "message", "14/907 messages", "Observed only on user messages; payload/URLs excluded from outputs"),
        ("input", "dict", "bot message", "29/442 bot records", "Items-based uncertain proxy for structured-input configuration"),
    ]
    return pd.DataFrame(rows, columns=["field", "observed_type", "grain", "observed_presence_or_missingness", "meaning_and_uncertainty"])


def schema_summary(categories: list[dict[str, Any]], messages: pd.DataFrame) -> pd.DataFrame:
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
