# Annotation rubric v1 (`rubric-v1`)

For human reviewers of golden-v1 ([ADR-0028](../adr/0028-evaluation-dataset-golden-v1.md)). Labels describe the request. They say nothing about which model is best. Allowed values live in `evaluation/golden/annotations.py` and `eval.rubric_value`; the import refuses anything else. Every example is **[SYNTHETIC]**, written for this rubric.

**Do not assume** that long means complex, that technical means a premium model is needed, that RAG means complex, or that the historical model or answer was right. Label from what the request asks and what it needs. Never copy message text into a label or a note.

## primary_intent

Exactly one. Choose the main task. Where something is really a context or task attribute, keep it a secondary label.

| Value | Meaning | [SYNTHETIC] example |
|---|---|---|
| `factual_qa` | Asks for knowledge or an explanation | What causes tides? |
| `bot_service_support` | A task bound to the bot's service or the user's account | Why has my order not arrived? |
| `conversational_smalltalk` | Greeting, thanks, small talk | Hi, how are you? |
| `writing_creative` | Write, rewrite or create text | Write a short poem about rain. |
| `translation` | Translate or explain language | Translate this sentence into English. |
| `coding` | Write, explain or debug code | Why does this loop never end? |
| `advice_recommendation` | Advice, recommendation or comparison | Which of these two laptops suits a student? |
| `math_reasoning` | Mathematics, multi-step reasoning, analysis | Solve this equation step by step. |
| `summarization_extraction_structured` | Summarise, extract, classify, or produce structured output | List the dates in this paragraph. |
| `media_generation` | Generate an image, audio or video | Draw a red bicycle. |
| `ambiguous_context_dependent` | Cannot be understood without earlier turns | And the second one? |
| `other_unclassified` | None of these (label audit) | A lone punctuation mark. |

## complexity

Human only. Length alone never sets it. Context dependency is recorded separately, not here.

| Value | Dependent steps | Knowledge | Constraints and context |
|---|---|---|---|
| `simple` | One operation; at most one dependent step (lookup, greeting, simple transformation) | None specialised | Few constraints |
| `average` | Two to four dependent steps or limited synthesis | Moderate domain knowledge | Several constraints; integrates a short provided context |
| `complex` | Five or more dependent steps | Specialised professional, scientific or engineering knowledge | Multi-constraint generation with trade-offs; substantial context integration; multi-part coding or debugging |

Give a `rationale_code`: `one_operation`, `two_to_four_steps`, `five_or_more_steps`, `specialised_knowledge`, `multi_constraint`, `context_integration`, `multi_part_code`, `other`.

## Secondary labels

Each takes `yes`, `no` or `unsure`. Overlaps are expected.

| Dimension | `yes` means | [SYNTHETIC] example of yes |
|---|---|---|
| `time_sensitive` | The right answer changes with time | What is the gold price today? |
| `current_info_dependent` | Needs information newer than a model could know | Who won last night's match? |
| `domain_specialized` | Needs a specialised domain; set `domain_subtype` to science, engineering, medical, legal, finance or academic (else `none`) | What dose is safe for a child? |
| `strict_format` | Demands an exact shape or length | Answer in exactly three bullets. |
| `structured_output` | Demands machine-readable output | Return this as JSON. |
| `attachment_dependent` | Cannot be answered without an attachment. Note presence and type only; do not analyse the content | What is in this picture? |
| `instruction_dependent` | The answer depends on the bot's instructions | What are your opening hours? |
| `rag_dependent` | The answer depends on retrieved documents | What does our refund policy say? |
| `history_recent` | Depends on the last few turns | Make it shorter. |
| `history_distant` | Depends on something much earlier in the session | Go back to the first plan. |
| `multi_context` | Depends on more than one of instruction, RAG and history | Apply the policy to the case above. |
| `advanced_reasoning_required` | Needs careful multi-step reasoning, whatever its length | Prove this inequality. |
| `cache_suitable` | The same answer would serve a repeat of this request | What is the capital of France? |
| `cache_invalidation_risk` | A stored answer could go stale or be wrong for another person | What is my balance? |

## answerable_without_clarification

`yes`, `no` or `unsure`, for ambiguous requests: could a capable reader answer as written, given its context?

## Context dependency

Not a separate column: it is the combination of `history_recent`, `history_distant`, `instruction_dependent`, `rag_dependent` and `multi_context`. None of them means self-contained.

## Process

1. Open the local sheet in `runs/evaluation/golden_v1/review_local/`. It holds real messages, so it stays on your computer: do not email, upload, or paste it into any tool.
2. Records with `double_annotate = True` go to two reviewers working independently.
3. Fill the label columns and leave unknowns blank. Blank means no label.
4. `python scripts/build_eval_dataset.py import-annotations <sheet.csv> --annotator <your pseudonym>`.
5. `python scripts/build_eval_dataset.py export-labels`, then commit the text-free `reviewed_labels.jsonl`.
