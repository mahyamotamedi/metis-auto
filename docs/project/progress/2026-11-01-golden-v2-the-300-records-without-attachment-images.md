## golden-v2: the 300 records without attachment images (2026-11-01)

Under the owner's task. Status: **awaiting review**; nothing committed. Decision: [ADR-0029](../../adr/0029-evaluation-dataset-golden-v2.md); guide: [golden_v2.md](../../evaluation/golden_v2.md).

- golden-v1 is untouched (its regenerated exports are byte-identical; `verify` PASS). golden-v2 is derived from the pinned golden-v1: the 23 attachment records are replaced inside their cell (16 from reserves, 7 from the pool; 5 of the 7 because remaining v1 reserves were at the per-bot cap), 277 records unchanged, 133 reserves left. Own config, fingerprint and ID mapping; `verify` PASS for both. V-01 to V-09, V-11, V-12 pass; V-10 pending human review.
- The `attachment_dependent` coverage minimum is dropped (golden-v2 does not cover attachment-dependent requests; use golden-v1). 16 `media_generation` records carry the caveat `text_model_cannot_fulfil_media`.
- New: `selection.derive_without`, `evaluation/golden/mapping.py`, `--config` and `carry-labels` in the CLI scripts, per-dataset report folders in `wiring.golden`. 21 new unit tests; the unit and architecture suites pass.
- **Next (owner-directed):** gpt-5.5 reference answers for golden-v2. No live call has been made.
