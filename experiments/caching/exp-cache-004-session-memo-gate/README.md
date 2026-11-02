# EXP-CACHE-004: session memo + greeting skip gate

- **Task:** final plan R-C1 (Pipeline C). **Traceability:** H-3 (retrieval reuse inside a conversation), X1 (cache candidate hits), FR-REQ-06 (no look-ahead: a decision uses only what exists before it), FR-XCACHE-01 (exact keys), FR-ACCT-02 (unknown is not zero), QA-PRIV (hashes only, local), Review Focus 1 (no double counting) and 4 (same chunk ID with changed text). Decisions: ADR-0036, ADR-0037 (items 1, 2, 3, 5, 7), ADR-0038, ADR-0039 ([draft](../../../docs/adr/0039-session-memo-gate-accounting.md)).
- **Hypothesis:** inside one session, (a) a greeting or thanks needs no retrieval, and (b) a follow-up whose retrieval queries repeat the last lookup's can reuse that lookup's chunks. Both avoid the lookup's per-call fee; (a) also sends no chunks.
- **Strategy:** `version.py`, `SessionMemo(overlap_threshold, phatic_words, *, lookups, ...)`, a `StepVersion` with step `"cache"` that never sets `served_from_cache` (the answer is still generated, so context and routing still apply). Competes with R-A1 (popular-question answer cache) and R-B1 (`exp-cache-002`, retrieval-result cache across sessions); it never reuses across sessions, so it does not duplicate R-B1.
- **Evidence class:** *simulation* (`LeverResult.evidence_class`). The phatic match is *heuristic*; the gate's token saving is a *hypothetical reconstruction* (ADR-0038). Hits and skips are *candidate* hits; `correctness_state` is `unmeasured`.

## Rules (owner decisions 2026-11-02)

1. **Greeting gate.** A user message is phatic when its `u_h_norm` equals `fingerprint(normalize_safe(p))` for a word `p` of `config/evaluation/sprint.toml [phatic].words`, or of `p` plus one trailing mark from `! . ? ؟`. Exact match only. Never turn 0, a message with attachments (unknown attachments count as attachments) or a workflow request. A skipped lookup sends no chunks: it saves its recorded fees and its chunk tokens (every chunk row's characters x 0.3384, ledger `recon.t0rag.coef_rag`, uncached input only; ADR-0038).
2. **Session memo.** The memo is the session's last lookup that actually ran (ADR-0039). Trigger: Jaccard between this turn's set of normalised query fingerprints and the memo's set; reuse when it is `>= overlap_threshold`. `overlap_threshold` has no default (`None` refuses to run). The decision never reads the current turn's chunks (FR-REQ-06). Reused chunks are still sent: fees only.
3. **Fees** are the recorded per-call amounts (ADR-0037 item 2). A lookup is skippable only when its message has one per-call item per logged query, all equal (item 3); otherwise it runs (`fee_unattributed`).
4. **Agreement** (memo only): Jaccard over `(chunk_id, h_exact)` between the reused chunks and the turn's logged chunks; an unknown hash or two empty sets is unknown (item 5). The gate has no agreement; the share of skipped turns whose logged answer cited a source (`a_citation_n > 0`) is a *proxy* risk indicator.
5. **Threshold rule** (tune split only): the lowest of {0.5, 0.8, 1.0} whose reuses have mean agreement >= 0.9 with at least half evaluable. Sessions replay whole (a session never straddles the split); only tune rows are scored.
6. **Results:** `as_logged` (recorded units) has `fees`, `token_cost` and `total` and a session-clustered interval; the repriced baselines have an **empty** `saving` (fee part not priced) and the token part in slice `session_memo` as `token_saving_lower_bound`.

## Assumptions

- *Current:* `u_h_norm` is `fingerprint(normalize_safe(user text))` (ingest rule), so the gate needs no user text.
- *Current:* the logged retrieval queries exist before the lookup (they are its input), so using them breaks no look-ahead rule.
- *Current:* the phatic list is general vocabulary, not taken from the data; review pending (`[PLACEHOLDER: Persian review]`, K-2).
- *Current (owner decision):* a skipped turn sent all its chunk rows, duplicates included; its tokens come out of uncached input (A-84).
- *Speculative:* a phatic message needs no retrieval for an answer of the same quality. Not measured.
- *Speculative:* Metis-Auto can intercept retrieval (measured potential only, as R-B1).
- *Future:* combined with a context version, rows with `memo_status == "skipped_phatic"` must get no context saving (Review Focus 1).

## Run

```sh
.venv/bin/python scripts/derive_rag_query_fingerprints.py   # local query fingerprints, ~6 s
.venv/bin/python scripts/session_memo_levers.py --checks-only   # tune threshold table + free checks
.venv/bin/python scripts/session_memo_levers.py   # also writes reports/levers/cache.session_memo_gate.*.json (report split, read once)
```

Both write `reports/caching/exp-cache-004/summary.json` (counts and shares, by split, LLM rows in every numerator). Run the last command on a clean tree so the manifest carries the code commit.

Overhead (L-1): `scripts/measure_lever_overhead.py` has no target for this lever yet (A owns the script). A target builds `SessionMemo(<chosen threshold>, words, lookups=build_lookups(...))` from the sampled rows' sessions; with one-row frames the memo has no history, so it times the gate and the lookup path only.
