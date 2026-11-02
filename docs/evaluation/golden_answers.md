# Golden answers: gpt-5.5 reference answers for golden-v2

Status: **run complete: 300 of 300 answered** (run `ga-v2-20261101`, 2026-11-01). Results below. Decision: [ADR-0030](../adr/0030-golden-answers-gpt-5-5.md). Dataset: [golden_v2.md](golden_v2.md).

**What this is.** One answer from `gpt-5.5` for each of the 300 golden-v2 records, to be used as a strong-model **reference**: something cheaper models and human reviewers can be compared with. **It is not ground truth.** The model can be wrong, and the request it saw is an approximation of what Metis sent (below). No aggregate over these answers is production performance.

**Licence.** The conversations are licensed to Rahnama College for educational use and may not be redistributed. Sending them to a provider needs the owner's approval, so a live run is refused unless `golden_answers.real_data_approved = true` is set in `config/local.toml`. Prompts and answers stay in the local database, `runs/` and `data/recorded/` (git-ignored). Only the content-free summary is committable.

## Result of run `ga-v2-20261101`

| Measure | Value |
|---|---|
| Answered / failed | 300 / 0 (finish reason `complete` for all, none truncated) |
| Settings | one settings hash, `gpt-5.5` (`gpt-5.5-2026-04-23`), effort `medium`, 8192 output tokens, layout `dataset_positions` |
| Tokens | 1,444,759 input (124,160 cached), 142,254 output (48,989 of them reasoning); mean 474 output tokens per record |
| Cost | 12.03 USD from provider-reported usage; the ledger shows 12.58 USD for the run because two timeouts were charged at their estimates (0.56 USD, A-85) |
| Latency | median 6.8 s, p90 20.5 s, max 107 s |
| Language-mismatch proxy | 31 of 219 checked requests (14%); a script-based proxy, not a quality judgement |
| Media-caveat records | 16 answered, reported apart (0.67 USD) |

What happened on the way: the pilot (10 records) cost 0.83 USD. The full run stopped after 237 further answers, when Metis answered HTTP 402 (Payment Required) to five calls in a row once the ledger had reached 10.04 USD, the old dashboard limit. Those calls were not billed. After the limit was raised, the run resumed with `--retry-failed auth` and answered the other 53 records. One record needed three attempts (two timeouts). Provider prompt caching works through the Metis wrapper: records grouped by identical instructions read 124,160 cached tokens in total.

The adapter files HTTP 402 under the error class `auth`; the real cause was the spending limit.

## Method

| Point | What is done |
|---|---|
| Records | The 300 primary records of golden-v2. Never the reserves. |
| Request | The dataset's post-retrieval components: bot instructions, earlier messages, the target message, its retrieved chunks. Order: the dataset's recorded component positions, as Metis sent it (the chunks follow the target message); setting `run.layout`, recorded in the manifest and the settings hash, alternative `pass_through`. No added system prompt. |
| Independence | One fresh call per record; no shared conversation, cache, routing, compression or escalation; same model and settings for all. |
| Model | `gpt-5.5`, `reasoning_effort = medium`, `max_completion_tokens = 8192` (reasoning tokens count against it and are billed as output). |
| Limits | Context 1,050,000 and output 128,000, from OpenAI's model page, checked 2026-11-01. Re-verify; Metis may differ. No record comes near the window (the largest request is about 128 k tokens). |
| Retries | Timeout, rate limit, server error, connection: up to 3 attempts, waits of 5 s and 20 s. Content filter, context overflow, invalid request (incl. unknown model) and auth are recorded, not retried. |
| Failures | Recorded with their error class. Reserves are never swapped in; the owner decides. |
| Resume | A rerun skips answered records and non-retryable failures; it never repeats a paid call. Each answer is written to `runs/golden_answers/<run_id>/answers.jsonl` before the database. |
| Storage | `eval.golden_answer`, keyed by `(run_id, record_id)`, several runs side by side. |

## What the request leaves out (read before using an answer)

