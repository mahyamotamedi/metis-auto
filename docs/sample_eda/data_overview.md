# Sample data overview

## What the file represents

`data/sample_data/raw/data.json` is a read-only JSON export containing 100 anonymized sessions and 907 messages. Its root is a list of four category objects, each with 25 sessions. The category names are treated as opaque strata; their meanings are undocumented and are not inferred here.

The parsed sample contains 465 `user` and 442 `bot` messages. The actual role names are `user` and `bot` (not `assistant`). All 100 session IDs are unique. Declared session/message/user/bot counters match the parsed records, and all message roles are one of the two observed values.

## Record structure and field inventory

| Field | Grain | Observed form and presence | Meaning / uncertainty |
|---|---|---|---|
| `category` | Category bucket | String; 4 equal groups | Opaque stratum only. |
| `session_id` | Session | String; 100/100, unique | Stable ID in this export; not exposed in saved candidate tables. |
| `created_at` | Session | Naive ISO-like timestamp; 100/100 | No timezone/clock semantics. |
| `session_len` | Session | Integer; 100/100 | Matches message-array length in this sample. |
| `user_turns`, `bot_turns` | Session | Integers; 100/100 | Both match parsed message roles in this sample. Some sessions have consecutive turns of one role. |
| `messages` | Session | List; 100/100 | Ordered message records. |
| `role` | Message | String; 907/907 | Values: `user`, `bot`. |
| `content` | Message | String; 907/907 | May contain ordinary text, serialized/structured payloads, long instructions, or other non-chat-like content. Kept in memory only for analysis. |
| `timestamp` | Message | Naive ISO-like string; 907/907 | Parses successfully; equal adjacent timestamps occur. Not an API-latency field. |
| `model`, `provider` | Bot message | 442 bot records; each has 27 null and 415 non-null | Includes `default`/`workflow` labels. Logged labels are not verified billing entities or model versions. |
| `instructions` | Bot message | 442 records; 415 non-null, 27 null | Relationship to actual provider prompt is undocumented; reported separately and excluded from request/context totals. |
| `rag` | Bot message | 71/442 bot records | Object with `query` string and `context` list; context elements observed as strings. Missing `rag` does not prove retrieval was unused. |
| `attachments` | User message | Present on 14 messages; 15 items total | Lists include `contentType` and `content`; observed content type is `IMAGE`. Payloads/URLs are not reproduced. |
| `input` | Bot message | Present on 29 records across 8 sessions | Object with `items` list. Treated only as an uncertain structured-input-configuration proxy, not proof a user used a widget. |

The full field-presence table and data dictionary are in `reports/sample_eda/tables/schema_presence.csv` and `reports/sample_eda/tables/data_dictionary.csv`.

## Time coverage and integrity observations

- Session `created_at` values range from **2026-01-14** through **2026-09-09**.
- Message timestamps range from **2026-03-02** through **2026-09-09**. Thus the sample description's January–September range applies to session creation metadata, not observed message timestamps.
- One session's creation month differs from its first message month; five sessions have an absolute created-to-first-message timestamp gap over one hour, including one where the first message precedes `created_at`. Treat time aggregates cautiously.
- Message timestamps are parseable and nondecreasing in array order for all sessions, but timestamps have no timezone suffix.
- No empty message text, duplicate session IDs, unexpected roles, or declared counter mismatches were found.
- Session message counts range from 3 to 44. Very large observed session durations are driven by timestamp gaps and should not be read as continuous active conversation time.

## Language, model, retrieval, and optional features

By a simple Unicode-script heuristic, user messages are 90.8% Persian-script (422), 6.0% English/Latin-script (28), 2.8% mixed Persian/English (13), and 0.4% other/unknown (2). This is not linguistic ground truth; Arabic and Persian share Unicode blocks and transliteration is missed.

There are 18 non-null model labels and 7 non-null provider labels, plus null values. `deepseek-v4-flash` is the most frequent model label (127 bot messages, 28.7%); `deepseek` is the most frequent provider label (129, 29.2%). The next observed labels and missing values are tabulated in the notebook and CSV outputs.

Retrieval metadata occurs on 71 bot messages across 24 sessions. The 71 context arrays contain string values; joined context lengths have a median of 1,476 characters and a maximum of 4,019. Ten contexts have exactly 4,019 characters, which may indicate a serialization/length ceiling; this needs schema-owner confirmation and is not proof of truncation.

Attachments occur in 14 user messages (15 attachment records) and the uncertain `input` proxy occurs on 29 bot records in 8 sessions. Neither should be treated as ground-truth user action without schema confirmation.

## Limitations

This is a small sample, not a production census. It has no verified exact input/output/billed tokens, prices, provider cost, request lifecycle latency, quality labels, cache outcomes, or user-selected-model field. Prompt and attachment content may be sensitive; the analysis avoids reproducing it. Embedded serialized content is not assumed to have a uniform schema and is not parsed as ground truth.
