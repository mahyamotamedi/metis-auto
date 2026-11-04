# ADR-0062: The owner's benchmark values, the open Metis gate and the pinned reranker are recorded in configuration

- Status: **decided** by the project owner, 2026-11-04 (values and gate); the reranker pins were read from the Hugging Face API by the owner and re-checked in this change. Nothing paid or GPU-bound has run.
- Date: 2026-11-04
- Relates to: [ADR-0018](0018-live-calls-for-development-under-a-lifetime-budget.md) (amendment 3: 92 USD), [ADR-0053](0053-paid-benchmark-p1-p3.md), [ADR-0040](0040-reranker-cut-and-lever-overhead.md), [ADR-0060](0060-sprint-close-readiness-and-resumable-reruns.md) (placeholders and refusals); FR-EVAL-04, FR-CTX-02, QA-COST, QA-PRIV, H-2.
- Code and config: `config/evaluation/benchmark.toml`, `config/reference/rerankers.toml`, `wiring/benchmark.py` (`summary_status`), `scripts/spend_share.py`.

## Context

ADR-0060 left the owner's values as placeholders so that nothing could run on a guess. The owner has now decided them, confirmed that Metis answered in writing that samples may go to model APIs, and supplied the reranker pins.

## Decision

1. **Benchmark values** (Q-62 to Q-64): `run.hard_cap_usd = "35"`, `run.max_output_tokens = 8192`, `run.order_seed = "p1-order-2026-11-04"`; judges `gpt-4o-mini` and `deepseek-v4-flash` (two families), 64 reply tokens, English instructions; `labels.acceptable_score = 0.5` (fixed before any result existed), `cheap_arms = gpt-5-nano, gpt-4o-mini, deepseek-v4-flash`; machines `kimia`, `mahya`, `saba`, `parham`, summaries at most 24 hours old.
2. **Self-preference is stated, not removed.** Both judges are also answering arms; the 60-item human spot-check is the control. Any "quality" claim stays conditional on it.
3. **The Metis gate is open** (`metis_allows_samples = true`) on the owner's statement of 2026-11-04. The written answer is held by the owner and is not in the repo; `metis_answer_ref` says so. Other gates are unchanged: the per-run owner approval after the printed estimate, and the shared ledger.
4. **Missing ledger summaries are reported, never faked.** `plan` and `spend_share.py merge` list which expected machines have no summary; a paid run still refuses until all four exist.
5. **The reranker is pinned** to `BAAI/bge-reranker-v2-m3` revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` (licence apache-2.0): the three large files' sha256 from the Hub API, and the three small files the adapter loads (`config.json`, `tokenizer_config.json`, `special_tokens_map.json`) hashed from our own download of just those files at that revision (trust on first download, sizes equal the Hub listing). The weights are still not fetched.

## Alternatives considered

- **Keep the gate closed until the written answer is in the repo.** Rejected by the owner's decision; the statement is recorded in the config and here, and the answer itself stays with the owner.
- **Different judge families from the answering arms.** Not chosen by the owner; the spot-check is the control.

## Consequences

- `plan --estimate --with-db` can print a computed estimate on a machine with the golden-v2 database; without it the only refusal is the missing input sizes.
- The owner values are now in the committed file; the refusal tests use temporary copies with one value removed.
- Q-53 and Q-55 in `assumptions_and_questions.md` still show the pre-answer wording and need the owner's update.