- **History is sent in full**, as golden defines it. Whether Metis transmitted it that way is unknown (`transmitted_to_provider = unknown`).
- **The bot's configuration** (temperature and similar) is not sent; "answers as the bot would" holds for the instructions and context only.
- **Attachments are never sent** (golden-v2 has none).
- **Caveats per record:** `config_unknown` (51), `no_instructions` (30), `input_widget_not_sent` (22), `earlier_rag_not_sent` (68: chunks of earlier turns are in neither routing profile), and `text_model_cannot_fulfil_media` (16 `media_generation` records).
- **The media records** are answered but must be **reported separately**: a text model cannot produce the requested media, and the intent is a rule proposal that review may change.

## Run it

```bash
python scripts/golden_answers.py plan
```
No call. Prints counts, the pilot IDs, the cost bounds, the IDs that exceed the context window (none), and which approvals are missing.

For the live steps (only after the owner says so), these `config/local.toml` lines are needed:

```toml
[golden_answers]
real_data_approved = true

[budget]
run_cap = "3.5"   # the pilot only; see the plan's pilot bounds
```
`[live] enabled = true` and `METIS_API_KEY` are also required. `max_output_tokens_cap` is not needed: this task sets its own limit.

```bash
python scripts/golden_answers.py pilot --run-id <id> --live
python scripts/golden_answers.py run --run-id <id> --live     # the rest, same run id
python scripts/golden_answers.py summary --run-id <id>
```

The summary is `reports/evaluation/golden_v2/answers_<run_id>_summary.json`: counts per stratum, success and failure by reason, latency quantiles, truncation rate, language-mismatch rate (a script-based proxy for Persian and English requests), tokens, cost, caveat counts, and the media subset.

## Reviewing language mismatches

The run summary counts requests whose answer came back in a different script group than the request (the proxy rule `summary.language_mismatch`: Persian and English requests only). This command lets a person look at each one. It makes no call.

```bash
python scripts/golden_answers.py review-language <run_id>
```

The selection **is** the summary's rule (the code calls `language_mismatch()`, it has no copy of it), so the count equals the summary's. It prints counts only: mismatches by direction (Persian to X, English to X), by bot (top 10), and how many have instructions that mention a language.

It writes two files:

| File | Holds | Rule |
|---|---|---|
| `runs/golden_answers/<run_id>/review/language_mismatch_local.json` | **message text**: per record the IDs, cohort, languages, caveats, the target user message, the first 800 characters of the bot instructions (plus their total length and the language flag), and the full answer | **Never share, paste, upload or commit it.** It stays on this computer. The command refuses to write it unless git ignores the path. |
| `reports/evaluation/golden_v2/review/language_mismatch_<run_id>.csv` | no text: `record_id, bot_id, request_lang, answer_lang, instructions_mention_language, verdict, notes` | Committable. |

`instructions_mention_language` is a flag computed in code over the whole instructions (the words Persian, Farsi, English, language and their Persian forms). It says the instructions talk about a language, not what rule they give.

**Filling the verdicts.** Open the local file on your own computer and the CSV next to it. For each record choose one `verdict`:

| verdict | Meaning |
|---|---|
| `ok_bot_rule` | the bot's instructions require that answer language |
| `ok_not_really_english` | the request only looked English or Persian to the detector (a name, a term, code) |
| `model_error` | the model answered in the wrong language |
| `detector_error` | the script detector mislabelled the request or the answer |
| `unsure` | cannot tell |

`notes` is optional and **must never contain message text** (no quotes, no translations, no paraphrases); a short reason such as "bot asks for English" is fine. Running the command again keeps the verdicts already in the CSV and the command reports any value outside the list above. Commit the CSV, never the local file.

## Human spot-check (planned, not done)

About 30 answers, sampled across the strata, are read by a reviewer using [the annotation rubric](annotation_rubric_v1.md), to estimate how often the reference is wrong or unusable. Until then every use of these answers should say "reference", not "correct". Record the reviewer, the sample IDs and the findings next to the summary (IDs and labels only).

## Limits

A strong model's answer to a request that may be incomplete, in a language mix it can misjudge, with retrieval whose use by Metis is unknown. Truncated answers (finish reason `length`) are kept and counted. Costs are provider-reported usage priced from the Metis price file of 2026-10-18; Metis's own bill may differ (Q-36).
