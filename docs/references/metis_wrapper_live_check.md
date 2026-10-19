# Metis wrapper: live check results (Stage 7.5)

The tiny live check that the [owner brief](../project/live_testing_and_demo_brief.md) §3 and ADR-0018 point 7 require before relying on what the wrapper reports. It resolves most of TODO-12 and checks A-46, A-54, A-56, and A-58. §4 adds the follow-up probe of the same day (Q-32…Q-34).

- **Run:** 2026-10-18, 12:19 UTC, run ID `wrapper-check-20261018T121945Z-a24138`, approved by the owner. Script: `scripts/live_wrapper_check.py --run` ([ADR-0021](../adr/0021-live-openai-compatible-adapter.md)).
- **Raw results** (content-free): [metis_wrapper_live_check_2026-10-18.json](metis_wrapper_live_check_2026-10-18.json). The answers themselves are only in `data/recorded/` (git-ignored).
- **Input** (synthetic, the same for every model): one system message, `[SYNTHETIC] You are a test assistant. Reply in one short sentence.`, and one user message, `[SYNTHETIC] سلام! Please reply with the word OK.` One attempt per model, with no retry or failover, through the real pipeline, spend guard, ledger, and recording decorator. Generation limit: 4,096 (Grok: 1,024, the default for an unknown limit).
- **Cost:** pre-call upper bound 0.0096 USD; **actually charged 0.000188 USD** (sum of five costs computed from reported usage; ledger total afterwards 0.000188210 USD). The Metis dashboard's figure can be compared by the owner.
- **Local counts** in the JSON were made with tokenizer table `tokenizers-2026-10-18` (before this check's update).

## 1. Results

| Model | Reported model | Finish | Input reported / counted (content + framing) | Output reported / visible answer | Cached reported | Reasoning reported | Cost |
|---|---|---|---|---|---|---|---|
| gpt-5-nano | `gpt-5-nano-2025-08-07` | stop | 43 / 44 (33 + 11) | 267 / 2 | 0 | 256 (inside completion) | 0.000120 |
| gpt-4.1-nano | `gpt-4.1-nano-2025-04-14` | stop | **44 / 44** (33 + 11) | 1 / 1 | 0 | 0 | 0.000005 |
| gpt-4o-mini | `gpt-4o-mini-2024-07-18` | stop | **44 / 44** (33 + 11) | 1 / 1 | 0 | 0 | 0.000008 |
| deepseek-v4-flash | **`deepseek-flash`** | stop | 65 / 39 (35 + 4) → **65 / 65** after the update (35 + 30) | 33 / 2 | 0 | 30 (inside completion) | 0.000033 |
| grok-4-1-fast | `grok-4-1-fast` | stop | 98 / 29 (chars/4, no framing) | 2 / 1 | **not reported** | **not reported** | 0.000023 |

Costs in USD, from reported usage and the Metis prices of 2026-10-18. Latency was 0.8–3.1 s for OpenAI and DeepSeek and 8.2 s for Grok (one sample each, not a measurement).

## 2. Findings

1. **Endpoints, auth, model IDs (A-46): confirmed** for all three families. The base URLs, the Bearer key, and every model ID were accepted. Each generation-limit field was accepted: `max_completion_tokens` for OpenAI, and `max_tokens` for DeepSeek and for Grok (the Grok field was unverified until now).
2. **Usage, finish reason, reported model: returned** by every family in OpenAI's chat-completions shape. OpenAI and DeepSeek return `prompt_tokens_details.cached_tokens` and `completion_tokens_details.reasoning_tokens`, with reasoning **inside** `completion_tokens`. **Grok returned neither field**, so its costs carry the caveat `cached_input_not_reported` and its reasoning is unknown.
3. **Provider caching was not exercised.** The prompts were tiny (43–98 tokens) and each was sent once. OpenAI's [prompt-caching guide](https://developers.openai.com/api/docs/guides/prompt-caching) (checked 2026-10-18) states a minimum cacheable length of 1,024 tokens for GPT-5.6 and later, and says the minimum "varies by request settings" for earlier models such as ours. Every reported cached count was 0, so the field is confirmed present, but not that a cache hit is reported correctly (a follow-up probe is proposed in Q-33).
4. **OpenAI framing (A-56):** the cookbook template is **exact** for gpt-4.1-nano and gpt-4o-mini on this layout, and overcounts gpt-5-nano by 1 token (conservative). It stays labelled an approximation: one request per model, two messages.
5. **gpt-5-nano bills hidden reasoning** (256 of 267 output tokens), as the catalogue already says. A further 9 output tokens beyond the 2-token visible answer are unexplained (probably output formatting). Costs counted from the visible answer are therefore lower bounds, as the existing caveat says.
6. **DeepSeek (A-54, A-58): the wrapper serves DeepSeek-V4.1-Flash in thinking mode.** The reported model is `deepseek-flash` (DeepSeek's current name for V4.1-Flash-1017), and 30 reasoning tokens were billed inside the output. Encoding the documented V4.1 thinking-mode prompt (BOS, `<｜System｜>` with a 25-token reasoning-effort prefix, content, `<｜User｜>`, `<｜Assistant｜><think>`) with the tokenizer reproduces the reported **65** prompt tokens exactly. Content counts with the pinned V4 tokenizer are unaffected (same vocabulary and merges). **Configuration updated:** DeepSeek template `deepseek-v41-thinking-2026-10-18` (framing 30 instead of 4 for this layout), and the capability `hidden_reasoning_billed_as_output` verified for `deepseek-v4-flash`.
7. **Grok:** the wrapper still serves `grok-4-1-fast` (reported under that name), although xAI no longer lists it (Q-32). Its input is reported as 98 tokens against 29 counted (chars/4, no framing): chars/4 plus no template **undercounts this request by 70 %**. One request cannot separate a fixed overhead (framing or an added system prompt) from the chars/4 error on the content, so nothing was fitted (Q-33).
8. **Spend guard:** every pre-call estimate exceeded its actual cost, because the output limit dominates the estimate. The input part of the estimate was too low for DeepSeek (before the update) and for Grok, which matters only for long inputs (A-50).
9. **Errors:** none occurred, so error mapping, and whether Metis reports usage on errors (Q-26), remain tested on mocked HTTP only.

## 3. What changed because of the check (configuration only)

| File | Change |
|---|---|
| `config/reference/tokenizers.toml` (`-s75`) | DeepSeek thinking-mode template (sequence start 27, retrieved prefix 1); evidence notes on the OpenAI and Grok rows |
| `config/reference/catalogue-metis-test.toml` (`-s75`) | `deepseek-v4-flash`: `hidden_reasoning_billed_as_output` verified; Grok: wrapper acceptance verified |

## 4. Follow-up probe (2026-10-18, owner decisions Q-32, Q-33 b, Q-34)

- **Run:** 2026-10-18, 12:46 UTC, run ID `wrapper-probe-20261018T124659Z-6b2e40`, approved by the owner. Script: `scripts/live_probe.py --run` (ADR-0021 amendment 1). Raw content-free results: [metis_wrapper_live_probe_2026-10-18.json](metis_wrapper_live_probe_2026-10-18.json).
- **Calls:** 12 (all succeeded, finish reason `stop`). Pre-call upper bound 0.0085 USD; **charged 0.001374 USD**. Lifetime ledger total afterwards: **0.001563 USD** of 20.
- **Input** (synthetic): the cache test used 30 numbered synthetic shop rules in English and Persian (`long_instructions()` in `wiring/wrapper_check.py`; 1,263 o200k, 1,505 DeepSeek, and 1,796 MiMo content tokens), sent twice per model with two different short messages, so Metis's own exact cache missed and only the provider's prefix cache could hit. Output limit 512. The tiny checks used the §1 input.

### 4.1 Provider cache (second call of each pair)

| Model | Prompt tokens (reported = counted?) | Cached on call 2 | Cost call 1 → call 2 (USD) | Discount computed |
|---|---|---|---|---|
| gpt-5-nano | 1,273 (counted 1,274: +1, as in §1) | **0** (no hit) | 0.000103 → 0.000131 | none |
| gpt-4.1-nano | 1,274 = 1,274 | **1,152** | 0.000141 → 0.000046 | 0.000095 |
| gpt-4o-mini | 1,274 = 1,274 | **1,152** | 0.000211 → 0.000116 | 0.000095 |
| deepseek-v4-flash | 1,535 = 1,535 | **1,280** | 0.000261 → 0.000054 | 0.000207 |
| mimo-v2.5 | 1,807 = 1,807 | **1,792** | 0.000282 → 0.000013 | 0.000270 |

1. **Cached tokens are reported on a hit** by OpenAI (gpt-4.1-nano, gpt-4o-mini: 1,152, a multiple of 128 as OpenAI's caching guide describes), DeepSeek (1,280, a multiple of 64), and MiMo (1,792). The adapter maps them, and the accounting prices them at the cached-input rate. "Discount computed" is the `provider_cache_saving` term of the savings decomposition (cached tokens × (input − cached-input price)), which is what the pipeline reports.
2. **gpt-5-nano did not hit** within about 2 seconds (cached 0 both times). Provider caching is best effort, so one pair can't say whether it is never, sometimes, or later. Its answers spent 64 and 128 hidden reasoning tokens.
3. **MiMo omits the cached field when nothing is cached.** Call 1 (and the tiny check) had no `cached_tokens`, so the cost carries `cached_input_not_reported` (an upper bound); call 2 reported 1,792.
4. **Whether Metis bills the discount is not visible through the API.** The computed costs assume it does. The owner can compare the Metis dashboard with the ledger (0.001563 USD for both runs, Q-36).

### 4.2 MiMo tiny check (A-59)

`mimo-v2.5`: reported model `mimo-v2.5` (the requested ID; Xiaomi's switch to `mimo-v2.6-flash`, A-60, is not visible in responses). Prompt tokens **47 = 47** (36 content + 11 ChatML framing), exact, as were the 1,807 above. Output 15, of which 12 is reported reasoning inside `completion_tokens` (thinking on by default): the capability `hidden_reasoning_billed_as_output` is now verified. Latency 2.1 s here and 5–10.6 s on the long prompts (one sample each).

### 4.3 DeepSeek with `thinking: {"type": "disabled"}` (Q-34)

**Works through the wrapper.** Reported model `deepseek-flash`, no reasoning field, output 1 token (the visible answer), 0.000007 USD against 0.000033 with thinking on (§1). Prompt tokens **40** against 65 counted with the thinking-mode template, so the framing is 5 tokens in this mode. Two framings fit 40 (`BOS <｜System｜>{system}<｜User｜>{msg}<｜Assistant｜></think>`, or `BOS {system}<｜User｜>{msg}<｜Assistant｜><think></think>`), and one request can't separate them. No chat-mode template is configured; with the option set, counted input overcounts by about 25 tokens (conservative). The default stays thinking on (Stage 8 decides). *Update 2026-10-19 (Demo milestone A):* a `thinking_disabled` template variant (framing 5, the first layout) is now configured and used when the option is set (A-68).

### 4.4 Configuration changed by the probe

| File | Change |
|---|---|
| `catalogue-metis-test.toml` | `mimo-v2.5`: `hidden_reasoning_billed_as_output` verified |
| `tokenizers.toml` | evidence notes: OpenAI and DeepSeek templates confirmed again on a 1,263-token prompt; MiMo template exact on two layouts; DeepSeek thinking-off framing (5) recorded |
