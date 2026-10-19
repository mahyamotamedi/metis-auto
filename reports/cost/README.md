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

## Overhead in Demo A: detectors on, LLMLingua-2 off and on (Demo milestone, 2026-10-19; brief §9, §11)

`python scripts/measure_overhead.py --sizes-from-sample --tokenizer <ref> --compression off|llmlingua2 [--compress-rate 0.5] --out …`: the same 465 SYNTHETIC sample-sized requests as above (all misses), now with the Demo A feature detectors (language, code, length bucket, greeting, and the same for every earlier user turn). With `llmlingua2`, every history turn and retrieved item of at least 200 characters is compressed at rate 0.5 (instructions and the message never). Hardware: Apple M4, macOS (Darwin 25.5.0), CPython 3.13.16, CPU only. The LLMLingua-2 run used torch 2.14.1, transformers 5.18.0, llmlingua 0.2.2 (the versions of the `compress` extra), model revision `ebaba9b0…`. **Indicative only (A-22).** The texts are repeated synthetic filler: the **times** reflect the lengths; the compression **rates** do not reflect real text.

| Run | Overhead p50 / p95 / max (ms) | Features p50 / p95 | Compression p50 / p95 / max (ms) | Input tokens sent (sum over 451 contexts) | Data |
|---|---|---|---|---|---|
| o200k, compression off | 0.416 / 1.94 / 6.15 | 0.169 / 0.654 | — | 1,377,163 | [json](overhead-2026-10-19-demo-sample-sizes-openai-o200k-base-compression-off.json) |
| DeepSeek, compression off | 1.19 / 10.6 / 61.3 | 0.167 / 0.655 | — | 1,672,741 | [json](overhead-2026-10-19-demo-sample-sizes-deepseek-v4-compression-off.json) |
| o200k, **LLMLingua-2 on** | **316 / 3,123 / 6,163** | 0.203 / 0.785 | **317 / 3,124 / 6,160** | 1,262,036 (−8.4 %) | [json](overhead-2026-10-19-demo-sample-sizes-openai-o200k-base-compression-llmlingua2.json) |

With LLMLingua-2: 1,062 texts compressed and 2,195 left alone (shorter than 200 characters); 800,637 → 423,839 characters and 311,829 → 153,691 of its own (cl100k) tokens.

Reading:
- **The detectors are cheap:** features cost p50 0.17 ms and p95 0.65 ms with every history turn checked; the overhead stays far inside 100 ms without compression (the DeepSeek maximum is still the large-instructions count, as in Stage 8). Sticky routing itself: below 0.08 ms per decision with 43 earlier turns (micro-benchmark of `StickyPolicy.choose`).
- **LLMLingua-2 on CPU is far outside the 100 ms budget:** p50 about 0.3 s, p95 about 3 s, up to 6 s for the longest histories. On real traffic it would need a GPU, a smaller model, caching of compressed history per session prefix, or compressing only once per turn as history grows (each turn re-compresses the whole history today).
- **The target-token saving is small on this composition (−8.4 %),** because instructions dominate input and are never compressed (context plan §1). It is a saving at the cheapest price (the savings decomposition's compression term), against a large latency cost; and compressed history breaks the provider's prefix cache for everything after it (caching plan C5).
- Quality is unmeasured (needs the ablation, context plan §2); on SYNTHETIC Persian text it drops the ZWNJ (A-67).
