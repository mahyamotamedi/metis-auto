# ADR-0002: Baselines — configurable premium placeholder plus mandatory as-logged baseline

- Status: **decided** (the premium model choice itself remains **open**, Q-05)
- Date: 2026-10-14
- Relates to: Q-05; context.md §7

## Context
The brief evaluates cost and latency against a "single premium-model baseline". The premium model can't be chosen yet: there is no full dataset, no provider access, and no verified prices. Logged answers come from heterogeneous models, so a second reference point is needed in any case.

## Decision
1. The **premium baseline is a configuration setting**, never a hard-coded model. Until it is chosen, it holds a clearly marked placeholder (e.g. `PLACEHOLDER_PREMIUM_MODEL`, with `verified: false`). Experiments that need priced premium cost must report "not computed — premium baseline unset" rather than invent a value.
2. **Every experiment also reports against the "as-logged" baseline**: what the logged model labels actually did, with the label→model mapping and its fidelity stated.
3. Baseline definitions live in versioned configuration next to the model catalogue and price tables (Stage 6/7).

## Alternatives considered
- **Pick a premium model now.** This would fabricate a choice without access or verified prices.
- **Report only against as-logged.** This drops the brief's stated target.

## Consequences
- The experiment result format (Stage 8) needs fields for both baselines, plus an explicit "unavailable" state.
- Q-05 stays open until provider access and verified prices exist.
