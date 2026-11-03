## Decision router R5 finished, R6: Jev via Metis, the LLM backup, the live check (2026-11-03)

Owner pre-approvals of 2026-11-03 applied (no review stop between phases).

**R5.**
- The pinned THX-01 is in the cascade through settings (`[router.backends.thx01]`).
- The slice replay has a `thx01` scenario: the real backend with the fake answering client. `all` still runs the three fake scenarios only.
- The benchmark has every variant:
  - threads 2/4/8;
  - at most 300 message characters;
  - text vs JSON state;
  - `--out` to save a copy.
- The benchmark reports the gate share for the mapping questions and for all questions.

**Q-61 (owner):** the confidence gate reads the mapping questions (complexity, needs_reasoning, cheap_model_ok) by default, through `[router] confidence_questions = "mapping"`; `"all"` reads every answer. `result_confidence` takes the question IDs.

**R6.**
- **Jev:** `adapters/routers/jev_metis.py`.
  - Bearer key, `/v1/systemone`, the reported version.
  - Cost and an upper-bound estimate come from the router price table.
  - No key means unavailable.
- **LLM backup:** `adapters/routers/llm_system_one.py`.
  - The live answering client is asked for JSON; replies are uncalibrated.
  - Cost comes from the catalogue price, injected by wiring.
- **Wiring:** `wiring.routers` builds both backends from settings.
- **Live check:** `wiring/router_live_check.py` and `scripts/router_live_check.py`.
  - Calls: Jev, gpt-4.1-nano, gpt-4o-mini and mimo-v2.5, plus a strict `json_schema` probe.
  - The plan's upper bound is about 0.0014 USD, under the 0.05 USD run cap.
  - Each call runs under its own spend guard (A-116).
  - Without the key the run is skipped and says so.
  - All tests are mocked; no live call was made here.

**TODO-18 (owner):**
- `httpx` is declared in the `router-local` extra; the locked version is unchanged.
- Main's HTTP-client test now checks that `httpx` is declared, and allows it only in the router's two HTTP adapters. This is the one hook in a teammate's file: `tests/architecture/test_live_sdk_imports.py` (Kimia, ADR-0043).

**Approved by the owner 2026-11-03:** A-106, A-107 (as revised), A-108, A-109, A-110. **Mizan** is skipped as future work (A-117).
