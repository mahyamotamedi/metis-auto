## Decision router: final results and decisions (2026-11-03)

From the owner's second native run (`runs\finish_router_2.ps1`).

- **Tests on Windows:** 1,988 passed, 0 failed. The fixes are in the previous entry (TODO-20).
- **THX-01 latency is inherent on this CPU:**
  - the weights are already float32, so no cast was needed;
  - one batched pass of 5 × 172–222 tokens: forward 3.3–4.8 s, sequence building about 14 ms, decoding about 1–6 ms;
  - slice p50 3.7 s, p95 10.8 s; load 152 s (building the agent 142 s); 2.3 GB.
  - **Final (owner):** inline routing is rules only; THX-01 is used for shadow and offline evaluation only.
  - Future work: a GPU host, ONNX int8, fewer or shorter questions, and distilling labels into a small classifier (A-118).
- **Offline shadow run:**
  - THX-01 answered 82.7% and **changed no routing decision**: agreement 1.0 everywhere, with no upgrade and no downgrade.
  - There is no saving over the rules on the slice. Correctness needs labels; the L1 plan is next (A-121).
  - Both gate proposals (0.0671 reported, 0.3897 probability) stay provisional and unused (A-119).
- **Live** (total 0.0016 USD, A-124):
  - `mimo-v2.5` is refused in every shape and `gpt-4.1-nano` returns 404. Both get `enabled = false`, applied by the catalogue's owner (Q-42, TODO-17).
  - Tier 0 is then `gpt-5-nano` alone (A-123).
  - `json_schema` is unsupported on the OpenAI wrapper; the backup keeps prompt-and-parse (A-122).
  - Jev works through Metis (`jev-1.14.0`, 3.5 s, 0.0000323 USD a call), for shadow runs, labelling and evaluation on SYNTHETIC or approved data only.
- **The spend guard's "stopped live calls for this run" line** belongs to that call's own guard. The live check gives each call its own guard (A-116, A-120), so later calls ran. In a pipeline run the stop holds (tested). Not a bug.

Status: **done**, awaiting the owner's commit on a branch. The decision router is a measured, shadow-only component.
