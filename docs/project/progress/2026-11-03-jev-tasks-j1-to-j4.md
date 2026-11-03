## Jev tasks J-1 to J-4: the note, the configuration, and the remapping (2026-11-03)

Final sprint plan, Parham's Jev tasks only. Scope change (2026-11-03): Kimia took over R-0, F-1, T-0 and P-1 to P-3; they are not touched here.

- **J-1:** [jev_model_note.md](../../references/jev_model_note.md).
  - **Jev is a System-One decision model, not a chat model.** It cannot answer users, so it is not a cheaper model to route to. In this project it is the router itself: Mode 1, with THX-01 as the local Mode 2.
  - Not OpenAI-compatible.
  - Endpoint, auth, model ID and price, each with its source and date. Unknowns are marked *unverified*.
  - The answer to Metis question (c) for O-1 is in the note; O-1 itself was not edited.
- **J-2:** nothing duplicated.
  - The price is the existing dated row `metis-jev-latest`.
  - Endpoint and model are in `[router.backends.jev_metis]`. `base_url` replaces the unused `endpoint_family` key.
  - No `endpoints-metis.toml` row: the plan adds one only for an OpenAI-compatible model (A-112).
  - No catalogue row: Jev is never a routing target. `sprint.toml candidates_jev` stays empty.
- **J-3, J-4 and the Jev benchmark arm:** not built as written, by the plan's own rule for an incompatible model (A-111, owner):
  - J-3 → Jev as the routing model (Mode 1); the decided tier meets R-0 in exp-route-013;
  - J-4 → the router live check (`scripts/router_live_check.py`);
  - benchmark arm → the router's shadow evaluation (`scripts/evaluate_router_slice.py`).

Status: **awaiting the owner's live-check run.** The note's starred facts are confirmed or corrected after it.
