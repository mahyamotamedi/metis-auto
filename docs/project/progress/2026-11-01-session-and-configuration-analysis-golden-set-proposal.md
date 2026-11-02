## Session and configuration analysis, golden-set proposal (2026-11-01)

Run on `full-eda` under the owner's task. Status: **awaiting review**; nothing committed. Report: [session_config_report.md](../../full_eda/session_config_report.md). Code: `scripts/full_eda_sessions.py`, `analysis/session_config.py`, `analysis/prompt_labels.py`, `evaluation/golden/`; tests in `tests/unit/analysis/test_session_analysis.py`. Run locally with no paid calls and no raw prompts sent anywhere; only aggregate frequent single words (at least five accounts) were viewed to steer the rules.

Measured: 71.6% of sessions inferred chatbot, 0.4% inferred direct, 27.9% unclassifiable (mostly `workflow`); top five owner accounts hold 96.75% of user turns; identical instruction and RAG is almost absent. Not done: human label review (44.4% of requests are `unknown`), golden set not approved, no reference answers.
