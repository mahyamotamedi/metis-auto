# ADR-XXXX (session-memo-gate-accounting): The session memo reuses the last real lookup, and the greeting gate's repriced saving is unknown

- Status: **decided** by the project owner, 2026-11-02 (Pipeline C, sprint task R-C1). The phatic word list is a **placeholder** (`[PLACEHOLDER: Persian review]`, K-2); the chosen `overlap_threshold` is **provisional** (fitted on 2 reuses, see Consequences).
- Date: 2026-11-02
- Relates to: [ADR-0036](0036-replay-scope-split-and-baselines.md) (split, recorded vs repriced units), [ADR-0037](0037-retrieval-result-cache-accounting.md) (retrieval cache accounting, items 1, 2, 3, 5 and 7), [ADR-0038](0038-context-token-saving-conversion.md) (characters to tokens, uncached input); FR-REQ-06, FR-XCACHE-01, FR-ACCT-02, H-3, X1; sprint plan R-C1, Review Focus 1 and 4.
- Code: `experiments/caching/exp-cache-004-session-memo-gate/version.py`, `scripts/session_memo_levers.py`, `scripts/derive_rag_query_fingerprints.py`.

## Context
R-C1 has two rules inside one cache version. The **greeting gate** skips a turn's retrieval when the user message is phatic; the turn then sends no chunks, so it saves the lookup's fees and the chunk tokens. The **session memo** reuses earlier chunks of the same session when this turn's retrieval queries overlap enough; the reused chunks are still sent, so it saves fees only (ADR-0037 item 1). The owner fixed the gate rule, the memo trigger (Jaccard of normalised query fingerprints, no default threshold), the agreement metric and the threshold rule before this ADR. Two points stayed open:

1. After a turn reuses, what does the next turn compare with? With thresholds below 1 the memo can drift: turn 2 matches turn 1, turn 3 matches turn 2 but not turn 1, and turn 3 would get turn 1's chunks.
2. Against the three repriced baselines (price-file units, no `fees` key, ADR-0036), the gate's token part has a price but its fee part does not. `compare._total` sums the blocks when `saving` has no `total`, so `saving = {"token_cost": x}` would be ranked as if the whole saving were `x`.

## Decision
1. **The memo holds the session's last lookup that actually ran**: its query fingerprints and its logged chunks. A turn compares its own query set with the memo's; a reused turn, a skipped phatic turn and a turn without a lookup never update the memo. A lookup that runs because its fee is unattributable (ADR-0037 item 3) or the guard refused it does update the memo. The reused chunks were retrieved for exactly the queries they are compared with.
2. **Repriced results carry an empty `saving`.** For `premium_gpt_5_5`, `todays_models` and `best_single_cheap` the `LeverResult` has `baseline_cost` `token_cost` and `total`, and `saving = {}`: `compare` shows "saving unknown" and never ranks it (as ADR-0037 item 7). The known token part goes to slice `session_memo` as `token_saving_lower_bound`, with an assumption saying the fee part is not priced. Recorded fees (`fee_avoided`) appear only in the `as_logged` result. Neither `compare` nor `wiring/lever_view` changes.
3. **One rule for skipping**: a lookup is skipped (gate) or reused (memo) only when its recorded fee is attributable (ADR-0037 item 3); otherwise it runs. So the gate never counts a token saving on a turn whose fee it cannot account for.

## Alternatives considered
- **Compare with the previous retrieval turn, reuse the memo's chunks** (literal reading of the trigger): the queries compared and the chunks reused can come from different turns, so a chain of small steps reuses chunks for unrelated queries. Rejected. At threshold 1.0 both rules give the same result.
- **Repriced `saving = {"token_cost": x}`**: ranked as a full saving while the fee part is missing. Rejected (unknown is not zero, FR-ACCT-02).
- **Two lever IDs** (a fee version for `as_logged` and a token version for all baselines): two versions in `compare` for one mechanism, and the token version would show fees 0, which is wrong for a skipped lookup. Rejected.
- **Skip a phatic turn with an unattributable fee and count its tokens only**: one turn, two accounting rules. Rejected.

## Consequences
- On the tune split (2026-11-02, aggregates): normalised query sets overlap the previous retrieval turn's at >= 0.5 on 0.58% of LLM retrieval turns, while chunk sets do on 23.0%. The memo therefore reuses rarely: 73 reuses at 0.5 (mean agreement 0.73), 2 at 0.8 and 1.0 (agreement 1.0). The rule picks 0.8 on 2 reuses; the choice is provisional and says so in the result.
- 34% of LLM retrieval turns have no recorded per-call item, so neither rule can skip them.
- Combined with a context version (S-6 within-message dedup, R-B2), a gated turn's chunks are already gone; a context version that still counts them double-counts the saving (Review Focus 1). `combine` does not prevent it, because the gate does not set `served_from_cache`. The context versions must skip rows with `memo_status == "skipped_phatic"` before I-1 combines them.
- Guarding tests: `tests/unit/experiments/test_exp_cache_004_session_memo_gate.py` — `test_memo_holds_the_last_real_lookup`, `test_unattributable_fee_is_not_skippable`, `test_levers_script_writes_one_result_per_baseline` (repriced `saving` empty, token part in the slice, no recorded fees), `test_memo_reuse_lowers_fees_only`, `test_skip_saves_fees_and_chunk_tokens`.
