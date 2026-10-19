# ADR-0018: Live calls for development and testing, through the Metis wrapper, under a 20 USD lifetime budget

- Status: **decided** (owner decisions, 2026-10-18). The per-run cap default and the placeholder tiers are **provisional**. **Amended 2026-10-18** ([amendment 1](#amendment-1-2026-10-18-lifetime-cap-10-usd-q-29)): the lifetime cap is 10 USD, under the unchanged 20 USD ceiling.
- Date: 2026-10-18
- Amends: [ADR-0003](0003-offline-by-default-model-calls.md) (its open points: provider choice and budget). ADR-0003's rules stay: offline by default, live opt-in, a cap before any live call.
- Resolves: Q-08, Q-12. Partly answers Q-05.
- Source: [live_testing_and_demo_brief.md](../project/live_testing_and_demo_brief.md) §1–§5 (owner decisions made outside Claude Code, 2026-10-18).
- Relates to: ADR-0002, ADR-0013, ADR-0014, ADR-0019, FR-ACCT, QA-PRIV, A-13, A-33

## Context

ADR-0003 kept every model call offline and left two things open: which provider to call and how much may be spent. The owner has now decided both. Real answers are needed to test the pipeline end to end (Stage 7.5) and for the demo (Demo milestone), and later for quality testing. The owner has one Metis API key, which reaches several model families through the Metis "wrapper" endpoints ([metis_wrapper_api.md](../references/metis_wrapper_api.md)).

## Decision

1. **Purpose.** Live calls are for **development and testing only**: real answers to test the pipeline and to run the demo. No production use.
2. **Provider.** The **Metis wrapper**, with **one Metis API key** (`METIS_API_KEY`) for every family. OpenAI, DeepSeek, and Grok are OpenAI-compatible and share one adapter (Stage 7.5), with a base URL per family in configuration. Gemini needs a different wire format and is **deferred** (Stage 10 roadmap). Base URLs, model IDs, tiers, and prices are configuration in `config/reference/`, not secrets.
3. **Budget: 20 USD for the whole project.** Every live call counts: chat models, LLM judges, paid embeddings, token-counting APIs.
   - **Lifetime cap** 20 USD, enforced across **all** runs by a **persistent, cumulative** spend ledger: an append-only, git-ignored file (`data/spend/ledger.jsonl`), shared by native and container runs. The spend guard blocks any call whose pre-call estimate would exceed what is left.
   - **Per-run cap**, default **1 USD** (provisional, A-49). The guard uses the tighter of the two.
   - **Warnings** at **50 %** and **80 %** of the lifetime cap (operator log).
   - **The 20 USD ceiling is configuration that only `config/defaults.toml` may set.** Every other layer can lower the caps but never raise them above the ceiling; the loader rejects an attempt. Raising the ceiling needs a reviewed commit and a new decision record.
   - The ledger fails closed: an unreadable or malformed ledger blocks live calls.
4. **Two keys, plus caps, plus the credential.** A live client is built only when the experiment asks for the `live` counterfactual source **and** the runtime configuration sets `live.enabled = true` **and** both caps are set **and** `METIS_API_KEY` is present (configuration.md §3 rule 2). Wiring refuses otherwise and lists every missing condition.
5. **Content sent to providers.** Only the owner's own or **synthetic** test messages. Sending sample-data conversations to a provider needs the owner's explicit approval **per run** plus the privacy review; it is not allowed by default.
6. **Record once, replay free.** Every live answer goes through the recording wrapper (ADR-0014), so each answer is paid for once.
7. **Verify before relying.** The wrapper's coverage is partial (its docs say so). Before the adapter relies on token usage, finish reason, cached-token counts, or the reported model, a tiny live check (fractions of a cent) confirms them; results are recorded with their date (Stage 7.5).
8. **Premium baseline for development and the demo: `gpt-5.4`, never called.** It is disabled in the catalogue, so routing and failover can't select it. Its cost is estimated from locally counted tokens (brief §5, Stage 7). This partly answers Q-05; the choice for the full-dataset evaluation is revisited then.
9. **Test models:** `gpt-5-nano`, `gpt-4.1-nano`, `gpt-4o-mini`, `deepseek-v4-flash`, `grok-4-1-fast`, with Metis user prices from the pricing page saved 2026-10-18 ([prices](../../config/reference/prices-metis-2026-10-18.toml)). Quality testing later uses all models.

## Alternatives considered

- **Per-run cap only (ADR-0003's minimum).** Simple, but nothing stops twenty 1 USD runs. Rejected: the owner's budget is a project total.
- **Ledger in `runs/`.** `runs/` holds disposable run records; clearing it would silently reset the lifetime total. Rejected in favour of a dedicated `data/spend/` path.
- **Ledger in a database.** Durable and concurrent, but there is no database yet (Stage 9) and a file is enough for one developer. A file behind the `SpendLedger` port can be replaced later without touching the guard.
- **Direct provider keys (OpenAI, DeepSeek, xAI).** More keys to manage and bill, and no single budget view. Rejected: the owner has one Metis key.
- **Hard-code the 20 USD limit.** Unchangeable by accident, but a price or scope change would need a code change. Rejected: it is configuration, protected by the defaults-only rule and review.

## Consequences

- Stage 6 implements the settings, caps, the file ledger (`adapters/system/ledger.py`), the live permission check (`wiring/from_settings.py`), and `scripts/show_budget.py`. No live client exists until Stage 7.5.
- **Known limits of the guard:** (a) the actual cost of a call can exceed its pre-call estimate, so the total can overshoot a cap by at most one call's estimation error; after that, `remaining()` is zero and every call is blocked; (b) two processes can both pass the check before either charges; acceptable for one developer, revisit if runs go parallel; (c) deleting the ledger file resets the total. The Metis dashboard's own spending limit, if Metis offers one, is the **second safety net** (Q-29).
- The TODO in the spend guard stands: an actual cost that can't be computed must stop the run (Stage 7.5, with the live adapter).
- A-33 (SDK retries can be turned off) must be verified for the OpenAI SDK in Stage 7.5.
- Catalogue context windows are unknown today, so routing would exclude every real model (FR-ROUTE-05). They need sourced values before the first live call (TODO-10).

## Amendment 1 (2026-10-18): lifetime cap 10 USD (Q-29)

- **Decided by:** the project owner, answering Q-29: the Metis dashboard spending limit for this API key is **10 USD**.
- **Change:** `budget.lifetime_cap = "10"` in `config/defaults.toml`, so the ledger's limit matches the dashboard's. The **ceiling stays 20 USD** (`budget.lifetime_ceiling`, defaults only) as the project maximum; point 3's rules are unchanged (no layer can raise a cap above the ceiling, and the run cap stays 1 USD).
- **Why both:** the ledger blocks a call *before* it is made, from its estimate; the dashboard limit is the provider-side safety net that also covers calls the ledger cannot see (another computer, another tool using the key). With equal limits, the ledger trips first on this machine.
- **Consequences:** warnings fire at 5 and 8 USD (50 % and 80 % of the cap). Raising the cap up to 20 USD is a one-line change in `defaults.toml` (reviewed), and should follow a change of the dashboard limit. Comparing the dashboard's charges with the ledger is still open (Q-36).
