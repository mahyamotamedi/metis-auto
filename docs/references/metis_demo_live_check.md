# Demo A: live check of the whole flow (2026-10-19)

The owner-approved live check of the Demo A backend ([ADR-0023](../adr/0023-demo-backend-components.md) amendment 1): one scripted chat session through the real pipeline, spend guard, persistent ledger, and recording decorator, with SYNTHETIC messages written for the check.

- **Run:** 2026-10-19, 07:34 UTC, run ID `demo-check-20261019T073409Z-c153f5`, approved by the owner with a 512-token output cap. Script: `scripts/demo_live_check.py --run` (logic in `wiring/demo_check.py`).
- **Raw results** (content-free: no answer text): [metis_demo_live_check_2026-10-19.json](metis_demo_live_check_2026-10-19.json). The answers are only in `data/recorded/` (git-ignored).
- **Estimate first:** the plan (no call) summed the spend guard's pre-call estimates of every call. It assumed every earlier answer was the full 512 tokens, so history was not underestimated. The first plan was 0.002971 USD (9 calls), above the approved 0.0021, so two steps were dropped: the unanchored greeting and a plain follow-up. Both are covered offline. **Final plan: 0.002057 USD for 7 calls** (0.003541 if every call had escalated once). The run's spend cap was set to 0.0021 USD, so the guard itself enforced the approval.
- **Charged: 0.000271 USD** (7 calls, all `complete`, no retry, no escalation). Lifetime ledger total afterwards: **0.002623 USD** of 10.
- **Configuration:** catalogue `cat-metis-test-2026-10-18-s75`, prices `prices-metis-2026-10-18-s75`, tokenizers `tokenizers-2026-10-19-demo`, compressors `compressors-2026-10-19`; instructions "[SYNTHETIC] You are the assistant of a demo shop in a test. Answer in one or two short sentences."

## Results

| Step | Routing reason | Served by / model (reported) | Input reported = counted (framing) | Output (reasoning) | Cost USD | Model call |
|---|---|---|---|---|---|---|
| first substantive (Persian question) | `sticky.first_substantive.rule.default` | model / mimo-v2.5 (`mimo-v2.5`) | **49 = 49** (11) | 113 (46) | 0.000042 | 13.1 s |
| greeting after anchoring («مرسی») | **`sticky.greeting.stay`** (Q-41) | model / mimo-v2.5 | **127 = 127** (21) | 43 (14) | 0.000033 | 3.3 s |
| code message | `sticky.reroute.code_appeared.rule.code` | model / gpt-4o-mini (`gpt-4o-mini-2024-07-18`) | **141 = 141** (27) | 98 (0) | 0.000088 | 1.6 s |
| bot-level cache, user 2 | `sticky.first_substantive.rule.default` | model / mimo-v2.5 | **53 = 53** (11) | 79 (32) | 0.000032 | 10.2 s |
| bot-level cache, user 3, same question | (same) | **cache** (`full/global: hit`), no call | — | — | 0 | — |
| DeepSeek, thinking disabled, turn 1 | `fixed_model` | model / deepseek-v4-flash (`deepseek-flash`) | **41 = 41** (5) | 20 (not reported) | 0.000020 | 1.9 s |
| DeepSeek, thinking disabled, turn 2 (history) | `fixed_model` | model / deepseek-v4-flash (`deepseek-flash`) | **76 = 76** (9) | 22 (not reported) | 0.000027 | 1.1 s |
| LLMLingua-2 on a retrieved document | `sticky.first_substantive.rule.default` | model / mimo-v2.5 | **92 = 92** (15) | 46 (21) | 0.000028 | 3.1 s |

Session decomposition (USD): premium baseline 0.006296; routing saving 0.005996; compression saving 0.000007; cache saving 0.000022; provider-cache saving 0; extra cost 0; **actually paid 0.000271**.

## Findings

1. **Counting is exact on every call.** Reported prompt tokens equal our local count, chat framing included, for all 7 calls and 4 layouts. The layouts were: system + user; with history (two and four earlier turns); with a retrieved system message (MiMo, thinking on); and DeepSeek with thinking disabled, with and without a history turn. The templates stay labelled approximations by rule; the evidence is now broader.
2. **A-68 verified.** The DeepSeek thinking-off template counts 5 framing tokens for system + user and 9 with one earlier exchange. Of the two candidate layouts, 9 fits the configured one, `<BOS><System>…<User>…<Assistant></think>`, and not the other (which would give 10). With thinking disabled, DeepSeek reported no reasoning field, and the request body carried `thinking: {"type": "disabled"}` (checked over mocked HTTP in the test).
3. **Sticky routing behaved as designed on live answers.** The anchor was set by the first substantive message. The greeting stayed on the anchor (Q-41). Code re-routed to tier 1. A second user of the same bot was answered from the bot-level cache with no call. A cache hit does not anchor.
4. **MiMo bills more hidden reasoning than the placeholder.** It billed 46, 14, 32, and 21 reasoning tokens (mean 28) against the cost model's 12 (A-66). MiMo still ranks cheapest in tier 0 with these values: (300 + 46) × 0.308 is below 300 × 0.44 per million output tokens. MiMo was also slow: 3–13 s per call.
5. **LLMLingua-2 on the live path** compressed the retrieved document from 86 to 42 of its own tokens in 414 ms (overhead). The compression saving was 0.000007 USD at MiMo's price.
6. **MiMo's cached-token field is absent** when nothing is cached (as in the probe), so its costs carry `cached_input_not_reported` (an upper bound). `mimo-v2.5` was still accepted and reported under that name on 2026-10-19 (A-60, Q-42).

## What changed because of the check

| File | Change |
|---|---|
| `config/reference/tokenizers.toml` (`-demo-lc`) | evidence note on DeepSeek's `thinking_disabled` template (no count changed) |
| register | A-68 decided; A-66 updated with MiMo's observed reasoning |
