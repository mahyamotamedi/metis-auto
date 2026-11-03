## Decision router: Parham's work brought up to date with main (2026-11-02)

Parham's copy was cloned at `4d28bf3` (#9) and carried the decision-router work R0 to R5 uncommitted (46 modified files, 70 new). Main had moved to `873b2a1` (#29: 18 merged pull requests, 319 files). The teammates' changes were applied under his work; nothing of his was dropped. Status: **awaiting review**; nothing committed (the owner commits).

**Merged.** Six files changed on both sides and were resolved by hand: `settings/loader.py` and `settings/model.py` (both new section names kept: `data` from the router, `events` and `cache` from Pipeline B), `wiring/from_settings.py` (both imports), `docs/architecture/module_reference.md` (the `wiring/from_settings.py` row holds both the router and the event-sink and cache-store functions, with the union of imports), `docs/README.md` (main's generated ADR table; the router line kept under the guides), and `progress.md`.

**Main's conventions applied to the router work** (AGENTS.md, `docs/adr/README.md`):
- The router's ADR was numbered 0031 on this copy while main gave 0031 to the full-data lever replay. It is now the draft `docs/adr/0047-system-one-decision-router.md`, cited as ADR-0047 in every router file; main's own ADR-0031 references were left alone. `adr_finalize.py` gives it the next free number at merge (0047 or later: main had reached 0046 by 2026-11-03).
- The router's progress sections moved out of `progress.md` into six entries (R0 to R5, follow-ups inside each), with their links one folder deeper; `progress.md` is main's index, regenerated with `progress_index.py`.
- The experiment ID `exp-route-011`, which this copy's router work used for its future evaluation, was taken on main by the kNN router (Pipeline B, #24). The router's references now say `exp-route-013`; Pipeline B's are unchanged. The routing.md §7 heading no longer carries the ADR number, so its anchor survives the finalize step.
- Docstrings and comments that grew past 88 characters with the placeholder were re-wrapped (ruff clean); the contracts field reference was regenerated.

**Two of main's new rules met the router code.**
- `test_stdlib_http_only_in_the_gemini_adapter` (ADR-0043): `adapters/routers/hub.py` (R5, stdlib `urllib`, the model pinning client; never on the request path) is added to its allow-list, with the reason.
- `test_no_gemini_sdk_or_undeclared_http_client_anywhere`: the local `/v1/systemone` client imports `httpx`, which every lock installs through `huggingface-hub` but `pyproject.toml` does not declare. Exempted in that test as **TODO-18**, open for the owner (declare it in `router-local`, or move the client to `urllib`).

**Locks.** Main fixed part of TODO-16: `requirements-dev.lock` now carries `colorama` and `tzdata` with `sys_platform == "win32"` markers. The same two entries, with the same hashes, were copied into `requirements-router-local.lock`, so its install needs no `runs\win-extra.txt` (router quickstart §1 and §7 updated; the `db`, `compress` and `ui` locks still need it).

**Noticed, not changed.** Main's `config/defaults.toml` now has `lifetime_cap = "20"` (ADR-0018 amendment 2, for the golden-answers run). The router's rule stays a 10 USD lifetime cap on this machine; it is set in the git-ignored `config/local.toml` before any live call (R6).

Tests (Linux): 1,907 passed, 2 failed, 38 skipped; the two failures are the tokenizer-asset tests that fail the same way on an untouched main in the same environment. Ruff check and format clean; `progress_index.py --check` OK.
