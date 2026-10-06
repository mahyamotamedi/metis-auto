"""Local, reproducible Metis-Auto EDA. Conversation contents are never executed."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

SEED = 20261006


def resolve_input(root, kind, explicit=None):
    root = Path(root)
    supplied = explicit or os.environ.get("METIS_DATA_PATH" if kind == "data" else "METIS_PDF_PATH")
    if supplied:
        return Path(supplied)
    default = root / "data" / ("data.json" if kind == "data" else "project-draft.pdf")
    if default.exists():
        return default
    manifest_path = root / "outputs/run_manifest.json"
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8")).get(kind + "_path")
        if previous and Path(previous).exists():
            return Path(previous)
    return default


def text(value):
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def digest(value):
    return hashlib.sha256(text(value).encode("utf-8")).hexdigest()


def normalize(value):
    # Keep raw separately. Unify Arabic/Persian letters; ZWNJ becomes a space.
    s = unicodedata.normalize("NFC", text(value)).translate(str.maketrans("يك", "یک"))
    s = re.sub(r"[\u064b-\u065f\u0640]", "", s)
    return re.sub(r"\s+", " ", s.replace("\u200c", " ").replace("\u200f", "")).strip()


def redact_urls(value):
    def clean(match):
        try:
            u = urlsplit(match.group(0))
            return urlunsplit((u.scheme, u.netloc, u.path, "", ""))
        except ValueError:
            return "[URL]"
    return re.sub(r"https?://[^\s\"<>]+", clean, text(value))


def snippet(value, limit=140):
    return redact_urls(value).replace("\n", " ").replace("|", "¦")[:limit]


def markdown(df):
    if df.empty:
        return "هیچ موردی مشاهده نشد."
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in df.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(snippet(round(v, 4) if isinstance(v, float) else v, 220) for v in row) + " |")
    return "\n".join(lines)


def parse_time(value):
    try:
        t = pd.Timestamp(value) if isinstance(value, str) and value else pd.NaT
        if pd.isna(t):
            return pd.NaT, "invalid"
        zone = "explicit" if t.tzinfo is not None else "unknown"
        # Naive timestamps provisionally share a clock, NOT proven UTC.
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC"), zone
    except (ValueError, TypeError, OverflowError):
        return pd.NaT, "invalid"


def content_kind(value):
    if not isinstance(value, str):
        return "native_" + type(value).__name__
    s = value.strip()
    try:
        json.loads(s)
        return "valid_json"
    except (ValueError, TypeError):
        decoder = json.JSONDecoder()
        if s.startswith(("{", "[")):
            try:
                obj, end = decoder.raw_decode(s)
                if isinstance(obj, (dict, list)) and s[end:].strip():
                    return "mixed_text_json"
            except ValueError:
                pass
        if s.startswith(("{", "[")):
            return "invalid_json_like"
        for match in re.finditer(r"[\[{]", s):
            try:
                obj, end = decoder.raw_decode(s[match.start():])
                if isinstance(obj, (dict, list)):
                    return "mixed_text_json"
            except ValueError:
                pass
        return "plain_text"


def shape(value):
    if isinstance(value, dict):
        return {k: shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return {"list_item_shapes": sorted({json.dumps(shape(v), ensure_ascii=False, sort_keys=True) for v in value})}
    return type(value).__name__


def completeness_inventory(data):
    """All dictionary paths, including widget defaults; absence != invalidity."""
    parents, states, paths = Counter(), Counter(), set()
    samples = {}
    def visit(value, path):
        if isinstance(value, dict):
            parents[path] += 1
            for key, child in value.items():
                child_path = path + "." + key
                paths.add((path, child_path))
                state = "null" if child is None else "empty_string" if isinstance(child, str) and not child.strip() else "empty_container" if isinstance(child, (list, dict)) and not child else "nonempty"
                states[(child_path, state)] += 1
                samples.setdefault(child_path, snippet(child))
                visit(child, child_path)
        elif isinstance(value, list):
            for child in value:
                visit(child, path + "[]")
    visit(data, "root")
    rows = []
    for parent, path in sorted(paths):
        counts = {s: states[(path, s)] for s in ["null", "empty_string", "empty_container", "nonempty"]}
        total = sum(counts.values())
        rows.append(dict(path=path, parent_objects=parents[parent], present=total,
                         absent=parents[parent] - total, **counts, example=samples[path]))
    return pd.DataFrame(rows)


def language(s):
    arabic = len(re.findall(r"[\u0621-\u064a\u067e\u0686\u0698\u06af\u06a9\u06cc]", s))
    latin = len(re.findall(r"[a-zA-Z]", s))
    if arabic + latin < 8 or content_kind(s) == "valid_json":
        return "unknown"
    if min(arabic, latin) / (arabic + latin) >= .15:
        return "mixed"
    if arabic > latin:
        # Arabic script is not language proof. Persian markers strengthen fa.
        return "fa_likely" if re.search(r"[پچژگکی]|\b(من|است|را|برای|می)\b", s) else "arabic_script_uncertain"
    return "latin_likely"


def request_features(m, history):
    s = m["normalized_content"]
    code = bool(re.search(r"```|\b(def |class |import |SELECT |function\s|console\.|print\()", s, re.I))
    coding_intent = bool(code or re.search(r"کدنویسی|دیباگ|برنامه نویسی|\b(?:python|javascript|debug|api|sql)\b|کد.*(?:بنویس|اصلاح|خطا)", s, re.I))
    has_json = m["content_kind"] in {"valid_json", "mixed_text_json", "invalid_json_like"}
    url = bool(re.search(r"https?://", s))
    formula = bool(re.search(r"\$[^$]+\$|\\(?:frac|sum|int)|\b\w+\s*[=<>]\s*\d+", s))
    table = bool(re.search(r"\|.+\||جدول|csv|اکسل", s, re.I))
    output = bool(re.search(r"json|جی سان|فقط|قالب|فرمت|حداکثر|بدون توضیح|به صورت جدول", s, re.I))
    context = bool(m.get("prior_visible_input", False) or (history and (len(s.split()) <= 5 or re.search(r"قبلی|ادامه|همان|همون|این مورد|بیشتر|اون|آن", s))))
    multi = bool(re.search(r"مرحله|گام|اثبات|استدلال|مقایسه|تحلیل|ابتدا.*سپس", s))
    specialist = bool(re.search(r"بیماری|درد|بارداری|قاعدگی|پریود|درمان|سرطان|حقوقی|قرارداد|سرمایه|مالیات", s))
    support = bool(re.search(r"پشتیبانی|حساب|پرداخت|شکایت|ورود|ثبت نام|کیف پول", s))
    creative = bool(re.search(r"بنویس|تولید محتوا|داستان|شعر|کپشن|ترجمه|عنوان جدید|متن جدید|لحن انتخابی", s))
    transform = bool(re.search(r"استخراج|تبدیل|خلاصه|دسته بندی|مرتب کن", s))
    multimodal = m["attachment_count"] > 0
    labels = [name for name, flag in [("multimodal", multimodal), ("coding", coding_intent), ("multi_step", multi), ("specialist", specialist), ("support", support), ("data_transform", transform), ("content_generation", creative)] if flag]
    kind = labels[0] if labels else "general"
    # Length and JSON do not contribute to difficulty score.
    evidence = int(coding_intent) + int(multi) + int(formula) + int(output and (coding_intent or transform))
    if len(re.findall(r"[\w\u0600-\u06ff]", s)) < 8 or multimodal or (context and not labels) or m["content_kind"] in {"valid_json", "invalid_json_like"}:
        complexity = "uncertain"
    elif multi and (coding_intent or formula) or evidence >= 3:
        complexity = "high"
    elif evidence or specialist or context or transform:
        complexity = "medium"
    else:
        complexity = "low"
    personal = bool(re.search(r"\[[A-Z_]+\]|شماره|کد ملی|حسابم|وضعیت.*من|اطلاعات.*من|بارداری|پریود", s))
    sensitive_time = bool(re.search(r"امروز|اکنون|الان|قیمت|موجودی|آخرین|روز جاری", s))
    greeting = bool(re.fullmatch(r"(?:سلام|درود|hi|hello|سلام خوبی)[ !؟?.]*", s, re.I))
    return dict(language=language(s), has_code=code, coding_intent=coding_intent, has_json=has_json, has_url=url,
                has_formula=formula, has_table=table, output_constraint=output,
                needs_context=context, request_type=kind, request_type_labels=";".join(labels),
                complexity_heuristic=complexity, complexity_evidence=evidence,
                personal_or_stateful=personal, time_sensitive=sensitive_time,
                is_greeting=greeting, is_very_short=len(s.split()) <= 3,
                prior_visible_input=m.get("prior_visible_input", False),
                history_chars=len(history), history_words=len(history.split()))


def flatten(data):
    issues, rows, sessions, schema = [], [], [], Counter()
    def issue(scope, key, idx, code, field="", value=""):
        issues.append(dict(scope=scope, session_key=key, message_index=idx, issue=code, field=field, sample=snippet(value)))
    def walk(v, path):
        schema[(path, type(v).__name__)] += 1
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, path + "." + k)
        elif isinstance(v, list):
            for x in v:
                walk(x, path + "[]")
    walk(data, "root")
    def check(obj, required, scope, key, idx):
        for f in required:
            if f not in obj:
                issue(scope, key, idx, "missing", f)
        for f, v in obj.items():
            if v is None:
                issue(scope, key, idx, "null", f)
            elif isinstance(v, str) and not v.strip():
                issue(scope, key, idx, "empty_string", f)
    if not isinstance(data, list):
        raise ValueError("Expected a top-level list of groups")
    for gi, g in enumerate(data):
        if not isinstance(g, dict) or not isinstance(g.get("sessions"), list):
            issue("group", f"g{gi}", None, "invalid_structure", "sessions", g)
            continue
        check(g, ["category", "sessions"], "group", f"g{gi}", None)
        for si, s in enumerate(g["sessions"]):
            key = f"g{gi}_s{si}"
            if not isinstance(s, dict):
                issue("session", key, None, "invalid_structure", "session", s)
                continue
            check(s, ["session_id", "created_at", "session_len", "user_turns", "bot_turns", "messages"], "session", key, None)
            for f in ["session_len", "user_turns", "bot_turns"]:
                if type(s.get(f)) is not int:
                    issue("session", key, None, "invalid_type", f, s.get(f))
            if not isinstance(s.get("session_id"), str):
                issue("session", key, None, "invalid_type", "session_id", s.get("session_id"))
            created, cz = parse_time(s.get("created_at"))
            if cz == "invalid":
                issue("session", key, None, "invalid_timestamp", "created_at", s.get("created_at"))
            msgs = s.get("messages", [])
            if not isinstance(msgs, list):
                issue("session", key, None, "invalid_structure", "messages", msgs)
                msgs = []
            actual = Counter(m.get("role") for m in msgs if isinstance(m, dict))
            sr = dict(session_key=key, group_index=gi, category=g.get("category"), session_id=s.get("session_id"),
                      created_at_raw=s.get("created_at"), created_at=created, timezone=cz,
                      reported_session_len=s.get("session_len"), actual_message_count=len(msgs),
                      reported_user_turns=s.get("user_turns"), reported_bot_turns=s.get("bot_turns"),
                      actual_user_turns=actual["user"], actual_bot_turns=actual["bot"],
                      transcript_hash=digest(msgs), content_session_hash=digest([(m.get("role"), m.get("content")) for m in msgs if isinstance(m, dict)]))
            for f, n in [("session_len", len(msgs)), ("user_turns", actual["user"]), ("bot_turns", actual["bot"])]:
                if s.get(f) != n:
                    issue("session", key, None, "count_mismatch", f, f"reported={s.get(f)} actual={n}")
            previous_time, previous_role = pd.NaT, None
            for i, m in enumerate(msgs):
                if not isinstance(m, dict):
                    issue("message", key, i, "invalid_structure", "message", m)
                    continue
                check(m, ["role", "content", "timestamp"] + (["model", "provider", "instructions"] if m.get("role") == "bot" else []), "message", key, i)
                role = m.get("role")
                if role not in {"user", "bot"}:
                    issue("message", key, i, "unexpected_role", "role", role)
                for f in ["role", "content", "timestamp"] + (["model", "provider", "instructions"] if role == "bot" else []):
                    if m.get(f) is not None and not isinstance(m[f], str):
                        issue("message", key, i, "invalid_type", f, type(m[f]).__name__)
                t, tz = parse_time(m.get("timestamp"))
                if tz == "invalid":
                    issue("message", key, i, "invalid_timestamp", "timestamp", m.get("timestamp"))
                if pd.notna(t) and pd.notna(previous_time) and t < previous_time:
                    issue("message", key, i, "nonmonotonic_timestamp", "timestamp", m.get("timestamp"))
                if pd.notna(t) and pd.notna(created) and t < created:
                    issue("message", key, i, "before_session_created", "timestamp", m.get("timestamp"))
                if previous_role == role:
                    issue("message", key, i, "consecutive_role", "role", role)
                previous_time, previous_role = t, role
                raw = text(m.get("content"))
                kind = content_kind(m.get("content"))
                if kind in {"invalid_json_like", "mixed_text_json"}:
                    issue("message", key, i, kind, "content", raw)
                rag = m.get("rag")
                if "rag" in m and rag is not None and not isinstance(rag, dict):
                    issue("message", key, i, "invalid_structure", "rag", rag)
                if isinstance(rag, dict):
                    check(rag, ["query", "context"], "rag", key, i)
                    if not isinstance(rag.get("query"), str) or not isinstance(rag.get("context"), (str, list)):
                        issue("message", key, i, "invalid_structure", "rag_fields", rag)
                rc = rag.get("context") if isinstance(rag, dict) else None
                context_text = "\n".join(text(x) for x in rc) if isinstance(rc, list) else text(rc)
                a = m.get("attachments")
                att = a if isinstance(a, list) else ([a] if isinstance(a, dict) else [])
                if "attachments" in m and a is not None and not isinstance(a, (dict, list)):
                    issue("message", key, i, "invalid_structure", "attachments", a)
                for item in att:
                    if not isinstance(item, dict):
                        issue("message", key, i, "invalid_structure", "attachment_item", item)
                    else:
                        check(item, ["contentType", "content"], "attachment", key, i)
                instruction = text(m.get("instructions"))
                r = dict(session_key=key, category=g.get("category"), session_id=s.get("session_id"), message_index=i,
                         role=role, raw_content=raw, normalized_content=normalize(raw), content_storage_type=type(m.get("content")).__name__,
                         content_kind=kind, timestamp_raw=m.get("timestamp"), timestamp=t, timezone=tz,
                         chars=len(raw), words=len(raw.split()), model=m.get("model"), provider=m.get("provider"),
                         instructions_raw=instruction, instructions_chars=len(instruction), instructions_words=len(instruction.split()),
                         instructions_hash=digest(instruction) if instruction else "", rag_context_raw=context_text,
                         rag_context_chars=len(context_text), rag_query=text(rag.get("query")) if isinstance(rag, dict) else "",
                         rag_context_hash=digest(context_text) if context_text else "",
                         has_rag="rag" in m, has_input="input" in m, has_attachments="attachments" in m,
                         input_raw=text(m.get("input")), input_shape=text(shape(m.get("input"))) if "input" in m else "",
                         rag_shape=text(shape(rag)) if "rag" in m else "", attachments_raw=text(a),
                         attachments_shape=text(shape(a)) if "attachments" in m else "", attachment_count=len(att),
                         attachment_types=";".join(text(x.get("contentType")) for x in att if isinstance(x, dict)),
                         placeholders=";".join(re.findall(r"\[[A-Z][A-Z_0-9]*\]", raw)),
                         raw_message_hash=digest(m), content_hash=digest(raw), normalized_hash=digest(normalize(raw)))
                rows.append(r)
            bot_msgs = [m for m in msgs if isinstance(m, dict) and m.get("role") == "bot"]
            sr["distinct_models"] = len({m.get("model") for m in bot_msgs if m.get("model")})
            sr["distinct_providers"] = len({m.get("provider") for m in bot_msgs if m.get("provider")})
            sr["model_switches"] = sum(a.get("model") != b.get("model") for a, b in zip(bot_msgs, bot_msgs[1:]))
            sr["provider_switches"] = sum(a.get("provider") != b.get("provider") for a, b in zip(bot_msgs, bot_msgs[1:]))
            sr["instruction_changes"] = sum(a.get("instructions") != b.get("instructions") for a, b in zip(bot_msgs, bot_msgs[1:]))
            times = [parse_time(m.get("timestamp"))[0] for m in msgs if isinstance(m, dict)]
            times = [t for t in times if pd.notna(t)]
            sr["first_message_at"] = min(times) if times else pd.NaT
            sr["last_message_at"] = max(times) if times else pd.NaT
            sr["created_to_first_message_seconds"] = (sr["first_message_at"] - created).total_seconds() if times and pd.notna(created) else np.nan
            sessions.append(sr)
    S, M = pd.DataFrame(sessions), pd.DataFrame(rows)
    for (category, sid), subset in S.groupby(["category", "session_id"], dropna=False):
        for key in subset.session_key.iloc[1:]:
            issue("session", key, None, "duplicate_id_within_group", "session_id", sid)
    for sid, subset in S.groupby("session_id", dropna=False):
        if subset.category.nunique() > 1:
            for key in subset.session_key:
                issue("session", key, None, "duplicate_id_across_groups", "session_id", sid)
    for col, label in [("transcript_hash", "duplicate_session_exact"), ("content_session_hash", "duplicate_session_content")]:
        for r in S[S.duplicated(col)].itertuples():
            issue("session", r.session_key, None, label, col, getattr(r, col))
    for col, label in [("raw_message_hash", "duplicate_message_exact"), ("content_hash", "duplicate_message_content")]:
        for r in M[M.duplicated(["role", col])].itertuples():
            issue("message", r.session_key, r.message_index, label, "content", r.raw_content)
    P, pairing_issues = pair_requests(M)
    issues.extend(pairing_issues)
    Q = pd.DataFrame(issues, columns=["scope", "session_key", "message_index", "issue", "field", "sample"])
    schema_df = pd.DataFrame([dict(path=p, type=t, count=n) for (p, t), n in sorted(schema.items())])
    return S, M, P, Q, schema_df


def pair_requests(M):
    pairs, issues = [], []
    for key, frame in M.groupby("session_key", sort=False):
        records = frame.to_dict("records")
        for j, r in enumerate(records):
            if r["role"] == "bot" and not any(x["role"] == "user" for x in records[:j]):
                issues.append(dict(scope="message", session_key=key, message_index=r["message_index"], issue="orphan_response", field="role", sample=snippet(r["raw_content"])))
            if r["role"] != "user":
                continue
            # All user messages in a consecutive block point to the following bot block.
            # This preserves requests, but is explicitly ambiguous and never doubles costs.
            end = j + 1
            while end < len(records) and records[end]["role"] == "user":
                end += 1
            start = j
            while start > 0 and records[start - 1]["role"] == "user":
                start -= 1
            bots = []
            k = end
            while k < len(records) and records[k]["role"] == "bot":
                bots.append(records[k])
                k += 1
            history = "\n".join(x["role"] + ": " + x["raw_content"] for x in records[:j])
            prevbots = [x for x in records[:j] if x["role"] == "bot"]
            r = dict(r, prior_visible_input=bool(prevbots and prevbots[-1]["has_input"]))
            first = bots[0] if bots else None
            ambiguous = end - start > 1 or len(bots) > 1
            status = "unanswered" if not bots else ("ambiguous_block" if ambiguous else "paired")
            if not bots:
                issues.append(dict(scope="request", session_key=key, message_index=r["message_index"], issue="unanswered_request", field="role", sample=snippet(r["raw_content"])))
            delta = (first["timestamp"] - r["timestamp"]).total_seconds() if first and pd.notna(first["timestamp"]) and pd.notna(r["timestamp"]) else np.nan
            metadata_history = [{k: x[k] for k in ["role", "message_index", "input_raw", "attachments_raw"]} for x in records[:j] if x["has_input"] or x["has_attachments"]]
            p = dict(session_key=key, category=r["category"], session_id=r["session_id"], message_index=r["message_index"],
                     request_raw=r["raw_content"], request_normalized=r["normalized_content"], request_timestamp=r["timestamp"],
                     request_timezone=r["timezone"], request_chars=r["chars"], request_words=r["words"],
                     history_raw=history, history_hash=digest([history, metadata_history]), status=status, ambiguous=ambiguous,
                     history_metadata_raw=text(metadata_history), history_has_attachments=any(x["has_attachments"] for x in records[:j]),
                     preceding_user_block_size=end - start, response_count=len(bots),
                     response_indices=text([x["message_index"] for x in bots]), response_raw="\n".join(x["raw_content"] for x in bots),
                     response_chars=sum(x["chars"] for x in bots), response_model=first["model"] if first else None,
                     response_provider=first["provider"] if first else None, response_timestamp=first["timestamp"] if first else pd.NaT,
                     response_instructions_chars=first["instructions_chars"] if first else 0,
                     response_instructions_hash=first["instructions_hash"] if first else "",
                     response_rag_context_chars=first["rag_context_chars"] if first else 0,
                     response_rag_hash=first["rag_context_hash"] if first else "",
                     prior_instruction_hash=prevbots[-1]["instructions_hash"] if prevbots else "",
                     attachment_count=r["attachment_count"], attachment_types=r["attachment_types"],
                     has_input=r["has_input"], input_raw=r["input_raw"], attachments_raw=r["attachments_raw"],
                     delta_seconds_proxy=delta, timezone_comparable=bool(first and first["timezone"] == r["timezone"]))
            p.update(request_features(r, history))
            pairs.append(p)
    return pd.DataFrame(pairs), issues


def describe_numeric(S, M, P):
    tables = []
    def summarize(df, group, cols, unit):
        for keys, sub in df.groupby(group, dropna=False) if group else [("all", df)]:
            for col in cols:
                v = pd.to_numeric(sub[col], errors="coerce").dropna()
                if v.empty:
                    continue
                q1, q3 = v.quantile([.25, .75])
                tables.append(dict(unit=unit, group="/".join(map(str, keys)) if isinstance(keys, tuple) else str(keys),
                                   grouping="+".join(group) if group else "all", metric=col, n=len(v), mean=v.mean(),
                                   median=v.median(), p90=v.quantile(.9), p95=v.quantile(.95), min=v.min(), max=v.max(),
                                   iqr_outliers=int(((v < q1 - 1.5 * (q3 - q1)) | (v > q3 + 1.5 * (q3 - q1))).sum())))
    for group in [[], ["category"]]:
        summarize(S, group, ["actual_message_count", "actual_user_turns", "actual_bot_turns"], "session")
    for group in [[], ["role"], ["category", "role"], ["model"], ["provider"]]:
        source = M[M.role == "bot"] if group in [["model"], ["provider"]] else M
        summarize(source, group, ["chars", "words"], "message")
        summarize(M[M.role == "bot"], group, ["instructions_chars"], "bot")
        summarize(M[M.has_rag], group, ["rag_context_chars"], "rag_message")
    for group in [[], ["category"], ["response_model"], ["response_provider"]]:
        summarize(P, group, ["request_chars", "request_words", "history_chars"], "request_historical_response_group")
    return pd.DataFrame(tables)


def text_profiles(M, root):
    stop = set("از به با در را و که این آن یک برای است هست من شما ما می یا هم تا اگر on the a and to of is in it you".split())
    corpora = {
        "user_content": M[M.role == "user"].raw_content.tolist(),
        "bot_content": M[M.role == "bot"].raw_content.tolist(),
        "instructions_unique": M[M.instructions_chars.gt(0)].drop_duplicates("instructions_hash").instructions_raw.tolist(),
        "rag_context_unique": M[M.rag_context_chars.gt(0)].drop_duplicates("rag_context_hash").rag_context_raw.tolist(),
    }
    rows = []
    for corpus, docs in corpora.items():
        frequency, document_frequency = Counter(), Counter()
        for doc in docs:
            words = [w.lower() for w in re.findall(r"[^\W\d_]{2,}", normalize(doc), re.UNICODE) if w.lower() not in stop]
            frequency.update(words)
            document_frequency.update(set(words))
        for word, df in document_frequency.most_common(30):
            rows.append(dict(corpus=corpus, term=word, documents=df, corpus_documents=len(docs), occurrences=frequency[word]))
    terms = pd.DataFrame(rows)
    terms.to_csv(root / "outputs/text_terms.csv", index=False, encoding="utf-8-sig")
    return terms


def cache_analysis(P, root):
    texts = P.request_normalized.fillna("").tolist()
    eligible = (~P.is_greeting & ~P.is_very_short & ~P.personal_or_stateful & ~P.time_sensitive &
                ~P.needs_context & ~P.history_has_attachments & (P.attachment_count == 0) & ~P.has_input & P.request_normalized.str.len().gt(0))
    P["cache_text_eligible"] = eligible
    # Global vocabulary is used ONLY for exploratory similarity, not chronological replay.
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
    X = vectorizer.fit_transform([s or " " for s in texts])
    similarities = (X @ X.T).toarray()
    examples = []
    for i in range(len(P)):
        for j in range(i):
            score = similarities[i, j]
            if score >= .65:
                a, b = P.iloc[j], P.iloc[i]
                examples.append(dict(a_session=a.session_key, a_index=a.message_index, b_session=b.session_key, b_index=b.message_index,
                                     similarity=score, exact_normalized=texts[i] == texts[j],
                                     different_history=a.history_hash != b.history_hash,
                                     different_instruction=a.response_instructions_hash != b.response_instructions_hash,
                                     different_rag=a.response_rag_hash != b.response_rag_hash,
                                     different_answer=a.response_raw != b.response_raw,
                                     a_text=snippet(a.request_raw), b_text=snippet(b.request_raw),
                                     a_response=snippet(a.response_raw), b_response=snippet(b.response_raw)))
    E = pd.DataFrame(examples, columns=["a_session", "a_index", "b_session", "b_index", "similarity", "exact_normalized", "different_history", "different_instruction", "different_rag", "different_answer", "a_text", "b_text", "a_response", "b_response"])
    E.to_csv(root / "outputs/cache_candidates.csv", index=False, encoding="utf-8-sig")
    replay = []
    # Requests at tied timestamps are simultaneous: responses must precede the lookup strictly.
    for idx in P.sort_values(["request_timestamp", "session_key", "message_index"], kind="stable").index:
        current = P.loc[idx]
        if pd.isna(current.request_timestamp) or not eligible.loc[idx]:
            replay.append(dict(index=idx, max_similarity=0., strict_similarity=0., candidate_count=0))
            continue
        previous = P[(P.response_timestamp < current.request_timestamp) & eligible & (P.status == "paired") &
                     P.timezone_comparable & (P.request_timezone == current.request_timezone)]
        if previous.empty:
            replay.append(dict(index=idx, max_similarity=0., strict_similarity=0., candidate_count=0))
            continue
        # Fit only on completed previous requests. No future IDF or response features in query.
        v = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        xp = v.fit_transform(previous.request_normalized)
        sim = (v.transform([current.request_normalized]) @ xp.T).toarray()[0]
        # A toy context-aware key, with category as proxy for domain and PREVIOUS instructions.
        strict = ((previous.category == current.category) & (previous.history_hash == current.history_hash) &
                  (previous.prior_instruction_hash == current.prior_instruction_hash) &
                  previous.prior_instruction_hash.ne("") & bool(current.prior_instruction_hash))
        best = previous.iloc[int(sim.argmax())]
        replay.append(dict(index=idx, max_similarity=float(sim.max()), strict_similarity=float(sim[strict.to_numpy()].max()) if strict.any() else 0., candidate_count=len(previous),
                           matched_session_key=best.session_key, matched_message_index=best.message_index,
                           matched_response_available_at=best.response_timestamp))
    R = pd.DataFrame(replay).set_index("index").reindex(P.index)
    P["prior_cache_max_similarity"] = R.max_similarity
    P["prior_cache_strict_similarity"] = R.strict_similarity
    trace = P[["session_key", "message_index", "request_timestamp", "cache_text_eligible"]].join(R)
    trace.to_csv(root / "outputs/cache_replay_trace.csv", index=False, encoding="utf-8-sig")
    T = pd.DataFrame([dict(threshold=t, requests=len(P), eligible=int(eligible.sum()),
                           text_only_hits=int((R.max_similarity >= t).sum()),
                           simulated_hit_rate=float((R.max_similarity >= t).mean()),
                           strict_proxy_hits=int((R.strict_similarity >= t).sum()),
                           strict_proxy_rate=float((R.strict_similarity >= t).mean())) for t in [.7, .8, .9, .95, 1.0 - 1e-9]])
    T.to_csv(root / "outputs/cache_thresholds.csv", index=False, encoding="utf-8-sig")
    return T, E


def costs(P, M, root, prices_path):
    prices = json.loads(Path(prices_path).read_text(encoding="utf-8"))
    # Only unambiguous matched requests. Unanswered/orphan/ambiguous workload excluded explicitly.
    work = P[P.status == "paired"].copy()
    cpt = prices["characters_per_token"]
    for component, col in [("request", "request_chars"), ("history", "history_chars"), ("instructions", "response_instructions_chars"), ("rag", "response_rag_context_chars"), ("output", "response_chars")]:
        work[component + "_tokens_estimate"] = work[col] / cpt
    work["input_tokens_estimate"] = work[[x + "_tokens_estimate" for x in ["request", "history", "instructions", "rag"]]].sum(axis=1)
    work["economy_usd_estimate"] = (work.input_tokens_estimate * prices["economy_input_per_million"] + work.output_tokens_estimate * prices["economy_output_per_million"]) / 1e6
    work["premium_usd_estimate"] = (work.input_tokens_estimate * prices["premium_input_per_million"] + work.output_tokens_estimate * prices["premium_output_per_million"]) / 1e6
    # Conservative illustrative routing policy: only low -> economy.
    low = work.complexity_heuristic.eq("low")
    routed = np.where(low, work.economy_usd_estimate, work.premium_usd_estimate)
    classifier = prices["classifier_per_request"]
    retrieval = prices["retrieval_per_request"] * (work.response_rag_context_chars > 0).astype(int)
    lookup = prices["embedding_per_request"] + prices["cache_lookup_per_request"]
    hit = work.prior_cache_max_similarity.ge(.9)
    esc = prices["escalation_rate"]
    sums = {
        "premium_all": (work.premium_usd_estimate + retrieval).sum(),
        "economy_all": (work.economy_usd_estimate + retrieval).sum(),
        "feature_routing": (routed + classifier + retrieval).sum(),
        "routing_text_cache_simulated": (lookup + np.where(hit, 0, routed + classifier + retrieval)).sum(),
        "cascade_expected": (work.economy_usd_estimate + retrieval + classifier + prices["judge_per_cascade_request"] + esc * (work.premium_usd_estimate + retrieval)).sum(),
    }
    C = pd.DataFrame([dict(scenario=k, requests=len(work), total_usd_estimate=v, mean_usd_estimate=v / len(work) if len(work) else np.nan,
                           assumptions_status=prices["status"]) for k, v in sums.items()])
    sensitivity = []
    for scale in [.5, 1., 2.]:
        for hit_rate in [0., .1, .3, .5]:
            for rate in [0., .1, .2, .5, 1.]:
                sensitivity.append(dict(price_multiplier=scale, assumed_hit_rate=hit_rate, escalation_rate=rate,
                                        cascade_cache_expected_usd=len(work) * lookup + (1 - hit_rate) * (scale * (work.economy_usd_estimate.sum() + rate * work.premium_usd_estimate.sum()) + (1 + rate) * retrieval.sum() + len(work) * (classifier + prices["judge_per_cascade_request"]))))
    sensitivity = pd.DataFrame(sensitivity)
    sensitivity.to_csv(root / "outputs/cost_sensitivity.csv", index=False, encoding="utf-8-sig")
    work.to_csv(root / "outputs/token_cost_estimates.csv", index=False, encoding="utf-8-sig")
    C.to_csv(root / "outputs/cost_scenarios.csv", index=False, encoding="utf-8-sig")
    return C, sensitivity, prices


def figures(S, M, P, T, C, sensitivity, root):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
    import arabic_reshaper
    from bidi.algorithm import get_display
    sns.set_theme(style="whitegrid", font="DejaVu Sans")
    plt.rcParams["axes.unicode_minus"] = False
    interpretations = []
    def save(name, interpretation):
        plt.tight_layout()
        plt.savefig(root / "reports/figures" / (name + ".png"), dpi=160, bbox_inches="tight")
        plt.close()
        interpretations.append((name, interpretation))
    def start(width=10, height=5):
        plt.figure(figsize=(width, height))
    start()
    sns.histplot(data=S, x="actual_message_count", hue="category", discrete=True, multiple="stack")
    plt.xlabel("Messages per session")
    save("01_session_length", "طول نشست ظرفیت history budget را تعیین می‌کند؛ تعداد پیام معیار پیچیدگی درخواست نیست.")
    start(12, 5)
    sns.boxplot(data=M, x="category", y="chars", hue="role")
    plt.yscale("symlog", linthresh=10)
    save("02_message_lengths", "مقیاس طول به نقش و کاربرد وابسته است؛ سقف متن و سیاست خلاصه‌سازی تاریخچه باید جداگانه تعیین شوند.")
    fig, ax = plt.subplots(1, 2, figsize=(15, 7))
    M[M.role == "bot"].model.fillna("UNKNOWN").value_counts().plot.barh(ax=ax[0], title="Recorded model")
    M[M.role == "bot"].provider.fillna("UNKNOWN").value_counts().plot.barh(ax=ax[1], title="Recorded provider")
    save("03_models_providers", "فراوانی مدل استفاده تاریخی را نشان می‌دهد، نه مطلوبیت یا کیفیت مدل برای routing.")
    start(12, 9)
    b = M[M.role == "bot"]
    sns.heatmap(pd.crosstab(b.model.fillna("UNKNOWN"), b.provider.fillna("UNKNOWN")), annot=True, fmt="d", cmap="Blues")
    save("04_model_provider", "ماتریس برای تعریف registry و رفع مدل‌های null/default مفید است؛ ناسازگاری نیازمند registry رسمی است.")
    fig, ax = plt.subplots(3, 1, figsize=(13, 10))
    ts = M.timestamp.dropna()
    ts.dt.strftime("%Y-%m-%d").value_counts().sort_index().plot.bar(ax=ax[0], title="Daily message counts")
    ts.dt.strftime("%Y-%m").value_counts().sort_index().plot.bar(ax=ax[1], title="Monthly message counts")
    ts.dt.hour.value_counts().reindex(range(24), fill_value=0).plot.bar(ax=ax[2], title="Hour (recorded clock; timezone unverified)")
    save("05_time", "این نمودار زمان ثبت نمونه را توصیف می‌کند؛ timezone نامشخص مانع نتیجه‌گیری درباره ساعت اوج محلی تولید است.")
    start()
    M.groupby("category")[["has_rag", "has_input", "has_attachments"]].mean().mul(100).plot.bar(ax=plt.gca())
    plt.ylabel("% of messages with field")
    save("06_capabilities", "حضور فیلد با دسترس‌پذیری آن پیش از routing یکسان نیست؛ RAG ثبت‌شده روی bot نیازمند retrieval-first است.")
    fig, ax = plt.subplots(1, 3, figsize=(17, 5))
    P[["has_code", "has_json", "has_url", "has_formula", "has_table", "output_constraint", "needs_context"]].mean().mul(100).plot.barh(ax=ax[0])
    P.complexity_heuristic.value_counts().reindex(["low", "medium", "high", "uncertain"], fill_value=0).plot.bar(ax=ax[1], title="Heuristic complexity")
    P.language.value_counts().plot.bar(ax=ax[2], title="Script-based language heuristic")
    save("07_routing_features", "ویژگی‌ها کم‌هزینه‌اند؛ uncertain باید مسیر بازبینی/مدل پیش‌فرض داشته باشد و برچسب‌ها نیازمند ارزیابی انسانی‌اند.")
    start()
    plt.plot(T.threshold, T.simulated_hit_rate, marker="o", label="text-only chronological replay")
    plt.plot(T.threshold, T.strict_proxy_rate, marker="o", label="context-key proxy replay")
    plt.legend(); plt.xlabel("Lexical cosine threshold"); plt.ylabel("Simulated hits / all requests")
    save("08_cache_threshold", "اختلاف کش متن‌محور و کلید زمینه نشان می‌دهد شباهت واژگانی به‌تنهایی شاهد قابلیت reuse پاسخ نیست.")
    start()
    valid = P[(P.status == "paired") & P.timezone_comparable & P.delta_seconds_proxy.ge(0)]
    sns.histplot(data=valid, x="delta_seconds_proxy", bins=30)
    plt.xscale("symlog", linthresh=5); plt.xlabel("Request-response logged delta (seconds), NOT API latency")
    save("09_delay_proxy", "اختلاف timestamp شامل ثبت لاگ و تأخیرهای نامعلوم است؛ برای SLA به span واقعی API و TTFT نیاز است.")
    start(12, 5)
    sns.barplot(data=C, x="scenario", y="total_usd_estimate")
    plt.xticks(rotation=18, ha="right"); plt.ylabel("Hypothetical USD; quality untested")
    save("10_cost_scenarios", "سناریوها صرفاً بودجه فرضی‌اند؛ بدون سنجش پاسخ مدل‌های جایگزین، حفظ کیفیت یا صرفه‌جویی قطعی اثبات نمی‌شود.")
    start()
    v = sensitivity[sensitivity.price_multiplier == 1.].pivot(index="escalation_rate", columns="assumed_hit_rate", values="cascade_cache_expected_usd")
    sns.heatmap(v, annot=True, fmt=".4f", cmap="YlOrRd")
    save("11_cost_sensitivity", "بودجه cascade تابع نرخ escalation و hit فرضی است و هزینه تلاش اولیه و gate در تمام missها باقی می‌ماند.")
    start()
    lengths = M[M.role == "bot"][["instructions_chars", "rag_context_chars", "chars"]].rename(columns={"chars": "response_chars"})
    sns.boxplot(data=lengths)
    plt.yscale("symlog", linthresh=10)
    save("12_payload_components", "instruction و RAG جدا از پاسخ تحلیل شده‌اند؛ payload واقعی و سیاست ارسال مجدد باید ثبت شوند.")
    start()
    plt.axis("off")
    persian = "آزمایش نمایش فارسی: تحلیل درخواست و زمینه قبلی"
    # Matplotlib >=3.11 performs native complex-text layout; legacy preprocessing
    # there would reverse/re-shape Persian twice. Older versions need the fallback.
    native_layout = tuple(int(x) for x in matplotlib.__version__.split(".")[:2]) >= (3, 11)
    visual = persian if native_layout else get_display(arabic_reshaper.reshape(persian))
    plt.text(.5, .5, visual, ha="center", fontsize=17)
    save("13_persian_render_check", "نمایش فارسی با فونت DejaVu Sans و layout بومی Matplotlib≥3.11 بررسی شد؛ نسخه‌های قدیمی از reshaper/bidi استفاده می‌کنند تا دوبار وارونه‌سازی نشود. عنوان نمودارهای تحلیلی برای خوانایی فنی انگلیسی است.")
    return interpretations


def evaluation_plan(S, P, root):
    # Whole-session union of exact normalized duplicates, excluding ubiquitous greetings/shorts.
    parent = {k: k for k in S.session_key}
    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    candidates = P[~P.is_very_short & ~P.is_greeting]
    for _, sub in candidates.groupby("request_normalized"):
        keys = sub.session_key.unique()
        for key in keys[1:]:
            parent[find(key)] = find(keys[0])
    components = sorted({find(k) for k in parent})
    rng = np.random.default_rng(SEED)
    rng.shuffle(components)
    allocation = {k: "train" if i < .6 * len(components) else "validation" if i < .8 * len(components) else "test" for i, k in enumerate(components)}
    split = S[["session_key", "session_id", "category", "created_at"]].copy()
    split["duplicate_component"] = split.session_key.map(find)
    split["proposed_split"] = split.duplicate_component.map(allocation)
    split.to_csv(root / "outputs/session_split_proposal.csv", index=False, encoding="utf-8-sig")
    # Borderline cases, preserve history in a local review file; no invented gold labels.
    review = pd.concat([sub.sample(min(10, len(sub)), random_state=SEED) for _, sub in
                        P.sort_values(["complexity_heuristic", "session_key", "message_index"]).groupby("complexity_heuristic")]).reset_index(drop=True)
    for col in ["gold_request_type", "gold_complexity", "gold_context_needed", "quality_0_to_4", "instruction_adherence_0_to_4", "context_preservation_0_to_4", "cache_reuse_safe", "reviewer", "rationale"]:
        review[col] = ""
    review.to_csv(root / "outputs/human_review_sample.csv", index=False, encoding="utf-8-sig")
    return split, review


def report(S, M, P, Q, D, T, E, C, prices, plots, doc_text, root):
    b, u = M[M.role == "bot"], M[M.role == "user"]
    n, nm, nr = len(S), len(M), len(P)
    def frac(count, denominator):
        return f"{count}/{denominator} ({100 * count / denominator:.2f}٪)" if denominator else "بدون مخرج"
    actual = {"sessions": n, "messages": nm, "user_messages": len(u), "bot_messages": len(b), "groups": S.category.nunique(),
              "rag_messages": int(M.has_rag.sum()), "input_messages": int(M.has_input.sum()), "attachment_messages": int(M.has_attachments.sum()),
              "models_non_null": b.model.nunique(), "providers_non_null": b.provider.nunique()}
    (root / "outputs/summary.json").write_text(json.dumps(actual, ensure_ascii=False, indent=2), encoding="utf-8")
    # Document comparisons are extracted from PDF, never injected into analysis counts.
    checks = []
    for field, pattern in [("sessions", r"(\d+)\s+anonymized chatbot sessions"), ("messages", r"(\d+)\s+messages in total"),
                           ("models_non_null", r"(\d+)\s+distinct models"), ("providers_non_null", r"across\s+(\d+)\s+providers"),
                           ("rag_messages", r"(\d+)\s+messages contain retrieval"), ("input_messages", r"widgets\s*\((\d+)\s+messages"),
                           ("attachment_messages", r"attachments\s*\((\d+)\s+messages")]:
        match = re.search(pattern, doc_text, re.I)
        if match:
            expected = int(match.group(1))
            checks.append(dict(metric=field, document=expected, observed=actual[field], agrees=expected == actual[field]))
    checks_df = pd.DataFrame(checks)
    checks_df.to_csv(root / "outputs/document_comparison.csv", index=False, encoding="utf-8-sig")
    counts = S.groupby("category").agg(sessions=("session_key", "size"), messages=("actual_message_count", "sum"), users=("actual_user_turns", "sum"), bots=("actual_bot_turns", "sum")).reset_index()
    counts["session_share_percent"] = counts.sessions / n * 100
    counts["message_share_percent"] = counts.messages / nm * 100
    quality = []
    for (scope, label, field), subset in Q.groupby(["scope", "issue", "field"], dropna=False):
        denom = n if scope == "session" else nr if scope == "request" else int(M.has_rag.sum()) if scope == "rag" else int(M.attachment_count.sum()) if scope == "attachment" else S.category.nunique() if scope == "group" else nm
        if scope == "message" and field in {"model", "provider", "instructions"}:
            denom = len(b)
        quality.append(dict(scope=scope, issue=label, field=field, count=len(subset), denominator=denom,
                            percent=100 * len(subset) / denom if denom else np.nan, example=subset.iloc[0]["sample"]))
    quality = pd.DataFrame(quality)
    quality.to_csv(root / "outputs/data_quality_summary.csv", index=False, encoding="utf-8-sig")
    good_proxy = P[(P.status == "paired") & P.timezone_comparable & P.delta_seconds_proxy.ge(0)]
    q1, q3 = good_proxy.delta_seconds_proxy.quantile([.25, .75])
    outliers = good_proxy[good_proxy.delta_seconds_proxy > q3 + 1.5 * (q3 - q1)]
    proxy_stats = good_proxy.delta_seconds_proxy.describe(percentiles=[.5, .9, .95]).to_frame("seconds").reset_index()
    outliers.to_csv(root / "outputs/delay_proxy_outliers.csv", index=False, encoding="utf-8-sig")
    repeated_raw = int(u.duplicated("raw_content").sum())
    repeated_norm = int(u.duplicated("normalized_content").sum())
    single = int(((S.actual_user_turns == 1) & (S.actual_bot_turns == 1)).sum())
    unanswered = int(P.status.eq("unanswered").sum())
    uncertain = int(P.complexity_heuristic.eq("uncertain").sum())
    placeholder_counts = Counter(p for s in M.placeholders for p in s.split(";") if p)
    precision_count = int(M.timestamp_raw.str.contains(r"\.", na=False).sum())
    cache90 = T.iloc[(T.threshold - .9).abs().argmin()]
    repairable, repairable_prefix = 0, 0
    for raw in M[M.content_kind == "invalid_json_like"].raw_content:
        modified = re.sub(r'(?<!")\[[A-Z][A-Z_0-9]*\](?!")', lambda m: json.dumps(m.group(0)), raw)
        try:
            json.loads(modified)
            repairable += 1
        except ValueError:
            try:
                obj, end = json.JSONDecoder().raw_decode(modified.strip())
                if isinstance(obj, (dict, list)):
                    repairable_prefix += 1
            except ValueError:
                pass
    optional = M.groupby("role")[["has_rag", "has_input", "has_attachments"]].sum().reset_index()
    optional["role_messages"] = optional.role.map(M.role.value_counts())
    attached_types = Counter(x for s in M.attachment_types for x in s.split(";") if x)
    completeness = pd.read_csv(root / "outputs/field_completeness.csv", keep_default_na=False)
    observed_fields = set()
    # Detect usage/latency fields via complete recursive schema in run(), not lexical content.
    schema_df = pd.read_csv(root / "outputs/schema_inventory.csv")
    for path in schema_df.path:
        if re.search(r"token|usage|cost|latency|ttft|duration|status_code|error|retry", path, re.I):
            observed_fields.add(path)
    text_parts = [
        "# گزارش EDA پروژه Metis-Auto\n\n**نوع تحلیل:** مشاهده محلی، heuristic قابل‌ممیزی و شبیه‌سازی با فرضیات؛ seed=" + str(SEED) + ".",
        "## ۱. خلاصه مدیریتی\n" +
        f"داده شامل **{n} نشست، {nm} پیام، {len(u)} پیام user و {len(b)} پیام bot** است. " +
        f"درخواست بی‌پاسخ: {frac(unanswered, nr)}. نشست دقیقاً یک user و یک bot: {frac(single, n)}. " +
        f"مدل غیر-null: {b.model.nunique()}؛ provider غیر-null: {b.provider.nunique()}. " +
        f"تکرار مازاد درخواست خام: {frac(repeated_raw, len(u))}؛ نرمال‌شده: {frac(repeated_norm, len(u))}. " +
        f"replay متن‌محور در آستانه ۰٫۹: {frac(int(cache90.text_only_hits), nr)}؛ proxy کلید زمینه: {int(cache90.strict_proxy_hits)}/{nr}. " +
        "این توازن نمونه، سهم واقعی ترافیک تولید را تعیین نمی‌کند. هیچ مدل جایگزین اجرا و هیچ صحت پاسخ کش ارزیابی نشده است.",
        "## ۲. سند، ساختار و کیفیت داده\n" + markdown(checks_df) + "\n\n" + markdown(counts),
        f"\nبازه پیام‌ها: **{M.timestamp.min()} تا {M.timestamp.max()}** (UTC در parser صرفاً برچسب محاسباتی برای زمان بدون timezone است). " +
        f"بازه created_at: {S.created_at.min()} تا {S.created_at.max()}. سند January–September 2026 را ذکر می‌کند؛ این نمونه پیام ثبت‌شده ژانویه/فوریه ندارد، اما بازه created_at با سند سازگار است. بنابراین اختلاف تعریف بازه پیام و ایجاد نشست باید روشن شود. " +
        "تعداد مدل‌ها null را حذف و default را یک مقدار مشاهده‌شده می‌شمارد؛ default/workflow را مدل واقعی فرض نمی‌کنیم. نام مدل در سند مثال تاریخی است، نه الزام انتخاب.",
        "### روش واحد تحلیل و جفت‌سازی\nشناسه session_key از موقعیت گروه/نشست ساخته شده تا شناسه تکراری باعث ادغام نشود. ترتیب آرایه حفظ می‌شود؛ timestamp ترتیب مکالمه را بازنویسی نمی‌کند. " +
        "هر user یک ردیف دارد. بلوک user متوالی به بلوک bot بلافاصله بعد متصل می‌شود؛ چند user یا چند bot وضعیت ambiguous_block دارند. متن تمام پاسخ‌های بلوک و اندیس‌ها حفظ می‌شوند؛ این اتصال ادعای پاسخ مستقل برای هر درخواست نیست. " +
        "user بدون بلوک پاسخ با unanswered باقی می‌ماند. bot ابتدایی در issues با orphan_response ثبت می‌شود. تاریخچه فقط شامل پیام‌های پیش از خود درخواست است. هزینه و proxy اصلی فقط از paired غیرمبهم محاسبه می‌شوند.",
        "### یافته‌های کنترل کیفیت با مخرج\n" + markdown(quality),
        "### کنترل‌های صفر و وضعیت ساختار\n" + markdown(pd.DataFrame([dict(check=label, occurrences=int(Q.issue.eq(label).sum())) for label in ["missing", "invalid_type", "invalid_structure", "duplicate_id_within_group", "duplicate_id_across_groups", "duplicate_session_exact", "duplicate_session_content", "count_mismatch", "unexpected_role", "invalid_timestamp", "nonmonotonic_timestamp", "before_session_created", "orphan_response", "unanswered_request", "consecutive_role"]])),
        "### timezone و انواع content\n" + markdown(M.groupby(["role", "timezone"]).size().reset_index(name="count")) + "\n\n" + markdown(M.groupby(["role", "content_kind"]).size().reset_index(name="count")),
        f"از {int(M.content_kind.eq('invalid_json_like').sum())} content شروع‌شونده با JSON نامعتبر، {repairable} مورد صرفاً با quote آزمایشی placeholderهای بدون quote به JSON کامل قابل parse تبدیل می‌شوند و {repairable_prefix} مورد دیگر prefix قابل parse همراه متن باقی‌مانده دارند. این تشخیص جانشین ترمیم داده نیست؛ فایل و متن خام تغییر نکرده‌اند. invalid_json_like می‌تواند متن ترکیبی با prefix معیوب نیز باشد؛ معیار صرفاً نحوی است. احتمال اثر ناشناس‌سازی بر اعتبار JSON باید هنگام ارزیابی schema جدا شود.",
        "### تنوع فیلدهای اختیاری\n" + "\n\n".join(markdown(M[M[f"has_{name}"]].groupby(f"{name}_shape").size().reset_index(name="count")) for name in ["rag", "input", "attachments"]) + "\n\n" + markdown(optional) +
        "\n**نکته زمان دسترسی:** تمام inputهای این نمونه روی bot هستند: widget خروجی‌اند، نه ورودی ساختاریافته اثبات‌شده روی درخواست جاری. RAG نیز فقط روی bot ثبت شده است. همه پیوست‌ها روی user هستند. widget قبلیِ قابل مشاهده، نشانه context در heuristic است؛ مقدار انتخاب‌شده ساختاریافته مستقلی ثبت نشده.\n\n" + markdown(pd.DataFrame(attached_types.items(), columns=["contentType", "attachments_count"])) +
        "\nمخرج نرخ حضور پیوست تعداد پیام است؛ تعداد فایل‌ها جداست. contentType مقدار IMAGE است نه MIME رسمی؛ محتوای تصویر دانلود یا ارزیابی نشده.",
        "### ممیزی فیلدهای تو در تو\n" + markdown(completeness[(completeness['null'] > 0) | (completeness.empty_string > 0) | (completeness.empty_container > 0)][["path", "parent_objects", "present", "absent", "null", "empty_string", "empty_container"]]) +
        "\nممیزی تمام مسیرها در field_completeness.csv است؛ غیبت optionalها مجاز و غیبت model روی user متناسب نقش است. null پیش‌فرض/placeholder widget الزاماً خطای داده نیست. issueها روی فیلدهای الزامی و اختلال ساختار تمرکز دارند؛ در جدول بالا مخرج parent_objects همان container مربوط است.",
        "### ناشناس‌سازی\n" + markdown(pd.DataFrame(placeholder_counts.items(), columns=["placeholder", "occurrences"])) +
        "\nplaceholder مفقودی نیست. جایگزینی نام/شناسه می‌تواند افراد مختلف را یکسان کند و کش را بیش‌برآورد کند؛ حذف اعداد و شناسه‌ها می‌تواند تشخیص پیچیدگی محاسباتی و وابستگی به وضعیت فرد را مخدوش کند. ادعای حذف PII در سند جایگزین بررسی یا شناسه tenant نیست.",
        "## ۳. توصیف طول، کاربرد و مدل\n" + markdown(D[D.grouping.isin(["all", "role"])]) +
        "\nتمام طول‌ها کاراکتر یا کلمه whitespace هستند؛ هیچ‌کدام تعداد توکن واقعی نیستند. IQR فقط پرچم توصیفی است؛ نقاط پرت حذف نشده‌اند. آمار تفکیکی کامل category/model/provider در descriptive_statistics.csv است.",
        "### مدل–provider ثبت‌شده\n" + markdown(b.groupby(["model", "provider"], dropna=False).size().reset_index(name="bot_messages")) +
        f"\nتغییر مدل در {frac(int(S.model_switches.gt(0).sum()), n)} نشست و provider در {frac(int(S.provider_switches.gt(0).sum()), n)} نشست دیده می‌شود. تغییر نام ثبت‌شده اثبات cascade/failover نیست؛ reason و attempt_id موجود نیست. " +
        f"instruction غیرخالی {frac(int(b.instructions_chars.gt(0).sum()), len(b))} پیام bot و {b[b.instructions_chars.gt(0)].instructions_hash.nunique()} نسخه hash دارد؛ در {frac(int(S.instruction_changes.gt(0).sum()), n)} نشست متن instruction تغییر می‌کند. hash متن خام نسخه رسمی policy نیست؛ متن می‌تواند اطلاعات پویا داشته باشد. " +
        "در absence registry، مدل–provider چندگانه صرفاً پرچم بازبینی است و ناسازگاری قطعی نیست.",
        f"تعداد مدل‌های ثبت‌شده با بیش از یک provider غیر-null: {int(b.groupby('model').provider.nunique().gt(1).sum())}. default/workflow: {frac(int(b.model.eq('default').sum()), len(b))}؛ dalle/imagination: {frac(int(b.model.eq('dalle').sum()), len(b))}. متن bot دقیقاً برابر Error: {frac(int(b.raw_content.str.strip().eq('Error').sum()), len(b))}؛ این نشانه متنی دلیل کافی برای نوع خطای API یا نرخ failover نیست.",
        "### تنوع instruction\n" + markdown(b.groupby("instructions_hash", dropna=False).agg(bot_messages=("role", "size"), chars=("instructions_chars", "first")).reset_index()),
        "### کاربرد گروه‌ها با شاهد متن\n" + markdown(pd.DataFrame([dict(category=cat, example=snippet(sub.iloc[0].raw_content), heuristic_types="; ".join(P[P.category == cat].request_type.value_counts().head(3).index)) for cat, sub in u.groupby("category")])) +
        "\nنمونه developer شامل اطلاعات سلامت/قاعدگی است؛ بنابراین نام دسته نقش یا هویت فرد را ثابت نمی‌کند. نوع کاربرد را باید در سطح درخواست و همراه context برچسب زد.",
        "### واژگان جداگانه\n" + markdown(pd.read_csv(root / "outputs/text_terms.csv").groupby("corpus", sort=False).head(8)) +
        "\nبرای instruction و RAG، سندهای یکتا استفاده شده‌اند تا تکرار payload واژه‌ها را مسلط نکند؛ user و bot هرکدام به‌صورت پیام مستقل‌اند. document frequency و occurrence صرفاً baseline واژگانی‌اند، نه برچسب معنا. متن instruction هرگز با پاسخ مخلوط نشده است.",
        "## ۴. پیامدهای Router\n" + markdown(P.groupby(["request_type", "complexity_heuristic"]).size().reset_index(name="requests")) +
        "\n### rubric پیشنهادی، نه حقیقت مبنا\n- low: بدون نشانه کد/فرمول/چندمرحله/تخصص/وابستگی به زمینه، متن قابل تفسیر.\n- medium: دست‌کم یک نشانه کد، فرمول، تبدیل داده، تخصص یا زمینه.\n- high: چندمرحله همراه کد/فرمول یا دست‌کم سه شاهد ترکیبی.\n- uncertain: متن بسیار کم‌اطلاع، پیوست نیازمند بررسی، یا درخواست کوتاه زمینه‌محور بدون شاهد نوع.\n" +
        f"uncertain: {frac(uncertain, nr)}؛ high: {frac(int(P.complexity_heuristic.eq('high').sum()), nr)}. نبود high با این قواعد اثبات نبود درخواست دشوار نیست. طول و JSON به‌تنهایی امتیاز دشواری ندارند؛ JSON-like مستقل بدون قابلیت روشن در uncertain قرار می‌گیرد. کم‌ریسک بودن کاربرد از این rubric نتیجه نمی‌شود. نمونه‌های مرزی در human_review_sample.csv بدون gold ذخیره شده‌اند.",
        "### زمان دسترسی ویژگی‌ها\n| مرحله | ویژگی | محدودیت |\n|---|---|---|\n| پیش از routing | متن user، history قبلی، script، طول، کد/JSON/URL/فرمول/جدول، قیود صریح، input و metadata پیوست روی user | metadata روی bot به درخواست منتسب نشده؛ زبان heuristic است |\n| بعد از retrieval در retrieval-first | query/context بازیابی، نسخه دانش و طول context | زمان retrieval و نسخه دانش در این فایل اثبات نشده |\n| فقط پس از پاسخ | پاسخ، model/provider انتخاب‌شده، instruction و RAG روی bot، delta timestamp | از router حذف شده‌اند |\n| پیش از routing با عدم‌قطعیت | hash instruction روی bot قبلی | نسخه فعال درخواست فعلی را اثبات نمی‌کند؛ فقط کلید toy cache است |",
        "## ۵. فرصت Semantic Cache\n" +
        f"تکرار مازاد user خام {frac(repeated_raw, len(u))} و نرمال‌شده {frac(repeated_norm, len(u))}؛ اثر خالص نرمال‌سازی {repeated_norm - repeated_raw} تکرار اضافه. " +
        f"تکرار مازاد پاسخ bot خام {frac(int(b.duplicated('raw_content').sum()), len(b))} و نرمال‌شده {frac(int(b.duplicated('normalized_content').sum()), len(b))}. " +
        f"سلام {frac(int(P.is_greeting.sum()), nr)}؛ بسیار کوتاه ≤۳ کلمه {frac(int(P.is_very_short.sum()), nr)}؛ هم‌پوشانی این دو وجود دارد. " +
        f"eligible متن‌محور {frac(int(P.cache_text_eligible.sum()), nr)}. ی/ک، حذف کشیده/حرکات و تبدیل نیم‌فاصله به فاصله تکرار سطحی را کم می‌کنند اما برابری معنی را تضمین نمی‌کنند.",
        "### replay زمانی\n" + markdown(T) +
        "\nهمه مخرج‌ها کل userها هستند. تنها پاسخ paired که timestamp آن strictly قبل از درخواست فعلی است قابل درج است؛ در tie پاسخ وارد کش نمی‌شود. TF-IDF char_wb 3–5 فقط بر درخواست‌های قبلاً تکمیل‌شده fit می‌شود. " +
        "این replay یک shadow-cache بدون محدودیت ظرفیت، TTL یا eviction است که همه تعاملات تاریخی eligible و تکمیل‌شده را وارد index می‌کند، حتی اگر lookup قبلی آن‌ها در شبیه‌سازی hit بود؛ اثر سیاست miss-only insertion بررسی نشده است. نزدیک‌ترین candidate و زمان دسترس‌پذیری در cache_replay_trace.csv ثبت شده است. " +
        "سلام، خیلی کوتاه، شخصی/متغیر، زمان‌حساس، وابسته به زمینه، input و پیوست از eligibility متن‌محور حذف می‌شوند. text-only عمداً دامنه/نسخه instruction/دانش را تضمین نمی‌کند. " +
        "strict_proxy علاوه بر آن category برابر (جانشین ناقص دامنه)، hash کامل تاریخچه برابر و instruction قبلی غیرخالی برابر می‌خواهد. این هم safe hit rate نیست؛ نسخه فعال instruction و دانش retrieval معلوم نیست. هیچ replay مبتنی بر صحت پاسخ انجام نشده است.",
        "### متن مشابه، زمینه متفاوت\n" + markdown(E[E.different_history & E.different_answer].sort_values(["exact_normalized", "similarity"], ascending=False).head(8)) +
        "\ncandidateهای واژگانی کل داده از TF-IDF transductive برای اکتشاف‌اند و در hit rate replay استفاده نشده‌اند. پاسخ متفاوت ممکن است صرفاً stochastic باشد؛ جدول دلیل نیاز به بازبینی زمینه است، نه اثبات تضاد. " +
        "کلید تولید باید tenant/app/domain، policy/instruction version، history یا state fingerprint، input/attachment fingerprint، retrieval corpus/version و TTL زمان‌حساس را داشته باشد؛ اغلب این‌ها اکنون موجود نیستند. embedding در اجرای پایه استفاده نشد.",
        "## ۶. هزینه و تأخیر\n" +
        f"فیلدهای ساختاری مرتبط با usage/cost/latency/error در schema: {sorted(observed_fields)}. token usage، قیمت پرداخت‌شده، TTFT، span API، شناسه تلاش و وضعیت شکست در داده ثبت نشده‌اند.\n\n" +
        markdown(proxy_stats) +
        f"\nproxy غیرمبهم و غیرمنفی {frac(len(good_proxy), nr)} درخواست؛ وضعیت ambiguous_block {frac(int(P.status.eq('ambiguous_block').sum()), nr)}؛ منفی {frac(int(P.delta_seconds_proxy.lt(0).sum()), nr)}؛ timestamp delta ناموجود {frac(int(P.delta_seconds_proxy.isna().sum()), nr)}؛ IQR upper outlier {frac(len(outliers), len(good_proxy))}. " +
        f"پرچم کلی ambiguous روی {int(P.ambiguous.sum())} درخواست است که {int((P.ambiguous & P.status.eq('unanswered')).sum())} مورد آن هم‌زمان unanswered است؛ این دو شمارش نباید جمع شوند. " +
        f"اختلاف request و نخستین response فقط proxy فاصله ثبت دو پیام است؛ TTFT/inference/API latency نیست. {precision_count}/{nm} timestamp پیام بخش اعشاری ثانیه دارد؛ دقت ثانیه‌ای مشاهده‌شده می‌تواند فاصله صفر را پنهان کند. " +
        f"created_at تا نخستین پیام در {frac(int(S.created_to_first_message_seconds.abs().gt(86400).sum()), n)} نشست بیش از یک روز فاصله دارد؛ این می‌تواند ناشی از نشست قدیمی یا transcript ناقص باشد، نه مدت inference. " +
        "timezone یکسان فرض محاسباتی است. outlierها جدا ذخیره شده و حذف پنهان نشده‌اند.",
        "### سناریوهای هزینه فرضی\n" + markdown(C) + "\n\n```json\n" + json.dumps(prices, ensure_ascii=False, indent=2) + "\n```\n" +
        f"حجم هزینه فقط {len(P[P.status == 'paired'])}/{nr} درخواست paired است؛ درخواست بی‌پاسخ، بلوک مبهم و bot یتیم حذف هزینه‌ایِ مستند دارند، نه حذف از داده. " +
        "برآورد توکن = کاراکتر/characters_per_token؛ فارسی، JSON و chat overhead ممکن است تفاوت عمده داشته باشند. request/history/instruction/RAG/output جدا در token_cost_estimates.csv ذخیره شده‌اند. " +
        "فرض payload: کل تاریخچه پیشین شامل پاسخ‌ها + درخواست جاری + instruction ثبت‌شده پاسخ + RAG ثبت‌شده همان پاسخ ارسال می‌شود. ثبت instruction اثبات ارسال مجدد نیست؛ این سناریوی full-history + instruction resend است، نه کران بالای تضمین‌شده. widget metadata، ابزارها، tokenization metadata و محتوای binary پیوست محاسبه نشده‌اند. " +
        "خروجی تاریخی به‌عنوان طول جانشین در تمام مدل‌ها ثابت است، نه پیش‌بینی output واقعی. instruction null در حجم مشاهده‌شده صفر است، نه اثبات نبود instruction در API؛ workflow و تولید تصویر نیز workload متنی معادل محسوب شده‌اند و برای قیمت واقعی باید سناریوی مجزا داشته باشند. retrieval فقط برای رخداد تاریخی RAG شارژ فرضی دارد. premium/economy هزینه classifier ندارند؛ routing دارد. " +
        "کش برای همه lookup هزینه embedding+lookup دارد و در miss classifier/retrieval/model. cache hit سناریوی متن‌محور optimistic است و validated نیست. cascade همه را ابتدا economy می‌فرستد، gate و classifier دارد، سپس نرخ فرضی escalation با premium و retrieval مجدد؛ تلاش اول حتی هنگام escalation پرداخت می‌شود. " +
        "failover rate قابل استخراج نیست؛ در production هزینه retry/خطاهای billable باید افزوده شود. قیمت‌ها فرضی‌اند و هیچ منبع/تاریخ بازار ادعا نشده است. ادعای حفظ کیفیت یا صرفه‌جویی قطعی نمی‌شود.",
        "### حساسیت\nprice multiplier={0.5,1,2}؛ hit={0,0.1,0.3,0.5}؛ escalation={0,0.1,0.2,0.5,1}. جدول کامل cost_sensitivity.csv و heatmap ضمیمه‌اند. embedding/classifier/retrieval/gate ثابت می‌مانند؛ multiplier فقط قیمت مدل را تغییر می‌دهد. " +
        "نرخ hit در این grid پارامتر فرضی مستقل از replay است؛ sensitivity سناریوی cascade+cache متفاوت از routing+cache است. برای tokens نیز با characters_per_token=2/4/6 بازاجرا کنید؛ tokenizer مدل برای تصمیم مالی لازم است.",
        "## ۷. ارزیابی آینده و داده‌های لازم\nاین داده برای audit، baseline ویژگی، تکرار واژگانی و طراحی workload کافی است؛ برای مدل بهینه، کیفیت counterfactual، نرخ failure و SLA واقعی کافی نیست.\n" +
        "- split سطح نشست الزامی است؛ session_split_proposal.csv نمونه ۶۰/۲۰/۲۰ در سطح component تکرار دقیقِ درخواست غیرکوتاه است، نه split نهایی. تعداد نشست‌ها الزاماً همین نسبت نیست؛ خوشه‌های نزدیک و multilingual باید پیش از split ممیزی و کنار هم نگه داشته شوند.\n" +
        "- آزمون زمانی بر اساس پایان نشست‌های train و شروع نشست‌های test با purge overlap و duplicate cluster؛ ارزیابی به تفکیک category و نوع درخواست با CI در سطح نشست و وزن‌های ترافیک واقعی جداگانه.\n" +
        "- human_review_sample.csv تا ۱۰ نمونه از هر سطح پیچیدگی دارد. دو داور مستقل، adjudication و agreement؛ نوع درخواست چندبرچسبی، نیاز زمینه، قابلیت‌ها و پیچیدگی با rationale.\n" +
        "- rubric کیفیت ۰ تا ۴: ۰ غلط/غیرقابل استفاده، ۱ نقص عمده، ۲ قابل استفاده با اصلاح، ۳ صحیح با نقص جزئی، ۴ صحیح و کامل؛ instruction adherence و context preservation جدا با همین مقیاس. صحت تخصصی توسط داور مناسب حوزه بررسی شود. JSON validity با parser و schema مورد انتظار، نه صرف وجود JSON.\n" +
        "- baseline router: economy-all، premium-all، قواعد حاضر و classifier انسانی‌آموزش‌دیده. baseline cache: خام، نرمال، TF-IDF و embedding با gate زمینه. baseline cascade: economy + validator deterministic (JSON/schema/constraint) + gate کیفیت کالیبره. provider failover فقط برای خطاهای transport/rate limit و cascade برای کیفیت ثبت شود.\n" +
        "- پاسخ تاریخی gold نیست؛ semantic similarity به آن معیار مستقل صحت نیست. به جای آن correctness، تبعیت، حفظ زمینه، هزینه و latency روی اجرای جفتی مدل‌ها و نمونه‌های یکسان گزارش شوند.\n" +
        "- لاگ مرحله بعد: request/trace/session/app/tenant ID، policy version، routing feature snapshot، decision reason و confidence، model resolved version، provider، attempt index/reason/status، retrieval timing+corpus version، cache key/version/TTL/hit similarity، input/output/cached/reasoning tokens، قیمت با source/date، billed cost، start/first-token/end monotonic spans و quality labels.\n" +
        "- Observability: p50/p90/p95/p99 E2E و TTFT به تفکیک مدل/نوع، classifier/retrieval overhead، answered/abandoned/error rates، escalation و failover جدا، cache hit eligible و total، sampled unsafe reuse، token/cost per successful request شامل retry و تلاش ناموفق، quality-adjusted savings و drift زبان/طول/نوع. raw متن را بی‌نیاز در dashboard منتشر نکنید.\n" +
        "- افزونه اختیاری embedding: مدل چندزبانه محلی با license/version ثابت، فایل weights از قبل فراهم، هیچ دانلود خودکار؛ replay فقط index قبلی و gate دامنه/زمینه با برچسب reuse انسانی. LLM-as-a-judge اختیاری با credentials و بودجه جدا، rubric ثابت، blind model names و calibration انسانی؛ judge به محتوای گفتگو دستور اجرایی ندهد.",
        "## ۸. نمودارها و تفسیر طراحی\n" + "\n\n".join(f"### {name}\n![{name}](figures/{name}.png)\n\n{interpretation}" for name, interpretation in plots),
        "## ۹. محدودیت‌ها و اولویت‌ها\nنمونه کوچک و عمداً متوازن است؛ برآورد جامعه یا سود تجاری از آن مجاز نیست. language/intent/context/complexity regex دارای false positive/negative است؛ JSON معتبر صرفاً نحوی است. پیوست‌ها فقط metadata و هیچ URL دانلود نشده است. " +
        "نرمال‌سازی متن با حفاظت نسخه خام همراه است. raw خروجی محلی می‌تواند URL امضاشده داشته باشد؛ در Markdown، نمونه‌های quality و candidateها query string حذف شده است.\n\n" +
        "**P0:** رفع ابهام schema/model null، ثبت trace و timing/usage/policy version؛ برچسب‌گذاری rubric و schema خروجی. **P1:** benchmark مدل‌ها با split بدون نشت و quality gate؛ کش با کلید tenant/state و TTL؛ registry قابلیت‌ها. **P2:** کالیبراسیون cascade، replay وزن‌دار تولید و pricing واقعی/داشبورد.",
        "## جدول نهایی تصمیم\n| یافته | شاهد عددی | پیامد طراحی | اقدام پیشنهادی | میزان اطمینان |\n|---|---|---|---|---|\n" +
        f"| نمونه متوازن | {n} نشست؛ {S.category.nunique()} گروه؛ تعداد هر گروه در جدول بالا | سهم نمونه ≠ سهم تولید | وزن ترافیک واقعی جمع‌آوری شود | بالا، مشاهده |\n" +
        f"| درخواست بی‌پاسخ | {frac(unanswered, nr)} | عدم پاسخ را شکست API تلقی نکنید | status/abandonment ثبت شود | بالا در شمارش؛ کم در علت |\n" +
        f"| پیچیدگی نامطمئن | {frac(uncertain, nr)} | مسیر پیش‌فرض و label انسانی لازم | rubric کالیبره شود | پایین، heuristic |\n" +
        f"| تکرار نرمال درخواست | {frac(repeated_norm, nr)} مازاد | فرصت lookup، نه پاسخ امن | gate زمینه و نسخه | بالا در تکرار؛ کم در reuse |\n" +
        f"| کش در آستانه ۰٫۹ | {frac(int(cache90.text_only_hits), nr)} متن‌محور؛ {int(cache90.strict_proxy_hits)}/{nr} با کلید زمینه | نرخ تکرار با reuse یکسان نیست | بازبینی انسانی candidateها و کلید tenant/policy | شبیه‌سازی؛ صحت نامعلوم |\n" +
        f"| instruction بزرگ | median={b.instructions_chars.median():.0f} و p95={b.instructions_chars.quantile(.95):.0f} کاراکتر | حجم payload می‌تواند از درخواست مسلط‌تر باشد | ثبت payload واقعی و budget/version instruction | بالا در طول؛ کم در توکن واقعی |\n" +
        f"| RAG ثبت‌شده | {frac(int(M.has_rag.sum()), nm)} | قابلیت retrieval جدا از router | نسخه corpus و retrieval timing | بالا، مشاهده |\n" +
        f"| مدل null | {frac(int(b.model.isna().sum()), len(b))} | انتساب هزینه/قابلیت مبهم | resolved model ثبت شود | بالا، مشاهده |\n" +
        f"| proxy timestamp | {len(good_proxy)} جفت قابل محاسبه غیرمبهم | SLA واقعی قابل نتیجه‌گیری نیست | API spans و TTFT | بالا در محدودیت |\n" +
        "| هزینه واقعی نامعلوم | usage/pricing واقعی ثبت نشده | اقتصاد فعلاً فرضی است | usage و pricing version ثبت شود | بالا در محدودیت |"
    ]
    (root / "reports/eda_report.md").write_text("\n\n".join(text_parts), encoding="utf-8")
    return actual


def run(data_path=None, pdf_path=None, output_root=None, prices_path=None):
    np.random.seed(SEED)
    root = Path(output_root or Path(__file__).resolve().parents[1]).resolve()
    data_path = resolve_input(root, "data", data_path)
    pdf_path = resolve_input(root, "pdf", pdf_path)
    prices_path = Path(prices_path or os.environ.get("METIS_PRICES_PATH", root / "config/prices.json"))
    for folder in ["outputs", "reports", "reports/figures", "notebooks"]:
        (root / folder).mkdir(parents=True, exist_ok=True)
    import fitz
    with fitz.open(pdf_path) as doc:
        doc_text = "\n".join(page.get_text() for page in doc)
    (root / "outputs/project_document.txt").write_text(doc_text, encoding="utf-8")
    data = json.loads(data_path.read_text(encoding="utf-8-sig"))
    completeness_inventory(data).to_csv(root / "outputs/field_completeness.csv", index=False, encoding="utf-8-sig")
    S, M, P, Q, schema_df = flatten(data)
    text_profiles(M, root)
    schema_df.to_csv(root / "outputs/schema_inventory.csv", index=False, encoding="utf-8-sig")
    D = describe_numeric(S, M, P)
    T, E = cache_analysis(P, root)
    C, sensitivity, prices = costs(P, M, root, prices_path)
    split, review = evaluation_plan(S, P, root)
    plots = figures(S, M, P, T, C, sensitivity, root)
    for name, df in [("sessions", S), ("messages", M), ("request_response_pairs", P), ("data_quality_issues", Q), ("descriptive_statistics", D)]:
        df.to_csv(root / "outputs" / (name + ".csv"), index=False, encoding="utf-8-sig")
    # Additional reusable traffic tables with explicit units.
    M.groupby(["category", "role"], dropna=False).size().reset_index(name="messages").to_csv(root / "outputs/category_role_counts.csv", index=False, encoding="utf-8-sig")
    for group in ["category", "model", "provider"]:
        frame = M if group == "category" else M[M.role == "bot"]
        frame.groupby(group, dropna=False).agg(messages=("role", "size"), sessions=("session_key", "nunique"),
              rag_messages=("has_rag", "sum"), input_messages=("has_input", "sum"), attachment_messages=("has_attachments", "sum"),
              rag_rate=("has_rag", "mean"), input_rate=("has_input", "mean"), attachment_rate=("has_attachments", "mean")).reset_index().to_csv(root / "outputs" / f"usage_by_{group}.csv", index=False, encoding="utf-8-sig")
    for period, series in [("daily", M.timestamp.dt.strftime("%Y-%m-%d")), ("monthly", M.timestamp.dt.strftime("%Y-%m")), ("hourly", M.timestamp.dt.hour)]:
        series.value_counts().sort_index().rename_axis(period).reset_index(name="messages").to_csv(root / "outputs" / f"traffic_{period}.csv", index=False, encoding="utf-8-sig")
    summary = report(S, M, P, Q, D, T, E, C, prices, plots, doc_text, root)
    packages = ["pandas", "numpy", "matplotlib", "seaborn", "scikit-learn", "nbformat", "nbclient", "ipykernel", "PyMuPDF", "arabic-reshaper", "python-bidi"]
    versions = {p: importlib.metadata.version(p) for p in packages}
    (root / "requirements-lock.txt").write_text("\n".join(f"{k}=={v}" for k, v in versions.items()) + "\n", encoding="utf-8")
    manifest = dict(seed=SEED, data_path=str(data_path), pdf_path=str(pdf_path), data_sha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),
                    pdf_sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(), prices_sha256=hashlib.sha256(prices_path.read_bytes()).hexdigest(),
                    versions=versions, summary=summary, figure_count=len(plots))
    (root / "outputs/run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return dict(sessions=S, messages=M, pairs=P, issues=Q, statistics=D, cache=T, cache_examples=E, costs=C,
                sensitivity=sensitivity, split=split, review=review, summary=summary, plots=plots, document=doc_text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=None)
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--prices", default=None)
    args = parser.parse_args()
    result = run(args.data, args.pdf, args.output_root, args.prices)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
