# Jev (TypeSafe) via Metis: model note (J-1)

Final sprint plan task **J-1** (Parham). Written 2026-11-03 from the decision-router R0 findings ([router_r0_findings.md](router_r0_findings.md) §4) and the Metis TypeSafe page the owner saved on 2026-11-02 ([metis_typesafe_wrapper_page.md](metis_typesafe_wrapper_page.md)). Each fact has its source and check date. *Unverified* means no source states it. The live check (R6, below) re-checks the starred items.

## Answer first

**Jev is a System-One decision model, not a chat model.** It reads a short *state* and answers named, typed questions about it (`choice`, `score`, `noul` = yes/no probability). It generates no text, so it **cannot answer a user**. It is therefore not a cheaper model to route to.

In this project Jev is **the router itself**:

- **Mode 1:** hosted Jev through the Metis wrapper, for shadow runs and labelling only.
- **Mode 2:** THX-01, the local open-weight model, is the inline router.

Both sit behind one port, `ports.BaseRouter`. Decision record: [ADR-XXXX (system-one-decision-router)](../adr/draft-system-one-decision-router.md).

**Not OpenAI-compatible.** Jev has its own endpoint and wire format (`/v1/systemone`, `{model, state, questions}` → `{model, answers, usage}`), so the existing OpenAI-compatible adapter (`adapters/providers/openai_compat.py`) cannot call it. It has its own adapter, `adapters/routers/jev_metis.py`. By the plan's own rule, J-4 and P-2 therefore do not use Jev as a chat model.

## Facts

| Item | Fact | Source, date | Status |
|---|---|---|---|
| Provider | TypeSafe AI; on the Metis price list under family `typesafe` | Metis pricing page (owner, 2026-11-02) | documented |
| Endpoint | `POST https://api.metisai.ir/typesafe/v1/systemone` | Metis TypeSafe page, saved 2026-11-02 | documented* |
| Auth | The Metis API key, `Authorization: Bearer <key>`; no TypeSafe account needed | Metis TypeSafe page | documented* |
| Model ID | `jev-latest` is the only model offered through Metis. The response names the exact version (example `jev-1.13.0`) | Metis TypeSafe page | documented* |
| API format | Request `{state, model, questions}`. Each question is `{type, instructions, criteria}`: `criteria` is an object of option → description for `choice`, a list of level labels for `score`, and absent for `noul`. Response `{model, answers, usage{input_tokens, output_tokens}}` | Metis page (curl example); Zuplo and LiteLLM pages, 2026-11-02 | documented* |
| OpenAI-compatible | **No** (own path and body; no `messages`, no generated text) | as above | documented |
| Price (Metis) | input **0.0462** USD and output **0.0000** USD per 1M tokens. The output price of zero is confirmed by the owner from the Metis pricing page. The page's own example reports non-zero `output_tokens` (65), which therefore cost nothing | Metis pricing page, family `typesafe`, model `jev-latest`, checked by the owner 2026-11-02 | recorded in `config/reference/prices-metis-router-2026-11-02.toml` (`metis-jev-latest`) |
| Price (TypeSafe direct) | 0.042 USD per 1M input tokens, output free | Zuplo gateway catalogue, 2026-11-02 | **never used** (owner decision) |
| Context window, output limit | Not stated | — | *unverified* |
| Persian support | Not stated. The router's states and questions are Persian or English | — | *unverified*; to be measured by the shadow evaluation once Jev may see dataset text (it may not yet, Q-55) |
| Tokenizer | Not published | — | *unverified*. The router's pre-call estimate is an upper bound (questions' characters / 2), not a count |
| Thinking tokens billed | Jev generates no text; `output_tokens` is priced at 0.0000 | Metis pricing page | documented |
| Rate limits, error format | Not stated | Metis TypeSafe page | *unverified*. `429` maps to `rate_limited`; other statuses map by code |
| Latency | No source | — | *unverified*. It is not needed inline: Jev is shadow and labelling only (owner, A-89) |
| Licence of data sent | Dataset text may **not** go to TypeSafe until Metis confirms it in writing. Mode 1 uses SYNTHETIC or the owner's own text only (`router.real_data_approved` stays false) | owner, 2026-11-02 (Q-53, Q-55) | decided |

## Configuration (J-2)

All of this already exists from the router work, so nothing is duplicated:

