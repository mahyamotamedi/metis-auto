# Sprint notes (local, never committed)

## S-0 test baseline (Windows, branch sprint-saba, 2026-11-01)
pytest -q: 1092 passed, 5 skipped, 0 failed, 0 collection errors (108 s).
No failing test IDs. The plan expected 33 failed + 3 collection errors; not reproduced on this tree.

## S-0 data run (2026-11-02)
- Raw data present (13 message shards). full_eda_ingest --smoke ok; full ingest ok (301 s).
- messages: 710,640 (matches ledger scope.messages). requests.parquet: 349,079 rows x 95 cols (matches AI messages). sessions 80,179, users 448, bots 1,830.
- pair_flags: clean 331,397; no_preceding_user 9,211; consecutive_user 6,928; multiple_answers 1,543.
- Database/golden-v1: BLOCKED. Port 5432 used by another postgres (pid 6700); free disk was 540 MB at preflight (preflight needs 20 GB), later 13 GB.

## Claims ledger: already answered (id = value)
- bill.state.items = 0.701833
- bill.state.empty_list = 0.297251
- bill.state.null = 0.000916698
- fee.per_call_rows = 90639
- fee.per_call_modal_amount = 0.002
- fee.per_call_modal_share = 0.975761
- fee.percall_msgs_with_rag_queries = 0.995333
- fee.corr_percall_items_rag_queries = 0.985512
- fee.messages_with_percall = 0.122443
- rag.requests_with_chunks = 0.181664
- rag.state.null = 0.557192
- rag.state.empty = 0.261027
- rag.state.ok = 0.181781
- rag.bot_configured = 0.148949
- rag.configured_with_chunks = 0.869334
- rag.unconfigured_with_chunks = 0.0613093
- rag.chunks_per_req.count = 63415
- rag.chunks_per_req.total = 994031
- rag.chunks_per_req.mean = 15.675
- rag.chunks_per_req.median = 15
- rag.chunks_per_req.p90 = 18
- rag.chunks_per_req.p95 = 18
- rag.chunks_per_req.p99 = 24
- rag.chunks_per_req.max = 115
- rag.chars_per_req.count = 63415
- rag.chars_per_req.total = 9.8429e+08
- rag.chars_per_req.mean = 15521.4
- rag.chars_per_req.median = 7440
- rag.chars_per_req.p90 = 40833.8
- rag.chars_per_req.p95 = 42395
- rag.chars_per_req.p99 = 45084.9
- rag.chars_per_req.max = 257702
- rag.chunk_rows = 994031
- rag.chunk_chars.count = 994031
- rag.chunk_chars.total = 9.8429e+08
- rag.chunk_chars.mean = 990.201
- rag.chunk_chars.median = 470
- rag.chunk_chars.p90 = 2462
- rag.chunk_chars.p95 = 2495
- rag.chunk_chars.p99 = 2529
- rag.chunk_chars.max = 53032
- rag.chunk_mode_len = 151
- rag.chunk_at_mode_len = 0.0157138
- rag.chunk_dup_rows = 0.973855
- rag.distinct_chunks = 25989
- rag.chunk_repeat_in_session = 0.612125

## DB + golden-v1 (2026-11-02)
- Postgres on host port 5433 via untracked compose.override.yaml (5432 taken by another postgres); scripts need METIS__DATABASE__PORT=5433.
- db_ingest: Run 1 ok, 2,404,351 rows, 26 reconciliation checks. users 448, chat_bot 1,830, chat_session 80,179, chat_message 710,640.
- build_eval_dataset all: golden-v1 300 records, 150 reserves. verify: PASS.
- Build rewrote tracked reports/evaluation/golden_v1/{golden_v1_shareable.jsonl,quality_report.md} (see line-ending note); do not commit.
