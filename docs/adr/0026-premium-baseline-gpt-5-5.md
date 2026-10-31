# ADR-0026: The premium baseline becomes gpt-5.5 (estimate and sampling only, never routed)

- Status: **decided** by the project owner, 2026-10-30; amends the premium choice in [ADR-0002](0002-configurable-baselines.md) and [live_testing_and_demo_brief.md](../project/live_testing_and_demo_brief.md) §5 (premium `gpt-5.4`, Q-05 partly answered).
- Relates to: ADR-0018 (live budget), ADR-0020 (accounting), [evaluation framework](../experiments/evaluation_framework.md) §1, §5

## Context
The premium baseline was `gpt-5.4`, never called, its cost estimated. The owner asked for `gpt-5.5`. The Metis pricing page saved 2026-10-18 lists `gpt-5.5` (standard tier 5.5 input, 33.0 output, 0.55 cached USD per 1M tokens; long tier 11.0, 49.5, 1.1).

## Decision
1. `config/reference/baselines.toml`: premium `model_id` is `gpt-5.5` (`baselines-2026-10-30`). Method stays `estimate_only`; the sampling run (E4) is what observes its answers and usage.
2. Prices: a **new** price file, `prices-metis-2026-10-18-g55.toml` (`prices-metis-2026-10-18-s75-g55`), copying the previous one unchanged and adding `gpt-5.5`; the old file stays untouched (a price change is a new file). Defaults point at the new file.
3. Catalogue: `gpt-5.5` added, **disabled**, with context window and output limit **unknown** and no capability listed, because no first-party source was retrieved (third-party aggregators disagreed on the window). `gpt-5.4` stays in the catalogue and price file.
4. Tokenizer: `gpt-5.5` uses `openai-o200k-base` by family mapping (`tiktoken.encoding_name_for_model('gpt-5.5')` returned `o200k_base`, checked 2026-10-30), `exact_local` under the same A-53 reading as `gpt-5.4`; it will be checked against provider-reported usage when first sampled.
5. Tests updated for the new premium and price file; demo UI labels name `gpt-5.5`.

## Consequences
- Demo premium-baseline estimates now price `gpt-5.5` (about 1.9× `gpt-5.4`), so displayed savings versus premium rise; no routing, caching, or serving default changes.
- The long-tier boundary reading and the price-page age (12 days on 2026-10-30) are unchanged caveats; re-verify before any budget decision.
- Open: `gpt-5.5` limits and reasoning capability (unverified), and the E4 pilot budget (Q-29, ADR-0018 cap).
