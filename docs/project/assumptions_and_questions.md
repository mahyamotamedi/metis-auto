# Assumptions & Open-Questions Register

Living register. Last updated 2026-10-14 (Stage 1). Context: [context.md](context.md). Decision records: [`docs/adr/`](../adr/).

Tags:
- **Kind:** `current` (a current requirement), `future` (a likely future need), `spec` (speculative).
- **Status:** `decided`, `provisional`, `open`.
- **Question status:** `answered`, `partly answered`, `open`.

When an item is resolved, keep it in place, update its status, and say how it was resolved.

## Assumptions

| ID | Assumption | Kind | Status | Basis / what would overturn it |
|---|---|---|---|---|
| A-01 | The sample's schema (roles, fields, nesting) is **not** assumed to represent the full dataset's schema or quality. Contracts are generic; sample quirks are confined to a sample loader. | current | decided (revised 2026-10-14, [ADR-0008](../adr/0008-sample-eda-is-exploratory.md)) | Previously: "representative, provisional". The full EDA (Stage 9) establishes the real schema. |
| A-02 | Category labels are opaque strata. We never infer their meaning or tune to one category. | current | decided | The brief says categories are intentionally unnamed. |
| A-03 | Logged `instructions` *may* be the system prompt sent to providers, but this is unproven. Designs must work either way. | current | open | Production prompt-construction code or payload logs (U-04). |
| A-04 | Bot↔user pairing in the sample is the EDA's "latest preceding user by array order" heuristic. It is never treated as a clean 1:1 log. | current | decided | A request ID in the full dataset would replace it. |
| A-05 | The online system will mint its own correlation IDs (request, session, attempt). The sample's absence of IDs is not carried into the online design. | future | provisional | Confirmed in Stage 4 contracts. |
| A-06 | Timestamps are kept **naive**. No timezone is inferred. Analyses never mix `created_at` with message timestamps without saying so. | current | provisional (unverified) | Data owner states the timezone (Q-06). Confirmed as the working assumption 2026-10-14. |
| A-07 | Model and provider labels are not billing entities. Cost needs a curated mapping from label to priced model. | current | decided | C-02. |
| A-08 | Tokenization, embeddings, and similarity must be Persian-aware (a design principle). That Persian is *dominant* is a sample signal (F-2) to re-verify. | current | decided (principle); provisional (share) | Brief §4 says "predominantly Persian"; the full EDA gives the real mix. |
| A-09 | Content is sensitive despite the brief's PII claim. No raw text goes into docs, logs, fixtures, commits, or exported tables. | current | decided | Master prompt §2 Privacy; C-12. |
| A-10 | Python 3.13 is the implementation language. | current | decided | [ADR-0001](../adr/0001-python-tooling.md). |
| A-11 | Offline replay over the dataset is the first consumer of the architecture. An online gateway comes later. | current | decided | Master prompt §4. |
| A-12 | Audio attachments may appear later (the brief mentions them). They aren't in the sample. | future | open | Full dataset. |
| A-13 | Experiments will eventually make live provider calls (for counterfactual answers or judges), opt-in and under a spending cap. Until then everything uses mocks or recorded responses. | future | decided (approach); open (providers, budget) | [ADR-0003](../adr/0003-offline-by-default-model-calls.md). |
| A-14 | RAG contexts of exactly 4,019 chars are **likely capped or truncated**. Treat them as possibly truncated. | current | provisional (unverified) | Data owner (Q-09). |
| A-15 | The failover target ("to ensure 100…") is likely 100% availability. Treat it as a **high-availability target with the exact SLA unknown**. | current | provisional (unverified) | Brief owner (Q-04). |
| A-16 | `input.items` and the `default`/`workflow` labels have **unknown meaning**. Keep the cautious proxy treatment: an uncertain configuration feature, and labels that aren't models. | current | provisional (unverified) | Data owner (Q-09). |
| A-17 | The premium baseline is a configuration setting with a clearly marked placeholder. The as-logged baseline is mandatory for every experiment. | current | decided | [ADR-0002](../adr/0002-configurable-baselines.md). |
| A-18 | All of Metis-Auto's own work (router, embeddings, judge, verifier, failed and escalated attempts) counts against savings. | current | decided | FR-ACCT-03, [ADR-0006](../adr/0006-evaluation-metric-definitions.md). |
| A-19 | Requests with attachments are **not cache-eligible** by default, because attachment content is unseen. | current | provisional | A content-hash rule plus evidence from the full dataset. |
| A-20 | No single cheap signal is assumed sufficient to detect an unsatisfactory answer. Escalation will combine detectors, and the useful ones are found by experiment. | current | provisional | Cascade experiments (U-07). |
| A-21 | Quality claims rest on non-inferiority against a baseline, or on judge scores, not on agreement with as-logged answers alone. | current | decided (δ provisional, Q-13) | [ADR-0006](../adr/0006-evaluation-metric-definitions.md). |
| A-22 | Pipeline overhead measured on a local dev machine is indicative only. Hardware is recorded with every measurement. | current | decided | Online-phase measurement. |
| A-23 | Every sample-EDA number is a provisional signal, not a fact. Designs may be informed by it but not depend on its exact value. | current | decided | [ADR-0008](../adr/0008-sample-eda-is-exploratory.md). Re-verified by the full EDA. |
| A-24 | The sample-EDA helpers are unreliable and reference-only. | current | decided | [ADR-0008](../adr/0008-sample-eda-is-exploratory.md). |

