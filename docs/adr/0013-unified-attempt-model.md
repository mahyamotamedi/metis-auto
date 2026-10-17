# ADR-0013: Unified attempt model — retry, failover, and escalation are one loop driven by a pure attempt policy

- Status: **decided** (model). Error-class mappings and limits are **provisional**. Usable detectors are **open** (U-07, TODO-06).
- Date: 2026-10-14
- Relates to: FR-CASC-01…05, FR-FAIL-01…07, FR-ACCT-03, FR-ACCT-06, A-20
- Detail: [attempts.md](../architecture/attempts.md)

## Context
The brief asks for a cascade (escalate on an unsatisfactory answer) and provider failover. FR-FAIL-02 keeps the two distinct: failover is for reliability within a tier; escalation is for quality across tiers. Retries are a third case. All three need bounded loops, deadlines, events, and full cost attribution. Nested loops (retry inside failover inside escalation) are hard to bound and test.

## Decision
1. Every model call is an **attempt** with a kind: `primary`, `retry`, `failover`, or `escalation`.
2. A pure **attempt policy** (`domain/attempts`) takes the full `AttemptState` and returns the next `AttemptAction`: invoke a target with a kind, return an answer, or fail. The pipeline executes it.
3. Provider failures arrive as **normalised error classes** from adapters. Configuration maps each class to retry, failover, context rebuild, or fail.
4. **Escalation** is driven by pluggable detectors, each returning a verdict, combined by a configured rule. Every verdict is recorded.
5. When the deadline, budget, or chain runs out, the best successful answer so far is returned with a flag. If there is none, an error response is returned.
6. The spend guard checks every live attempt before the call.

## Alternatives considered
- **Separate mechanisms**: retries inside adapters, failover in a wrapper client, escalation in the pipeline. Each is simple alone. But adapter-internal retries hide attempts from the record (FR-FAIL-04), and three layers of loops make the deadline and the cap hard to enforce. Rejected.
- **Retries delegated to provider SDKs.** Same problem: those attempts would be invisible and uncharged. Rejected. Live adapters must turn off SDK-level automatic retries where possible; this is verified per SDK.
- **A fixed cascade with no failover across providers.** This fails the brief's availability goal. Rejected.

## Consequences
- Fault- and quality-injecting fake clients let the whole state machine be tested offline (FR-FAIL-06).
- Context is rebuilt per target, so attempts on different models are measured correctly.
- The sub-package is `domain/attempts`, replacing the earlier provisional `domain/escalation` name (repository_structure.md §2).
