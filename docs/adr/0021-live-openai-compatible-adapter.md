# ADR-0021: One live OpenAI-compatible adapter, no SDK retries, and an uncomputable cost stops the run

- Status: **decided** (adapter shape, retries off, the uncomputable-cost rule, the generation-limit cap). Usage and finish-reason mappings **confirmed** by the [live wrapper check](../references/metis_wrapper_live_check.md) of 2026-10-18 for OpenAI, DeepSeek, and Grok; error mappings **provisional** (no error occurred; tested on mocked HTTP only).
- Date: 2026-10-18
- Resolves: A-33 (SDK retries can be turned off: verified for openai 3.24.0), A-55 (message layout), the spend-guard TODO of ADR-0018, TODO-10 (except Grok, Q-32).
- Relates to: ADR-0003, ADR-0013, ADR-0014, ADR-0018, ADR-0019, ADR-0020, providers.md §2–§3, attempts.md §5, [owner brief](../project/live_testing_and_demo_brief.md) §3, §12.

## Context

Stage 7.5 makes the first live calls ([brief §12](../project/live_testing_and_demo_brief.md)). The Metis wrapper exposes OpenAI, DeepSeek, and Grok as OpenAI-compatible chat completions at different base URLs, with one key ([metis_wrapper_api.md](../references/metis_wrapper_api.md)). The budget is 20 USD for the whole project, so every attempt must be visible and charged (ADR-0013), and the spend guard must keep working when a call's cost can't be computed. Research on 2026-10-18 showed that the providers' own documentation has moved on: DeepSeek serves the legacy name `deepseek-v4-flash` with a model released the day before, and xAI no longer lists `grok-4-1-fast`.

## Decision

1. **One adapter for every OpenAI-compatible family** (`adapters/providers/openai_compat.py`), using the official `openai` Python SDK 3.24.0 in a new optional extra `live`. The SDK is imported only there (an architecture test enforces it), so offline code and the runtime lock never need it. The base URL and the generation-limit field come per family from `endpoints-metis.toml` (`max_tokens_param`: `max_completion_tokens` for OpenAI, `max_tokens` for DeepSeek and, unverified, Grok).
2. **SDK retries off.** `max_retries=0`: the SDK's loop then sends exactly one request (`range(max_retries + 1)` in `openai/_base_client.py`, checked 2026-10-18), and a test over mocked HTTP shows a 429, a 500, a timeout, and a connection error each make one request. Every retry is the pipeline's.
3. **Message layout (A-55):** one message per input part; instructions and each retrieved item are `system` messages; history keeps its roles. No provider-specific options are sent (no DeepSeek `thinking`, no reasoning effort): the check records the defaults.
4. **Normalisation.** Finish reason: `stop` → `complete`, `length`, `content_filter`, anything else → `other`. Usage under ADR-0020's inclusion rules: `input` = `prompt_tokens`; cached = `prompt_tokens_details.cached_tokens`, else DeepSeek's `prompt_cache_hit_tokens`; reasoning = `completion_tokens_details.reasoning_tokens`, added to output when the provider reports it **outside** `completion_tokens`; the field used is written into `TokenCount.method`. Cache-write counts are not mapped (no test model prices them). Errors map to the nine classes by HTTP status and the provider's error `code`/`type` (never its message). The full table is in [providers.md §3.1](../architecture/providers.md#31-the-openai-compatible-adapter-adr-0021).
5. **An uncomputable actual cost charges the estimate and stops the run.** When a live attempt's actual cost is "not computed" (an error with no reported usage, or a missing price), the spend guard charges the attempt's **pre-call estimate** to the persistent ledger (never zero) and blocks every later live attempt in that run. The ledger total therefore stays an estimate-backed upper bound, and nothing more is spent on a total that can't be trusted.
6. **Generation-limit cap.** `[pipeline.context] max_output_tokens_cap` (default 4,096 in `defaults.toml`) lowers the limit actually requested and reserved in the pre-call estimate below each model's own output limit. Otherwise, for example, gpt-5-nano's 128,000 output tokens would make each pre-call estimate about 0.056 USD.
7. **Every live call goes through:** pipeline → spend guard → recording decorator (`data/recorded/live-<run>.jsonl`, content, git-ignored) → adapter. Recording failures are logged and never raised, so a paid call is always charged.
8. **Unknown limits stay unknown.** No first- or second-party source states Grok 4.1 Fast's limits on 2026-10-18, so its catalogue limits stay unknown and routing excludes it (FR-ROUTE-05). An explicit diagnostic switch, `pipeline.routing.eligibility.allow_unknown_context_window`, used only by the wrapper check and `chat.py --allow-unknown-window`, lets it be called anyway. It is never set in `defaults.toml`.

