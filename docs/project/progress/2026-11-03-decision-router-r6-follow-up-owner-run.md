## Decision router: the owner's native run and its follow-up (2026-11-03)

The owner ran `runs\finish_router.ps1` on Windows (4 CPUs). This entry records what the run showed and what was changed.

**Tests:** 8 failed and 3 errors there, none caused by the router work's logic:
- **7 failures and the 3 errors** were Windows platform fragility in teammates' tests: cp1252 default encoding, and CRLF line endings under a byte hash. They were reproduced here by simulating Windows (a CRLF checkout and a cp1252 default) and fixed minimally with explicit UTF-8 and normalised line endings (TODO-20):
  - `test_live_wiring_gemini.py` (4 failures);
  - `test_gemini_check.py` (the 3 errors);
  - `test_routing_base.py` (1);
  - `test_logged_prices.py` (2).
- **One failure was ours:** `test_an_unpinned_or_uninstalled_thx01_degrades_to_the_rules` assumed THX-01 absent, but the owner's machine has it pinned and installed. It now uses an empty asset folder.
- My first script recorded only the FAILED lines. The new one keeps the full pytest output, ERROR lines included.

**THX-01 latency:**
- Before: p50 about 4 s and p95 6–12 s on the slice; load 145–168 s; 2.3 GB.
- Threads 2/4/8, at most 300 message characters, and JSON vs text state changed little (the shortest states brought p95 to about 5.8 s).
- In the package, all five questions run in one forward pass, the 10-option intent question uses no tournament (it applies above 24 options), padding is to the longest sequence, and the agent is in `eval()` under `no_grad`.
- Loading now records the weights' dtypes and casts any non-float32 weight to float32. Calls run under `inference_mode`. One benchmark with a per-call breakdown confirms the result in the follow-up run.
- The pre-approved rule applies whatever the result: **inline routing is rules only**, and THX-01 runs in shadow and offline evaluation (A-118).

**Shadow evaluation:**
- The inline-settings run was invalid. THX-01 timed out on the 60 ms deadline 3 times, the breaker opened for the other 121 decisions, and agreement 1.0 compared the rules with themselves.
- New offline mode: 60 s per request, no cache, gate off. It reports per-question confidence and probability distributions.
- New gate proposal, with its rule declared before the results: the threshold is the tune split's 20th percentile, and its effect is measured on the check split (A-119).
- New setting `confidence_statistic` (`reported` or `probability`).

**Live results:**
- **Jev** answered as `jev-1.14.0`: 699 in / 171 out tokens, 0.0000322938 USD (input only), **3.5 s**. Its estimate was not an upper bound (593 tokens) and is revised to about 1,350.
- **gpt-4.1-nano:** HTTP 404 `model_not_found`. The router's backup now uses gpt-4o-mini. The catalogue flag is left to the team, because a teammate's test pins that file's hash (TODO-17).
- **mimo-v2.5:** HTTP 400; two diagnostic calls follow.
- **json_schema probe:** redone on gpt-4o-mini.
- **The spend guard's "stopped" line** refers to that call's own guard. The live check uses one guard per call (A-116, A-120). In a pipeline run the stop holds, and a test now proves it.

**Experiment ID again:** main's #33 (R-C3, Pipeline C, after the sync of this morning) took `exp-route-012`, so the decision router's experiment is now **`exp-route-013`** (folder, tests and references renamed; Pipeline C's are untouched). Main's ADR-0046 is R-C3's, so the router's draft ADR will be numbered 0047 or later at merge.

Status: **awaiting `runs\finish_router_2.ps1`**: the failing tests, one benchmark, the offline shadow run and the live diagnostics.
