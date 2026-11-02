# Replay pricing for the logged models (2026-11-02)

Pipeline B, extra task approved by the lead on 2026-11-02. Decision record: [ADR-XXXX (replay-pricing-for-logged-models)](../../../docs/adr/draft-replay-pricing-for-logged-models.md). Traceability: FR-ACCT-02 (unknown price → not computed, never zero), FR-ACCT-07 (logged labels → priced models); ADR-0002, ADR-0026, ADR-0036. No live calls. Aggregates only: label names and counts, no content and no IDs.

## What changed

| File | Change |
|---|---|
| `config/reference/prices-metis-2026-10-18-logged.toml` | **New.** Version `prices-metis-2026-10-18-logged`. A copy of `prices-metis-2026-10-18-g55.toml` (rows unchanged) plus 47 price rows for 43 logged labels (4 labels have two context tiers). |
| `config/reference/catalogue-metis-replay.toml` | **New.** Version `cat-metis-replay-2026-11-02`. A copy of `catalogue-metis-test.toml` plus 43 rows. All are `enabled = false`, with `equivalence_group = "replay-only"` and `tier = 0` (placeholders: the schema needs an integer tier). None has a limit, a tokenizer or a capability. |
| `config/evaluation/sprint.toml` | Only `[baselines] catalogue` and `price_table` now point at the two new files. |
| `tests/unit/settings/test_logged_prices.py` | **New.** 12 tests (listed in the ADR). |

The live defaults (`config/defaults.toml`, `catalogue-metis-test.toml`, `prices-metis-2026-10-18-g55.toml`) are unchanged. A test pins the sha256 of both reference files.

**Selection rule.** A label gets a row when (a) it is a logged label in `label-mapping-full-v1.toml` that is not already a catalogue model, (b) it is a real text model (not `not_a_model` or `not_a_text_model`), and (c) the pricing page extract has a row under exactly the same model name. Amounts come from the CSV's `raw` text only. They are stored as decimal strings in USD per 1M tokens. Context tiers follow the gpt-5.4 reading.

**Token prices only.** Among the 43 new rows, the left-out non-token prices are: Web Search on 18 rows, Search Query on 9, Input Audio Token on 6, Per Call on 0. Across the whole CSV (128 rows): Web Search 45, Search Query 21, Input Audio Token 9, Per Call 9. Cache-write prices are token prices, so they are kept. "Cache Write Token" is stored as one amount (the four tiered OpenAI rows). Anthropic's "(5m)"/"(1h)" prices become the `ttl-5m`/`ttl-1h` variants. `baselines_full` does not use cache-write prices.

## Rows with cached_input = input (decision 2)

The page lists no cached-input price for these 10 labels. Each row sets `cached_input` to its own input price, which assumes no discount, so it is an upper bound. Each row carries the note "page lists no cached price; no discount assumed (upper bound); EDA: Google cached input ~0.03%".

| Label | Provider | LLM requests |
|---|---|---|
| gemini-2.5-flash-lite | google | 91,358 |
| gemini-2.5-flash | google | 43,800 |
| gemini-2.0-flash | google | 1,467 |
| gemini-3.1-flash-lite | google | 290 |
| gemini-3-flash-preview | google | 75 |
| gemini-3.5-flash-lite | google | 67 |
| command-r | cohere | 10 |
| gemini-2.5-pro | google | 4 |
| gemini-3.1-flash-lite-preview | google | 3 |
| gemini-3-pro-preview | google | 1 |

On these 137,075 requests, cached tokens are 0.016% of effective input: 156,398 tokens. So the upper bound changes the total by less than 156,398 × 4.4 USD/1M ≈ 0.69 USD (4.4 is the highest input price among these rows). That is under 0.15% of the new todays_models total. The three Gemini 2.5 rows also carry the availability note (decision 7).

## Coverage on the real `requests.parquet`

Method: `baseline_costs` (unchanged `analysis/baselines_full.py`) on the scoped frame (`replay_scope.scope`, sprint periods), with `cached_reported_separately` from the same frame. Run once with the old pair (prices `prices-metis-2026-10-18-s75-g55`, catalogue `cat-metis-test-2026-10-18-s75-g55`) and once with the new pair. 245,518 LLM requests; workflow rows are never counted. Units: price-file USD, not recorded units. *Simulation*: token counts are assumed model-independent.

| todays_models | Before | After |
|---|---|---|
| Known LLM requests | 95,429 (38.9%) | 244,770 (99.7%) |
| Unknown LLM requests | 150,089 (61.1%) | 748 (0.3%) |
| Total (price-file USD, known rows only) | 31.260506100 | 490.137823863 |

The 748 unknown requests are 525 requests on a priced label with unknown billed tokens (unknown in every repriced baseline) plus the 223 requests on unpriced labels below.

The other baselines are unchanged: `premium_gpt_5_5` 8,639.128163600 and `best_single_cheap` 94.188809781, both with 244,993 known and 525 unknown. `as_logged` is in recorded units and is never compared with the totals above.

Where the new total sits: gemini-2.5-flash 322.87 (65.9%), gemini-2.5-flash-lite 36.70 (7.5%), claude-4-opus 31.06 (6.3%), gpt-5.2 20.37 (4.2%), gpt-4o-mini 18.34 (3.7%), gpt-5.1 15.87 (3.2%). The three Gemini 2.5 labels make up 55.1% of LLM requests and 73.4% of the new total. No request on a tiered label has more than 270,000 input tokens, so the tier-boundary caveat is unused. Four new labels report cached tokens outside the input count (`cached_reported_separately`): deepseek-v4-pro, gpt-5.4-mini, gpt-5.4-nano, gpt-5.6-sol. Their cached tokens are added back as the S-3 rule says.

### Labels still unpriced (unknown, never zero)

| Label | LLM requests | Reason |
|---|---|---|
| Flux-Schnell | 90 | not a text model (image generation) |
| dalle | 79 | not a text model (image generation) |
| gpt-image-1 | 27 | not a text model (image generation); the page lists token prices, but decision 3 excludes it |
| deepseek-chat | 14 | no page row under this name (`label-mapping-full-v1.toml` aliases it to deepseek-v4-flash; todays_models matches the exact name and does not use that alias) |
| Flux-Pro | 7 | not a text model (image generation) |
| deepseek-reasoner | 5 | no page row under this name (same alias note as deepseek-chat) |
| google/gemma3-27b | 1 | the page has a same-name row (sotoon), but the catalogue schema refuses `/` in a `model_id` (`Name` pattern), so the label cannot be a catalogue row. Per decision 6 (fix the files, not the code), it is left out. |

## Notes for reviewers

- `label-mapping-full-v1.toml` lists `gpt-4o` twice (271 and 7 requests, identical bytes). `requests.parquet` has one label `gpt-4o` with 278 LLM requests. The file is a reference list that the settings loader cannot read (its `requests` key is not a schema field). It is unchanged here and has one row in the new files.
- New OpenAI rows carry the CSV's provider `openai_chat_completion`, as decision 4 says. The copied test-catalogue rows keep `openai`. Nothing groups by provider for disabled rows.
- `metis-gpt` and `metis-gpt-mini` are Metis's own labels, and the page names no underlying model. They are priced because the page lists token prices under exactly these names.
- **price_version changes for every lever result.** A, B and C re-run their LeverResults on a clean tree before I-1.
