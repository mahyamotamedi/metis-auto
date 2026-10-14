# ADR-0003: Model calls — offline by default (mocks/recorded), live calls opt-in with a spending cap

- Status: **decided** (provider choice and budget are **open**)
- Date: 2026-10-14
- Resolves (partly): Q-08

## Context
Evaluating alternative routing or caching needs answers from models that weren't used (the counterfactual problem, context.md §8). Real model calls will eventually be allowed, but no provider has been chosen, there are no keys, and there is no budget.

## Decision
1. **For now, no real calls.** Experiments, tests, and the walking skeleton default to **mock or recorded responses** behind the provider-adapter interface.
2. **Live calls will be opt-in**, enabled by explicit configuration and never by default in tests.
3. Live runs will enforce a **configurable spending cap**: a per-run limit and optionally a cumulative one, checked before each call against estimated cost and recorded from reported usage. A run stops when the cap is reached. The default cap is **unset**, so live runs are refused until a cap is configured. The budget amount is open.
4. In Stage 6, `.env.example` will contain **commented-out example entries** for likely provider credentials, each with comments explaining where to get the key, which line to uncomment, and that `.env` is git-ignored. No real secrets.

## Alternatives considered
- **Allow live calls now.** Rejected: no provider, keys, or budget yet.
- **Proxy metrics only, forever.** Rejected: too weak for quality claims. Kept as one of three counterfactual methods.

## Consequences
- The provider-adapter interface must support fake and replay implementations from the first skeleton (Stage 5).
- Cost accounting (Stage 7) supplies the pre-call estimate the cap needs.
- Budget and provider list remain open questions.
