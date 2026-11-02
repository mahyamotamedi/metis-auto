# ADR-0029: golden-v2, the 300-request evaluation dataset without attachment records

- Status: **decided** by the project owner, 2026-11-01 (option A below). Quotas and rules are those of golden-v1 and stay **provisional**; the dataset is **`annotated_provisional`**.
- Date: 2026-11-01
- Relates to: ADR-0028 (golden-v1, unchanged), ADR-0027, ADR-0025; [golden_v2.md](../evaluation/golden_v2.md)

## Context
23 of golden-v1's 300 records carry an attachment (25 attachments, all of type `IMAGE`; 21 of the 23 belong to one account, "User B"). The sending side of the tooling (answers from a text model, routing on text) cannot use the image, so these records cannot be answered or scored fairly. Attachments were never a stratum or a quota in golden-v1; they were a **mandatory coverage minimum** (`attachment_dependent`, at least 15, achieved 23), set from `bool(attachment_types)`.

## Decision
1. **A new dataset, `golden-v2`** (`config/evaluation/golden_v2.toml`, record prefix `gv2`, its own fingerprint in `reports/evaluation/golden_v2/`). golden-v1, its config, its fingerprint and its outputs are not changed (tested; `verify` passes for both).
2. **Option A, derive from the stored golden-v1 selection.** Drop every record with an attachment. Replace each inside its own primary-intent × cohort cell: first the next unused v1 reserve of that cell in `reserve_rank` order, then, if none is usable, the next candidate of the v1 distinct pool in seeded order (`selection.derive_without`). The same checks as the original selection apply: one record per session, exact and near family, the per-bot cap, the single-account cohort cap, and the exact bigram near-duplicate check against the whole set and its reserves. Same seed, quotas, caps and rules.
3. **The base is pinned.** `[derive] base_fingerprint` is the golden-v1 fingerprint; the build refuses unless the local golden-v1 matches it. golden-v2 is therefore a deterministic function of golden-v1 and the config (tested; `validate --rebuild` re-derives it, V-12).
4. **The `attachment_dependent` coverage minimum is dropped.** It cannot hold without attachments. **golden-v2 does not cover attachment-dependent requests; use golden-v1 for those.** The loader refuses a derived config that still requires it.
5. **IDs and mapping.** Record IDs are `gv2-` plus the request id, so an ID never names two datasets. `reports/evaluation/golden_v2/golden_v1_to_golden_v2_mapping.jsonl` (IDs only) links them, and `carry-labels` re-keys reviewed v1 labels for the unchanged records.
6. **Status:** `annotated_provisional`, like v1. Human review is still pending for both.
7. **Caveats.** Records whose rule intent is `media_generation` carry `stratum.caveats = ["text_model_cannot_fulfil_media"]` (`[caveats.by_intent]`): a text model cannot produce the requested media. They still get an answer; analyses report them separately. The caveat follows the rule intent, a proposal, so a reviewed intent may differ.

## Result (built and verified 2026-11-01)
- 277 records identical to v1; 23 replaced: 16 from reserves, 7 from the pool. 5 of the 7 pool fills happened because the remaining v1 reserves of those cells belong to bots already at the per-bot cap of 15 (v1 ranked reserves without the cap); 2 because the cell had no reserves left. Unfilled: 0. 133 reserves remain.
- Margins drift by at most 6 records (complexity proxy: `average` +6, `simple` −6). Every mandatory minimum is met. V-08 documents each difference with its cause. 16 records carry the media caveat.

## Alternatives considered
- **Re-run the whole selection without attachment candidates (option B).** Meets every margin by design, but the greedy pass reshuffles many records, so reviewed labels would not carry over. Rejected for A, which keeps 277 records.
- **Keep golden-v1 and answer attachment records text-only.** A text-only answer to a request about an image is not a fair reference. Rejected.
- **Skip the 23 and run with 277.** Breaks the 300-record design and the quotas. Rejected.
- **Edit golden-v1 in place.** Would change its fingerprint and every artefact built on it. Rejected.
- **Keep the `gv1` prefix for shared records.** One ID would name two datasets. Rejected.

## Consequences
- Population and weights of golden-v2 are over eligible **text-only** requests; length bucket edges are still computed over all eligible requests, so unchanged records keep their strata.
- The 23 replacement records have rule labels only; the 277 others can take v1's reviewed labels.
- A change to golden-v1's config or records fails golden-v2's build until the pin is deliberately moved.
- Open: whether golden-v1 stays the attachment-dependent set (it is, for now).
