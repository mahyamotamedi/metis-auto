# System-One decision router, phase R0: verification findings

Phase R0 of the decision-router work (owner's master prompt of 2026-11-02, "Metis-Auto System-One Decision Router"; ADR-0047 to follow in R1). **No product code was written.** Every fact below names its source and check date; anything not confirmed by a primary source is marked **unverified**. Traces: FR-FEAT-02, FR-ROUTE-03/04, FR-ACCT-03, FR-DATA-02/06, QA-LAT, QA-PRIV, QA-TEST, H-5.

Checked 2026-11-02 (Asia/Tehran), by the agent, on the owner's Windows machine (`desktop-88s7q9u`, win32 x64) through the desktop bridge, plus a Linux 3.13 workspace for the test run.

## 1. Test baseline

| Where | Python | Locks installed | Result |
|---|---|---|---|
| Linux workspace (copy of the working tree, no `data/`) | 3.13.18 | `requirements-dev.lock` only | **collection stops**: `wiring/golden_answers.py` imports SQLAlchemy at module level, so two test modules cannot be collected without the `db` extra |
| Linux workspace | 3.13.18 | `requirements-db.lock` | **1,136 passed, 2 failed, 23 skipped**; `ruff check` and `ruff format --check` clean. The 2 failures are the known missing-tokenizer-assets cases (`test_live_probe.py::test_probe_plan_is_under_the_owners_limit`, `test_live_wiring.py::test_demo_live_check_plan_and_mocked_run`) |
| Owner's Windows machine | — | — | **not run**: the bridge shell is a Linux VM (no Windows Python, no network) and this working copy has no `.venv`. The last recorded Windows baseline is E1's "33 failed, 3 collection errors" (progress.md, 2026-10-30), which predates the ledger's Windows lock (below). Owner to re-run. |

## 2. Spend ledger on Windows

- `adapters/system/ledger.py` already has a Windows branch since commit `1bd1ac4` (2026-10-31): `msvcrt.locking` on one byte at offset 2^40, exclusive for readers and writers; `fcntl.flock` elsewhere. It is therefore **not POSIX-only** any more.
- **No test exercises the Windows branch** (`tests/unit/adapters/test_adapters_file_ledger.py` runs on whichever platform runs it). Proving it needs that test file run on Windows, ideally plus a two-process contention test.
- `data/spend/` does **not exist** on this working copy: the lifetime total here starts at zero, while the earlier live calls (Stage 7.5, Demo A/B checks) were charged to the ledger on the previous machine. Live calls stay blocked until the owner decides how to carry that total over.

## 3. Dataset (metadata only; no content read)

Source: `C:\Users\Mandish\Desktop\metis-data` (the target of the `data\full_data\raw` junction; the junction itself is not readable from the bridge VM, the target folder is).

- **Revision:** all 35 Hugging Face download metadata files name `30f578f283b903cdbd06cd1b5f7f962f76452ded`, as pinned in `config/evaluation/source_v1.toml`.
- **sha256:** all 31 Parquet files match `source_v1.toml`; none missing, none unlisted.
- **Row counts and column sets:** all 10 tables match `expected_rows` and the pinned column names (read from Parquet footers: schema and `num_rows` only; row-group statistics were skipped because they can hold min/max text).
- **Every file has exactly one row group.** Consequence for the slice reader (§4.4 of the prompt): row-group predicate pushdown cannot skip I/O; an `isin` filter reduces memory, not bytes read. Pass 1 must still decode `session_id`/`type`/`timestamp`/`finish_reason` (and `content` for `utf8_length`) shard by shard; peak memory stays bounded by one shard (~50 MB on disk) at a time.
- `README.md` and `LICENSE.txt` read: educational use by Rahnama College only; no redistribution, publication or sharing with third parties without Metis's written permission; licence effective 2026-10-28. This supports the prompt's rule that dataset text never leaves the machine without per-run approval, and **raises a licence question for Mode 1** (sending dataset text to TypeSafe through Metis): see Q-R0-2.
- PostgreSQL: not checked. The bridge VM cannot reach services on the Windows host, and this copy has no `config/local.toml` (so `[database] enabled` is at its default). Owner to say whether `eval.request` is populated on this machine.
- Golden exclusion lists exist as ID-only exports: `reports/evaluation/golden_v1/golden_v1_shareable.jsonl` (300 `gv1-` IDs) and `golden_v2/golden_v2_shareable.jsonl` (300 `gv2-` IDs).

## 4. Hosted backend (Mode 1)

| Item | Finding | Source, date | Status |
|---|---|---|---|
| Metis TypeSafe page | Not readable automatically (`robots_disallowed`); the owner saved its text on 2026-11-02 as [`metis_typesafe_wrapper_page.md`](metis_typesafe_wrapper_page.md) (Persian; summarised here, not translated). | https://docs.metisai.ir/api/wrapper/typesafe, saved 2026-11-02 | read 2026-11-02 |
| Metis endpoint | `POST https://api.metisai.ir/typesafe/v1/systemone`. (R0's first guess, `…/api/v1/wrapper/typesafe/…`, was **wrong**; the Grok-style path does not apply.) | Metis page, 2026-11-02 | documentation claim; verify in the live check |
| Metis auth | The Metis API key in `Authorization: Bearer <key>`; no TypeSafe account needed | Metis page | documentation claim |
| Metis model IDs | Request `model` must be `jev-latest`, the only model offered through this endpoint. The response may name the exact version (example: `jev-1.13.0`); the page says the mismatch is expected | Metis page | documentation claim |
| Metis request body | `{state, model, questions}`; questions as in the wire-format row below (`choice` with an object `criteria`, `score` with an array `criteria`, `noul` with `instructions` only) | Metis page (curl example) | documentation claim |
| Metis response body | `{model, answers, usage{input_tokens, output_tokens}}`. In the example the `score` answer carries `score`, `confidence`, `legend` and **no `probabilities`**; `choice` carries `choice`, `confidence`, `probabilities` (the example's `confidence` 0.78 differs from its top probability 0.85, so confidence is not max-probability); `noul` carries `noul`. The example reports **non-zero `output_tokens`** (65) | Metis page | documentation claim. Consequence: `probabilities` must be optional on `score` answers in the wire model; `confidence` is read, never derived |
| Metis price | Not stated on the wrapper page. **From the Metis pricing page** (https://docs.metisai.ir/pricing, family `typesafe`, model `jev-latest`, checked by the owner 2026-11-02): input 0.0462 USD, output 0.0000 USD per 1M tokens | owner, 2026-11-02 | recorded as `config/reference/prices-metis-router-2026-11-02.toml` (`metis-jev-latest`); TypeSafe's direct price is never used |
| Metis rate limits | **Not stated** | Metis page | **unverified**: configurable; `429` maps to `rate_limited` |
| Metis error format | **Not stated** | Metis page | **unverified**: status-code mapping only, as `openai_compat.py` does |
| Wire format | `POST /v1/systemone`, body `{model, state, questions}`; each question `{type, instructions, criteria}`: `criteria` is an object for `choice`, an array of level labels for `score`, absent for `noul`. Response `{model, answers, usage{input_tokens, output_tokens}}`; answers: `choice` → `choice, probabilities, confidence`; `score` → `score, legend, probabilities, confidence`; `noul` → `noul` (P(yes)). Gateway headers include `x-typesafe-request-id`. | Zuplo AI Gateway Jev page; LiteLLM TypeSafe pass-through page; THX-01 `server.py`; Mizan card; all 2026-11-02 | verified across four independent descriptions (third-party, not TypeSafe's own docs) |
| Direct base URL | `https://api.typesafe.ai` (LiteLLM default `TYPESAFE_API_BASE`) | LiteLLM page, 2026-11-02 | secondary source |
| Model IDs | `jev-latest`, `jev-preview`, `jev-1.13.0`, `jev-1.14.0`; responses report the versioned ID (e.g. `jev-1.13.0`) | LiteLLM and Zuplo pages, 2026-11-02 | secondary source |
| Price | USD 0.042 per million input tokens; output tokens free | Zuplo page (gateway catalogue), 2026-11-02 | secondary source; the **Metis** price is unknown |
| Latency (180–560 ms, ~2 s end to end) | No source found | — | **measured 2026-11-03** (owner's live check): 3.5 s end to end for one call; `jev-latest` reported `jev-1.14.0`; 699 input / 171 output tokens, charged 0.0000322938 USD (input only). See [jev_model_note.md](jev_model_note.md) |
| Python SDK `typesafe-sdk` | PyPI page not reachable from here | — | **unverified**. Provisional decision: do not use it; `httpx` (0.28.1, already in every lock through `openai`) with a strict pydantic wire model, so no new dependency and the base path stays configuration |

## 5. Local backends (Mode 2)

**THX-01** (`thx01` 1.0.0 on PyPI, released 2026-10-08; sdist source read without running it; model card read 2026-11-02):
- Apache-2.0; 322M (307M mmBERT-base encoder + 15M head); question types `choice`, `noul`, `score` (+ `number`, `excerpt`, `cite`). Pure-Python wheel, `Requires-Python >=3.10`; depends on `torch>=2.0`, `transformers>=4.48`, `safetensors`, `huggingface_hub`, `numpy`. No `trust_remote_code`.
- ~~The repository root is the English checkpoint; the multilingual one is `subfolder="multilingual"`.~~ **Corrected 2026-11-02 (R5, the owner's `plan` returned 404 and his browser showed no such folder): the repository root *is* the multilingual model.** The R0 reading came from a stale example in the `thx01.load()` docstring (`# English (repo root)` / `subfolder="multilingual"`); `subfolder` is only a generic option for repositories that bundle several checkpoints. Evidence: the model card and `PYPI.md` describe one model, base `jhu-clsp/mmBERT-base` (multilingual), post-trained in 18 languages including Persian, `language` list including `fa`; the quick start is `thx01.load("doofz/THX-01")`; the repository (main at `b323afc`, about 679 MB) has no `multilingual` folder. The Persian 89.0% / ECE 0.052 claim therefore belongs to this root model (self-reported, one task). The package reads `rl_agent_config.json`, `model.safetensors` (every weight, encoder included: it requires `encoder.*` tensors and loads strictly), `encoder/config.json` (the encoder is built with `AutoModel.from_config`, no weights) and `tokenizer/` (`tokenizer.json`, `tokenizer_config.json`); `config.json` is in its download allow-list but never read. No other repository is needed.
- Loads from a local directory with no network **only if** that directory holds `rl_agent_config.json`, `model.safetensors`, `tokenizer/` and `encoder/`; if `encoder/` or `tokenizer/` is missing it falls back to `from_pretrained(cfg["encoder"])`, i.e. a Hub download. The fetch script must take all four and the adapter must set `HF_HUB_OFFLINE=1`.
- Interface: `Agent.system_one(state, questions)` returns `{"model", "answers", "usage": {"input_tokens", "output_tokens": 0}}`; questions use the same `instructions`/`criteria` shape as Jev. One forward pass for all questions of a request.
- **Calibration caveat:** the package clamps fitted temperatures to [0.5, 5.0] and documents that the shipped `choice:11+` bucket (0.1006) turned a 0.24 top probability into 0.99. The planned 12-option `intent` question falls in that bucket: keep `intent` at ≤ 10 options, or treat its confidence as uncalibrated. Decision for R3.
- Sequence budget comes from the checkpoint config (`max_len`, code default 512; the card says 1,024): verify after fetching.
- CPU latency: not reported anywhere authoritative (card gives GPU only: ~9–10 ms). Must be measured (R5).
- Warnings are written with `print` to stdout; the adapter must contain that.
- Its own REST server serves `POST /v1/systemone` as an alias of `/v1/decide`, so `SystemOneHttpBackend` can also front THX-01.

**Mizan-1.5-4B** (model card read 2026-11-02): Apache-2.0, Qwen3.5-4B base; GGUF `mizan-1.5-4b-Q4_K_M.gguf` (2.7 GB) in `xmanii/Mizan-1.5-4B-GGUF`; llama.cpp build b11443 or newer, `llama-server … --port 8080` serves `/v1/systemone`. Persian, 3,000 human-labelled records: Mizan 82.0% (ECE 0.064), Q4 82.1% (0.058), Jev 83.7% (0.092), Laya 62.4% (0.210); self-reported, no per-task n. Calibration temperatures live in `unsloth_decision_config.json` (values not on the card); **whether `llama-server` applies them is not stated**: check in R5. No latency figures.

**vLLM-SR d3:** not researched (only needed if THX-01 fails on Persian).

## 6. Repository facts that shape the design

- `domain/routing/policy.py::_cheapest_in_tier` raises `NotImplementedError`; `rule_based` never reaches it because it returns a `model_id`. `RequestPipeline._overhead_cost()` returns zero (TODO).
- `pyarrow` may be imported only in `data_access/postgres` (`tests/architecture/test_db_imports.py`). A Parquet reader in `data_access/full/` needs that test widened, on purpose (R2).
- No gpt-4.1-nano 404 note exists in the repository; gpt-4.1-nano answered normally in the 2026-10-18 live check. TODO-13 (mimo-v2.5 retirement, due 2026-10-21) is still open in the register.
- This working copy has no `.env`, no `config/local.toml`, no `data/derived/`, no `data/spend/`.

## 7. Planned live check (not run; plan only)

`scripts/router_live_check.py`, plan by default, `--run` only with owner approval, SYNTHETIC states only, every call through the spend guard:

| # | Call | Purpose | Upper bound (at researched prices) |
|---|---|---|---|
| 1 | `POST https://api.metisai.ir/typesafe/v1/systemone`, `model = "jev-latest"`, 1 `choice` + 1 `noul` + 1 `score`, ~150-token SYNTHETIC state | auth, path, reported model ID, usage fields (including `output_tokens`), whether `score` returns `probabilities`, latency from the owner's network | ≤ 2,000 input tokens |
| 2 | same, Persian SYNTHETIC state | Persian round trip, latency | ≤ 2,000 |
| 3 | same, malformed question (unknown type) | error mapping (`invalid_request`), error body shape (codes only recorded) | ≤ 2,000 |
| 4 | same, `model = "jev-1.13.0"` (a pinned ID the page does not offer) | whether pinned IDs are refused, error mapping | ≤ 2,000 |
| 5 | gpt-4.1-nano via the OpenAI wrapper with `response_format: json_schema` | does Metis pass JSON-schema output through (LLM-as-System-One backup) | 1,500 in + 300 out |

Bound: calls 1–4 ≤ 8,000 input tokens × USD 0.042/M ≈ USD 0.0004 **if Metis charges TypeSafe's price** (the Metis page states no price: the check refuses to run until a Metis price is configured or `router.allow_unpriced` is set for that run); call 5 ≈ USD 0.0003 at the 2026-10-18 gpt-4.1-nano price. Total well under USD 0.01.

**Ledger before the first live call (owner decision, 2026-11-02):** this machine has no `data/spend/ledger.jsonl`, and the old one cannot be copied. The earlier live spend on another machine was under USD 0.01 (progress.md). The new ledger is created only by the code on the first charge, never by hand; the earlier spend is allowed for by lowering the lifetime cap in the git-ignored `config/local.toml` (exact keys given in the R6 plan), and the owner checks the Metis dashboard total first.

**Owner decision (2026-11-02), licence:** Mode 1 (Jev via Metis and the LLM-as-System-One backup) sends SYNTHETIC or owner-written text only, until Metis confirms in writing that dataset text may be sent to TypeSafe. No slice or golden text goes to a hosted backend; `router.real_data_approved` stays false.

## 8. Decisions (all provisional until owner review)

- **Data access for the dev slice:** Parquet through pyarrow in a new `data_access/full/` (extra `db`, which already pins pyarrow 25.0.1), unless the owner confirms `eval.request` is populated on this machine, in which case the slice is selected from it.
- **HTTP client for Jev/Metis and local `/v1/systemone`:** `httpx` with a strict wire model; no `typesafe-sdk`.
- **Internal question vocabulary** (`options`, `levels`, `p_yes`) maps to the wire's `criteria` / `noul` in the adapters only.
- **THX-01 checkpoint:** the repository root (corrected 2026-11-02; there is no `multilingual` subfolder, §5), pinned by revision and sha256: exactly the files the package reads.
