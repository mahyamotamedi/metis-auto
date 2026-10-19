# External Model and Provider Interfaces (Stage 3)

Status: `ModelClient` port semantics and the error taxonomy **decided**; the live OpenAI-compatible adapter **built** in Stage 7.5 ([ADR-0021](../adr/0021-live-openai-compatible-adapter.md); mappings provisional until the live wrapper check); catalogue limits **sourced** (TODO-10, except Grok); the provider is the Metis wrapper ([ADR-0018](../adr/0018-live-calls-for-development-under-a-lifetime-budget.md)); tokenizers and prices **decided** in Stage 7 ([ADR-0020](../adr/0020-token-and-cost-accounting.md), [token_accounting.md](token_accounting.md)). Last updated 2026-10-18.
Index: [architecture README](README.md). Components: CMP-10 (model clients), CMP-12 (tokenizers), CMP-13 (embedders), CMP-15 (judges). Requirements: FR-API-02, FR-FAIL-*, FR-ACCT-01, FR-ROUTE-05, FR-CTX-05.

No provider API, SDK method, price, or capability is stated in this document. Each one is researched, with source and check date, when an adapter or a catalogue entry is written (MP§3.8).

---

## 1. The `ModelClient` port

One operation, provisionally `invoke(ModelInvocation) -> ModelResult`.
- **Input** `ModelInvocation`: catalogue model ID, ordered input parts from the `ContextPlan`, attachment references, generation limits (maximum output tokens), request and attempt IDs, timeout.
- **Output** `ModelResult`, which is one of:
  - a **response**: text, normalised finish reason (`complete`, `length`, `content_filter`, `other`), `TokenUsage` with fidelity `provider_reported` when the provider returns usage, provider latency, provider-reported model version if returned;
  - a **normalised error**: an error class (§3), a retryable flag, and the provider's error code (a code, not a message, because messages can echo content);
  - **no answer** (added in Stage 4, `ModelNoAnswer`): a replay or proxy source has nothing for this target. It lowers coverage and is never retried or failed over ([ADR-0014](../adr/0014-counterfactual-answers-via-model-client.md)).
