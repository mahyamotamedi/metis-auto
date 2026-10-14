# Metis-Auto — Context and Requirements Baseline (Stage 0)

Status: **decided** as a Stage 0 baseline; individual items carry their own status. Last updated 2026-10-14.
Related: [assumptions & open questions](assumptions_and_questions.md) · [progress](progress.md) · sample EDA ([results](../sample_eda/eda_results.md), [methodology](../sample_eda/eda_methodology.md), [data overview](../sample_eda/data_overview.md), [questions](../sample_eda/eda_questions.md)).

This is the one document to read to understand the problem, the real shape and limits of the data, and what is unknown. It summarises; the EDA documents hold the evidence.

---

## 1. Problem in one paragraph

Metis-Auto is a middleware "virtual meta-model" between users/applications and several LLM providers. Its goal is to **lower the cost of answering requests without materially lowering quality or raising latency**. The candidate levers are exact caching, semantic caching, context reduction, routing to cheaper models, cascade escalation, provider failover, and observability of tokens/cost/latency/quality/savings. None of these levers is assumed to work; each must be shown to work with evidence. This repository is developed **separately from production Metis**. There is no access to production servers, databases, deployment, or code. The only data so far is a 100-session sample, and a larger anonymised dataset will arrive later.

## 2. The project brief, summarised

