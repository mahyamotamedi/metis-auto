# Demo B: live smoke test of the UI (2026-10-19)

The owner-approved live smoke test of the Demo B UI ([ADR-0024](../adr/0024-demo-ui-streamlit.md)). It drives the real page (`scripts/demo_ui.py`) with Streamlit's test runner in **live** mode. Every call goes through the page's Live switch (both keys checked), the real pipeline, the spend guard, the persistent ledger, and the recording decorator. The messages are SYNTHETIC: the English FAQ preset and its suggested messages.

- **Run:** 2026-10-19, 13:36 UTC, run ID `chat-20261019T133631Z-a6ba8506`. Approved by the owner: SYNTHETIC messages only, total under 0.02 USD, estimate shown first. Script: `scripts/demo_ui_live_check.py --run` (steps and limits in `wiring/demo_ui_check.py`). Output cap 512 tokens. The run's spend cap was set to the approved 0.02 USD, so the guard itself enforced the approval.
- **Raw results** (content-free: no answer text): [metis_demo_ui_live_check_2026-10-19.json](metis_demo_ui_live_check_2026-10-19.json). The answers are only in `data/recorded/` (git-ignored).
- **Estimate first** (no call): the plan ran the same steps with a planning fake whose answers were the full 512 tokens. It summed the spend guard's pre-call estimates: **0.001791 USD for 4 calls** (gpt-5-nano 0.000296, 0.000325, 0.000355; gpt-4o-mini 0.000815; the second user's greeting is a cache hit, 0). The worst case, if every call escalated once, was **0.003706 USD**.
- **Charged: 0.001674 USD** for 6 billed attempts (4 answers, 2 escalated first attempts). The lifetime ledger total afterwards was **0.006098 USD** of 10. Before the run it was 0.004424 USD; that included two charges (0.000067 USD) from run `chat-20261019T132838Z-1c397509` at 13:29–13:32 UTC. That run was not this check and not made by Claude Code: no demo page or script of this session was running at that time.
- **Configuration:** catalogue `cat-metis-test-2026-10-18-s75`, prices `prices-metis-2026-10-18-s75`, endpoints `endpoints-metis-2026-10-18-s75`, tokenizers `tokenizers-2026-10-19-demo-lc`. Preset `en_faq` (`config/demo/presets-synthetic.toml`). Bot-level cache [DEMO] on; sticky routing v1; compression off; DeepSeek thinking at its default.

## Results

| Step (SYNTHETIC message) | Badge / routing reason | Served by / model (reported) | Input / cached / output / reasoning (provider-reported) | Cost USD | Saved vs premium |
|---|---|---|---|---|---|
| greeting (`hi`) | greeting + escalated / `sticky.greeting` | model / gpt-4o-mini (`gpt-4o-mini-2024-07-18`); the first attempt on gpt-5-nano was cut off | 1,285 / 0 / 9 / 0 | 0.000514 | 86.7 % |
| first question (`How do I export my notes to PDF?`) | anchored + escalated / `sticky.first_substantive.rule.default` | model / gpt-4o-mini; the first attempt on gpt-5-nano was cut off | 1,311 / 0 / 73 / 0 | 0.000562 | 88.8 % |
| similar follow-up (`Does the Team plan include SSO?`) | stayed / `sticky.stay` | model / gpt-4o-mini (the anchor, raised by the escalation) | 1,400 / **0** / 38 / 0 | 0.000256 | 94.5 % |
| coding request (`write a python function that lists all my notes with the API`) | re-routed / `sticky.reroute.coding_intent_appeared.rule.coding_intent` | model / gpt-4o-mini | 1,458 / **0** / 154 / 0 | 0.000342 | 95.0 % |
| New user (same bot), then `hi` | cache / `sticky.greeting` | **cache** (`full/global: hit`), no call | — | 0 | 100 % |

Session decomposition (USD): premium baseline 0.024256; routing saving 0.023101; compression saving 0; cache saving 0.000075; provider-cache saving 0; **extra cost 0.000593** (the two cut-off gpt-5-nano attempts); **actually paid 0.001674**. The terms add up exactly. Metis-Auto's own overhead was 1.3–7.6 ms per message.

## Findings

1. **The UI works live end to end.**
   - The Live switch was accepted (both keys present), and the banner showed live calls on.
   - Each step's routing decision and badge matched the offline plan, except that the escalations raised the anchor.
   - The second user's greeting was a bot-level cache hit with no call.
   - The cost panel's figures equal the backend's decomposition.
2. **gpt-5-nano spent its whole output on hidden reasoning.**
   - Both of its attempts reported **512 reasoning tokens out of 512** output tokens, finish reason `length`, and no visible answer.
   - The truncation detector escalated each to gpt-4o-mini, which then became the anchor, as designed (ADR-0013, sticky v1). Each cut-off attempt cost 0.000296 USD, shown as *extra cost*.
   - The routing cost model expects 150 reasoning tokens for gpt-5-nano (A-66, from tiny prompts). With this ~1,300-token prompt it needed more than 512, so routing chose gpt-5-nano on an effective cost that was far too low.
   - The demo's normal generation limit is 4,096 (`max_output_tokens_cap`). There, gpt-5-nano would probably finish, but bill many more hidden tokens than routing assumed. **A-66 updated; Q-44 opened** (what to do about it). Nothing was changed.
3. **The provider cache did not hit.**
   - The follow-up and the coding request were the third and fourth gpt-4o-mini calls within seconds. Each shared a ~1,300-token prefix (instructions + documents + the first turns) with the call before it, yet each reported **0 cached tokens**.
   - The Stage 7.5 probe saw gpt-4o-mini hit (1,152) on an identical repeated request. Provider caching is best effort, and one run can't say how often it hits.
   - The quickstart's demo script (step 7) now says so and no longer promises a hit.
4. **Counting:** every token figure on the live answers was provider-reported (input, cached, output, reasoning). gpt-4o-mini reported 0 reasoning tokens, as expected for a non-reasoning model.

## What changed because of the check

| File | Change |
|---|---|
| register | A-66 updated (gpt-5-nano reasoning on long prompts); Q-44 opened |
| `docs/guides/demo_quickstart.md` | step 7 (provider caching is best effort; it did not hit in this check); a note that gpt-5-nano can be cut off and escalate in live mode |
| `scripts/demo_ui.py` | `use_container_width` replaced by `width="stretch"` (Streamlit 1.65 deprecation warnings seen during the run) |
