## Stage 7.5 — Live adapter and wrapper check (2026-10-18)

### Research first (TODO-10; sources and dates in the catalogue, checked 2026-10-18)
- **Limits** for five of six models: gpt-5-nano 400,000 / 128,000; gpt-4.1-nano 1,047,576 / 32,768; gpt-4o-mini 128,000 / 16,384; gpt-5.4 1,050,000 / 128,000 (OpenAI model pages); deepseek-v4-flash 1,000,000 / 384,000 (DeepSeek pricing page, "1M" and "384K" read conservatively).
- **grok-4-1-fast: limits unknown.** xAI's model list no longer has it, its pages return 404, and OpenRouter doesn't list it; third-party aggregators conflict. It is excluded from routing except by an explicit diagnostic switch (Q-32).
- **DeepSeek** serves the legacy `deepseek-v4-flash` with DeepSeek-V4.1-Flash-1017 (released 2026-10-17), thinking on by default. V4.1's tokenizer has the same vocabulary and merges as the pinned V4 file (diffed 2026-10-18; only special tokens differ).

### Outputs
- **Adapter** `adapters/providers/openai_compat.py`: one live `ModelClient` for OpenAI, DeepSeek, and Grok (base URL and generation-limit field per family from `endpoints-metis.toml`); openai SDK 3.24.0 in the new extra `live` (dev lock only; `httpx2`, `jiter`, `sniffio`, `truststore` 0.10.4 held back by the age rule); `max_retries=0` (A-33 verified); A-55 message layout; nine error classes; finish reason; usage with cached and reasoning tokens and the field used; reported model; SDK loggers held at WARNING (their DEBUG output holds request bodies).
- **Recording decorator** implemented (`data/recorded/live-<run>.jsonl`, git-ignored; failures logged, never raised).
- **Spend guard TODO resolved:** an uncomputable actual cost charges the pre-call estimate and stops live calls for the run.
- **Domain knobs:** `[pipeline.context] max_output_tokens_cap` (4,096 in defaults) and the diagnostic `pipeline.routing.eligibility.allow_unknown_context_window` (never in defaults).
- **Wiring:** `wiring/live.py` (`build_live_client`, `live_overrides`), `wiring/chat.py` (`ChatSession`, content-free `TurnReport`), `wiring/wrapper_check.py` (`plan`, `run`); `AccountingService.pre_call_estimate`; `RequestPipeline.live_stopped`.
- **Scripts:** `scripts/chat.py` (live or `--fake`; `/model`, `/models`, `/reset`, `/budget`), `scripts/live_wrapper_check.py` (plan by default; `--run` asks).
- **Config:** catalogue `-s75` (limits; DeepSeek reasoning capability), endpoints `-s75` (`max_tokens_param`), tokenizers `-s75` (DeepSeek V4.1 thinking-mode template; evidence notes), defaults (output cap).
- **Docs:** [ADR-0021](../../adr/0021-live-openai-compatible-adapter.md); [live check results](../../references/metis_wrapper_live_check.md) and the raw JSON; providers.md §3.1 (mapping table); token_accounting.md; metis_wrapper_api.md; module_reference (6 rows); guide §5.1 (enabling live calls); docs index; ADR-0020 update; `CLAUDE.md` pointer; `config/local.example.toml`; register.
- **Tests (+55 test cases):** adapter over mocked HTTP (`httpx2.MockTransport`: request shape, routes, auth, layout, limit fields, usage variants, finish reasons, 13 HTTP error cases, timeout and connection, one request per call), recording, spend guard, domain knobs, settings and reference, live wiring end to end (ledger, recording, history, stop on uncomputable cost, the check over mocked HTTP), an architecture test (the SDK only in the adapter), and one opt-in `network` test (skipped by default).

### The live wrapper check (owner-approved, 2026-10-18 12:19 UTC)
Five tiny synthetic calls, one per test model. Pre-call upper bound 0.0096 USD; **charged 0.000188 USD** (ledger: 5 charges). Every call succeeded, with finish reason `stop`.
- **OpenAI framing exact** for gpt-4.1-nano and gpt-4o-mini (44 = 44); overcounts gpt-5-nano by 1. gpt-5-nano billed 256 reasoning tokens for a one-word answer.
- **DeepSeek: served as `deepseek-flash`** (V4.1) in thinking mode (30 reasoning tokens billed as output). The V4.1 thinking-mode framing reproduces the reported 65 input tokens exactly; template and capability updated (configuration only).
- **Grok:** accepted and reported as `grok-4-1-fast`; no cached or reasoning fields; 98 reported vs 29 counted input tokens (Q-33).
- Cached-token fields are present (all 0) for OpenAI and DeepSeek; a real cache hit was not exercised (Q-33).

### Validation
- **Full suite: 499 passed, 1 skipped** (the opt-in network test), offline, warnings as errors.
- ruff check and format clean; import rules, the module reference, and the new SDK-import test pass; relative links and anchors in changed docs resolve; raw sample data unchanged (sha256 `e0f56a2f…`).
- `scripts/chat.py --fake` and `scripts/live_wrapper_check.py` (plan) run offline. **`scripts/chat.py` has not been run live**: only over mocked HTTP. The first live chat is yours.
- `.env` was never opened; the key reached only the SDK client, at run time.

