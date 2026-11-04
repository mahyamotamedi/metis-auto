# Sprint decisions: what was tried, what won, why (N-1)

Status: **provisional: cost only, pending quality.** Written 2026-11-03 (plan task N-1, `docs/2026-11-01-final-plan.md` "Decision rules"). Every figure is an offline replay on logged requests (evidence class *simulation* or *hypothetical reconstruction*); **no quality is measured**, no model was called and nothing was spent. Traces: FR-EVAL-06, QA-COST, H-1, H-3, H-5, X1, X7; ADR-0031, ADR-0032, ADR-0036, ADR-0037, ADR-0044, ADR-0046, ADR-0047, ADR-0051, ADR-0053.

## How to read the tables

- **Population:** the report split (Aug–Oct 2026, 73,063 requests; 20,750 LLM requests), read with settings frozen on the tune split. Rows marked *tune* have no report read. The popular-question cache and `rc-v1` are scored on the report *period* (77,774); the decision router and C's classifier on 73,062 (the period filter drops one row). The combined run (Stage 4) uses the 73,063 split for everything.
- **Units:** `as_logged` is recorded cost (fees + token cost). `todays_models` and `premium_gpt_5_5` are price-file units, token cost only (fees are not priced). Recorded and repriced figures are never added. `best_single_cheap` is 0 for every routing version (the cheapest model is already the target) and is left out of the tables.
- **Share** is the saving as a share of the baseline cost over LLM requests with a known cost, with the session-clustered 95% interval where the version has one. Ranks exist only inside one step and one baseline (`reports/levers/comparison.md`).
- **Candidate lists changed on 2026-11-03** (owner): `gpt-4.1-nano` (HTTP 404) and `mimo-v2.5` (HTTP 400) left `sprint.toml [routing] candidates`; the primary set (reasoning-billed models out) is `gpt-4o-mini` alone. Versions not re-run with the new list are marked *not re-run*.

## Cache

| version | n | as_logged | todays_models | premium | correctness | overhead p95 |
|---|---|---|---|---|---|---|
| A popular question `pq-v1`, first turn | 77,774 | 0.31% [0.27, 0.36] | 0.22% | 0.20% | sampled:30 | 49.5 ms |
| A popular question `pq-v1`, all turns | 77,774 | 0.37% [0.33, 0.42] | 0.26% | 0.26% | unmeasured | 48.9 ms |
| A popular question `pq-v2` (24 h), first / all turns | 77,774 | 0.07% / 0.08% | 0.05% / 0.06% | 0.04% / 0.06% | unmeasured | 51.7 / 48.8 ms |
| **B retrieval-result cache `ttl_1d`** (**winner**) | 73,063 | **1.37% [1.26, 1.49]** (fees only) | not computed | not computed | unmeasured | 7.5 ms |
| B `ttl_7d` / `ttl_30d` / `ttl_90d` (*tune only*) | 230,762 | 1.48% / 2.04% / 2.51% | not computed | not computed | unmeasured | 7.5 ms |
| C session memo + greeting gate | 73,063 | 1.35% [1.17, 1.54] (fees) | not computed | not computed | unmeasured | not measured |