## Open questions — project decisions

| ID | Question | Status | Resolution / next step |
|---|---|---|---|
| Q-01 | Add the project brief to the repo? | **answered** | Yes. Committed at `docs/brief/project-draft.pdf` ([ADR-0004](../adr/0004-repository-hygiene.md)). |
| Q-02 | Commit the master prompt, renamed without `_1`? | **answered** | Yes. Now `metis_claude_code_master_prompt.md` at the root (ADR-0004). Its final location is part of Stage 2. |
| Q-03 | Tracked vs. ignored for `.idea/`, `.vscode/`, `AGENTS.md`, `docs/agents/`. | **answered** | IDE folders are untracked and stay ignored. `AGENTS.md` (root) and `docs/agents/` are tracked and their ignore lines removed (ADR-0004). Where `docs/agents/` should live is a Stage 2 proposal; not moved yet. |
| Q-05 | Which concrete model is the "single premium-model baseline"? | **open** | Deferred until the full data, provider access, and verified prices exist. Meanwhile it is a configurable placeholder ([ADR-0002](../adr/0002-configurable-baselines.md)). |
| Q-07 | Dependency manager and linting. | **answered** | Python 3.13, venv + pip, `pyproject.toml`, locked versions (pip-tools with hashes, provisional), ruff for lint and format, pytest. The venv must come from a real Python 3.13, not conda base ([ADR-0001](../adr/0001-python-tooling.md)). |
| Q-08 | Are live provider calls allowed? | **partly answered** | Eventually yes. For now none: mocks or recorded responses by default. A spending cap is planned, and live runs are refused until it is set. **Open:** provider choice, budget amount ([ADR-0003](../adr/0003-offline-by-default-model-calls.md)). |
| Q-10 | Should teammate EDA branches feed this work? | **open** | Not addressed. `origin/main`'s EDA remains the sole baseline. |
| Q-11 | When is the full dataset expected, and at what size? | **open** | Not addressed. |
| Q-12 | Budget amount for live runs. | **open** | Needed before any live run (ADR-0003). |
| Q-13 | What quality loss counts as "material"? That is, the non-inferiority margin δ, and which signal (judge or human) is authoritative. | **answered (provisional)** | 2026-10-14:<ul><li>δ: mean judge score drops at most **3%** vs. baseline overall, **and** no stratum (opaque category, language) drops more than **5%**.</li><li>Primary judge: **LLM-as-a-judge**, calibrated against a small human-rated set.</li><li>Similarity to logged answers is a secondary metric only.</li><li>Revisit with the full dataset.</li></ul>Working interpretation, to confirm: "%" is **relative** to the baseline's mean judge score. Thresholds are configuration. Recorded in [ADR-0006](../adr/0006-evaluation-metric-definitions.md) and QA-QUAL. |
| Q-14 | Latency budget: the maximum acceptable pipeline overhead (p95), and the end-to-end tolerance vs. baseline. | **answered (provisional)** | 2026-10-14: Metis's own added overhead (cache lookup + routing), excluding model response time, is **≤ 100 ms at p95**. Revisit once real model latencies are measured. The end-to-end tolerance is still open.<br>Working interpretation, to confirm: the budget covers **all** pre-model work Metis adds: feature extraction, embedding for semantic lookup, cache lookup, routing, and context building. It excludes provider time, and escalation attempts are reported separately. Recorded in QA-LAT and [ADR-0006](../adr/0006-evaluation-metric-definitions.md). |
| Q-15 | Online phase only: must the future gateway's wire API be compatible with an existing client API (e.g. whatever production Metis clients call today)? | **open** (question for the Metis team) | 2026-10-14: unknown, because there is no production access. **Provisional default:** a separate external-API adapter layer, assuming an **OpenAI-compatible chat-completions style**. Internal contracts stay independent of it (FR-API-03, [ADR-0005](../adr/0005-current-phase-scope.md)). |
| Q-16 | May a cached answer be served across sessions or users at all, and if so, within what scope? This is a product/privacy decision. | **partly answered** | 2026-10-14:<ul><li>The default for anything serving users is reuse **within the same session only**.</li><li>Scope is configurable: `session` / `user` / `global`.</li><li>Offline experiments measure cross-session and cross-user reuse candidates **separately**, to quantify the opportunity.</li><li>**The final policy stays open** as a product/privacy decision.</li></ul>Note: the sample has no user ID, so cross-user candidates need a privacy-safe user ID in the full dataset. Recorded in [ADR-0007](../adr/0007-cache-sharing-scope.md) and FR-XCACHE-05. |
| Q-17 | Do you confirm deferring brief Action 3 (pricing engine and dashboard UI), keeping only its data enablers in scope? | **answered** | 2026-10-14: confirmed. The pricing engine and dashboard UI are deferred. The observability/event design must still capture everything a dashboard would need (tokens, cost, savings, latency, routing decisions), so one can be added without redesign ([ADR-0005](../adr/0005-current-phase-scope.md), FR-OBS-05). |

