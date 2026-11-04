# EXP-COST-001: does hidden "thinking" inflate `gemini-2.5-flash` output? (sprint task F-1)

- **Question:** does `gemini-2.5-flash` (12.5% of requests, 65% of recorded cost) bill much more output than its visible answers need? Trigger for the Gemini stretch item (adapter, thinking A/B, replacement). Traces: FR-ACCT-01, H-7, QA-REPRO; ADR-0042, ADR-0043.
- **Evidence class:** *hypothetical reconstruction*. Billed output tokens are observed; the visible-answer tokens are answer characters divided by an **assumed** slope (the EDA's turn-0 slope, 3.44 characters per token, fitted on input; tokenizers differ). The ratio compares models on the same slope. It is a signal, not a measure.
- **Method:** `check.gemini_thinking(req, model_label, chars_per_token)`: ratio = billed output tokens / (answer characters / slope), median and p90, for the model and for the other high-volume models. Rows with unknown billed output or unknown or zero answer length are left out and counted. "No cached tokens logged" is reported as a **logging gap**, never "no caching". Free and offline; run by `scripts/gemini_thinking_check.py`; output `reports/cost/exp-cost-001/summary.json`. Tests: `tests/unit/experiments/test_gemini_thinking_check.py`.
- **Result (2026-11-03, full data):**

| model | rows | median ratio | p90 ratio |
|---|---|---|---|
| **gemini-2.5-flash** | 43,646 | **1.15** | **53.49** |
| gemini-2.5-flash-lite | 90,921 | 1.15 | n/a here (summary file) |
| gpt-4o-mini | 65,289 | 1.17 | |
| deepseek-v4-flash | 26,965 | 1.58 | |
| gpt-5.4-nano / gpt-4.1-mini | 2,927 / 2,733 | 1.17 / 1.23 | |

  The others' median of medians is 1.17 and their median p90 is 1.44.
- **Reading:** at the median `gemini-2.5-flash` looks like its peers (the median verdict is *no*). Its **tail is heavy**: p90 is 53.5 against about 1.4 (the tail verdict is *yes*, placeholder factor 1.5). So hidden thinking is **not** typical for this model, but a share of its requests bill far more output than the visible answer needs. That is the trigger condition for the Gemini stretch item, to be confirmed with a live thinking A/B (not run: Rule zero). Cached-input tokens are logged for this model (there is no logging gap here).
- **Limits:** the slope is an assumption; Persian and English answers differ in characters per token; a long answer can legitimately bill more than the average ratio.
