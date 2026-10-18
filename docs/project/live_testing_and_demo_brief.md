# Metis-Auto: Live Testing & Demo Brief (decisions from 2026-10-18)

Owner decisions made outside Claude Code. Read before Stages 6, 7, 8 and the Demo milestone.
Record each decision in the register / ADRs as the stage that implements it is reached.
Sources live next to this file: `metis-docs/` (saved Metis docs pages) and
`metis_pricing_extracted.csv` (+ `metis-pricing-rendered.html`), saved 2026-10-18 from https://docs.metisai.ir/pricing.
Do NOT read or copy `metis-docs/metis-docs-api-keys.html` (a dashboard page, not needed).

---

## 1. Purpose and budget (answers Q-08)
- One **Metis API key**, used ONLY for development and testing (real answers to test the pipeline and the demo). No production use.
- **Total budget for the whole project: 20 USD.** Every live call counts: chat models, LLM judges, paid embeddings, token-counting APIs.
- **Spend ledger must be persistent and cumulative across ALL runs** (a gitignored file, e.g. under `runs/` or `data/`), not per run. The spend guard blocks any call whose pre-call estimate would push the lifetime total over the cap.
  - Defaults: lifetime cap 20 USD; small per-run cap (propose, e.g. 1 USD); warnings at 50% and 80% of the lifetime budget. Configurable, never above 20 USD total.
- Live calls only with the owner's own or synthetic test messages. Sending sample-data conversations to a provider needs explicit owner approval per run plus the privacy review (ADR-0003). Not allowed by default.
- All live answers go through the recording wrapper (pay once, replay free).
- Remind the owner to also set a spending limit in the Metis dashboard as a second safety net, if Metis offers one.

## 2. Secrets
- `.env` (already in `.gitignore`) holds only `METIS_API_KEY=` with a comment saying the owner pastes the key there. Claude Code creates the file with an empty value; the owner pastes the key. Never read, print, log, or commit the key.
- `.env.example` (committed) mirrors it with placeholders.
- Base URLs, model IDs, tiers, prices are **config** (`config/`), not secrets.

## 3. Metis wrapper API (from the saved docs)
All endpoints use the same Metis key. The model is chosen per request; the full message list is sent each time (fits P-8).

| Family | Base URL | Format |
|---|---|---|
| OpenAI | `https://api.metisai.ir/openai/v1` | OpenAI chat completions, `Authorization: Bearer <key>` |
| DeepSeek | `https://api.metisai.ir/deepseek/v1` | OpenAI-compatible |
| Grok (xAI) | `https://api.metisai.ir/api/v1/wrapper/grok` | OpenAI-compatible |
| Gemini | `https://api.metisai.ir` | Google `google-genai` format, `x-goog-api-key` header. NOT OpenAI-compatible → **deferred** (second adapter later) |

Notes:
- Wrapper mode disables Metis bot features (knowledge bases, function calling). Metis-Auto supplies its own instructions and retrieval context.
- DeepSeek silently redirects legacy names (`deepseek-chat`, `deepseek-reasoner`) to `deepseek-v4-flash`: always send exact IDs; record the provider-reported model.
- Metis says not every provider feature is fully covered. Before relying on them, a tiny live check (fractions of a cent) must confirm the wrapper returns: token usage, finish reason, cached-token counts. Record results with date.
- The OpenAI endpoint also serves embeddings (e.g. `text-embedding-3-small`): an option for the semantic cache later (counts against the budget).

## 4. Models
**Test models (development and demo only; quality testing later uses all models):**

| model_id | Family | Input $/1M | Output $/1M | Cached input $/1M | Note |
|---|---|---|---|---|---|
| gpt-5-nano | OpenAI | 0.055 | 0.44 | 0.0055 | reasoning model: hidden reasoning tokens are billed as output |
| gpt-4.1-nano | OpenAI | 0.11 | 0.44 | 0.0275 | |
| gpt-4o-mini | OpenAI | 0.165 | 0.66 | 0.0825 | most-used OpenAI model in the sample |
| deepseek-v4-flash | DeepSeek | 0.165 | 0.66 | 0.0033 | most-used model in the sample |
| grok-4-1-fast | Grok | 0.22 | 0.55 | 0.11 | |

**Premium baseline (never called):** `gpt-5.4`: input 2.875, output 17.25, cached 0.2875 $/1M for ≤270K context; long-context prices 5.75 / 25.875 / 0.575.

Prices are **Metis's user prices in USD** (≈10–15% above provider list prices), from the Metis pricing page saved 2026-10-18. The price schema must support: cached input, cache writes, and **context-length price tiers** (≤270K vs long context).

