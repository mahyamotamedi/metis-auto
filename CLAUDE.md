# CLAUDE.md

Durable working rules for agent sessions on Metis-Auto. Keep this file short and link to the docs rather than copying them. Also follow [`AGENTS.md`](AGENTS.md) (issue tracker in `.scratch/`, triage labels, `GLOSSARY.md` / `docs/adr/` conventions).

## Where things live
- Project state: [`docs/project/progress.md`](docs/project/progress.md). Read it first.
- Context & unknowns: [`docs/project/context.md`](docs/project/context.md).
- Assumptions & open questions: [`docs/project/assumptions_and_questions.md`](docs/project/assumptions_and_questions.md).
- Decision records: `docs/adr/` (`NNNN-slug.md`: context, alternatives, decision, consequences).
- Sample EDA: `experiments/sample_eda/`, `docs/sample_eda/`, `reports/sample_eda/`.

## Data and privacy
- `data/sample_data/raw/` is **read-only**. Never modify it; write derived data elsewhere.
- Never put raw message content, instructions, RAG context, or attachments into docs, commits, logs, test fixtures, or exported tables. Use hashed or opaque IDs and derived features. Synthetic fixtures must be clearly labelled synthetic.
- Category names are opaque strata. Do not interpret them or tune to one category.

## How to work
- Work stage by stage. At the end of each stage, give the 6-part report (changes, decisions, assumptions, questions, next stage, exit criteria). Update `progress.md` and then **stop** for review.
- Inspect before deciding. Don't delete, move, or restructure existing work (especially EDA, data, and reports) without approval.
- Label assumptions as current, future, or speculative, and design elements as decided, provisional, or open.
- Never fabricate prices, model capabilities, tokenizer behaviour, API signatures, or data facts. Cite the source and the check date, and mark the fact for re-verification.
- Keep the design simple and replaceable. Prices, catalogues, thresholds, and strategies are configuration, not code.
- Tests run offline with no API keys. Network tests are opt-in.
- Python 3.13, black formatting, pytest (tooling still provisional; see the progress doc).
