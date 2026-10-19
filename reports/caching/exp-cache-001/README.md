# EXP-CACHE-001: exact-cache baseline (sample; re-run 2026-10-19)

**Candidate hits, not safe hits.** Nothing here checks whether a matched answer would have been right: hit correctness is *unmeasured* in every row. The sample is exploratory, so every number is a provisional signal (ADR-0008). Plan: [caching_plan.md C1](../../../docs/experiments/caching_plan.md#c1-exact-cache-baseline-exp-cache-001-done-2026-10-18). Config: [experiments/caching/exp-cache-001-exact-baseline/config.toml](../../../experiments/caching/exp-cache-001-exact-baseline/config.toml).

| Run | Loader treatment of a missing optional key (`attachments`, `rag`, `input`) | Config hash |
|---|---|---|
| **`exp-cache-001-20261019T054606Z-e8d1f0` (primary)** | `absent`: the keys appear only when present (owner decision Q-37, 2026-10-19; A-61) | `cfg1:eb7571b5b01f8ed6` |
| `exp-cache-001-20261019T054608Z-8d6712` (alternative) | `unknown` (reason `key_missing`), the conservative reading | `cfg1:449dc7a39553cf47` |

In both runs the nulls that occur together (model + provider + instructions, 27 answers in 2 sessions) stay `unknown` (`not_in_log`, Q-25). The counts equal the 2026-10-18 runs of the same code; only which run is primary changed.

Both: 465 replay cases from 100 sessions (432 `clean`, 16 `skipped_consecutive_user`, 15 `unanswered`, 2 `multiple_answers`; 6 answers with no preceding user message excluded), naive logged-time order, counterfactual source `logged_match` (earlier cases' logged answers), code `08638fe` plus the uncommitted Stage 8 changes, sample sha256 `e0f56a2f…49e1`, random fingerprint key per run (A-44: counts reproduce, fingerprints don't). Each folder holds `manifest.json`, `results.json` (every metric per stratum), `extras.json` (the table below and more), and `comparison.md` (the comparison format).

## Candidate hits, literal treatment

`whitespace` and `nfkc_casefold_ws` gave **identical counts** for every variant on this sample. "Cross-session" = a global hit with no same-session match; the sample has no user reference, so same-user vs cross-user is **unmeasured**.

Primary run (missing key = `absent`):

| Variant | Eligible | Within session | Global | Cross-session | Ineligible (attachments / unknown) |
|---|---|---|---|---|---|
| `full` (serving composition), strict | 404 | **0** | **0** | 0 | 14 / 47 |
| `full`, wildcard | 451 | 0 | 0 | 0 | 14 / 0 |
| `full_no_model`, strict / wildcard | as `full` | 0 | 0 | 0 | as `full` |
| `msg_instr_ctx`, strict | 404 | 5 | 6 | 1 | 14 / 47 |
| `msg_instr_ctx`, wildcard | 451 | 7 | 11 | 4 | 14 / 0 |
| `msg_instr`, strict | 404 | 8 | 9 | 1 | 14 / 47 |
| `msg_instr`, wildcard | 451 | 10 | 14 | 4 | 14 / 0 |
| `msg_only`, strict | 451 | 10 | 47 | 37 | 14 / 0 |
| `msg_only`, wildcard | 451 | 10 | 47 | 37 | 14 / 0 |

The 47 strict-ineligible cases (no attachments, instructions unknown): 19 whose paired answer has the null labels (`not_in_log`, Q-25) and 28 with no paired answer to take the answer-side components from (`no_paired_answer`: skipped and unanswered user messages). 11 more cases with unknown instructions have attachments and are counted there.

Alternative run (missing key = `unknown`): **every strict variant is ineligible** for all 451 cases without attachments (their attachments are unknown); the wildcard variants give the same figures as above except `msg_instr_ctx` (9 within session, 13 global, 4 cross-session), where an unknown retrieved context matches a present one.

Candidate hit rates over all 465 cases (primary run): `msg_only` global **10.1 %** (Wilson 95 %: 7.7–13.2 %), within session 2.2 % (1.2–3.9 %); `msg_instr` strict global 1.9 % (1.0–3.6 %); `full` 0 % (0–0.8 %).

Reading:
- **The full serving key finds no candidate** in either run: every repeated message had a different history.
- Narrow variants find candidates, mostly **across sessions** (37 of 47 for `msg_only`). Adding instructions removes most of them (47 → 9), the sample EDA's signal that repeats usually come with different instructions.
- **Lexical answer-match signal** (not correctness): of the 47 `msg_only` global hits, 4 matched a case whose logged answer was identical after NFKC + casefold + whitespace; of the 10 within-session hits, 4. Most message-only matches were answered differently.
- **Lexical repeat groups** (all three treatments): 21 groups with ≥ 2 identical messages, covering 76 of 465 messages; 11 groups cross sessions; the largest has 26 messages.
- Per stratum (`msg_only`, global hits; the same in both runs): the four opaque categories have 14, 11, 7, and 15 hits (86, 95, 139, and 145 cases); first user turns 25 of 100, later turns 22 of 365.

## Baselines and money (estimates, ADR-0020)

| Figure | Value | n (cases) | Notes |
|---|---|---|---|
| As-logged cost, total | 0.1753 USD | 244 of 465 | only cases whose answer labels all map to a priced catalogue model; fidelity `approximation` (counted with chat framing) |
| As-logged cost per priced case | 0.00072 USD | 244 | |
| Premium estimate (gpt-5.4), total | 6.4005 USD | 434 | every case with a logged answer; never called; lower bound (`reasoning_not_counted`) |
| Premium estimate on the **same 244 priced cases** | 1.5774 USD | 244 | **9.0×** the as-logged cost of those cases (the like-for-like ratio; 6.40 / 0.175 ≈ 36× compares different case sets) |
| Coverage (cases with a logged answer) | 93.3 % | 465 | |
| As-logged cost of the `msg_only` global hits | 0.0227 USD | 24 of 47 hits priced | an upper bound on what those candidates could save, if all were correct |
| As-logged cost of the `msg_instr` strict global hits | 0.0189 USD | 3 of 9 hits priced | same reading |

Label resolution of the 436 logged answers: `exact_id` 242, `alias` 2 (`deepseek-chat`, `deepseek-reasoner`), `not_in_catalogue` 132, `not_a_model` 33 (`default`), `unknown_label` 27 (the null labels, Q-25). Prices are the Metis table of 2026-10-18, not those in force at log time.
