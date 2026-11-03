## Decision router: second sync with main, and R-0's routing base (2026-11-03)

Parham's copy (main `873b2a1` plus the uncommitted router work) was brought up to main `355d5f2` (#30–#32):
- R-C2 history budget, Pipeline C;
- R-0 routing base, Pipeline C: `analysis/routing_base.py`, ADR-0045;
- CI pinned to ubuntu-24.04, with a new step running `adr_finalize.py --check` and `progress_index.py --check`, ADR-0035 amendment 1.

There were no textual conflicts, and no teammate file was changed. Backups of every changed file: `runs\backup\upstream-sync-2\` (git-ignored). Nothing committed.

**Taken from the owner's machine first:** the pinned `config/reference/routers.toml` (`routers-2026-11-03`, THX-01 at `b323afc`, 6 files). Two router tests that assumed an unpinned table now check the pins.

**Consequences:**
- The router's draft ADR will get the next free number at merge (0046 on this main; 0047 or later once R-C3's ADR-0046 is merged). CI on a branch carrying it is red until the merger runs `adr_finalize.py`; ADR-0035 amendment 1 says that is expected.
- R-0 landed, so the decision router plugs into it, offline only: exp-route-013's routing step version uses `candidate_costs` and `candidate_list` unchanged (A-115).
  - The serving path keeps the serving eligibility filter, as ADR-0045 itself decides. Layer rules also forbid `domain`/`application` from importing `analysis`.
  - No R-0 file was changed.