### Decisions, assumptions, questions
- Decisions: [ADR-0021](../../adr/0021-live-openai-compatible-adapter.md). Defaults chosen and stated: the official SDK rather than plain HTTP; one adapter for all three families; charge the estimate and stop on an uncomputable cost; output cap 4,096; Grok limits left unknown rather than taken from aggregators; the V4 tokenizer file kept for V4.1 (same vocabulary); no provider-specific options sent (DeepSeek thinking left at its default).
- Register: A-33, A-46, A-54, A-55, A-58 decided; A-51 resolved except Grok; A-56 partly verified; A-57 new; TODO-10 resolved except Grok; TODO-12 mostly resolved; **Q-32** (keep, replace, or drop grok-4-1-fast), **Q-33** (a second small probe: Grok overhead and a provider-cache hit), **Q-34** (DeepSeek thinking on or off) new; Q-29 still open (the Metis dashboard limit).

**Carried into later stages:**
- **Stage 8:** replay lookup over `data/recorded/`; per-model generation limits if the cap truncates reasoning models; error mappings checked against real errors when they occur (Q-26).
- **Demo milestone:** `ChatSession` and `TurnReport` are the UI's backend.
- **Stage 10 roadmap:** the Gemini adapter.

**Exit criteria** (brief §12: live adapter, the wrapper check with dated results, `chat.py`): **met.** The adapter is built and tested offline; the check ran once, under budget, and its dated results are in `docs/references/` and the register; `chat.py` works over the real pipeline (fake and mocked-live). The Grok gaps (limits, overhead, reasoning) are recorded as open questions rather than filled in.

### Stage 7.5 follow-up — owner decisions Q-32, Q-33, Q-34 (2026-10-18)

| Item | Status | Answer and what was done |
|---|---|---|
| Q-32 | answered | **mimo-v2.5 replaces grok-4-1-fast** as the fifth test model. Grok stays in the catalogue, **disabled**, with the reason. MiMo: endpoint `https://api.metisai.ir/mimo/v1` (`max_completion_tokens`); prices 0.154 / 0.0031 / 0.308 (pricing page; the Metis MiMo page shows about 10 % less); limits 1,000,000 / 131,072 (model cards; Xiaomi API reference); tokenizer `mimo-v2` **exact_local** (MiMo-V2.5 `tokenizer.json`, MIT, pinned and fetched) and a ChatML template (11 framing tokens for system + user). |
| Q-33 | answered | Probe (b) plus the MiMo tiny check; (a) skipped. `scripts/live_probe.py`: 12 calls, upper bound 0.0085 USD (limit 0.02). **Run 2026-10-18 with the owner's go: 0.001374 USD** (results below). |
| Q-34 | answered | DeepSeek keeps thinking on. New option `[model_options."<model>"] thinking`, allowed by the endpoint file for DeepSeek and MiMo, default unset; the probe tests `disabled` once. |
| Q-29 | open | The owner will check the Metis dashboard. |

**Found during the research (2026-10-18):** Xiaomi auto-routes `mimo-v2.5` to **`mimo-v2.6-flash`** since 2026-10-14 and makes the ID **invalid on 2026-10-21** (A-60, Q-35). The V2.6-Flash tokenizer counts identically (A-59).

**Changes:** config (catalogue, prices, endpoints, tokenizers `-s75`; defaults comment); settings (`ModelRequestOptions`, `ThinkingMode`, `ProviderEndpoint.request_options`); adapter (`request_options` → `extra_body`); `wiring/live.py` (`request_options`); `wiring/wrapper_check.py` (probe; `CHECK_MODELS` now has mimo-v2.5); `scripts/live_probe.py`; tests (+8; 507 pass, 1 skipped); ADR-0021 amendment 1; register; module reference; guide.

**Probe results (2026-10-18 12:46 UTC, [live_check.md §4](../../references/metis_wrapper_live_check.md#4-follow-up-probe-2026-10-18-owner-decisions-q-32-q-33-b-q-34)):** 12 of 12 calls succeeded; charged 0.001374 USD; **lifetime total 0.001563 USD of 20**.
- **Provider cache:** hits reported and priced for gpt-4.1-nano and gpt-4o-mini (1,152 cached tokens), deepseek-v4-flash (1,280), and mimo-v2.5 (1,792). Second-call costs dropped 45–95 %. gpt-5-nano did not hit in one pair (best effort). MiMo omits the cached field when nothing is cached. Whether Metis bills the discount: dashboard only (Q-36).
- **mimo-v2.5:** counts exact (47 = 47, 1,807 = 1,807; A-59 decided); hidden reasoning verified (capability added); reported model `mimo-v2.5`, so the V2.6 switch is invisible (A-60).
- **DeepSeek thinking disabled:** works (no reasoning; framing 5 instead of 30 tokens, not yet a template variant). Default unchanged (Q-34).
- **Config from the probe:** catalogue (MiMo reasoning capability), tokenizers (evidence notes). Tests: 507 pass, 1 skipped.
- **Open for the owner:** Q-29 and Q-36 (dashboard limit and charges), Q-35 (mimo-v2.5 ID expiry on 2026-10-21).

### Owner request — teammate quickstart for the Demo milestone (2026-10-18)

- **Recorded** as a required Demo-milestone deliverable: brief §10 and §12 (dated amendment; the brief's sha256 changes from `8e7293a4…` to `5f720a61…`), the planned-steps list above, and the docs index.
- **Drafted now:** [`docs/guides/demo_quickstart.md`](../../guides/demo_quickstart.md), sections 1–8 as requested. The demo UI parts are marked *(Demo milestone)*. Every error message in its troubleshooting table was reproduced offline on 2026-10-18 (temporary config files, an empty key variable, mocked HTTP for the budget block; **no live call**), and the fake-mode cache example was run.
- **Linked** from `README.md`, `docs/README.md`, and the local development guide. `config/local.example.toml` stays the in-file reference; it gained a pointer to the guide and a warning against duplicate sections.
- No code changed.
