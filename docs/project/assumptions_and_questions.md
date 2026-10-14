# Assumptions & Open-Questions Register

Living register. Last updated 2026-10-14 (Stage 0). Context: [context.md](context.md).

Tags:
- **Kind:** `current` (a current requirement), `future` (a likely future need), `spec` (speculative).
- **Status:** `decided`, `provisional`, `open`.

When an item is resolved, keep it in place, mark it `decided`, and say how it was resolved.

## Assumptions

| ID | Assumption | Kind | Status | Basis / what would overturn it |
|---|---|---|---|---|
| A-01 | The sample's schema (roles, fields, nesting) is representative of the full dataset's schema. | current | provisional | The full dataset's inspection (Stage 9 checklist). |
| A-02 | Category labels are opaque strata. We never infer their meaning or tune to one category. | current | decided | The brief says categories are intentionally unnamed. |
| A-03 | Logged `instructions` *may* be the system prompt sent to providers, but this is unproven. Designs must work either way. | current | open | Production prompt-construction code or payload logs (U-04). |
| A-04 | Bot↔user pairing in the sample is the EDA's "latest preceding user by array order" heuristic. It is never treated as a clean 1:1 log. | current | decided | A request ID in the full dataset would replace it. |
| A-05 | The online system will mint its own correlation IDs (request, session, attempt). The sample's absence of IDs is not carried into the online design. | future | provisional | Confirmed in Stage 4 contracts. |
| A-06 | Timestamps are naive. Analyses assume a single consistent but unknown clock and never mix `created_at` with message timestamps without saying so. | current | provisional | Schema owner states the timezone (Q-06). |
| A-07 | Model and provider labels are not billing entities. Cost needs a curated mapping from label to priced model. | current | decided | C-02. |
| A-08 | Persian is the dominant language. Tokenization, embeddings, and similarity must be Persian-aware. | current | decided | F-2. |
| A-09 | Content is sensitive despite the brief's PII claim. No raw text goes into docs, logs, fixtures, commits, or exported tables. | current | decided | Master prompt §2 Privacy; C-12. |
| A-10 | Python is the implementation language, matching the existing EDA. | current | provisional | Tooling decision (Q-07). |
| A-11 | Offline replay over the dataset is the first consumer of the architecture. An online gateway comes later. | current | decided | Master prompt §4. |
| A-12 | Audio attachments may appear later (the brief mentions them). They aren't in the sample. | future | open | Full dataset. |
| A-13 | Live provider calls (for counterfactual answers or judges) will be possible later with project-owned keys and acceptable data-sharing terms. | spec | open | Q-08. |

## Open questions

| ID | Question | Owner | Blocks | What resolves it |
|---|---|---|---|---|
| Q-01 | Should the project brief be added to the repo (e.g. `docs/brief/`)? It currently lives outside the repo at `../project-draft.pdf`. | user | Traceability (Stage 1) | Your decision. |
| Q-02 | Should `metis_claude_code_master_prompt_1.md` be committed (and renamed without `_1`), or kept local? | user | — | Your decision. |
| Q-03 | `.gitignore` lists `.idea/`, `.vscode/`, `AGENTS.md`, and `docs/agents/`, but they are tracked. Should these be tracked (then remove the ignore lines) or untracked? New files under `docs/agents/` are currently silently ignored. | user / team | Agent conventions | Your decision. |
| Q-04 | What availability target was meant by "failover … to ensure 100…" (truncated in the brief)? | brief owner | Stage 1 reliability requirement | The full brief text. |
| Q-05 | Which concrete model is the "single premium-model baseline"? | user / team | Stage 1, 7, 8 | Your choice from verified current options. |
| Q-06 | Timezone and clock semantics of `created_at` and `timestamp`. | data owner | Time-based analyses, cache TTLs | Schema owner. |
| Q-07 | Dependency manager: uv, pip + venv, or conda? Also, should ruff be adopted for linting? | user | Stage 4/5 (first code that needs dependencies) | Your decision (see [progress](progress.md) tooling proposal). |
| Q-08 | Are live provider calls allowed for experiments (budget, keys, data-sharing constraints)? | user | Counterfactual method choice (Stage 3/8) | Your decision. |
| Q-09 | What do `input.items`, `default`/`workflow` labels, and the 4,019-char RAG plateau mean? | data owner | Feature design, C-03/C-04 | Schema owner. |
| Q-10 | Should teammate EDA branches (`eda-saba`, `shakib`, `eda_parham`) feed this work, or is `origin/main`'s EDA the sole baseline? | user / team | — | Your decision. Currently `origin/main` is the only baseline. |
| Q-11 | When is the full dataset expected, and what will its approximate size be? | user | Stage 9 planning | Your answer. |

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
