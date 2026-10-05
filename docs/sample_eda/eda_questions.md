# EDA questions

The notebook investigates each question with descriptive counts, distributions, and plots. “Sample can answer” means it can describe this export—not establish production behavior or causal impact.

| Area | Question and why it matters | Investigation | Can this sample answer? |
|---|---|---|---|
| Dataset structure | What records and fields exist, and at what grain? | Inspect JSON layers, field presence/types, role-specific optionality, dictionary. | Yes, for the parsed export. |
| Integrity | Do IDs, declared counters, roles, timestamps, and chronology agree? | Deterministic checks and session/message timestamp audit. | Mostly: basic checks pass; creation/message-time mismatch remains. |
| Request behavior | How large and variable are user prompts? | Character/word/line/sentence/script/format metrics, percentiles, histogram. | Yes, descriptively; character/4 token proxy is not billed tokens. |
| Conversation behavior | How deep are sessions, and how much prior-context dependence is plausible? | Turns, depth, text volume, duration, unanswered turns, model/provider switching. | Yes, descriptively; duration is not active time or latency. |
| Language | How much traffic appears Persian, English, mixed, or unknown? | Explainable Unicode-script heuristic and length/model segment summaries. | Approximately; no language labels are provided. |
| Request type/complexity | Is there heterogeneity that could motivate routing research? | Reproducible keyword flags and length/sentence/code/instruction-marker score. | Suggestively only; labels are not ground truth or difficulty. |
| Model/provider use | Which model/provider labels occur, and do assignments vary with observable request properties? | Counts, combinations, prompt buckets, session language, RAG, attachments, input proxy, code and depth. | Yes for logged association; not for comparative efficiency. |
| Semantic caching | Are exact or similar user prompts repeated, within/across sessions? | Exact, whitespace and conservative NFKC/casefold normalization; character TF-IDF cosine. | Yes for lexical repetition in the export; not safe eligibility or production hit rate. |
| Context/retrieval | How frequent and large is logged retrieval context, and how does it vary? | Context/query size proxies by model/provider, query script, prior request complexity, session depth. | Yes for logged `rag` records; completeness and relevance are unknown. |
| Cost | Could caching, routing, or context reduction save money? | Identify candidate workloads and map fields needed for counterfactual cost. | No: no exact billing, prices, or matched outcomes. |
| Quality | Could optimization preserve acceptable responses? | Identify required evaluation fields/experiments. | No: no quality labels or paired model evaluations. |
| Latency | Could routing improve response time? | Report observed timestamp gaps only and identify lifecycle instrumentation needed. | No: timestamps do not establish API latency. |
| User experience | Does Metis reduce manual model choice or improve satisfaction? | Inspect for preference, user choice, abandonment, satisfaction fields. | No such fields were found. |
| Business value | Is there enough signal to justify later experiments? | Separate direct observations, suggestive hypotheses, and unknowns. | Yes for prioritization, not for savings claims. |
| Full dataset | Which extra fields enable evidence-based optimization? | Specify request-linked tokens/cost/latency/quality/cache/routing events. | This sample can identify requirements, not supply them. |

The category field is used only as an opaque stratum. `input` is an uncertain configuration proxy; `instructions` is separate unverified metadata and excluded from request/context totals.
