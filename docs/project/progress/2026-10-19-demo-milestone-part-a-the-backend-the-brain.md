## Demo milestone, part A — the backend ("the brain") (2026-10-19)

Owner request of 2026-10-19: Demo A only (no UI; that is Demo B). Decision record: [ADR-0023](../../adr/0023-demo-backend-components.md). Every component is a **placeholder demo component** (repository_structure §6.2 steps 2–5, no evidence step); **serving defaults are unchanged** (`fixed_model`, `session` scope, full key, `pass_through`, no compression, providers' default thinking).

### Outputs
1. **Detectors** (`domain/features/detectors.py`, pure, tested on SYNTHETIC Persian, English, and mixed texts): language (fa, en, mixed, other, undetermined), code, length bucket, greeting / small talk (configured Persian + English phrase list). Feature set `fs-0.2.0-demo`; per-turn history features with each answer's producer.
2. **Rule-based routing** (`domain/routing/rule_based.py`): placeholder rules in `[pipeline.routing.rule_based]` → tier → cheapest **effective** cost (expected hidden reasoning billed as output; 0 when thinking is disabled). Nominal price would choose gpt-5-nano; with its reasoning it ranks last in tier 0.
3. **Sticky routing v1** (`domain/routing/sticky.py`), brief §7, modes `sticky_v1` / `per_request` in `[pipeline.routing.sticky]`; stateless reconstruction of the anchor from `Turn.producer`. **A-64 resolved:** `Turn.producer` (tri-state), **contract schema 0.4 → 0.5** (also `TurnFeatures`, `RoutingDecision.anchor_model_id`, `ContextAction.COMPRESSED`, the `context_compressed` event, span `context.compress`, `IneligibleReason.NOT_FIRST_TURN`); `contracts_reference.md` regenerated.
4. **Demo caching:** `scope_rule = "demo_bot_level"` (S-b shape, labelled DEMO) and the **demo seed** (5 first-turn clean sample answers under the message-only `demo_seed_msg_only` key; local only, never sent; off by default; `wiring/demo.py`, `RequestPipeline.seed_demo_entry`).
5. **LLMLingua-2** (EXPERIMENTAL, off by default): `ports.TextCompressor`, `adapters/compressors/llmlingua2.py` (+ labelled fake), `domain/context/compression.py` (history and retrieved only; never instructions by default; never the message), `wiring/compression.py`; extra `compress` with its own lock `requirements-compress.lock`; pinned weights in `config/reference/compressors.toml`, fetched by `scripts/fetch_compressor_assets.py` (2.2 GB, done and verified on this machine). Original LLMLingua not built (ADR-0023 point 7, Q-40).
6. **DeepSeek thinking** per request option: `mode_templates.thinking_disabled` in `tokenizers.toml` (`-2026-10-19-demo`), used per model by wiring; framing 30 → 5 tokens (system + user); routing cost model updated.
7. **`scripts/chat.py` / `wiring/chat.py`:** routing decision and reason, features, cache lookups, served by, model, tokens, cost, premium estimate, full decomposition, compression, overhead, budget, settings; commands `/mode`, `/model`, `/compress on|fake|off`, `/botcache`, `/seed on|off|list`, `/thinking`, `/newuser`, `/instructions`, `/degrade` (offline escalation). Toggles rebuild the pipeline but keep the cache store and the fingerprint key.
8. **Overhead re-measured** ([reports/cost](../../../reports/cost/README.md)): detectors p95 0.65 ms; overhead p95 1.9 ms (o200k) / 10.6 ms (DeepSeek) with compression off; **LLMLingua-2 on: p50 0.32 s, p95 3.1 s, max 6.2 s** on CPU; input tokens sent −8.4 % on the sample's sizes (instructions dominate).
9. **Docs:** ADR-0023; routing.md §6 (with a sticky-routing diagram), caching.md §6, context_construction.md §6, contracts.md, token_accounting.md §3.3, module_reference (17 rows), the three plans, live check note, ADR-0016 note, GLOSSARY, CLAUDE.md, README, docs index, local_development guide, `config/local.example.toml`, **demo_quickstart.md** (terminal demo, walkthrough, what Demo B adds).

### Validation
- **Full suite: 636 passed, 3 skipped** (the opt-in network test; the 2 real-LLMLingua-2 tests, which skip without the extra), offline, warnings as errors. New: detectors (45), routing (21), demo cache and compression decisions (7), demo backend end to end over fakes (12: anchoring through producers, escalation raising the anchor, per-request and fixed modes, bot-level cross-user hit with no model call, seed served without a model call and only on first turns, compression accounting and instructions untouched, thinking templates, failed toggle restores settings, producer contract, producer not in the fingerprint, missing sample file), compressor adapters (7), an import test (compression libraries only in their adapter).
- With `requirements-compress.lock` installed (`--require-hashes`; no dev-lock pin changed): **638 passed, 1 skipped**, the real LLMLingua-2 tests included (SYNTHETIC English and Persian texts, ≈ half its tokens kept, about 310 ms each). `chat.py --fake` with `/compress on` and a SYNTHETIC retrieved document: 86 → 42 compressor tokens, 404 ms, a non-zero compression saving. The LLMLingua-2 overhead benchmark ran with the same library versions from a scratch environment while the lock was compiling (pip-compile downloads every torch wheel, 7.6 GB, to hash it).
- ruff clean; import rules and module reference pass; raw sample data unchanged (sha256 `e0f56a2f…49e1`); **no live call**; `.env` never opened by me.

### Decisions, assumptions, questions
- ADR-0023. Register: **A-64 decided**; A-65 (detector placeholders), A-66 (expected reasoning placeholders), A-67 (LLMLingua-2 latency, ZWNJ loss), A-68 (DeepSeek thinking-off layout), A-69 (no attachments in `Turn`), A-70 (greeting in an anchored session); **Q-40** (skip original LLMLingua?), **Q-41** (greeting → cheapest or stay on the anchor?), **Q-42** (mimo-v2.5 after 2026-10-21 in live demos); **TODO-14** (compress lock on Linux).
- Live check of the whole flow: proposed with an upper bound of 0.0021 USD (cap 512); approved and run in the follow-up below.

### Carried into Demo B and later
- **Demo B:** the Streamlit UI over `ChatSession` / `TurnReport`, bot-setup presets (synthetic), cost panel, quickstart §7 completion and the fresh-clone walkthrough.
- **Stage 8 plans:** exp-route-002 / -010 replace the rules and sticky settings with evidence; context X3 ablation (quality, Persian stratum); caching C4/C5 (sticky variants and provider-cache warmth, Q-41).

**Exit criteria (Demo A):** every item of the request is implemented, tested offline with fakes, and usable from the terminal; the overhead benchmark was re-run with LLMLingua-2 on and off and recorded; the quickstart covers the terminal demo and lists Demo B. **Met**, pending review.

### Demo A follow-up — owner answers Q-40, Q-41, Q-42 and the live check (2026-10-19)

| Item | Status | Answer and what was done |
|---|---|---|
| Q-40 | answered | Skip original LLMLingua until a GPU or a small Persian-capable LM is available; documented as a **deferred** arm (context plan X4, ADR-0023 amendment 1). |
| Q-41 | answered | **Greetings in an anchored session stay on the anchor** (`sticky.greeting.stay`); the cheapest model only while unanchored (or if the anchor is ineligible). Done: `domain/routing/sticky.py`, `wiring/chat.py` label, tests (+2 routing cases, the end-to-end test extended), routing.md §6 diagram, routing plan §5, glossary, quickstart walkthrough, ADR-0023 amendment 1; **A-70 decided**. |
| Q-42 | answered | On 2026-10-21 the owner checks the Metis pricing page: switch to the new MiMo ID if listed (configuration only), otherwise `mimo-v2.5` `enabled = false` (routing falls back to the next-cheapest model). Procedure: demo_quickstart.md troubleshooting, "MiMo after 2026-10-21"; TODO-13 updated. |
| Live check | **run** (owner-approved, cap 512) | `scripts/demo_live_check.py` + `wiring/demo_check.py` (plan by default; `--run`). Exact plan first: 9 calls came to 0.002971 USD, above the approval, so two offline-covered steps were dropped → **0.002057 USD for 7 calls**; the run's spend cap was set to 0.0021 USD so the guard enforced it. **Charged 0.000271 USD**; ledger 0.002623 USD of 10. [Results](../../references/metis_demo_live_check.md). |

**Live-check findings:** reported input = locally counted input on all 7 calls (framing included, four layouts); **A-68 decided** (DeepSeek thinking-off template verified, also with a history turn: 76 = 76); sticky v1, the anchored greeting, the code re-route, and the bot-level cross-user cache hit behaved as designed on live answers; MiMo billed 14–46 reasoning tokens (placeholder 12, A-66 updated; still cheapest in tier 0) and took 3–13 s per call; LLMLingua-2 on the live path: 86 → 42 tokens in 414 ms. `mimo-v2.5` still accepted on 2026-10-19.

**Changes:** code `domain/routing/sticky.py`, `wiring/chat.py` (`last_trace`, greeting label), new `wiring/demo_check.py`, new `scripts/demo_live_check.py`; config `tokenizers.toml` (`-demo-lc`, evidence only); tests (routing +2, end-to-end extended, mocked-HTTP test of the live check); docs: the live check results (md + JSON), ADR-0023 amendment 1, register, routing.md, routing plan, context plan, glossary, quickstart, docs index, module reference.

### Demo A follow-up — coding intent (2026-10-19)

Owner request: the gap found while testing ("write a python function to add two numbers" has `code no`, so sticky routing stayed on the anchor). ADR-0023 **amendment 2**; register **A-71** (placeholder, A-65 style).

**Changes:**
- **Detector** `detect_coding_intent` in `domain/features/detectors.py` (`CodingIntentConfig`): true when the message has **no code** and either a word template matches ("write ... function", «تابع ... بنویس») or a keyword and a request cue both appear (after removing exclusions such as «کد تخفیف» and "discount code"). The lists are placeholders in `[pipeline.features.coding_intent]` (`config/defaults.toml`), in English and Persian. Feature set `fs-0.3.0-demo`. Cost at most 0.42 ms on a 2,000-character message, 0.003 ms on a short one (configured lists normalised once and cached).
- **Contract schema 0.5 → 0.6:** `RequestFeatures.has_coding_intent`, `TurnFeatures.has_coding_intent`; `contracts_reference.md` regenerated.
- **Rules:** `RuleCondition.has_coding_intent`; placeholder rule `coding_intent` → tier 1 (after `code`).
- **Sticky v1:** a new "very different" reason, `coding_intent_appeared`. It fires only when the intent **appears** against an anchor with neither code nor intent, so a follow-up without it stays.
- **Chat:** the features line shows `coding_intent yes|no`.
- **Tests (+35):**
  - detectors: mechanics, never with code present, empty configuration;
  - 26 SYNTHETIC English, Persian, and mixed cases on the shipped lists, including prose that mentions programming without asking;
  - the stated false positive (a customer's payment error with «چطور»);
  - routing: rule, re-route, follow-up stays, an anchor with code, unknown never satisfies a rule;
  - end to end over fakes: your exact message re-routes to tier 1 and a follow-up stays.
- **Docs:** ADR-0023 amendment 2, register (A-71), routing.md §6 (diagram and text), routing plan §5 and P1, contracts.md §6, module reference, glossary, quickstart (walkthrough step 4, features line), docs index.

**Validation:** 675 passed, 1 skipped (the opt-in network test), offline; ruff clean; no live call.

**Not changed:** a follow-up without the intent stays on the anchor; only appearing counts, by design. Code disappearing still re-routes even when the new message has a coding intent (the rules then send it to tier 1 again).
