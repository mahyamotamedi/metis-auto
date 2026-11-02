# ADR-0040: Price the logged models for replay from same-name pricing-page rows, in new replay-only files

- Status: **decided** by the lead, 2026-11-02 (Pipeline B, extra sprint task; sprint.toml change approved by Pipeline C as owner of that file). The amounts are those of the pricing page saved on 2026-10-18 and need re-verifying before any budget decision.
- Date: 2026-11-02
- Relates to: [ADR-0002](0002-configurable-baselines.md) (baselines are configuration), [ADR-0026](0026-premium-baseline-gpt-5-5.md) (a new price is a new file, a copy, never an edit), [ADR-0036](0036-replay-scope-split-and-baselines.md) (replay baselines, units, "unknown is never zero"); FR-ACCT-02, FR-ACCT-07; sprint plan S-3, Review Focus 3.
- Files: `config/reference/prices-metis-2026-10-18-logged.toml`, `config/reference/catalogue-metis-replay.toml`, `config/evaluation/sprint.toml` (`[baselines]`). Tests: `tests/unit/settings/test_logged_prices.py`. Coverage: [reports/cost/replay-pricing-logged/README.md](../../reports/cost/replay-pricing-logged/README.md).

## Context
`todays_models` (ADR-0036) reprices each request at the price of the model it ran on. It maps the logged label `bot_provider_model` to a catalogue `model_id` and then to that model's `price_ref`. The test catalogue holds only the five test models and the premium models. On 2026-11-02, 150,089 of 245,518 LLM requests (61.1%) had no price, so the baseline was mostly unknown. gemini-2.5-flash alone is 12.5% of requests and 65% of recorded cost, and gemini-2.5-flash-lite is 26.2% of requests. The pricing page extract (`docs/references/metis_pricing_2026-10-18.csv`) lists most logged labels under the same name. It has 21 Gemini rows, and 19 of them list no cached-input price. FR-ACCT-02 forbids pricing an unknown as zero or as a guess. `analysis/baselines_full._prices` refuses a price row without `input`, `output` or `cached_input`.

## Decision
1. **New price file** `prices-metis-2026-10-18-logged.toml` (version `prices-metis-2026-10-18-logged`). It is a copy of `prices-metis-2026-10-18-g55.toml` with its rows unchanged, plus one row per logged label that is a real text model **and** has a CSV row under exactly the same model name. That gives 43 labels and 47 rows. Amounts come from the CSV `raw` text only, as decimal strings in USD per 1M tokens. Where `raw` says "Long context", the rows are context tiers (four labels, read like gpt-5.4: the cheaper tier ends at 270,000 input tokens). Only token prices are kept: Per Call, Search Query, Web Search and audio prices are left out and named on each row. Cache-write prices are token prices and are kept: one amount, or `ttl-5m`/`ttl-1h` for Anthropic. `[evidence]` source is the saved page and the CSV, `checked_on = 2026-10-18`.
2. **No cached-input price on the page** → `cached_input` = that row's input price, with the row note "page lists no cached price; no discount assumed (upper bound); EDA: Google cached input ~0.03%". Never 0. Rows: gemini-2.5-flash-lite, gemini-2.5-flash, gemini-2.0-flash, gemini-3.1-flash-lite, gemini-3-flash-preview, gemini-3.5-flash-lite, command-r, gemini-2.5-pro, gemini-3.1-flash-lite-preview, gemini-3-pro-preview. On the real frame, cached tokens are 0.016% of these rows' effective input, so the upper bound moves the total by under 0.69 USD.
3. **No guessed mapping.** A label whose name differs from every CSV model, or that is not a text model, stays unpriced (unknown): Flux-Schnell, dalle, gpt-image-1, Flux-Pro (image models), and deepseek-chat and deepseek-reasoner (no same-name row; the label-mapping alias is not used by `todays_models`).
4. **New catalogue** `catalogue-metis-replay.toml` (version `cat-metis-replay-2026-11-02`). It is a copy of `catalogue-metis-test.toml` plus one row per newly priced label: `model_id` = `provider_model_name` = the logged label exactly, `provider` from the CSV, `enabled = false`, and `price_ref` to the new row. `equivalence_group = "replay-only"`. `tier = 0` is a placeholder, because the schema needs a non-negative integer and a string is refused. No `tokenizer_ref` (tokenizers.toml has no row for these models), no `context_window` or `max_output_tokens` (unknown), no capabilities. The live catalogue and `config/defaults.toml` are unchanged.
5. **sprint.toml:** only `[baselines] catalogue` and `price_table` change, with the comment "replay pricing for logged models, approved by Pipeline C (owner), 2026-11-02".
6. **No code change.** `baselines_full.py` and the other analysis modules are unchanged. Where the schema refused a file, the file was fixed: `google/gemma3-27b` (1 request) has a same-name CSV row, but `/` is not allowed in a `Name`, so it has no row and stays unknown.
7. **Gemini 2.5 rows** (gemini-2.5-flash-lite, gemini-2.5-flash, gemini-2.5-pro) carry the note "price page saved 2026-10-18; availability to re-check (Vertex retired 2.5 on 2026-10-20 per project research)".

Result on the real `requests.parquet` (price-file USD): `todays_models` known LLM requests go from 95,429 to 244,770, unknown from 150,089 to 748, and the total from 31.26 to 490.14. `best_single_cheap` and `premium_gpt_5_5` are unchanged.

## Alternatives considered
- **Edit the current price file and catalogue.** This is refused by ADR-0026: a new price is a new file. It would also change the live defaults.
- **Map near names** (deepseek-chat → deepseek-v4-flash, gpt-4o-mini-2024-07-18 → gpt-4o-mini, preview → release). That is a guess about what served the request (FR-ACCT-07 asks for curated mappings with fidelity). Exact-name rows only. gpt-4o-mini-2024-07-18 has its own same-name page row and is priced from it.
- **Cached price 0 or the provider's list discount** where the page lists none. 0 breaks FR-ACCT-02. A list discount is not a Metis price. Input price = upper bound, with the bias measured and reported.
- **Enable the new models.** `best_single_cheap` would then pick from models that are not test models and were never checked through the wrapper. They stay disabled, so routing, failover and `best_single_cheap` see the same callable set.
- **Change `baselines_full` to read the label mapping.** Out of scope (decision 6), and it would mix alias fidelity into a baseline that is defined by exact model.

## Consequences
- `price_version` and `catalogue_version` change for every lever result that reads sprint.toml. A, B and C re-run their LeverResults on a clean tree before I-1. Old and new results are not comparable on `todays_models`.
- `todays_models` is now 99.7% known. 73.4% of its total sits on the three Gemini 2.5 labels, which may no longer be served (decision 7): the baseline is "today's price list", not "what can be called today".
- The 10 rows of decision 2 are upper bounds. The bias is reported in the coverage README.
- Tests (`tests/unit/settings/test_logged_prices.py`):
  - every new amount matches the CSV raw text;
  - the tiers follow the page;
  - cached_input equals input exactly on the decision-2 rows, which carry the note;
  - the Gemini 2.5 note is present;
  - the new rows are exactly the selection rule's 43 labels, and each is disabled and priced, with no limit or tokenizer;
  - the old price file and the live catalogue are byte-identical to main (sha256), and the defaults still load them;
  - `best_single_cheap` is unchanged and its callable set is the same;
  - sprint.toml points at the new files, which pass the cross-file checks and price `todays_models` in `baselines_full`.
- Re-verify against the live pricing page before any budget decision. A price change makes another new file.
