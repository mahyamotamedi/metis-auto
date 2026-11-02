# ADR-XXXX (gemini-live-calls): Gemini is callable through the native adapter once enabled (amends ADR-0018 point 2)

- Status: **proposed**, until the owner approves a live check. Nothing changes in the configuration until then.
- Date: 2026-11-02
- Amends: ADR-0018 point 2 ("Gemini needs a different wire format and is **deferred**").
- Relates to: [ADR-XXXX (gemini-native-adapter)](draft-gemini-native-adapter.md), ADR-0003, ADR-0018 (amendments 1 and 2: the lifetime cap and ceiling), ADR-0019, ADR-0021.

## Context

ADR-0018 point 2 deferred Gemini because the Metis wrapper serves it in Google's format, which needs a second adapter. ADR-XXXX (gemini-native-adapter) adds that adapter, offline only, with every wire field name unverified. ADR-0018's rules still hold: live calls are for development and testing, under the lifetime cap; only own or synthetic messages; never without the owner asking.

## Decision (proposed)

1. **Point 2 is amended:** Gemini is reachable through the Metis wrapper with the native adapter (`adapters/providers/gemini_native.py`), with the same Metis key, once it is **enabled**. Enabling takes three changes, made together and only after this ADR is accepted: the `gemini` row in `endpoints-metis.toml` gets status `enabled`; the model gets a catalogue row, plus a price row (from the dated Metis pricing extract) and a tokenizer row; and the model gets an explicit `thinking_budget` in `[model_options]`.
2. **The first live call is the smoke test** `scripts/live_gemini_check.py`: one SYNTHETIC message, one attempt, output cap 64 tokens, run cap 0.01 USD, the persistent ledger, its printed estimate approved first. It runs only with (a) this amendment accepted, (b) the Metis dashboard limit raised to cover it (the account limit, Q-29), and (c) the owner's approval for that run.
3. **Gemini calls follow every ADR-0018 rule:** development and testing only; synthetic or own messages; sample conversations only with per-run owner approval; every attempt charged to the ledger.
4. Until the smoke test has run and its results are recorded (field names, the cached- and thinking-token conventions), Gemini results are **provisional**. No experiment uses them as evidence.

## Alternatives considered

- **Keep Gemini deferred.** Safe, but Gemini labels (unmapped today) stay without counterfactual answers.
- **Enable it at once, without a smoke test.** Rejected: no field name is verified, and a wrong mapping would misstate costs under a lifetime cap.

## Consequences

- No live call and no configuration change follow from this draft by itself.
- Once accepted and the check has run, the endpoint row's status and the catalogue decide whether Gemini is routable, as for every other family.
