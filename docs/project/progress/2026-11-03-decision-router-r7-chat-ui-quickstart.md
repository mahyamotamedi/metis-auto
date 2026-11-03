## Decision router R7: chat and UI toggles, environment switch, quickstart (2026-11-03)

- **Chat:**
  - `RoutingMode.DECISION_ROUTER` with a `router_mode` (off, local, hosted, hybrids) in `wiring.chat`, enabling the chain's backends.
  - Typed chat text is declared not dataset-derived; the seeded sample is.
  - The turn report names the router's path, backend and tier.
  - `scripts/chat.py --mode decision_router --router-mode local`.
- **Demo B UI:** a "Decision router" routing option and a "Decision backends" selector (two small additions to `scripts/demo_ui.py`, no logic).
- **Environment:** `METIS__ROUTER__MODE` plus `METIS__ROUTER__BACKENDS__<NAME>__ENABLED`, already tested.
- **Unchanged:** serving defaults (`router.mode = "off"`, `fixed_model`).
- **Quickstart:** `docs/guides/router_quickstart.md` gains:
  - §9: the live check, budget first;
  - §10: chat and UI;
  - §11: the shadow evaluation;
  - §12: `runs\finish_router.ps1`.
  - It is Windows first, with the network workarounds and `--no-build-isolation`.
- **Not done (owner: skipped for time):** the fresh-clone walkthrough (TODO-19).