- Contracts: `ModelInvocation`, `ModelResult` ([contracts.md §3.4](contracts.md#34-context-and-model-calls)).
- **Never raises for provider failures.** Exceptions mean a programming or configuration error.
- **Synchronous** for now ([ADR-0010](../adr/0010-request-pipeline-shape.md)).
- Internal message roles are generic (for example `user`, `assistant`, `instructions`). Mapping the sample's `bot` role is the sample loader's job (ADR-0008). Mapping internal roles to each provider's format is the adapter's job.

---

## 2. Adapters

| Adapter | Kind | Purpose | Network? |
|---|---|---|---|
| Fake client | base | Canned, clearly synthetic answers. Deterministic given a seed. The walking skeleton and most tests use it. | no |
| Fault-injecting client | decorator | Scripted errors, timeouts, and delays per call, for failover tests (FR-FAIL-06). | no |
| Quality-injecting client | decorator | Scripted empty, truncated, wrong-language, or refusal answers, for detector and cascade tests. | no |
| Replay client | base | Answers from recorded responses or logged references ([evaluation.md §4](evaluation.md#4-counterfactual-sources-and-their-limits)). "No answer" when none exists. | no |
| Recording decorator | decorator | Writes live results to `data/recorded/` for reuse. | no (wraps a live client) |
| Live client: **one** OpenAI-compatible adapter for OpenAI, DeepSeek, and Grok (`openai_compat.py`, Stage 7.5); Gemini needs a second adapter (Stage 10) | base | Real calls. Opt-in only, built only with both keys and caps (`wiring.live`), always wrapped in the recording decorator; tests use mocked HTTP; the one real-network test is marked `network` (ADR-0003, ADR-0021). | **yes** |

The decorators compose, for example *recording(live)* or *fault(fake)*. Wiring builds the stack from configuration. Pipeline code sees only `ModelClient`.

---

## 3. Normalised errors

| Class | Meaning | Retryable by default |
|---|---|---|
| `timeout` | No complete response within the attempt timeout. | yes |
| `rate_limited` | The provider asked the caller to slow down. | yes |
| `unavailable` | Server-side failure or overload. | yes |
| `connection` | Network failure before a response. | yes |
| `context_overflow` | The input exceeded the model's limit. | no (handled by the context rule) |
| `content_filtered` | The provider blocked the input or output. | no |
| `invalid_request` | The request was malformed. | no |
| `auth` | Credentials are missing or rejected. | no |
| `unknown` | Anything unmapped. | once |

Each live adapter documents how its provider's responses map onto these classes, with sources. [attempts.md §3](attempts.md#3-errors-and-failover) gives the default action per class.

### 3.1 The OpenAI-compatible adapter (ADR-0021)

Sources (checked 2026-10-18): openai SDK 3.24.0 (`_exceptions.py`, `types/completion_usage.py`, `completion_create_params.py`); DeepSeek [create-chat-completion](https://api-docs.deepseek.com/api/create-chat-completion) (usage fields, `finish_reason` values, `max_tokens`, 402 insufficient balance). xAI's site now documents only its Responses API, so Grok's chat-completions behaviour rests on OpenAI compatibility. The [live check](../references/metis_wrapper_live_check.md) of 2026-10-18 confirmed the success path for all three families (Grok reports no cached or reasoning fields); no error occurred, so the error rows are tested on mocked HTTP only.

| Provider outcome | Normalised | Retryable |
|---|---|---|
| SDK `APITimeoutError` | `timeout` | yes |
| SDK `APIConnectionError` (no response) | `connection` | yes |
| HTTP 429, except code `insufficient_quota` | `rate_limited` | yes |
| HTTP 401, 402 (DeepSeek: insufficient balance), 403; code `insufficient_quota` | `auth` | no |
| HTTP 408 | `timeout` | yes |
| code or type containing `context_length` / `context_window` | `context_overflow` | no |
| code or type containing `content_filter` / `content_policy` | `content_filtered` | no |
| other HTTP 4xx (400, 404 unknown model, 409, 422, …) | `invalid_request` | no |
| HTTP 5xx | `unavailable` | yes |
| 200 with no choice; any other SDK error | `unknown` | yes (bounded) |

`provider_error_code` = `http_<status>[:<code or type>]`, never the message. Finish reasons: `stop` → `complete`; `length`; `content_filter`; anything else (`tool_calls`, DeepSeek's `insufficient_system_resource`, `aborted`, missing) → `other`. Usage: `prompt_tokens` → input; `completion_tokens` → output, plus `reasoning_tokens` when the provider reports them outside the completion count (`total = prompt + completion + reasoning`); `prompt_tokens_details.cached_tokens`, else `prompt_cache_hit_tokens` → cached input (0 means reported and zero, absent means not reported); the response `model` → `provider_model_version`. SDK retries are off (`max_retries=0`). The SDK's and `httpx2`'s loggers are held at WARNING because their DEBUG output contains request bodies.

---

## 4. Model catalogue (reference data)

Fields of each catalogue entry (`config/reference/catalogue-*.toml`). Limits sourced in Stage 7.5 (TODO-10): provider pages, checked 2026-10-18; Grok's unknown (Q-32).
- `model_id` (internal, stable), `provider`, `provider_model_name`, `family`;
- `tier` (an ordinal for routing and cascades) and `equivalence_group` (for failover; FR-FAIL-03);
- `context_window` and `max_output_tokens`, each with source and check date;
- capabilities (modalities, for example image input), **each with `verified: true|false`, source, and check date**. Unverified means unsupported for eligibility (FR-ROUTE-05);
- `tokenizer_ref` (a row of `config/reference/tokenizers.toml`: backend, fidelity, evidence, chat template; Stage 7) and `price_ref` (price-table rows, possibly tiered);
- capability `hidden_reasoning_billed_as_output` (verified only with a source) marks models whose counted output is a lower bound (token_accounting.md §3.4);
- provider prompt caching: whether supported, minimum prefix, discount. Verified-only, otherwise unknown (FR-CTX-05);
- `enabled`.

The **label mapping** (logged label → catalogue model, with fidelity) is a separate reference file used by the as-logged baseline. `default`, `workflow`, and null labels stay unmapped unless the data owner explains them (FR-ACCT-07, A-16).

---

## 5. Other external-facing ports

| Port | Network backends (future, opt-in) | Offline backends | Rule |
|---|---|---|---|
| `Tokenizer` | provider token-counting endpoints (none documented for the Metis wrapper; not implemented) | chars/N approximation; tiktoken (`o200k_base`); Hugging Face `tokenizer.json` (DeepSeek V4), from pre-fetched, sha256-pinned files (Stage 7) | Every count carries its fidelity. Nothing downloads at run time; network counting would be opt-in and off in tests. |
| `Embedder` | hosted embedding APIs | fake; local models (Stage 8). Downloading weights needs network once, at setup. | Persian-capable; ID and version recorded. |
| `Judge` | LLM judge built on a `ModelClient` | fake; imported human labels | Opt-in; cost reported as evaluation cost or overhead. |

All network backends have the same privacy rule as live providers: content leaves the machine, so they are opt-in.
