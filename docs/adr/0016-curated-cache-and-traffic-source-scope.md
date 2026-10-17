# ADR-0016 (proposal): Curated shared cache, and cache scope chosen per request from the traffic source

- Status: **proposed — to be tested** (Q-21, 2026-10-17). This is accepted as a design to test, **not as a serving change**. **The serving defaults do not change:** `session` scope ([ADR-0007](0007-cache-sharing-scope.md)) and the full serving key ([ADR-0011](0011-cache-key-and-lookup-design.md)).
- Date: 2026-10-17
- Decision owner: project owner. Q-21 settled the shape of the proposal (see "Owner decisions"). Moving to *decided* for serving needs: Q-22 and Q-23 (data owner), the full-dataset EDA, the Stage 8 caching experiment (hypothesis H-8), and every prerequisite below.
- Relates to: FR-XCACHE-02, 04, 05, FR-SCACHE-01, 02, FR-REQ-01, FR-EVAL-06, ADR-0007, ADR-0008, ADR-0011, ADR-0014, A-02, A-34, A-35, TODO-07
- Architecture it would change: [caching.md](../architecture/caching.md)

## Context

**The owner's informal reading of sample conversations** (not an EDA finding; both premises are speculative, and are kept as hypotheses for the full-dataset EDA):
- Much traffic appears to come from chatbots embedded in other websites. For these bots, the correct answer depends on the bot's instructions and retrieved context plus the question, not on who the user is.
- Same-user repeats within a session seem rare, so the `session` serving default may capture little value.

**What the repository records today:**
- Neither premise is stated in the EDA documents. Both are recorded as unverified assumptions (A-34, A-35).
- The sample has no traffic-source field and no user identifier (B§4). "Same user" therefore cannot be measured in the sample; only "same session" can.
- The EDA's repeat tables (made with the unreliable helpers, so provisional) list 21 normalised repeat groups covering 76 user messages. Of those, 11 groups cross sessions, and the tables sum to 19 within-session repeat occurrences.
- These numbers neither confirm nor refute the premises. They are a reason to measure, not a basis to decide.

**Constraints from earlier decisions:**
- **ADR-0007:** widening the serving scope needs a new decision record citing measured false-hit rates. This document is the *proposal* for that record. It can only be accepted with that evidence.
- **ADR-0007 rejected "instruction group as a scope level"** in favour of keeping the instruction group as a key component. Part 2 below needs a sharing level "within an instruction group". Option S-b below expresses that without a new scope value.
- **A-02 / NG-08:** category names are opaque. Traffic source must never be inferred from category names. If the data owner states a mapping (Q-23), it becomes a *declared* attribute.
- **TODO-07:** there is no time-sensitivity detector yet. The current eligibility rule is a no-op that reports "not evaluated".

## Owner decisions (Q-21, 2026-10-17)

1. **Status:** proposed — to be tested. No serving change.
2. **Premises:** speculative (A-34, A-35). They come from the owner's informal reading of sample conversations, not from the EDA documents. They are hypotheses for the full-dataset EDA.
3. **Scope representation: S-b**, and **only together with the traffic-source rule** (Part 2, point 2):
   - `embedded_bot` with instructions present → `global`. Sharing stays within the instruction group, because the instructions fingerprint is in the key.
   - `direct_user` → `user`, or `session` when there is no privacy-safe user reference.
   - unknown or absent → `session`.

   **Direct users never get `global` scope.** S-b is not usable on its own, without the traffic-source rule. ADR-0007 is not reversed: no `instruction_group` scope value is added.
4. **Answers for shared serving:** regenerated and quality-checked answers are preferred over reused logged answers. Serving logged answers to other sessions needs a privacy review first.
5. **Prerequisites before any serving** (each is required):
   - a working time-sensitivity detector (TODO-07);
   - measured false-hit rates (ADR-0007);
   - a content source for the batch builder inside the privacy boundary. This is an open design gap for the online phase;
   - a privacy review.
6. **Evidence:** on the sample, the daily-window simulation tests the mechanics only. The payoff is measured on the full dataset.
7. **Stage 4:** reserve an optional `traffic_source` request field now, with the three states present / absent / unknown.

## Proposal

### Part 1: curated (static) cache, rebuilt periodically

1. **Builder job.** A batch cache-builder rebuilds the curated cache on a schedule: default every 24 h, configurable. It writes through the existing `CacheStore` and `VectorIndex` ports. No new storage interface.
2. **Admission.** Only frequently asked requests are admitted: a frequency threshold over a rolling window, counted per instruction group. The counting can use keyed fingerprints from events (ADR-0012, ADR-0015). The threshold and window are configuration.
3. **Key.** The full ADR-0011 composition, including instructions and retrieved context.
   - At first, only first-turn requests (history component = `absent`) are admitted.
   - A standalone-question detector, which would let later-turn requests ignore history, is a later option. It would be a narrower key variant, so it needs `serving_allowed` and its own evidence.
4. **Answers** are regenerated (preferred, decision 4) or chosen from logged answers, and are quality-checked offline before serving: by a judge and/or against a premium model. Reusing logged answers for shared serving needs a privacy review first. Each entry records:
   - its origin (`curated`) and build ID;
   - answer provenance: selected logged answer, or regenerated by which model;
   - the quality verdict, with the judge and its version.