**Decision rules applied.**
- *Retrieval caches (B, C) need agreement ≥ 0.9.* B `ttl_1d`: mean agreement **0.985** over 991 evaluable hits → **passes**. C: on the report split the memo reused **0** lookups and **0** were evaluable (the saving is the greeting gate's 789 skipped lookups, word list still `[PLACEHOLDER: Persian review]`) → **no agreement evidence, not passed**.
- *Answer caches (A) need error ≤ 1% over about 300 reviewed hits.* Reviewed: **30** (K-1) → A stays a **candidate**, never a winner.
- *Pick:* the highest net saving that passes.

**Provisional winner: B retrieval-result cache, `ttl_1d`** (provisional: cost only, pending quality). It saves the fee block only; answers are still generated, so context and routing still apply to those requests. The longer TTLs save more on tune (up to 2.51%) but have no report-split read, so they cannot be picked without a second look.

**Runner-up: A popular question `pq-v1` all turns** (0.37% as_logged). It serves a stored answer, so it targets a different block than B and may be **combined** with B (answer cache first). It becomes a winner if hit judging over about 300 reviewed hits shows an error rate ≤ 1%. Third: C memo + gate, which needs reuse-agreement evidence ≥ 0.9 and the K-2 word-list review.

## Context (tokens only, quality not measured)

| version | n | as_logged | todays_models | premium | overhead p95 |
|---|---|---|---|---|---|
| **C within-message dedup** (**winner**) | 73,063 | **6.11% [5.97, 6.25]** | 7.45% [7.03, 7.88] | 8.17% [7.67, 8.70] | not measured |
| B cross-turn chunks `k1`, pointer 8 (report) | 73,063 | 4.10% | 3.41% | 3.73% | 9.8 ms |
| B cross-turn `k0` (report; nothing assumed visible) | 73,063 | 0.00% | 0.00% | 0.00% | 9.2 ms |
| B cross-turn `all` (*tune only*) | 220,908 | 3.89% | 6.01% | 5.42% | 8.9 ms |
| A `rc-v1` reranker cut, observed relevancy | 77,774 | 1.91% [1.83, 1.98] | 2.42% [2.24, 2.63] | 2.61% [2.41, 2.81] | not measured |
| C history budget `b2000` / `b4000` / `b8000` / `half_over_8k` | 73,063 | 0.08% / 0.06% / 0.04% / 0.05% | 0.06% / 0.05% / 0.03% / 0.03% | ≤ 0.02% | not measured |

Not shown: A `rc-v1` with the `lexical_overlap` scorer (a 2,000-request sample, heuristic): **excluded from the combined run**, kept as a file.

Real reranker not run: no GPU on the owner's machine (Intel Mac, no CUDA or MPS). The A `rc-v1` rows rest on the token-sizing results `context.reranker_cut.lexical_overlap` and `observed_relevancy`, both *heuristic* scorers, not the real `bge-reranker-v2-m3`.

**Decision rule.** Context is "tokens only, quality not measured": no version can pass the plan's quality rule (loss minus win within noise + 3 points; no group more than 10 points worse; JSON validity, language and refusal rate not worse) without the paid ablation. Pick by saving, label every result accordingly.

**Provisional winner: C within-message dedup** (provisional: cost only, pending quality). It removes only **exact copies** of a chunk inside one message, so it is the lowest-risk way to remove tokens, and it saves the most (6.11% as_logged).

**Runner-up: B cross-turn chunks `k1`** (4.10%). Its saving rests on the stated visibility assumption (a chunk is still visible one turn back, A-84/EDA §2); it becomes a winner if the context ablation passes and visibility is checked. **Combining:** C's history budget and dedup save different tokens, but the history budget saves ≤ 0.08%, so a `ChainedContext` is **not needed for the winners**. `rc-v1` is built to run after dedup (no double counting); it is a chain candidate (+1.9%) only if the ablation passes.

## Routing (no labels: cost only)

| version | n | as_logged | todays_models | premium | overhead p95 | note |
|---|---|---|---|---|---|---|
| **Parham decision router, rules-only** (**winner, cost only**) | 73,062 | **21.94% [20.87, 23.27]** | **17.83% [16.38, 19.38]** | 28.41% [25.71, 30.89] | not measured | primary candidates |
| A per-bot reassignment (**runner-up**) | 73,063 | 3.94% [3.51, 4.31] | 3.74% [3.03, 4.48] | 5.92% [4.83, 7.11] | not measured | primary candidates |
| A per-bot + reasoning models | 73,063 | 3.85% [3.44, 4.23] | 7.12% [5.69, 8.51] | 8.23% [6.51, 9.97] | not measured | lower bound, reasoning not counted |
| B kNN `k5` | 73,063 | 2.46% [2.18, 2.86] | 2.25% [1.90, 2.74] | 3.34% [2.86, 3.88] | 421.6 ms (fails 100 ms) | *not re-run* (old candidates) |
| C small classifier `rules` | 73,062 | 3.15% [2.42, 4.48] | 1.60% [1.36, 1.92] | 1.95% [1.73, 2.16] | not measured | re-run with the new candidates, `MAX_INPUT_TOKENS` 16,000 still the tune choice |
| C small classifier `strict` | 73,062 | 1.48% [1.30, 1.71] | 0.84% [0.75, 0.96] | 1.04% [0.93, 1.14] | not measured | re-run with the new candidates |

**Decision rule.** Without labels no routing version can pass "acceptable rate within 10 points of the incumbent (lower 95% bound)". So: pick by cost only and say so; **keep a more complex router only if it beats per-bot reassignment outside the interval.**
- The decision router (`todays_models` [16.38, 19.38]) is outside per-bot's [3.03, 4.48] → **kept**.
- B's kNN (2.25%) and C's classifier are below per-bot → **dropped** (they do not beat the reference).

**Provisional winner: the decision router, rules-only** (`router.mode = "off"`; provisional: cost only, pending quality). Read it for what it is: the gate and rules send ~4% of requests to tier 0 (no tier-0 candidate is primary, so those stay) and the **safe tier (1) takes about 96%**, whose only primary candidate is `gpt-4o-mini`. The saving is mostly "move that traffic to `gpt-4o-mini` wherever it is cheaper than the logged model", chiefly away from Gemini, which carries 65% of cost. It says nothing about whether `gpt-4o-mini` answers well enough. THX-01 changed no decision on the dev slice (A-121) and Jev scored 72% on 100 *synthetic* requests (not evidence on real traffic), so "rules-only" is both the inline mode and the only mode that can run on 300k requests.

**Runner-up: A per-bot reassignment** (3.74%). A bot moves only if its target is eligible for **all** of its tune traffic, so it is the conservative router. It becomes the winner if the benchmark shows `gpt-4o-mini` fails the acceptable-rate rule on the decision router's tier-1 traffic but passes on the bots reassigned whole.

## Combined results (I-1, report split, 73,063 requests)

Each pipeline's saving as a share of the baseline cost over the same rows, frozen versions, one report-split run, sum rule held for every cell. **Provisional: cost only, pending quality.** Recorded (`as_logged`) and price-file units are never added; the retrieval cache and memo have no price-file figure (fees are not priced), so their cells are "not computed". Routing is priced on the post-context tokens (`PostContextRouting`, stated assumption). Source: `reports/pipelines/sprint-final/summary.json`, `reports/levers/final.json`.

| pipeline | as_logged | todays_models | premium_gpt_5_5 |
|---|---|---|---|
| Pipeline A (popular question, `rc-v1`, per-bot) | 5.40% | 6.08% | 8.33% |
| Pipeline B (retrieval cache, cross-turn `k1`, kNN `k5`) | 7.83% | 5.62% | 6.98% |
| Pipeline C (memo + gate, dedup, classifier `rules`) | 10.60% | 9.05% | 10.13% |
| Parham (decision router alone) | 21.00% | 17.83% | 28.41% |
| **Winners (provisional)**: retrieval cache + dedup + decision router | 27.07% | 22.92% | 31.53% |

- The winners combine to **27.07%** of recorded cost and **22.92%** at today's logged models' prices. Nearly all of it is the decision router (21.0% / 17.8% alone), which is mostly a move of the safe tier to `gpt-4o-mini`: it says nothing about quality.
- Unexplained cost (F-2): 0.43% of recorded cost in the report period (11.7% over all data, most of it March, in the tune period). It is part of token cost and is shown on the Results page so no share hides it.
- `best_single_cheap` saves 0 for routing everywhere (the cheapest model is already the target); its cells come from context only.
- Combined intervals are not computed (the steps overlap); each version's own interval is in `final.json` (`versions`).

## What did not run, and why

- B's kNN router tune re-run (`rb3`) was first stopped after 29 minutes against a 16-minute estimate; it was **re-run to completion on 2026-11-04** (next bullets) for the tune split, including `k15`, `k50` and `with_reasoning_models`. Only the report-split kNN row is still *not re-run*.
- C's `strict_unknown_blocked` and `rules.with_reasoning_models` **were re-run on 2026-11-04** (offline, about 20 s per mode, new candidate list; `scripts/small_classifier_levers.py` and `--strict`, report split, frozen thresholds): every number and config hash equals the files already in `reports/levers/`, so they are current; `reports/levers/comparison.md` was regenerated. They are not winners or runners-up.
- Sprint close (2026-11-04): the kNN **tune** re-run finished with the block-cached neighbour search (`rb3 --resume`, four passes; the last completed). The nested CV chose `k5` in all five outer folds (equal to the frozen `k5`), and the 24 tune `LeverResult` files (`k5`, `k15`, `k50`, each primary and `with_reasoning_models`, four baselines) and `reports/routing/exp-route-011/summary.json` were regenerated with the new candidate list; `comparison.md` was regenerated. **Still not re-run:** the kNN **report-split** row (`rb3-report`, `k5`): the owner approved one report run only, so it keeps the *not re-run* label.
- Slices/overhead on non-winners: see the progress entry.

## Quality evaluation plan (not run)

Nothing below was run, and nothing may run without the gates.

**Versions for the paid quality run (and why the others are dropped).**
- *Routing:* the decision router's tier-1 target `gpt-4o-mini` (the savings driver); `gpt-5-nano` and `deepseek-v4-flash` as comparison arms. Per-bot reassignment needs no extra arms (same targets). Dropped: kNN and C's classifier (they do not beat per-bot on cost, so paying to judge them has no use).
- *Answer cache:* hit judging of A `pq-v1` all turns and first turn (the runner-up); `pq-v2` (24 h) saves under 0.1% and is dropped.
- *Context:* the ablation on dedup (winner), B cross-turn `k1` and `rc-v1` (runner-ups); history budgets (≤ 0.08%) dropped.
- *Retrieval caches:* B `ttl_1d` agreement is **already measured** (0.985); C memo/gate needs its own evidence.

**Routing arms against `config/evaluation/benchmark.toml` and ADR-0053.** `plan` (no call) shows callable arms: `gpt-5-nano`, `gpt-4o-mini`, `deepseek-v4-flash`. **Cannot be called:** `gpt-4.1-nano` (HTTP 404) and `mimo-v2.5` (HTTP 400) are on the `[arms.not_callable]` list (kept there until the catalogue owner disables them, TODO-17); `jev-latest` is a decision model, not an answering arm; `gemini-2.5-flash` (12.5% of requests, 65% of cost) is **not an arm** (not OpenAI-compatible; the native adapter is offline until a live check, ADR-0043). So the benchmark compares the cheap arms against the `gpt-5.5` reference and can say nothing directly about Gemini's own answers; the free logged-answer arm is not wired (TODO-21). No arm has to be added; the benchmark's own `[arms]` list should drop the two retired models when the catalogue owner disables them.

**Checks and the rule each decides.**
| check | decides | cost in the plan |
|---|---|---|
| Routing: P-1 to P-3 benchmark (ADR-0053), golden-v2 pilot, two judges, both orders, 60-item human spot-check | the routing rule: acceptable rate within 10 points (lower 95% bound, judge-corrected) and lower cost; whether a complex router beats per-bot outside the interval | about 20–25 USD for 300 requests (plan estimate) |
| Answer cache: hit judging (cut-first d) | answer error ≤ 1% over about 300 reviewed hits | about 15 USD (plan) |
| Context: ablation (cut-first d) | loss − win within noise + 3 points; no group > 10 points worse; JSON validity, language, refusals not worse | about 15 USD (plan) |
| Retrieval caches: agreement | agreement ≥ 0.9 | already measured, free |

**What changes when labels arrive.** Result fields `correctness_state` (`unmeasured` → `sampled:<n>` / `measured`), the `assumptions` line "quality not proven" / "tokens only, quality not measured" (replaced by the measured rate and its interval), and the winner label "provisional: cost only, pending quality" in this file, `sprint-final.toml` and `final.json`. `evidence_class` stays *simulation*. Re-run the combination with `python scripts/run_sprint_final.py experiments/pipelines/sprint-final.toml` and `python scripts/compare_levers.py reports/levers/*.json --out reports/levers/comparison.md`; because every candidate keeps its `LeverResult`, a winner that fails quality is swapped for its runner-up without re-running anything.

**Gates before any spend.**
1. Metis permission to send samples to model APIs (gate 2, Q-55): **missing**.
2. Owner values Q-62 to Q-64 (budget share, run cap, generation limit, order seed; judges and thresholds; machine list and summary age): **unset** (`benchmark.toml`).
3. Budget: ADR-0018 Amendment 3 (92 USD) is **committed**; the plan's gate list still names Amendment 2 and should say Amendment 3. Spend on other machines is not visible until `spend_share.py` summaries exist.
4. Per-run owner approval after the printed estimate.

**Cost.** `scripts/benchmark.py plan` and `scripts/sampling_plan.py` were run in their no-call mode on 2026-11-03: **estimate not computed** (`generation.max_output_tokens`, `judges.models` unset; input sizes need the golden-v2 database; the sampling plan's dimensions are unset). The USD figures above are the plan's, not a computed estimate.
