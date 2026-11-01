# ADR-0030: Reference answers ("golden answers") from gpt-5.5 for golden-v2

- Status: **decided** by the project owner, 2026-11-01 (model, effort `medium`, `max_completion_tokens` 8192, attachments handled by golden-v2, pilot before the full run). The cost is **unresolved**: it exceeds the current 10 USD lifetime cap (see Consequences).
- Date: 2026-11-01
- Amends: [ADR-0018](0018-live-calls-for-development-under-a-lifetime-budget.md) point 5 (content sent to providers): the owner may approve sending real golden-v2 conversations for this purpose, run by run.
- Relates to: ADR-0003, ADR-0014, ADR-0021, ADR-0026, ADR-0027, ADR-0028, ADR-0029; [golden_answers.md](../evaluation/golden_answers.md)

## Context
The 300 golden-v2 requests need a strong-model **reference** answer each, to compare cheaper models against and to guide a human spot-check. The answer is a strong-model reference, not ground truth. The data licence (Rahnama College, educational use) forbids redistribution, and sending real conversations to a provider is sharing with a third party, so it needs the owner's approval. `gpt-5.5` is the premium baseline (ADR-0026), disabled in the catalogue with unknown limits (A-74).

## Decision
1. **Input:** the 300 records of golden-v2 (never the reserves), from the dataset's `routing_input_post_retrieval_v1` rows: bot instructions, earlier messages, the target message and its retrieved chunks. Nothing is reconstructed again. The send order is the project's pass-through order (instructions, history, retrieved, user; A-84), not the dataset's position numbers, in which the chunks come after the user message. No extra "golden" system prompt: the model answers as the bot would.
2. **Independence:** one fresh call per record with only that record's parts; no shared conversation, cache (exact or semantic), routing, compression or escalation; the same model and settings for every record. Tested.
3. **Model and settings:** `gpt-5.5`, `reasoning_effort = medium` (OpenAI's default for the model), `max_completion_tokens = 8192`; these are in `config/evaluation/golden_answers.toml` and in a settings hash stored with each answer. Limits (context 1,050,000; output 128,000) and the effort values come from OpenAI's model page, checked 2026-11-01 (A-86). The catalogue entry stays disabled for routing; the fit check uses the limits from this file.
4. **Effort is a typed request option** (`ModelRequestOptions.reasoning_effort`), allowed only on the OpenAI endpoint (`endpoints-metis-2026-10-18-s75-effort`) and sent as the Chat Completions parameter of that name. The general settings send none.
5. **Approval flag:** `golden_answers.real_data_approved` (default false), set only in the runtime layer; an experiment file cannot set it. A live run is refused, listing every reason, unless it is true **and** the existing keys hold (`live.enabled`, both caps, `METIS_API_KEY`) **and** golden-v2 `verify` passes **and** `--live` is given.
6. **Attachments are never sent.** golden-v2 has none (ADR-0029). Records carry caveats for what is not sent: `input_widget_not_sent`, `earlier_rag_not_sent`, `config_unknown`, `no_instructions`; and `text_model_cannot_fulfil_media` (from the dataset) for `media_generation` records, which are answered but reported apart.
7. **Failures are recorded, never replaced.** golden-v1's reserves exist for review swaps, not for failed calls, so a failed record is stored with its error class and the owner decides. Retried with backoff (5 s, 20 s; 3 attempts): timeout, rate limit, server error, connection. Recorded, not retried: content filter, context overflow, invalid request (including an unknown model, HTTP 404) and auth. Five failed records in a row halt the run.
8. **Storage:** table `eval.golden_answer` (migration 0006, `infra/db`), keyed by `(run_id, record_id)`, with model, effort, output limit, settings hash, prompt fingerprint, answer, finish reason, usage (input, cached, output, reasoning), cost, latency, status, error class, attempts, caveats, answer length and answer language group. Several runs coexist. A local copy goes to `runs/golden_answers/<run_id>/answers.jsonl`, written **before** the database, so a crash never loses a paid answer (restored on the next run). The table is outside the golden-v1 and golden-v2 fingerprints (tested live: `verify` passes with rows present).
9. **Resume:** a record answered in a run, or failed with a non-retryable error, is skipped; a retryable failure is tried again. An answer is never overwritten.
10. **Spend:** every call passes the spend guard against its worst-case estimate (counted input plus 8192 output tokens). A response is charged its actual cost. A timeout is charged at its estimate (it may have been billed); other error responses are not charged (A-85). A fake or replay client never touches the ledger.
11. **Committable output:** `reports/evaluation/golden_v2/answers_<run_id>_summary.json` holds counts per stratum, success and failure by reason, latency quantiles, truncation rate, language-mismatch rate (a script-based proxy), tokens, cost, caveat counts and the media subset. No content (tested; V-11 scans the folder).

## Alternatives considered
- **Answer the 23 attachment records text-only.** Unfair references. Rejected; golden-v2 removes them (ADR-0029).
- **Swap in a reserve when a call fails.** Silent changes to the dataset. Rejected; failures are recorded and the owner decides.
- **Reuse the E4 `execute`.** It plans and runs one batch in memory, with no database and no resume. Its approval type, cost functions and guard are reused; the loop is new.
- **Put effort in the invocation only.** `ModelInvocation.effort` existed but the adapter ignored it. A typed option reuses the endpoint check and the config hash.
- **Raise `max_output_tokens_cap`.** Not needed: the loop sets its own limit, so the pipeline cap does not apply and the task stays scoped.
- **Store answers in the files only.** No joins, no resume, no summary. Rejected.

## Consequences
- **Cost.** With approximate counts (the tokenizer files are not fetched; fetching them makes the counts `exact_local`), the 300 requests total about 1.44 M input tokens: at least **7.9 USD of input** alone, plus output and reasoning at 33 USD per 1M. The ceiling with every call at 8192 output tokens is 89 USD. The full run therefore most likely exceeds the 10 USD lifetime cap (and the Metis dashboard limit, Q-29). The pilot (10 records) is bounded at 0.58 to 3.28 USD. The owner decides on actual pilot numbers (pilot first).
- The 20 USD ceiling can only be raised in `config/defaults.toml` by a reviewed commit and a new decision record.
- Whether Metis bills reasoning tokens as output is still open for the Metis bill (OpenAI's docs say they are billed as output; A-75, Q-45). The pilot's reported usage shows it.
- Open: the human spot-check (about 30 items with the annotation rubric) and what the answers are used for.
