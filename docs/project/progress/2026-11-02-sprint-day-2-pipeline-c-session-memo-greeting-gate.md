## Sprint Day 2, Pipeline C: session memo + greeting skip gate (2026-11-02)

Sprint task R-C1, branch `cache-session-memo-greeting-gate` (from `main` at f44d84f, #23). **Awaiting review.** Traceability: H-3, X1, FR-REQ-06, FR-XCACHE-01, FR-ACCT-02, ADR-0036, ADR-0037, ADR-0038, ADR-XXXX (session-memo-gate-accounting).

- **Owner decisions (2026-11-02):** gate = exact `u_h_norm` match of a `[phatic]` word, bare or with one trailing `! . ? ؟`, never turn 0, attachments or workflow; a skipped lookup saves its fees and its chunk tokens (ADR-0038). Memo trigger = Jaccard of normalised query fingerprints, `overlap_threshold` without default; reuse saves fees only. Query fingerprints come from a local script (hashes only). Agreement = Jaccard over `(chunk_id, h_exact)`; threshold = lowest of {0.5, 0.8, 1.0} with mean agreement >= 0.9 and at least half evaluable, tune split only. Asked during the task: the memo holds the last lookup that ran; repriced results carry an empty `saving` with the token part in a slice. Recorded as ADR-XXXX (session-memo-gate-accounting), `docs/adr/draft-session-memo-gate-accounting.md`.
- **New:** `experiments/caching/exp-cache-004-session-memo-gate/{version.py,README.md}`, `scripts/derive_rag_query_fingerprints.py`, `scripts/session_memo_levers.py`, `tests/unit/experiments/test_exp_cache_004_session_memo_gate.py` (14 tests, synthetic), `reports/caching/exp-cache-004/summary.json` (tune threshold table and free checks, aggregates), the ADR draft. **Changed:** `experiments/README.md`, `experiments/caching/README.md` (one list entry each).
- **TDD:** the 14 tests first failed to import (no `version.py`), then failed against a stub (14 failed), then passed.
- **Not written:** the report-split `LeverResult`s. The owner runs `scripts/session_memo_levers.py` after committing, on a clean tree. A dry run on the tune split (scratch folder, not kept) wrote the four results.
- No `module_reference.md` row: no module under `src/`.

### Results (tune split unless stated; aggregates; LLM rows in every numerator)

Query fingerprints: 63,456 messages with queries (= the 45,241 LLM + 18,215 workflow retrieval turns), 192,245 queries, every query set known. 34% of LLM retrieval turns have no per-call billing item, so their fee is unattributable and they are never skipped (65.3% attributable).

| Threshold | Reuses | Mean agreement | Evaluable | Fees avoided (recorded) | Skipped phatic |
|---:|---:|---:|---:|---:|---:|
| 0.5 | 73 | 0.730 | 73 | 0.878 | 62 |
| 0.8 | 2 | 1.000 | 2 | 0.442 | 62 |
| 1.0 | 2 | 1.000 | 2 | 0.442 | 62 |

Chosen: **0.8**, on 2 reuses (provisional). Fees avoided include the gate's. Tune: 234,759 requests, 213,007 LLM, 27,797 LLM retrieval turns. Skipped-phatic share of LLM requests 0.029% (all requests 0.026%).

| Free check | Tune | Report |
|---|---:|---:|
| LLM retrieval turns | 27,797 | 14,882 |
| Chunk set overlaps previous retrieval turn's at >= 0.5 / 0.8 / 1.0 (diagnostic) | 0.230 / 0.029 / 0.009 | 0.247 / 0.037 / 0.012 |
| Query set overlaps previous turn's at >= 0.5 / 0.8 | 0.0058 / 0.0003 | 0.0036 / 0.0000 |
| Phatic match share of retrieval turns (gate-eligible) | 0.0030 (0.0029) | 0.0228 (0.0226) |
| Skipped turns whose answer cited a source (proxy) | 0 of 62 | not read |

- **Reading:** the trigger, not the fee rule, limits the memo: normalised query sets almost never repeat between turns, while a quarter of turns repeat half of the previous turn's chunks. A query-based memo cannot reach that overlap. The gate is small (0.3% of tune retrieval turns, 2.3% of report ones).
- **Tune dry run** (`write_levers`, threshold 0.8, tune rows only): `as_logged` saving 0.4995 of 339.62 recorded units (fees 0.436, token_cost 0.064), session-clustered interval 0.0011 to 0.0020 of the total; repriced savings empty, token lower bounds 2.07 (premium), 0.0105 (today's models), 0.0207 (best single cheap) price-file USD; 0 rows with an unknown saving.
- **Open:** the threshold rests on 2 reuses; the phatic list is a placeholder (K-2); a context version combined after this one must skip gated rows (Review Focus 1); `scripts/measure_lever_overhead.py` (A) needs a target for this lever.
