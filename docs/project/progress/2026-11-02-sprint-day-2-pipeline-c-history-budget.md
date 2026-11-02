## Sprint Day 2, Pipeline C: history budget, stepped window (2026-11-02)

Sprint task R-C2, branch `context-history-budget` (from `main` at 87a2c94, #26). **Awaiting review.** Traceability: FR-CTX-02, FR-CTX-03, FR-ACCT-02, H-2, X1, H-1 (cached-prefix risk), ADR-0036, ADR-0038, ADR-0039, [ADR-XXXX (history-token-measure)](../../adr/draft-history-token-measure.md).

- **Owner decisions (2026-11-02):** history tokens = excess of effective input over the bot's tune turn-0 median, less chunk tokens (`recon.t0rag.coef_rag`); bots under `min_n` turn-0 rows are unknown, never 0; per-turn sizes by logged characters, most recent turns sent; `HistoryBudget(budget_tokens, step_turns)` drops the oldest whole turns, no defaults; excluded: workflow, turn 0, memory and summarising bots, unknown rows, gate-skipped rows; removed tokens come from cached first (primary), uncached only as sensitivity; variants b2000, b4000, b8000 and half on requests over 8,000 tokens; slices `all`, `llm_only`, `over_8k`; "tokens only, quality not measured (FR-CTX-03)".
- **Agent's precisions, recorded in the ADR draft (provisional until reviewed):** the turn-0 base is net of turn-0 chunk tokens and taken from single-call rows; multi-call requests have unknown history; `as_logged` prices the removed cached part at `implied_cached_per_M`.
- **New:** `experiments/context/exp-ctx-004-history-budget/{version.py,README.md}` (variant list frozen in the README before any report-split run), `scripts/history_budget_levers.py`, `tests/unit/experiments/test_exp_ctx_004_history_budget.py` (11 tests, synthetic), `reports/context/exp-ctx-004/tune_checks.json` (tune aggregates), `docs/adr/draft-history-token-measure.md`. **Changed:** `experiments/README.md`, `experiments/context/README.md` (one list entry each).
- **TDD:** the 11 tests first errored (no `version.py`), then passed against the implementation.
- **Not written:** the report-split `LeverResult`s. The owner runs `scripts/history_budget_levers.py` after committing, on a clean tree. A dry run on the tune split (scratch folder, not kept) wrote 16 results (4 variants x 4 baselines).
- No `module_reference.md` row: no module under `src/`; `baselines_full.py` unchanged.
- **Traceability IDs:** the task prompt named H-1 and X4. In the repo, history windowing is X1 and the history hypothesis is H-2 (`docs/experiments/context_plan.md` §3 and §5, EDA §5); X4 is original LLMLingua (deferred). The README cites H-2 and X1, and H-1 only for the cached-prefix risk.

### Results (tune split, LLM rows; aggregates)

234,759 requests, 213,007 LLM; turn-0 base for 81 bots (`min_n` 30). States: known 126,613, turn 0 38,297, unknown 14,731, multi-call 14,463, summarising 10,801, memory 8,102. `hist_tokens > 0`: 0.517 of LLM rows, 0.870 of known rows. Median / p90 history tokens: turn 1 75 / 422; turn 20+ 336 / 2,135. Over-8k: 17,205 LLM rows, 3,823 with known history (8,560 multi-call); history is 0.979 of their input.

| Variant | Requests reduced | Tokens removed, primary / uncached only | `as_logged` saving (recorded), primary / uncached only |
|---|---:|---:|---:|
| b2000 | 6,793 | 178.0M / 177.5M | 18.02 / 18.01 |
| b4000 | 4,471 | 167.4M / 167.0M | 16.50 / 16.50 |
| b8000 | 3,485 | 152.3M / 151.9M | 14.83 / 14.83 |
| half_over_8k | 3,822 | 98.5M / 98.2M | 9.69 / 9.69 |

Tune `as_logged` token cost over known LLM rows: 233.15. **Concentration:** one bot holds 0.92 of the removed tokens at b2000 and one tenant 0.97 (long sessions, median turn 172, about 41,700 input tokens); per-bot and per-tenant reading is required (Review Focus 5).

### Open
- Owner review of the three precisions above (ADR draft, points 2, 5 and 6).
- The cached-prefix break after dropping turns (H-1) is not measured.
- Combined with R-C1 (I-1), the gate's `memo_status` column reaches this version through `combine` (a cache version's columns are passed on) and gated rows get no saving; a combined run on real data has not been made.
