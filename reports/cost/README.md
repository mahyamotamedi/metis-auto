# reports/cost/

Stage 7 measurements (2026-10-18). They are utility measurements, not experiments with an `EXP-ID`; Stage 8 experiments go in `reports/cost/<EXP-ID>/`. Content-free: numbers only, no text and no per-message values. Method and definitions: [token_accounting.md](../../docs/architecture/token_accounting.md).

## Pipeline overhead with real tokenizers (brief §11; A-38 re-measured)

`python scripts/measure_overhead.py --requests 2000 --tokenizer <ref> [--instructions-chars N] --out …`: 2,000 SYNTHETIC walking-skeleton requests, 50 % exact-cache hits (1,000 misses, 1,000 hits), fake model, in-memory cache. The synthetic models are counted with the named tokenizer. **Hardware:** Apple M4, macOS (Darwin 25.5.0), CPython 3.13.16, tiktoken 0.14.0, tokenizers 0.23.2. **Indicative only (A-22).**

Values are p50 / p95 / max in milliseconds. *Overhead* is the sum of the spans the contracts classify as overhead (`SPAN_CATEGORY`: measure, features, route, cache lookup, context). *Context* includes counting every component with the target's tokenizer. *Request* is the whole request with the fake model.

| Tokenizer | Synthetic instructions (chars) | Miss: overhead | Miss: context | Hit: overhead | Miss: whole request | Data |
|---|---|---|---|---|---|---|
| `approx-chars-div-4` | 0 | 0.074 / 0.089 / 1.17 | 0.017 / 0.020 / 1.11 | 0.060 / 0.069 / 24.66 | 0.156 / 0.234 / 1.30 | [json](overhead-2026-10-18-approx-chars-div-4.json) |
| `openai-o200k-base` | 0 | 0.083 / 0.158 / 24.15 | 0.021 / 0.025 / 0.13 | 0.064 / 0.070 / 0.18 | 0.175 / 0.251 / 24.31 | [json](overhead-2026-10-18-openai-o200k-base.json) |
| `deepseek-v4` | 0 | 0.096 / 0.169 / 24.43 | 0.035 / 0.042 / 0.22 | 0.063 / 0.073 / 0.20 | 0.195 / 0.272 / 24.59 | [json](overhead-2026-10-18-deepseek-v4.json) |
| `openai-o200k-base` | 4,000 | 0.176 / 0.244 / 1.26 | 0.107 / 0.114 / 1.20 | 0.072 / 0.089 / 1.40 | 0.265 / 0.347 / 23.34 | [json](overhead-2026-10-18-openai-o200k-base-instr4000.json) |
| `deepseek-v4` | 4,000 | 0.774 / 0.838 / 2.32 | 0.702 / 0.735 / 2.26 | 0.074 / 0.091 / 1.49 | 0.876 / 0.958 / 24.06 | [json](overhead-2026-10-18-deepseek-v4-instr4000.json) |
| `openai-o200k-base` | 40,000 | 0.899 / 0.962 / 2.43 | 0.811 / 0.835 / 2.34 | 0.090 / 0.108 / 1.53 | 0.991 / 1.080 / 23.84 | [json](overhead-2026-10-18-openai-o200k-base-instr40000.json) |
| `deepseek-v4` | 40,000 | 6.794 / 7.057 / 13.28 | 6.698 / 6.966 / 13.17 | 0.093 / 0.141 / 1.75 | 6.912 / 7.200 / 30.45 | [json](overhead-2026-10-18-deepseek-v4-instr40000.json) |

Reading:
- Every p95 is far inside the 100 ms budget (Q-14). The ~24 ms maxima are single outliers (one in 1,000; most likely garbage collection or a first-call warm-up), not a tail.
- Exact tokenizers cost little on short requests. With long instructions, counting them dominates the overhead. The DeepSeek tokenizer (Hugging Face `tokenizers`) is about 6–8× slower than tiktoken on the same text: about 7 ms per miss at 40,000 characters. Sample instructions reach about 271,000 characters (provisional signal), so a miss could cost tens of ms with DeepSeek. Caching counts per instructions fingerprint would remove most of it (token_accounting.md §9, Stage 8).
- Hits stay cheap: the exact lookup comes before context building.

## Overhead with the sample's request sizes (Stage 8, brief §11)

`python scripts/measure_overhead.py --sizes-from-sample --tokenizer <ref> --out …`: one SYNTHETIC request per sample replay case (465), rebuilt from **sizes only** (message, instructions, each history turn, each retrieved item get filler of the same length; attachments kept present where the case had them). Every request is a miss (unique messages), so this is the worst case for counting; the synthetic models' windows were raised to 1,000,000 placeholder tokens so that nothing overflows. Same hardware as above. **Indicative only (A-22).**

Sizes (characters; provisional sample signals): message p50 29 / p95 424 / max 4,666; instructions (400 cases) 3,578 / 79,050 / 271,155; history 490 / 8,711 / 34,828 over 4 / 22 / 43 turns; retrieved (71 cases) 1,472 / 4,015 / 4,015.

| Tokenizer | Overhead p50 / p95 / max (ms) | Context p50 / p95 / max | Whole request p50 / p95 / max | Data |
|---|---|---|---|---|
| `openai-o200k-base` | 0.207 / 1.375 / 5.89 | 0.146 / 1.345 / 5.52 | 0.294 / 1.507 / 5.98 | [json](overhead-2026-10-18-sample-sizes-openai-o200k-base.json) |
| `deepseek-v4` | 0.951 / 10.22 / 57.7 | 0.915 / 11.68 / 57.4 | 1.057 / 10.34 / 57.9 | [json](overhead-2026-10-18-sample-sizes-deepseek-v4.json) |

Reading: p95 stays far inside 100 ms. The DeepSeek maximum (58 ms, the 271,155-character instructions) is the first figure that approaches the budget; a per-instructions-fingerprint token-count cache (token_accounting.md §9) would remove repeated counting, since instructions repeat heavily. Context n is 451: the 14 attachment cases have no eligible model in the synthetic catalogue, so no context is built.

## Tokenizer-specific size estimates of the sample (optional item)

[sample_token_estimates.json](sample_token_estimates.json), from `python scripts/estimate_sample_tokens.py`: per text field (user messages, answers, instructions with every occurrence and distinct texts once, retrieval queries, retrieved items), per tokenizer, and per writing-system bucket (a crude letter-count heuristic, not language detection): counts, character and token totals, median, p95, max, tokens per 1,000 characters, and the chars/4 error. **ESTIMATES of size, not billed tokens:** no chat framing, and what production really sent is unknown (A-03, TODO-04). Provisional sample signals (ADR-0008). The sample file was only read (sha256 recorded in the JSON).

Headline (Arabic-script fields; o200k / DeepSeek V4): chars/4 undercounts by 20–29 % / 33–40 %; DeepSeek needs 13–21 % more tokens than o200k for the same text. On Latin-script fields chars/4 is between −1 % and +12 %. A single correction factor can't fix chars/4, because its error depends on the script.