Source: `project-draft.pdf` (Metis-OS Team, dated 2026-09-29). It is **not in the repository**; the copy found is one directory above the repo root (see [Q-01](assumptions_and_questions.md#open-questions)).

**Motivations stated:** remove "AI decision fatigue" (users shouldn't pick models by hand), hide API fragmentation behind one highly available gateway (routing, semantic cache, failover), and control unit economics and SLAs with real-time observability of tokens, savings, and routing decisions.

**Three actions:**

| Action | Brief's content | Notes |
|---|---|---|
| 1. Smart classifier & dynamic routing | Feature extraction: language, semantic intent, code presence, multimodal attachments (image/audio). Simple/conversational/structured inputs go to cheap fast models; complex, multi-step, or technical inputs go to advanced models. The classifier must be cheap in both latency and cost. | Model names in the brief (Gemini 1.5 Flash, GPT-4o-mini, Claude 3.5 Sonnet, o3-mini) are examples, not a catalogue (C-11). |
| 2. Cascade & semantic caching | A vector-based semantic cache serves repeated or "conceptually identical" queries. If a cheap model's answer is unsatisfactory, escalate to a stronger one. If a provider is down, fail over to a parallel provider "to ensure 100…" (the text is truncated). | "Unsatisfactory" is undefined (U-07). |
| 3. *(Optional)* Financial modelling & dashboard | A pricing engine (subscription vs. dynamic) showing Metis-Auto is cheaper than premium-direct, and a user-facing panel of tokens saved, routing savings, and latency. | Depends on verified prices (U-02). |

**Evaluation (§4.1):**
- **Quality** is the mean semantic similarity of routed answers vs. the actual logged bot answers, plus LLM-as-a-judge where feasible.
- **Semantic-cache hit rate** is the share of queries served from cache.
- **Cost** is the simulated cost per query vs. a single premium-model baseline.
- **Latency** is end-to-end response time vs. that baseline.

## 3. What actually exists in the repository

| Item | Real location | Notes |
|---|---|---|
| Sample data (read-only) | `data/sample_data/raw/data.json` | sha256 `e0f56a2f2340b2ac70bf273e05ee2e9b56126cd3874c0c58659f46b4983549e1` (2026-10-14). The brief calls it `sample-data/data.json`. |
| EDA notebook | `experiments/sample_eda/eda.ipynb` | 64 cells, kernel Python 3.13.5. Imports pandas, numpy, scipy, matplotlib, and scikit-learn (inside the helpers). |
| EDA helper module | `experiments/sample_eda/eda_helpers.py` | ~1,170 lines. Loading/flattening, text features, `approximate_tokens` (= ceil(chars/4)), `detect_language`, normalisation (`normalize_exact`, `normalize_safe`), `pair_bot_responses_with_preceding_users`, duplicate/near-duplicate detection, response-level analysis. These are **experiment code**, not a library. Reuse candidates go through the promotion process defined in Stage 2. |
| EDA docs | `docs/sample_eda/*.md` | Results, methodology, questions, data overview. |
| EDA outputs | `reports/sample_eda/figures/` (12 PNG), `reports/sample_eda/tables/` (~80 CSV) | Feature-only; they use hashed or opaque IDs. |
| Tests | `tests/test_sample_eda_helpers.py` | 3 unittest-style tests. Pass under pytest 8.3.4 (3/3, 2026-10-14). |
| Package | `src/metis_auto/` | Empty (`.gitkeep`). |
| Agent conventions | `AGENTS.md`, `docs/agents/` | `.scratch/` issue tracker, triage labels, `GLOSSARY.md` + `docs/adr/` (none exist yet). |
| Tooling | `.vscode/` (black format-on-save), `.idea/` (`src/` as source root) | No `pyproject.toml`, requirements, lockfile, linter config, CI, or Docker. |

Git notes:
- On 2026-10-14, `sys-des` was rebased onto `main` (= `origin/main` `5a9421a`). The branch had been cut from a stale local `main` that lacked the EDA.
- Teammate EDA branches exist (`origin/eda-saba`, `origin/shakib`, `origin/eda_parham`) but are **not** the baseline. `eda_parham` contains a price file that is explicitly hypothetical, with no source. It must not be reused as price data.
- `.gitignore` lists `.idea/`, `.vscode/`, `AGENTS.md`, and `docs/agents/`, yet those files are tracked (Q-03).

## 4. The data's real shape (verified against the raw file, 2026-10-14)

- **Structure:** a list of 4 category objects × 25 sessions = 100 sessions, 907 messages (465 `user`, 442 `bot`). Roles are `user`/`bot`, not `assistant`. Category names are **opaque strata** and are never interpreted.
- **Session fields:** `session_id`, `created_at`, `session_len`, `user_turns`, `bot_turns`, `messages`. All declared counters match the arrays. Sessions have 3–44 messages (median 6), and every session has more than one user turn.
- **User message fields:** `role`, `content`, `timestamp`, optional `attachments` (14 messages, 15 items, all `IMAGE`).
- **Bot message fields:** `role`, `content`, `timestamp`, `model`, `provider`, `instructions` (each null on 27 bots; 7 more instructions are blank), optional `rag` {`query`, `context`: list of strings} (71 bots, 24 sessions), optional `input` {`items`} (29 bots, 8 sessions).
- **Labels:** 18 model labels and 7 provider labels, including non-model labels `default`/`workflow` (36 records). No model switching within a session.
- **Time:** timestamps are naive (no timezone). `created_at` runs 2026-01-14 to 09-09; message timestamps run 03-02 to 09-09. One session's creation month differs from its first message; five have gaps over an hour, one with the first message *before* `created_at`.
- **Pairing is heuristic:** there is no request ID. The "latest preceding user message in array order" rule links 436 bots to 434 user events. 6 bots have no preceding user, 2 user events map to multiple bots, and there are 16 consecutive-user and 3 consecutive-bot transitions.

## 5. Established facts, hypotheses, unknowns

### 5.1 Established facts (about this sample only)
- **F-1** User prompts are short and right-skewed: median 29 chars, p90 182, p99 2,655, max 4,666.
- **F-2** About 91% of user messages are Persian-script by a Unicode heuristic, plus English (6%), mixed (3%), and other.
- **F-3** Logged `instructions` are large and reused. 408 are non-empty, with median 3,578 chars, p90 8,258, and max 271,155. They form 78 normalised groups, mostly reused within a category.
- **F-4** In a *hypothetical* "full history + request + logged instructions + logged RAG" scenario, character shares are about 82.6% instructions, 13.8% prior history, 2.5% RAG, and 1.2% current request.
- **F-5** Logged RAG context: median 1,476 chars, max 4,019, with 10 contexts at exactly 4,019.
- **F-6** 21 exact or normalised repeat groups cover 76 user messages (16.3%), and 11 of those groups cross sessions. There are 57 non-identical near-duplicate pairs at char-n-gram TF-IDF cosine ≥ 0.70.
- **F-7** Under a progressive cache-candidate screen:
  - 367 same-request pairs
  - 9 with the same instruction
  - 6 with no RAG
  - **0** with no prior history
  - **0** with similar responses

  Repeated requests often differ in instructions, model, RAG state, or history.
- **F-8** Bot responses: median 210 chars, p90 1,025. 13 repeat groups cover 7.5% of responses.
- **F-9** The observed user→bot timestamp gap has a median of 2 s and p90 of 7 s. This is **not** API latency.

### 5.2 Hypotheses worth testing (none established)
- **H-1** Prefix and instruction handling (provider-side prompt caching, instruction compaction) is the largest context-cost lever. This holds *if* logged instructions are actually sent to providers (F-4, U-04).
- **H-2** History trimming or summarisation can cut input size on later turns without quality loss (F-4, multi-turn sessions).
- **H-3** An exact cache keyed on request + instructions + history + RAG + model gives a small but safe hit share. A request-only key gives a larger but unsafe one (F-6, F-7).
- **H-4** A multilingual or Persian-capable semantic cache raises the hit share over lexical matching, with measurable false-hit risk.
- **H-5** Cheap observable features (length, language, code, attachments, depth, RAG presence) carry enough signal to route some traffic to cheaper models without quality loss.
- **H-6** A cascade (cheap first, escalate on a weak signal) beats single-model routing on cost at equal quality. This depends on finding a usable "unsatisfactory" signal.
- **H-7** Character/4 badly misestimates tokens for Persian text, so tokenizer-specific counting changes cost conclusions.

### 5.3 Unknowns (the sample cannot answer)
Each unknown has an entry in the [register](assumptions_and_questions.md#missing-information-todos).
- **U-01** Billed or actual token counts per request (input, output, cached).
- **U-02** Verified prices per model, and the mapping from logged labels to billable models and versions.
- **U-03** API latency, time-to-first-token, retries, failures, and fallbacks.
- **U-04** Actual provider-prompt composition: whether `instructions`, history, and RAG were sent, trimmed, or summarised.
- **U-05** Quality labels, user satisfaction, and whether users chose models themselves.
- **U-06** Why existing models were assigned (routing reasons).
- **U-07** What signal "unsatisfactory response" can be detected from.
- **U-08** Cache safety factors: time sensitivity, personalisation, hidden context.
- **U-09** The semantics of `input.items`, `default`/`workflow`, the 4,019-char plateau, and timezones.
- **U-10** Whether the sample represents the full dataset.

## 6. Conflicts between the brief and the data

| # | Brief says | Data shows | Consequence |
|---|---|---|---|
| C-01 | Traffic collected "between January and September 2026" | Only `created_at` spans Jan–Sep. Messages span Mar 2–Sep 9, and some created/first-message times disagree. | Time windows must name which timestamp they use. Timezone is unknown. |
| C-02 | "18 distinct models across 7 providers" | 18 / 7 labels, including `default`/`workflow` (36 records), which aren't models. 27 bots have null labels. | Labels can't be priced as-is. A normalised model catalogue is needed. |
| C-03 | 29 messages include "structured input widgets" | Only a bot-side `input.items` config on 29 bot records (8 sessions). User widget use is not observable. | Treat it as an uncertain proxy feature, not a user-action signal. |
| C-04 | Bots include retrieved context "when retrieval was used" | A missing `rag` doesn't prove there was no retrieval. Context is capped or plateaus at exactly 4,019 chars. | RAG absence isn't a cache-key-safe fact. Truncation is unverified. |
| C-05 | (no mention of `instructions`) | Instructions exist on 415 bots and dominate the logged size (F-3, F-4). | The brief's cost model ignores what is probably the largest input component. |
| C-06 | Attachments are "image/audio" | Only `IMAGE` is observed (15 items). | Audio support is a future need, not current. |
| C-07 | Quality = similarity to "actual bot answers" | The logged answers come from 18 heterogeneous labels and aren't gold. Pairing is heuristic. | Similarity-to-logged measures *agreement*, not correctness (see §7). |
| C-08 | Latency = end-to-end response time vs. baseline | No latency fields. Timestamp gaps aren't API latency. | Latency must come from live or replayed calls, or be marked unmeasured. |
| C-09 | Hit rate = share of queries served from cache | 0 pairs pass the strictest safe-candidate screen. | Hit rate must always be paired with a hit-correctness measure. |
| C-10 | Failover "to ensure 100…" | Truncated text. The data has no failure events. | The availability target is undefined (Q-04). |
| C-11 | Example models (Gemini 1.5 Flash, GPT-4o-mini, Claude 3.5 Sonnet, o3-mini) | The logs use other labels (e.g. `deepseek-v4-flash`). | The catalogue is configuration chosen later from verified current options. |
| C-12 | "All PII removed" | Content, instructions, RAG, and attachments may still be sensitive. | Apply the stricter rule: no raw content anywhere outside in-memory analysis. |

## 7. Weaknesses of the evaluation targets (to design around)

- **Quality vs. logged answers.** Logged answers are one sample from one (unknown-quality) model. High similarity can mean "copied the same mistakes", and low similarity can be a better answer. Report it as *agreement with as-logged*, and add LLM-as-a-judge or human labels on a stratified subset. Persian-capable embedding models are needed for similarity to mean anything.
- **Cache hit rate.** It is meaningless without hit correctness: whether the served answer was valid for this request's context. Report it as hit rate × false-hit rate, broken down by key-composition variant.
- **Simulated cost.** This depends on (a) verified, dated prices; (b) the right tokenizer per model, since Persian makes chars/4 unreliable; (c) the true prompt composition (U-04); and (d) cached-input discounts. Every cost figure must carry its token-count method and price source.
- **Latency.** It can't be measured offline from this data. Router or classifier overhead must be measured separately and added.
- **Single premium baseline.** "Premium" must be a concrete, priced model choice, and it is open (Q-05). An **as-logged baseline** is also needed, and every experiment reports against both.

## 8. The counterfactual problem (introduced; designed in Stages 3 and 8)

The dataset only contains the answer of the model that was actually used. Evaluating "what if we had routed or cached differently" needs one of the following:
1. **New model calls** over replayed requests. These are real, but cost money, need provider keys, and send data to providers (a privacy review is needed).
2. **Recorded or mocked responses.** These are cheap and reproducible, but only as good as what was recorded.
3. **Proxy metrics** such as size, similarity, and heuristics. These are free, but weak.

Stage 3/8 documents will state which one each experiment uses.

## 9. Pointers

- Durable working rules: [`CLAUDE.md`](../../CLAUDE.md).
- Fields the full dataset must provide: the "Requirements for the Full Dataset" section of [eda_results.md](../sample_eda/eda_results.md). The system's own event model must produce these fields (Stages 3–4).