## 5. Premium baseline method (no API call)
- Input: count the same full context (uncompressed, no cache) with the premium model's tokenizer, locally (verify in Stage 7 that an official local tokenizer exists for gpt-5.4).
- Output: re-count the cheap model's actual answer text with the premium tokenizer (assumption: same answer length).
- Label everything as an estimate. Caveats shown in the UI: premium answers may differ in length; reasoning models add hidden tokens (lower bound).

## 6. Savings decomposition (fixed order, sums exactly)
```
Premium baseline (premium model, full context)
 − routing saving     (premium → chosen model, full context)
 − compression saving (full → compressed context, at the chosen model's price)
 − cache saving       (whole call avoided on a hit; the routed model's cost)
 − provider-cache saving (cached-input discount reported by the provider)
 = actually paid
```
Per message and per session.

## 7. Routing: "sticky routing v1" (placeholder rules, all in config)
- Stateless: each history turn records who produced it (model ID or `cache`); the policy reads it from the request.
- A message **anchors** the session only if it is **substantive**. Not substantive: served from cache, or a greeting/small talk (short message matching a configurable Persian+English phrase list, e.g. سلام, hi, thanks, مرسی, ok). Non-substantive messages go to the cheapest model and leave the session unanchored. (Do not use "short = trivial": sample messages are short; median ≈ 29 chars.)
- Anchored + similar message → stay on the anchor model.
- Anchored + very different message → re-route and re-anchor. "Very different" = cheap feature changes only: code appears/disappears, attachment appears, language switch, length bucket jump.
- Unsatisfactory answer (detectors) → escalate; the session anchors to the stronger model (only up, never down).
- Rule-based initial routing over features maps to one of the 5 test models.
- Stage 8 experiment compares: per-request routing; sticky v1 (re-route after a cache hit); sticky with "stay after a cache hit" (keeps provider cache warm); per-bot.

## 8. Caching in the demo
- Live session cache, exact tier (always on).
- Demo bot-level scope (ADR-0016 shape): same instructions + same retrieval context ⇒ shared across "users" of that bot. Clearly labelled demo setting, not the serving default. A "new user" button shows cross-user hits.
- Optional demo seed: a few sample first-turn questions with logged answers, using a demo-only message-only key, clearly labelled; logged answers shown locally only, never sent to a provider.

## 9. Context reduction in the demo
- LLMLingua-2 (xlm-roberta-large) as an **experimental, labelled toggle**; original LLMLingua optional (heavy). Unpromoted: needs ablation evidence.
- Persian quality unknown (trained on English MeetingBank): measure.
- Show compression time; it counts as overhead (100 ms p95 budget).
- Heavy dependencies (torch, transformers, llmlingua) in an **optional extra**, never in the runtime lock.
- Never compress instructions by default.

## 10. Demo UI (Streamlit, thin wrapper over `wiring`, no logic in the UI)
- Chat window; the UI holds the history and sends it each turn (P-8).
- **Bot setup sidebar:** instructions box, retrieval-context box (one document per block), and **synthetic presets** (e.g. a Persian e-commerce support bot, an English FAQ bot) with long instructions and documents. Never copied from the sample.
- Toggles: routing mode (sticky v1 / per request), compression on/off, demo cache seed on/off, bot-level cache scope on/off.
- **Cost panel**, per message and session: actually paid; premium-baseline estimate; savings by routing, compression, cache and provider cache (§6); tokens; served by (cache / model); model; overhead; budget used vs 20 USD.

## 11. Overhead benchmark
A-38 was measured ad hoc. Add `scripts/measure_overhead.py`: N walking-skeleton requests, p50/p95/max per span, hit/miss mix, hardware. Re-run in Stage 7 (real tokenizers), Stage 8 (realistic sizes), and the Demo milestone (LLMLingua, live calls).

## 12. Where each part lands
| Stage | Content from this brief |
|---|---|
| 6 | `.env` + `.env.example`; `Settings`; config files: catalogue (5 test models + premium, base URLs, tiers) and price table (§4, with source and date); persistent cumulative spend ledger and caps (§1); Docker |
| 7 | Tokenizers for the 6 models (verify local tokenizer availability); price schema with cached input, cache writes, context tiers; premium-baseline estimate (§5); overhead benchmark script (§11) |
| 7.5 (new, small) | Live OpenAI-compatible adapter (one adapter, base URL per family; SDK auto-retries off; normalised errors; provider-reported usage, finish reason, cached tokens, model); the live wrapper check (§3); `scripts/chat.py` CLI |
| 8 | As planned + sample loader, pairing heuristic, replay-case builder pulled forward from Stage 9; sticky routing experiment plan (§7) |
| Demo milestone (after 8) | Rule-based + sticky routing v1; LLMLingua-2 strategy; demo cache scope + seed; savings decomposition (§6); Streamlit UI (§10) |
| 9–10 | As planned; Gemini adapter goes on the Stage 10 roadmap |
