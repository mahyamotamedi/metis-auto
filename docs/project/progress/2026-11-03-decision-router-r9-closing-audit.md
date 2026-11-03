## Decision router R9: closing audit (2026-11-03)

Checked in the workspace (Linux):
- **Tests:** 1,970 passed, 38 skipped, 2 failed. The two failures are the tokenizer-asset tests that fail the same way on an untouched main here.
- **Ruff:** check and format clean.
- **Progress index:** current.

- **Import rules:**
  - `httpx` only in `systemone_http.py` and `jev_metis.py`;
  - torch and transformers only in `thx01_local.py` (and the compressor);
  - adapters import only ports and contracts; costs are injected by wiring;
  - experiments are loaded by path.
- **Privacy:**
  - new `tests/architecture/test_router_reports_privacy.py`: no Arabic-script text under `reports/routing/`, and the slice IDs are opaque;
  - new `test_router_events_carry_no_message_text`;
  - the live check's and the shadow evaluation's outputs are tested content-free;
  - hosted backends never receive dataset states (`real_data_approved` stays false).
- **Module reference:** rows for `jev_metis`, `llm_system_one`, `router_eval` (wiring and metrics) and `router_live_check`; `routers`, `router_replay` and `chat` updated. The import columns match the code (tested).
- **Traceability:** exp-route-013's README cites H-1, the FR/QA IDs and the ADRs. The Jev note and the register cite their sources.
- **Register:**
  - A-106 to A-110 approved;
  - Q-61 answered;
  - TODO-18 resolved;
  - new A-111 to A-117 and TODO-19.
- **Glossary:** Jev, THX-01, Mode 1 / Mode 2, shadow evaluation.
- **Draft ADR:** R6–R8 section and the R-0 integration.
- **Serving defaults unchanged:** `router.mode = "off"`, `policy = "fixed_model"`, every router backend disabled.
- **Teammates' tests:** none broken. One hook in a teammate's test (`test_live_sdk_imports.py`), described in the R6 entry.
