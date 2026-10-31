# ADR-0025: Persian folding as versioned measurement treatments; keyed duplicate groups and leakage-safe splits for evaluation

- Status: **decided** (structure) for measurement only. Which treatment, if any, serving may use is **open**; nothing here changes the serving path.
- Date: 2026-10-30
- Relates to: ADR-0011, ADR-0015 (amendment 1), ADR-0008, FR-XCACHE-03, FR-EVAL-06, caching plan C1b, [evaluation framework §0.3, §0.5](../experiments/evaluation_framework.md)

## Context
Most traffic is Persian. NFKC does not unify Arabic and Persian yeh or kaf, and nothing handled digit forms or bidirectional marks, so one prompt can fingerprint as several, which understates duplicates, leaks across train/test splits, and misses cache candidates. ADR-0015 amendment 1 already says normalisation is a configured *treatment* applied before fingerprinting and recorded on the key; fingerprints never normalise implicitly.

## Decision
1. Persian folding is a **separate, versioned family** of treatments in `domain/caching/normalise.py`: `persian_fold_v1`, `persian_fold_zwnj_space_v1`, `persian_fold_marks_v1`. They differ only in open orthographic decisions (ZWNJ, diacritics and tatweel), so none is a default. A change of behavior is a new name. They are **not** in `TREATMENTS` (the default measurement set) and not in `policy.SUPPORTED_TREATMENTS`: serving stays `literal`.
2. The harness accepts them by name through `message_treatments`; the default variant set is unchanged. No fingerprint algorithm, `fp1`, or key-schema change.
3. Original text is never modified. Treated text is used only for comparison and fingerprint input, never sent to a model or judge.
4. **Duplicate-group IDs are keyed fingerprints** (purpose `dup_group`, ADR-0015 point 1). Empty text after treatment never groups (unknown never matches, ADR-0011).
5. **Leakage-safe splits** assign connected components (shared session or shared duplicate group) as a unit, deterministically; split fractions and seed are caller-supplied with no default; realised item shares are reported.
6. Latin case is not folded in these treatments; digits canonicalise to ASCII (a convention, not a claim about correctness).

## Alternatives considered
- **One configurable normaliser with flags.** Flags make a key's meaning depend on config that the key does not record; versioned names keep `KeyComponent.treatment` sufficient. Rejected.
- **Extending `TREATMENTS`.** Would change the default variant set of existing experiments and the pinned test. Rejected; opt-in by name instead.
- **Plain hashes for group IDs.** Reversible for short common prompts. Rejected (ADR-0015).
- **Consolidating with `detectors.normalise_phrase`.** That is production greeting routing; out of scope.

## Consequences
- Experiments may compare candidate-hit sets across treatments; whether any treatment is safe to serve needs measured false-hit rates and its own decision (ADR-0011 point 4).
- Open: diacritic/tatweel/ZWNJ handling, Latin case folding, and code points versus grapheme clusters for length remain unresolved and are listed in the evaluation framework §9.