- **Price:** `config/reference/prices-metis-router-2026-11-02.toml`, row `metis-jev-latest`. A dated file; the general price files are not edited.
- **Endpoint and model:** `[router.backends.jev_metis]` in `config/defaults.toml` (`base_url = "https://api.metisai.ir/typesafe"`, `model = "jev-latest"`, `price_ref = "metis-jev-latest"`, `enabled = false`).
  - **No row in `endpoints-metis.toml`.** The plan adds an endpoint row only for an OpenAI-compatible model, and that file's rows are chat endpoints.
- **Catalogue:** no row. Jev is never a routing target, so `config/reference/catalogue-metis-test.toml` is unchanged.
- **`candidates_jev`:** `sprint.toml [routing] candidates_jev` stays **empty** (A-111). The file is owned by Pipeline C; its comment still says J-3 fills it, and that is for its owner to update.

## What J-3, J-4 and the Jev benchmark arm become

The plan's rule for an incompatible model applies, so none of these is built as written (owner decision 2026-11-03, A-111):

| Plan task | As written | Remapped to | Where |
|---|---|---|---|
| J-3 | Run per-bot reassignment with Jev among the candidate models | **Jev as the routing model (Mode 1).** The router's decided tier is turned into a model by R-0's routing base, in exp-route-013's routing step version | `experiments/routing/exp-route-013-decision-router/`, ADR-XXXX (system-one-decision-router) |
| J-4 | A live smoke test through `live_wrapper_check.py` | **The router live check:** one SYNTHETIC state to Jev via Metis, the LLM backup on three test models, and a `json_schema` probe; under 0.05 USD, through the spend guard | `scripts/router_live_check.py` |
| P-1/P-2 Jev arm | Jev answers benchmark requests | **The router's shadow evaluation:** rules only vs the decision router on the frozen dev slice (local backends only until Q-55 is answered) | `scripts/evaluate_router_slice.py`, exp-route-013 |

## Metis question (c) for O-1

The plan asks "what is JEV, and are its limits and price right?". From the Metis pages:

- **What it is:** TypeSafe's Jev is a System-One decision model. It is not a chat model.
- **How to call it:** `POST https://api.metisai.ir/typesafe/v1/systemone`, with the Metis key as a Bearer header and `model = jev-latest`.
- **Price:** 0.0462 USD per 1M input tokens; output 0.0000.
- **Compatibility:** not OpenAI-compatible.

**Still to ask Metis:**

1. Context and output limits.
2. Rate limits.
3. Whether Persian is supported.
4. Whether dataset text may be sent to TypeSafe through the wrapper (Q-55).

This note is the answer; the O-1 owner forwards it. O-1 itself is not edited here.

## Live check (R6), 2026-11-03

The owner ran `scripts/router_live_check.py` on Windows, with one SYNTHETIC Persian state and the five routing questions. Every fact marked * above is **confirmed**:

| Item | Result |
|---|---|
| Endpoint, auth, model ID | `POST https://api.metisai.ir/typesafe/v1/systemone`, Bearer Metis key, `model = jev-latest`: answered (HTTP 200) |
| Reported version | **`jev-1.14.0`**. The page's example shows `jev-1.13.0`, so `jev-latest` has moved. The router records the reported version as `model_revision`, and a change of version clears the router cache (ADR point 8) |
| Answers | All 5 questions answered in the documented shape. Only **2 of 5** carried a `confidence` (the `score` and `choice` answers). The 3 yes/no (`noul`) answers carry `noul` (P(yes)) only |
| Usage | **699 input / 171 output tokens.** The output count is non-zero, as in the page's example |
| Cost | **0.0000322938 USD** = 699 × 0.0462 / 1M: input only, output free, as the Metis price list says. Charged to the ledger |
| Latency | **3.5 s** from the owner's network, end to end. Jev **cannot be used inline** (budget 60 ms p95); Mode 1 stays shadow runs, labelling and evaluation (A-89 confirmed) |

**Consequences:**
- The pre-call estimate for that call was 593 tokens, so it was not an upper bound: Jev wraps each question in its own template. The estimate now counts the questions' text at one token per character, plus 32 tokens per question and twice the state's tokens (about 1,350 tokens for this call).
- With the gate on the mapping questions and the backend's own `confidence`, a Jev answer is gated on `complexity` alone, because its yes/no answers report none. The probability statistic (`max(p, 1 - p)`) covers all three mapping questions.