## Open questions — for the data owner
These were all unanswered as of 2026-10-14: this is sample data and the full dataset hasn't arrived. The working assumptions are A-06, A-14, A-15, A-16, all unverified.

| ID | Question | Status | Working assumption |
|---|---|---|---|
| Q-04 | What availability target was meant by "failover … to ensure 100…" (truncated in the brief)? | open | A-15: a high-availability target, exact SLA unknown. |
| Q-06 | Timezone and clock semantics of `created_at` and `timestamp`. | open | A-06: keep timestamps naive and infer nothing. |
| Q-09 | What do `input.items`, the `default`/`workflow` labels, and the 4,019-char RAG plateau mean? | open | A-14 (possibly truncated), A-16 (cautious proxy). |

## Missing information (TODOs)

| ID | Missing | Needed for | Resolution |
|---|---|---|---|
| TODO-01 | Billed / exact token counts per request (U-01) | Cost accounting validation | Full dataset or live calls |
| TODO-02 | Verified, dated price table per model (U-02) | Cost metric, baseline | Research in Stage 7, citing sources and check dates |
| TODO-03 | Latency, TTFT, retries, and failures (U-03) | Latency metric, failover design | Instrumented live calls / full dataset |
| TODO-04 | Actual prompt composition (U-04) | Context-reduction and cost estimates | Production payload logs / owner statement |
| TODO-05 | Quality labels (U-05) | Quality metric, routing labels | Judge or human labelling plan (Stage 8) |
| TODO-06 | A signal for "unsatisfactory response" (U-07) | Cascade design | Stage 3 design + experiments |
| TODO-07 | Cache-safety factors such as time sensitivity and personalisation (U-08) | Cache validity rules | Full dataset + design |
| TODO-08 | A standalone (non-conda) Python 3.13 on the dev machine. Only Anaconda 3.13, python.org 3.14, and system 3.9 were found on 2026-10-14. | First venv (Stage 5/6) | Install 3.13 from python.org, Homebrew, or pyenv |
| TODO-09 | Whether pip can install from a PEP 751 `pylock.toml` (`pip lock` is experimental in pip 25.1) | Locking choice (ADR-0001) | Re-verify against pip release notes before Stage 6 |
