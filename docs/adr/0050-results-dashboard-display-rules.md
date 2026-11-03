# ADR-0050: The Results dashboard shows each step on its own, hides recorded-unit slices under repriced baselines, and prices repriced totals as token cost only

- Status: **provisional**, the agent's reading of the approved UI spec (Pipeline C, sprint task D-2, 2026-11-03), until the owner reviews it. The owner already decided points 2 (D-2 follow-up of 2026-11-02) and 3 (S-3 decision 3, 2026-11-02); this ADR records how the page applies them.
- Date: 2026-11-03
- Relates to: [ADR-0024](0024-demo-ui-streamlit.md) (thin Streamlit page, logic in wiring), [ADR-0032](0032-lever-result-and-manifest-format.md) (`LeverResult`), [ADR-0036](0036-replay-scope-split-and-baselines.md) (recorded vs price-file units; repriced baselines have no `fees`), [ADR-0039](0039-session-memo-gate-accounting.md) (greeting gate token part), spec `docs/design/metis-auto-ui-spec.md` §6.2 (UI-R20 to UI-R30).
- Code: `src/metis_auto/wiring/lever_view.py` (`dashboard`, `waterfall`, `cache_monitor`, `version_key`), `src/metis_auto/wiring/ui_config.py`, `scripts/demo_pages/results.py`; tests `tests/unit/wiring/test_results_dashboard.py`, `tests/unit/wiring/test_lever_view.py`, `tests/integration/test_demo_ui_app.py` (Results page).

## Context
The spec (UI-R20 to UI-R30) asks for a Results page over `reports/levers/*.json`: baseline and slice selectors, savings cards, a waterfall by cost block, a version comparison, a version switch per step, a cache monitor, routing per bot and the greeting gate's token part. The committed results (124 files, 2026-11-03) raise questions the spec does not answer:

- Pipeline B's repriced results (`rb1.*`, `rb2.*` under `premium_gpt_5_5`, `todays_models`, `best_single_cheap`) carry slices in **recorded units** (with `baseline:fees`) inside a repriced result. Shown as they are, a slice would mix units (ADR-0036).
- Slices carry `baseline:*` / `saving:*` keys, but the interval (`ci_low`, `ci_high`) belongs to the result as a whole.
- No `combine`-based result and no `final.json` exist; the format of `final.json` (I-2) is not agreed.
- Pipeline A's files reuse one `lever_id` for all four baselines (only the file names differ), so a `lever_id` is unique only per baseline.
- No result carries an `other` block (F-2) or guard-block reasons.

## Decision
1. **Repriced totals are token cost only (FR-REQ-04, ADR-0036).** Under a repriced baseline the fees row is "not priced", never unknown, and the totals are the token cost, labelled "token cost only, fees not priced". A missing `token_cost` key falls back to the stored `total`, which for a repriced baseline is the token cost.
2. **A slice is shown only in its baseline's units.** A slice holding `baseline:fees` inside a repriced result is in recorded units; it is not shown, with that reason. Routing per-bot money columns follow the same rule.
3. **`other` is part of `token_cost`** (owner, 2026-11-02). It is shown as its own row, marked as part of token cost, and never added to the totals a second time.
4. **Slice option "Result totals" (default).** It shows the result's own `baseline_cost` / `saving` with the interval. Every other slice shows its own `baseline:*` / `saving:*` / `saving_share` values, says that the interval belongs to the result totals, and is "not in the result" when absent.
5. **No combined number.** The overview shows each step's chosen version on its own; savings of different steps are never added (they can overlap, Review Focus 1). The version switch changes which version a step shows. `final.json` is only detected: present → "format not agreed yet (I-2)". When I-2 fixes its format, the overview reads it.
6. **Ranks only from `compare.compare`** (one step, one group, one baseline; insufficient evidence never ranked). The group label shows the request count and price version and leaves out the data-revision hash (no hashes on screen).
7. **Cache monitor counts as stored.** Retrieval cache: misses = lookups − hits − guard blocks − ineligible (its four statuses). Session memo: hits = reused, misses = lookups that ran. Others: misses = eligible requests not served from the cache. Each row says how it counts. Guard-block reasons are "not in the result" until a writer stores them.
8. **Default baseline: as-logged recorded cost**, the only baseline in recorded units; the other three are a click away.
9. **Lookups are per baseline** (a `lever_id` is unique only per baseline).

## Alternatives considered
- **Show repriced totals as unknown** (D-1 behaviour): true but unhelpful; the owner asked for "token cost only, fees not priced". Replaced.
- **Show recorded-unit slices under a repriced baseline with a warning:** mixes units on one screen. Rejected (ADR-0036).
- **Add the steps' savings for a combined card:** double counts overlapping savings. Rejected until a `combine`-based result exists.
- **Default to the premium baseline** (first in the spec's list): its estimate is the largest and least observed. Rejected for the default; still selectable.
- **Fix Pipeline B's slices or Pipeline A's lever IDs here:** their writers are theirs. Reported instead.

## Consequences
- Pipeline B's repriced slices are hidden until B writes them in price-file units (or drops `baseline:fees` from them): tell B.
- Pipeline A's shared `lever_id` across baselines contradicts ADR-0032 ("the file name"): tell A; the view copes.
- The combined view (demo script step 1) needs I-1/I-2 output; until then the page states that no combined result exists.
- Guarding tests: `test_repriced_total_says_fees_not_priced`, `test_repriced_slice_in_recorded_units_is_not_shown`, `test_other_block_is_part_of_token_cost`, `test_version_switch_changes_the_overview_never_sums_steps`, `test_different_baselines_or_price_versions_never_ranked_together`, `test_cache_monitor_counts_match_lever_result`, `test_real_results_shown_exactly_as_stored`.
