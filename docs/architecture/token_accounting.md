# Token and Cost Accounting (Stage 7)

Status: **decided** (methods, fidelity rules, price schema, inclusion rules, baseline method, decomposition) in [ADR-0020](../adr/0020-token-and-cost-accounting.md); chat templates **checked** against provider-reported usage by the Stage 7.5 [live check](../references/metis_wrapper_live_check.md) (OpenAI exact for gpt-4.1-nano and gpt-4o-mini, DeepSeek fixed to V4.1 thinking mode and exact for the checked layout) but still labelled approximations; the Grok approximation **provisional** (it undercounted the check's request by 70 %, Q-33). Last updated 2026-10-18 (Stage 7.5).
Index: [architecture README](README.md). Components: CMP-09 (accounting), CMP-12 (tokenizers). Requirements: FR-ACCT-01…06, H-7, ADR-0002, ADR-0006 pt 3, [owner brief](../project/live_testing_and_demo_brief.md) §4–§6, §11.

This document answers: **for a request and an answer on a given model, how many tokens are billed, what do they cost, how sure are we, and how does the cost compare with the premium baseline?**

Code: `domain/accounting/` (pure: cost, overhead, baseline, savings), `application/accounting/service.py` (`AccountingService`), `adapters/tokenizers/` (backends), `wiring/tokenizers.py` (building them), `config/reference/tokenizers.toml` and `prices-metis-2026-10-18.toml` (data).

---

## 1. Using it

```python
from metis_auto.settings import load_settings
from metis_auto.wiring.from_settings import build_accounting_service

service = build_accounting_service(load_settings())

# AccountedUsage: usage.input / .output / .total are TokenCounts (with fidelity
# and method); cost is a Cost (price version, tier, caveats).
result = service.account(request, "gpt-4o-mini", answer_text)

# Brief §5: an estimate, never a call.
premium = service.premium_estimate(request, answer_text, "gpt-5.4")

# Brief §6: the savings decomposition of a served response.
parts = service.decompose(request, final_response, premium_model_id="gpt-5.4")
```

Provider-reported usage, when an adapter has it (Stage 7.5), is passed as `usage=` and wins over local counts. Inside the pipeline the same domain functions price every attempt, the avoided cost of a cache hit, and the spend guard's pre-call estimate.

## 2. Tokenizers: supported models, methods, fidelity

Research checked on **2026-10-18**; re-verify at the next library upgrade or catalogue change.

| Model | Tokenizer ref | Method | Fidelity | Source and evidence |
|---|---|---|---|---|
| `gpt-5-nano` | `openai-o200k-base` | tiktoken 0.14.0, encoding `o200k_base` | **exact_local** | tiktoken (OpenAI's library) `tiktoken/model.py`: `"gpt-5"` → `o200k_base` (exact key and prefix); `encoding_name_for_model("gpt-5-nano")` = `o200k_base`. |
| `gpt-4.1-nano` | `openai-o200k-base` | same | **exact_local** | same file: prefix `"gpt-4.1-"` → `o200k_base`. |
| `gpt-4o-mini` | `openai-o200k-base` | same | **exact_local** | same file: prefix `"gpt-4o-"` → `o200k_base`; also the OpenAI cookbook's example model. |
| `gpt-5.4` (premium, never called) | `openai-o200k-base` | same | **exact_local** (by family mapping, A-53; accepted by the owner, Q-31, 2026-10-18) | tiktoken's `"gpt-5"` prefix covers `gpt-5.4`. OpenAI's gpt-5.4 model page names no tokenizer, and the claim can't be checked with a call (the model is never called). The premium cost is still labelled an estimate (§6). |
| `deepseek-v4-flash` | `deepseek-v4` | Hugging Face `tokenizers` 0.23.2, the model's `tokenizer.json` | **exact_local** (A-54) | `deepseek-ai/DeepSeek-V4-Flash` on Hugging Face, MIT licence, revision `60d8d707…`, last modified 2026-06-22. The wrapper actually serves `deepseek-flash` (DeepSeek-V4.1-Flash-1017, A-58, [live check](../references/metis_wrapper_live_check.md)); its `tokenizer.json` (revision `1bae0e10…`) has the same vocabulary and merges, so content counts are unchanged. |
| `grok-4-1-fast` | `grok-approx` | characters ÷ 4 | **approximation** | No public Grok 4 tokenizer found (Hugging Face `xai-org` has Grok-1 and Grok-2 only; docs.x.ai names none). Grok-2's `tokenizer.tok.json` exists but belongs to another model generation in a custom format: not used. A `tokenize-text` API endpoint is described by third-party mirrors but was not found on docs.x.ai or in the Metis wrapper docs: not used. |
| walking-skeleton models, unknown models | `approx-chars-div-4` | characters ÷ 4 | **approximation** | The sample EDA's heuristic. |

**Files and the offline rule.** Exact backends read pre-fetched files only. `python scripts/fetch_tokenizer_assets.py` downloads them once (an explicit network step, like installing a package) into `paths.tokenizer_assets` (default `data/tokenizers/`, git-ignored), and checks each against the sha256 pinned in `tokenizers.toml`:
- `o200k_base.tiktoken`, 3,613,922 bytes, sha256 `446a9538…1a2d`, the hash tiktoken itself pins, which our download matched. It is stored in tiktoken's cache layout (file name = sha1 of the URL), so tiktoken loads it with `TIKTOKEN_CACHE_DIR` and never downloads.
- DeepSeek-V4-Flash `tokenizer.json`, 6,367,146 bytes (the Hub's listed size), sha256 `8f9f37ca…33cf`, computed from our download on 2026-10-18 and confirmed by a second, independent download. The Hub lists no hash for this file (it isn't stored in LFS), so the pin is trust-on-first-download, recorded as such.

Each adapter re-checks the hash before loading. A missing library (extra `tokenizers`) or file makes `wiring.tokenizers` fall back to chars/4 **for that ref**, with a warning. The counts then say `approximation` with method `approx-chars-div-4@1`, never `exact_local`. Tests that need the real tokenizers skip with that reason when the files are absent; they never download.

**Libraries.** `tiktoken` and `tokenizers` are imported only inside `adapters/tokenizers/` and are an optional extra (`pip install -e ".[tokenizers]"`; included in `requirements-dev.lock`, not in the runtime `requirements.lock`). Network counting (provider counting endpoints) is not implemented: none is documented for the Metis wrapper. Any future one is opt-in, off in tests, and counted against the budget (ADR-0018).

## 3. What is billed, and what is modelled

### 3.1 Inclusion rules (`TokenUsage`)

- `input` = **every billed input token**. It includes `cached_input` (provider cache hits), `cache_write` (provider cache writes), and `template_overhead` (counted chat framing). This matches how OpenAI-style usage reports prompt tokens, with cached tokens as a subset; adapters map other formats onto it (Stage 7.5).
- `output` = every billed output token, **including hidden reasoning** (`reasoning` is the reported subset). OpenAI's reasoning guide (checked 2026-10-18): reasoning tokens "are billed as output tokens", are "not visible via the API", and are reported under `output_tokens_details`.
- Instructions (system prompt), history, retrieved context, and the message are all input, counted with the target's tokenizer. Structured input is not counted yet (A-16, Stage 8).

### 3.2 Pricing a call (`domain/accounting/cost.py`)

`cost = (input − cached − cache_write) × input price + cached × cached-input price + cache_write × cache-write price (matching variant) + output × output price`, in `Decimal`, using the rows of the tier chosen by the call's input tokens (§4). A non-zero count whose price is missing gives "not computed" (`price_unknown`), never zero.

### 3.3 Chat-template (message) overhead

Providers frame each message with special tokens. For counted usage, framing comes from a `ChatTemplate` in `tokenizers.toml`: `sequence_start + Σ(prefix + suffix of each part's role) + reply_priming`.

| Family | Framing used | Source | Fidelity |
|---|---|---|---|
| OpenAI (`o200k_base`) | 3 per message + 1 role token (system, developer, user, and assistant are one token each in `o200k_base`, checked 2026-10-18) → 4 per part; 3 to prime the reply | OpenAI cookbook, "How to count tokens with tiktoken" (`num_tokens_from_messages`), stated for gpt-4o-mini-2024-07-18 and gpt-4o-2024-08-06 only. [live check](../references/metis_wrapper_live_check.md) (system + user): exact for gpt-4.1-nano and gpt-4o-mini; gpt-5-nano reported 1 fewer | approximation |
| DeepSeek V4.1, **thinking mode** (Stage 7.5) | BOS 1 + `<｜System｜>` 1 + reasoning-effort prefix 25 = 27 once; user `<｜User｜>` 1; reply primed with `<｜Assistant｜><think>` 2; first system 0; later system (retrieved) `<｜System｜>` 1; earlier assistant turns `<｜Assistant｜></think>` 2 + `<｜end▁of▁sentence｜>` 1. Each marker is one token (checked with the tokenizer). | `encoding/README.md` of DeepSeek-V4.1-Flash-1017 (revision `1bae0e10…`), "Thinking mode"; [live check](../references/metis_wrapper_live_check.md): reproduced the reported 65 prompt tokens exactly | approximation (history and retrieved layouts unverified). Replaces the V4 chat-mode template (framing 4 vs 30 reported). |
| Grok | not modelled (no source); overhead not added. [live check](../references/metis_wrapper_live_check.md): 98 prompt tokens reported vs 29 counted by chars/4 for the system + user request (Q-33) | — | — |

Assumption **A-55**: the Stage 7.5 adapter sends each input part as one message, with retrieved context as its own system-role message. If it merges parts, the template overcounts slightly.

**Fidelity is strict:** a counted input's fidelity is the worse of content and framing, so counted inputs are `approximation` even when the content is exact. `template_overhead` is reported separately, so the UI can show "content exact, ≈ N framing tokens".

### 3.4 Modelled vs not modelled

| Billed item | Modelled? |
|---|---|
| Separate input and output prices | **yes** |
| Instructions, history, retrieved context, message | **yes**, target tokenizer |
| Chat-template framing | **yes**, approximation (OpenAI, DeepSeek); **no** for Grok |
| Provider-cached input (discounted) | **yes**, from provider-reported cached tokens; never predicted locally |
| Provider cache writes | **yes** in the schema (variant by TTL); none of the six models lists a cache-write price on the Metis page (2026-10-18) |
| Hidden reasoning (billed as output) | **yes** when reported; when counted from the visible answer of a model with a verified `hidden_reasoning_billed_as_output` capability, the cost is a **lower bound** (caveat `reasoning_not_counted`). Verified for `gpt-5-nano`, `gpt-5.4`, and `deepseek-v4-flash` (thinking on by default through the wrapper: 30 reasoning tokens inside the output, [live check](../references/metis_wrapper_live_check.md)). **Not verified:** Grok 4.1 Fast, whose usage through the wrapper has no reasoning field (Q-33). |
| Context-length price tiers | **yes** (§4) |
| Attachments (images) | **no**: content is never inspected (NG-07), so image tokens are missing from counted input; reported usage includes them |
| Structured input, tool and function definitions | **no** (A-16; wrapper mode disables function calling) |
| Per-call fees, search queries, audio | **no** (not used; the price reader rejects unknown price keys) |
| Batch, flex, regional uplift | **no** (not used by Metis-Auto) |
| Provider rounding and billing granularity | **no** (Decimal totals per call) |

## 4. Price schema

`PriceEntry`: `price_ref`, `token_type` (`input`, `output`, `cached_input`, `cache_write`, `reasoning`), `amount` (decimal; None = unknown), `per_tokens`, `currency`, `effective_from`, `evidence` (source and check date), and optionally:
- `tier`, `min_input_tokens`, `max_input_tokens` (inclusive bounds on the call's **input** tokens). The tier chosen by the input prices **every** token type of the call: OpenAI's gpt-5.4 page (checked 2026-10-18) says prompts above the threshold "are priced at 2x input and 1.5x output for the full session";
- `max_input_tokens_uncertain_up_to`: the source's bound may really be this high. Inputs between the two bounds are priced at the more expensive tier and flagged `context_tier_boundary_uncertain`;
- `cache_ttl` (cache writes only): the variant, e.g. `ttl-5m`, matched against `TokenUsage.cache_write_ttl`.

`PriceTable` rejects overlapping tiers for the same price ref, token type, and variant. In TOML, one `[[prices]]` row per tier, with amounts keyed by token type; `cache_write` may be a table of variants (`{ "ttl-5m" = "6.875", "ttl-1h" = "11" }`).

**gpt-5.4's "≤ 270K" (A-52 resolved).** The Metis page says "≤ 270K context" and doesn't define K. OpenAI's own page uses ">272K input tokens", a different figure, so the Metis wording can't be cross-checked. **Chosen: the conservative reading.** The standard tier ends at **270,000** input tokens, so no call is priced below the bill. Inputs of 270,001–276,480 (the 1,024-based reading) get the long-tier price plus the caveat. For the premium baseline, this reading can only *raise* the estimate in that narrow band, and the caveat says so. "Context" is read as the call's input tokens. Our requests are far below the threshold (the largest sample instructions count 84,834 o200k and 92,342 DeepSeek tokens, §8).

**Adding a model or a price needs configuration only:** a catalogue row (`tokenizer_ref`, `price_ref`), price rows, and, for a new tokenizer family, a `tokenizers.toml` row using an existing backend (`tiktoken` encoding, Hugging Face `tokenizer.json` with URL and sha256, or `approx_chars`). A new tokenizer *format* is one small adapter in `adapters/tokenizers/` plus a `TokenizerBackend` value. A price change is a new dated price file (A-47).

## 5. Cost caveats

Every computed `Cost` carries `caveats` (`CostCaveat`), shown with the figure:

| Caveat | When |
|---|---|
| `reasoning_not_counted` | Lower bound: a model that bills hidden reasoning, with output counted from the visible answer |
| `answer_length_assumed` | Baseline estimate: another model's answer stands in for the baseline model's |
| `template_overhead_approximated` | Counted input includes unverified chat framing |
| `context_tier_boundary_uncertain` | Input in the ambiguous band of a tier bound |
| `cached_input_not_reported` | Provider usage had no cached-token count, so all input was priced uncached (an upper bound) |

## 6. Premium-baseline estimate (brief §5)

`AccountingService.premium_estimate` → `domain.accounting.baseline_estimate`. **No premium API call ever:** `gpt-5.4` is disabled in the catalogue, and nothing in this path calls a model.
- **Input:** the full, uncompressed request (instructions, history, every retrieved item, message), counted with the premium model's tokenizer, plus its chat framing. No provider cache.
- **Output:** the answer actually served (by the cheap model, or from cache), re-counted with the premium tokenizer. Assumption: the same answer length.
- **Labelled** `basis = baseline_estimate`, `baseline = "premium"`, with caveats: always `answer_length_assumed`; `reasoning_not_counted` (gpt-5.4 supports reasoning, so the estimate is a lower bound, though its default effort is "none" per OpenAI's page); `template_overhead_approximated`; the tier caveat when it applies.
- **UI caveats (Demo):** premium answers may differ in length; reasoning models add hidden tokens, so this is a lower bound.

## 7. Savings decomposition (brief §6)

`domain/accounting/savings.py`, pure, in `Decimal`, per message (`decompose_message`) and summed per session (`sum_decompositions`):

```
  premium baseline        premium model, full context (§6)
− routing saving          premium − chosen model, both on the full context
− compression saving      chosen model: full − sent (compressed) context
− cache saving            on a hit: the chosen model's cost on the sent context; else 0
− provider-cache saving   on a miss: the cached-input discount on the answering call; else 0
+ extra cost              Metis overhead, failed / retried / escalated attempts,
                          local-vs-reported count differences (the remainder)
= actually paid           the request total
```

- **Why `extra cost`:** the brief's five terms sum exactly only when one call answers and local counts equal the bill. Retries, escalations, router or judge calls, and count differences are real money. The remainder term puts them in view, so the identity always holds exactly. The contract validator checks the sum.
- "Chosen model" is the model that produced the answer (on a hit, pass `chosen_model_id` to use the routing target). The chosen-model costs use the served answer's output (provider-reported when available) and no cache discount.
- A term whose inputs are not computed is "not computed", never zero. Sums are not computed if any message's term is not computed.
- `AccountingService.decompose` builds the inputs from a `FinalResponse`. The Demo UI reads it through wiring.

## 8. Measurements

**chars/4 vs exact tokenizers, SYNTHETIC texts** (pinned in `tests/unit/adapters/test_adapters_tokenizers.py`):

| Text | chars | o200k | DeepSeek V4 | chars/4 | chars/4 error vs o200k / DeepSeek |
|---|---|---|---|---|---|
| Persian | 140 | 42 | 54 | 35 | −17 % / −35 % |
| English | 131 | 30 | 31 | 33 | +10 % / +6 % |
| mixed Persian/English | 107 | 29 | 34 | 27 | −7 % / −21 % |
| code | 116 | 40 | 42 | 29 | −28 % / −31 % |

**Sample text fields** (an *estimate of size*, not billed tokens; aggregates only; ADR-0008 provisional signal): [reports/cost/sample_token_estimates.json](../../reports/cost/sample_token_estimates.json), from `scripts/estimate_sample_tokens.py`. chars/4 **undercounts** Arabic-script fields by about 20–29 % against o200k and 33–40 % against DeepSeek; on Latin-script text it is between −1 % and +12 %. Arabic-script content costs the DeepSeek tokenizer 13–21 % more tokens than o200k. Summary: [reports/cost/README.md](../../reports/cost/README.md).

**Overhead with real tokenizers** (brief §11, A-38 re-measured): see [reports/cost/README.md](../../reports/cost/README.md).

## 9. Open items

| Item | Resolved by |
|---|---|
| ~~Templates vs provider-reported usage; whether the wrapper reports cached and reasoning tokens~~ checked 2026-10-18 (live check); Grok overhead and a real provider-cache hit remain (Q-33) | Stage 7.5 live check |
| ~~DeepSeek thinking mode~~ verified (on by default; keep or disable: Q-34); Grok reasoning (no field reported) | Q-33, Q-34 |
| gpt-5.4 tokenizer by family mapping (A-53): **accepted** (Q-31, 2026-10-18); re-check at each tiktoken upgrade | an OpenAI statement if one appears |
| ~~Label mapping (logged label → catalogue model) for the as-logged baseline~~ **done in Stage 8**: `config/reference/label-mapping-sample-v1.toml` (contracts.md O-3) | Stage 8 |
| Structured input and attachment tokens | Stage 8 (A-16), and live reported usage |
| Repeated instruction counting dominates overhead with large instructions (§8); a per-fingerprint count cache would remove it | Stage 8, if realistic sizes make it matter |