## Alternatives considered

- **Plain HTTP (httpx) instead of the SDK.** One fewer dependency and full control over retries. But the SDK's typed errors and request shaping are maintained by the provider, and A-33 asks specifically about turning off SDK retries. Rejected; revisit if the SDK's dependency churn (it moved to `httpx2` in 2026) becomes a burden.
- **One adapter class per family.** Clearer per-family quirks, but three near-copies. Rejected: the differences are configuration (base URL, limit field) and a few mapping branches.
- **On an uncomputable cost, charge zero and continue.** Rejected: it undercounts the lifetime total.
- **Stop without charging.** Rejected: an error after the provider started generating may still be billed.
- **Charge a fixed penalty.** Rejected: arbitrary. The pre-call estimate is the best figure available.
- **Use third-party limits for Grok** (aggregators quote 2M context; output 30K or none). Rejected: second-hand, conflicting, and the model appears retired by xAI (Q-32).
- **Send DeepSeek `thinking: {"type": "disabled"}`.** Cheaper and closer to the chat-mode template, but unverified through the wrapper and a behaviour change. Deferred until the check shows what the wrapper does by default.

## Consequences

- The live check (`scripts/live_wrapper_check.py`) and `scripts/chat.py` run over the real pipeline. Both need the owner's two keys: the script asks for `live`, and `config/local.toml` sets `[live] enabled = true`.
- Retries after an uncosted error are blocked, so a transient 5xx ends a live run. That is acceptable for development; revisit if the check shows that Metis reports usage on errors (Q-26).
- The generation-limit cap can truncate long answers, especially from reasoning models. The truncation detector then fires, and the cap is configuration.
- DeepSeek: if the wrapper also serves V4.1-Flash-1017, the content tokenizer still counts plain text exactly (same vocabulary and merges as the pinned V4 file, checked 2026-10-18), but thinking mode changes the framing (A-58).

## Amendment 1 (2026-10-18, owner decisions Q-32, Q-33, Q-34)

- **Fifth test model:** `mimo-v2.5` (Xiaomi, `https://api.metisai.ir/mimo/v1`, the same adapter) replaces `grok-4-1-fast`, which stays in the catalogue, disabled, with the reason recorded. MiMo is counted exactly with its published tokenizer (A-59) and a ChatML template from its `chat_template`. Xiaomi retires the `mimo-v2.5` ID on 2026-10-21 (A-60, Q-35).
- **Provider request options (point 3 amended):** a typed `[model_options."<model>"]` settings section (today only `thinking = "enabled" | "disabled"`), sent as extra request-body fields. Each family's endpoint lists the options it documents (`request_options`: DeepSeek and MiMo allow `thinking`), and wiring refuses others. Nothing is set by default, so every provider keeps its default. Options are in the config hash and may be set by an experiment (Stage 8 decides on quality evidence, Q-34). Known limit: each chat template is for its provider's default mode, so with thinking off the counted framing is approximate (DeepSeek over, MiMo 2 tokens under).
- **Second probe** (`scripts/live_probe.py`, Q-33 b): the provider-cache test (a long synthetic prompt, twice per test model, different short messages so Metis's own exact cache misses), the MiMo tiny check, and DeepSeek with thinking disabled. Estimate shown and approved before running; limit 0.02 USD.
