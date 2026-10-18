# Metis wrapper API: endpoints and notes

Summary of the saved Metis documentation pages, for the live adapter (Stage 7.5) and the endpoint configuration (`config/reference/endpoints-metis.toml`).

- **Saved:** 2026-10-18, by the project owner, as HTML outside the repository (`../metis-docs/`). Summarised here on 2026-10-18. The pages are in Persian; the notes below are a paraphrase, not a translation.
- **Pages read:** the OpenAI, DeepSeek, and Gemini wrapper pages, and the wrapper overview page (which holds the Grok section). The other saved pages (Anthropic, GLM, Kimi, MiMo, TypeSafe, bots, corpora) were not needed. The API-keys page was **not opened** (owner's instruction).
- **Status:** documentation claims; endpoints, auth, model IDs, and the usage fields were **verified by the live check of 2026-10-18** (§4). Before that, not verified by a call. Every row below is re-checked by the tiny live wrapper check in Stage 7.5 ([brief §3](../project/live_testing_and_demo_brief.md)), and the result recorded with its date.

| Page (canonical URL) | Saved file |
|---|---|
| https://metisai.ir/api/wrapper/openai | `metis-docs-api-wrapper-openai.html` |
| https://metisai.ir/api/wrapper/deepseek | `metis-docs-api-wrapper-deepseek.html` |
| https://metisai.ir/api/wrapper/ (overview; Grok section) | `metis-docs-api-wrapper-.html` |
| https://metisai.ir/api/wrapper/gemini | `metis-docs-api-wrapper-gemini.html` |

## 1. Endpoints

All families use the same Metis API key. The model is chosen per request.

| Family | Base URL | Wire format | Auth header | Metis-Auto status |
|---|---|---|---|---|
| OpenAI | `https://api.metisai.ir/openai/v1` | OpenAI API (chat completions; the page says embeddings, batch, audio, and images work too) | `Authorization: Bearer <key>` (via the OpenAI SDK's `api_key`) | enabled in config; adapter in Stage 7.5 |
| DeepSeek | `https://api.metisai.ir/deepseek/v1` | OpenAI-compatible chat completions; streaming shown | `Authorization: Bearer <key>` | enabled in config; adapter in Stage 7.5 |
| Grok (xAI) | `https://api.metisai.ir/api/v1/wrapper/grok` (chat path `/chat/completions`) | OpenAI-compatible chat completions | `Authorization: Bearer <key>` | enabled in config; adapter in Stage 7.5 |
| Gemini | `https://api.metisai.ir` (e.g. `/v1beta/models/<model>:generateContent`) | Google `google-genai` format; **not** OpenAI-compatible | `x-goog-api-key: <key>` | **deferred**: needs a second adapter (Stage 10 roadmap) |

## 2. Notes from the pages

1. **Wrapper mode disables Metis features.** In direct ("wrapper") mode, Metis bots, knowledge bases, and function calling are not available (overview and OpenAI pages). Metis-Auto supplies its own instructions and retrieved context, so this fits P-8 (the full message list is sent each time).
2. **Coverage is partial.** The OpenAI page says not every provider feature is fully covered yet, and missing features can be requested through Metis support. So token usage, finish reason, and cached-token counts must be confirmed by a live check before the adapter relies on them (brief §3).
3. **DeepSeek models.** Two models are listed: `deepseek-v4-flash` (fast, low cost) and `deepseek-v4-pro` (stronger). The legacy names `deepseek-chat` and `deepseek-reasoner` are deprecated: requests using them are still accepted but are **silently redirected to `deepseek-v4-flash`** (even `deepseek-reasoner`), so the response's `model` differs from the one sent. Always send an exact model ID and record the provider-reported model.
4. **Grok model names in the examples** are `grok-4-fast` (curl) and `grok-beta` (Python). Our catalogue uses `grok-4-1-fast`, the ID on the pricing page. That the wrapper accepts it is unverified until the live check.
5. **Embeddings.** The OpenAI endpoint serves embeddings (example: `text-embedding-3-small`). A possible semantic-cache embedder later; every call counts against the budget (ADR-0018).
6. **Gemini** is reached with `google-genai` by setting `HttpOptions(base_url="https://api.metisai.ir")` and the Metis key. The example model is `gemini-2.5-pro`.
7. **The pages state no rate limits, error formats, retry behaviour, timeouts, or prices.** Prices come from the pricing page ([metis_pricing_2026-10-18.csv](metis_pricing_2026-10-18.csv)).

## 3. Price source

[`metis_pricing_2026-10-18.csv`](metis_pricing_2026-10-18.csv) is the owner's extract of the Metis pricing page (canonical URL `https://metisai.ir/pricing`; the brief cites it as `https://docs.metisai.ir/pricing`), saved 2026-10-18. Public prices; no secrets. Amounts are **Metis user prices in USD per 1M tokens** (the brief says about 10–15% above provider list prices; not checked here).

**Known extraction defect (found 2026-10-18):** for models with **context-length price tiers** (e.g. `gpt-5.4`), the structured columns are wrong: `Input Token` is empty, and `Cached Input Token`, `Long contextInput Token`, and `Output Token` hold the **long-context** values. The `raw` column is correct and shows both tiers. `config/reference/prices-metis-2026-10-18.toml` therefore takes tiered prices from the `raw` column, and a test (`tests/unit/settings/test_settings_reference.py`) checks every configured amount against the `raw` text.

## 4. Re-verification

| What | How | When |
|---|---|---|
| Base URLs, auth, model IDs accepted | live wrapper check (fractions of a cent) | Stage 7.5 |
| Usage, finish reason, cached tokens, reported model returned | same check | Stage 7.5 |
| Prices unchanged | re-read the pricing page; new dated CSV and price-table version if changed | before each live budget review, and Stage 7 |

**Stage 7.5 (2026-10-18):** the adapter and the check script exist (`scripts/live_wrapper_check.py`, [ADR-0021](../adr/0021-live-openai-compatible-adapter.md)); the check ran with the owner's approval: results in [metis_wrapper_live_check.md](metis_wrapper_live_check.md). Rows 1–2 of the table above are **confirmed** for OpenAI, DeepSeek, and Grok, with two corrections: DeepSeek reports `deepseek-flash` (V4.1, thinking on), and Grok reports no cached or reasoning fields.
