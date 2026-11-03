## Decision router R8: the evaluation harness and exp-route-013 (2026-11-03)

- **Shadow evaluation:** `wiring/router_eval.py`, `evaluation/router_eval/`, `scripts/evaluate_router_slice.py`.
  - Each frozen slice record goes through rules only (A-114) and through the router.
  - Reported, per split (all, tune, check), balanced and traffic-weighted, and per language group (Persian first):
    - tier mix, agreement and its direction;
    - decision status and gate share;
    - the share below the gate (mapping questions);
    - path mix, confidence, and the decision step's p95.
  - Local backends only. No labels yet, so agreement is not accuracy.
- **L4 synthetic labels in CI:** a scripted backend's own tiers are used as labels, and the harness must reproduce them (`tests/integration/test_router_shadow_eval.py`).
- **exp-route-013** (`experiments/routing/exp-route-013-decision-router/`):
  - the README declares the decision rules before results;
  - `version.py` turns decided tiers into routed models through R-0's `candidate_costs`, unchanged: eligible, then cheapest in tier, never dearer than the incumbent (A-115);
  - the L1 golden-v2 labelling plan, with its cost bound, is prepared, not run (P-1 to P-3 are now Kimia's);
  - the L3 review-sheet import path is `build_router_dev_slice.py import-labels`.
- **Runs on the owner's machine** (`runs\finish_router.ps1`): the THX-01 shadow run, the slice replay and the benchmark variants. Results and the inline-mode decision follow in the next entry.