5. **Tiers.** Both exact and semantic tiers. Semantic admission groups paraphrases by embedding similarity inside one partition key. The partition still includes the embedder version.
6. **Rebuild semantics.** Entries are valid until the next build plus a grace period. A rebuild replaces the curated set atomically, by build ID, so old curated entries become unreachable by construction.
7. **Cold start (optional hybrid).** A small dynamic cache with a short TTL alongside the curated one. Proposed lookup order: curated exact → curated semantic → dynamic. The order is open.
8. **Exclusions.** Time-sensitive requests stay excluded. Requests with attachments also stay excluded (A-19).

### Part 2: cache scope chosen per request from the traffic source

1. **New optional request component `traffic_source`**, with the three states present / absent / unknown (P-6).
   - Values are an open, configurable enumeration, initially `embedded_bot` and `direct_user`.
   - Each value carries a **provenance**: `declared` (by the caller or gateway, e.g. from the API key type or client ID) or `inferred` (a heuristic).
2. **Scope selection rule** (configuration, applied by the cache policy):

   | Traffic source | Scope |
   |---|---|
   | `embedded_bot`, with instructions present | `global` (S-b). Sharing stays within the instruction group through the key. This is the curated-cache scope. |
   | `embedded_bot`, instructions absent or unknown | `session` |
   | `direct_user` | `user`, falling back to `session` when there is no privacy-safe user reference. **Never `global`.** |
   | unknown or absent | `session` |

3. **Inferred labels are for analysis only.** They are never used to choose a serving scope until validated against declared ground truth (Q-22). Inference never uses category names.
4. **New evaluation stratum:** traffic source (an FR-EVAL-06 addition), with the provenance reported.

**How "shared within the instruction group" is represented (decided: S-b):**
- **S-a (not chosen).** A new scope value `instruction_group`. It would reverse an alternative ADR-0007 rejected.
- **S-b (chosen).** `global` scope, allowed only when the instructions component is *present* **and** the traffic source is `embedded_bot`. The instructions fingerprint is already in the key, so sharing is in effect limited to the instruction group. No new scope value, no ADR-0007 reversal.

## Evaluation (Stage 8 candidate, tests H-8)

- **Replay simulation of daily rebuilds.**
  - Build from window *d−1* (or a rolling window ending at *d−1*), then serve window *d*.
  - Windows use the naive message timestamp; the ordering rule is recorded (A-06, A-31).
- **Compared with** the current session-scoped dynamic cache, and with no cache.
- **Metrics,** overall, per traffic source, and per existing stratum:
  - hit rate, always with hit correctness (ADR-0006);
  - storage size: entries and bytes, reported as counts only;
  - cost saved, net of build cost. Regeneration and judge calls are charged to the curated cache, amortised over its hits, in the spirit of FR-ACCT-03.
- **Sensitivity:** frequency threshold, admission window, rebuild interval, and first-turn-only versus a standalone-question detector.
- **Counterfactual source** (ADR-0014):
  - With `logged_match`, chosen answers are logged answers, and correctness against a new request's reference is *agreement*, a secondary measure.
  - Claims about regenerated answers need `recorded` or `live` answers plus a judge.
- **Data needs.** The value depends on the **popularity distribution** of requests per instruction group, which the full-dataset EDA must measure.
  - The 100-session sample, spread over months, is far too sparse for daily windows. On the sample, this simulation can only exercise the mechanics.
  - Per-traffic-source results need declared labels (Q-22).
- **Success and kill criteria** are set in the Stage 8 caching plan. No thresholds are invented here.

## Alternatives considered

- **Keep the status quo** (session scope, dynamic cache only). Lowest risk. May capture little value if A-35 holds.
- **A global dynamic cache** with a short TTL and no curation. Simpler, but answers are served unvetted to everyone, and the false-hit exposure is highest.
- **A hand-curated FAQ per bot.** Needs operators, and doesn't scale across instruction groups. Could feed the curated cache later.
- **Provider-side prompt caching.** A different lever: it lowers input cost, not the number of calls. It is complementary (H-1, context_construction.md).

## Consequences

**Now (2026-10-17):**
- Stage 4 reserves the optional `traffic_source` field. It defaults to unknown, which maps to `session` scope. Serving is unaffected.
- The Stage 8 caching plan includes this experiment.
- The full-EDA checklist (Stage 9) tests A-34 and A-35.

**If later accepted for serving** (none of these apply yet):

- **Requirements:**
  - FR-REQ-01 gains the optional `traffic_source` component;
  - FR-XCACHE-05 allows the scope to be chosen per request by rule;
  - FR-EVAL-06 gains the stratum;
  - a new FR for the curated builder (admission, quality check, rebuild).
- **Architecture:** a builder use case in `application` (it runs offline, not on the request path), with pure admission and acceptance policies in `domain/caching`.
- **Builder input:** content for admitted groups. That needs a content-bearing request source inside the privacy boundary; none exists online today, so this is an open design gap.
- **Privacy:** serving a selected *logged* answer to other users or sessions spreads one conversation's output. Regenerated answers are safer. A privacy review is needed before any shared serving.
- **Prerequisite:** a working time-sensitivity detector (TODO-07). Until one exists, the curated cache can't safely be served across sessions.
