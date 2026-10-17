# External Model and Provider Interfaces (Stage 3)

Status: `ModelClient` port semantics and the error taxonomy **decided**; catalogue fields **provisional** (Stage 7 fixes the schema); which providers and SDKs to use is **open** (Q-08, ADR-0003). Last updated 2026-10-14.
Index: [architecture README](README.md). Components: CMP-10 (model clients), CMP-12 (tokenizers), CMP-13 (embedders), CMP-15 (judges). Requirements: FR-API-02, FR-FAIL-*, FR-ACCT-01, FR-ROUTE-05, FR-CTX-05.

No provider API, SDK method, price, or capability is stated in this document. Each one is researched, with source and check date, when an adapter or a catalogue entry is written (MP§3.8).

---

## 1. The `ModelClient` port

One operation, provisionally `invoke(ModelInvocation) -> ModelResult`.
- **Input** `ModelInvocation`: catalogue model ID, ordered input parts from the `ContextPlan`, attachment references, generation limits (maximum output tokens), request and attempt IDs, timeout.
- **Output** `ModelResult`, which is one of:
  - a **response**: text, normalised finish reason (`complete`, `length`, `content_filter`, `other`), `TokenUsage` with fidelity `provider_reported` when the provider returns usage, provider latency, provider-reported model version if returned;
  - a **normalised error**: an error class (§3), a retryable flag, and the provider's error code (a code, not a message, because messages can echo content);
  - **no answer** (added in Stage 4, `ModelNoAnswer`): a replay or proxy source has nothing for this target. It lowers coverage and is never retried or failed over ([ADR-0014](../adr/0014-counterfactual-answers-via-model-client.md)).
- Contracts: `ModelInvocation`, `ModelResult` ([contracts.md §3.4](contracts.md#34-context-and-model-calls)).
- **Never raises for provider failures.** Exceptions mean a programming or configuration error.
- **Synchronous** for now ([ADR-0010](../adr/0010-request-pipeline-shape.md)).
- Internal message roles are generic (for example `user`, `assistant`, `instructions`). Mapping the sample's `bot` role is the sample loader's job (ADR-0008). Mapping internal roles to each provider's format is the adapter's job.

---

## 2. Adapters

| Adapter | Kind | Purpose | Network? |
|---|---|---|---|
| Fake client | base | Canned, clearly synthetic answers. Deterministic given a seed. The walking skeleton and most tests use it. | no |
| Fault-injecting client | decorator | Scripted errors, timeouts, and delays per call, for failover tests (FR-FAIL-06). | no |
| Quality-injecting client | decorator | Scripted empty, truncated, wrong-language, or refusal answers, for detector and cascade tests. | no |
| Replay client | base | Answers from recorded responses or logged references ([evaluation.md §4](evaluation.md#4-counterfactual-sources-and-their-limits)). "No answer" when none exists. | no |
| Recording decorator | decorator | Writes live results to `data/recorded/` for reuse. | no (wraps a live client) |
| Live client, one per provider family | base | Real calls. Opt-in only, built only when a cap is set, tests marked `network` (ADR-0003). | **yes** |

The decorators compose, for example *recording(live)* or *fault(fake)*. Wiring builds the stack from configuration. Pipeline code sees only `ModelClient`.

---

## 3. Normalised errors

| Class | Meaning | Retryable by default |
|---|---|---|
| `timeout` | No complete response within the attempt timeout. | yes |
| `rate_limited` | The provider asked the caller to slow down. | yes |
| `unavailable` | Server-side failure or overload. | yes |
| `connection` | Network failure before a response. | yes |
| `context_overflow` | The input exceeded the model's limit. | no (handled by the context rule) |
| `content_filtered` | The provider blocked the input or output. | no |
| `invalid_request` | The request was malformed. | no |
| `auth` | Credentials are missing or rejected. | no |
| `unknown` | Anything unmapped. | once |

Each live adapter documents how its provider's responses map onto these classes, with sources. [attempts.md §3](attempts.md#3-errors-and-failover) gives the default action per class.

---

## 4. Model catalogue (reference data)

Provisional fields for each catalogue entry. Stage 7 fixes the schema.
- `model_id` (internal, stable), `provider`, `provider_model_name`, `family`;
- `tier` (an ordinal for routing and cascades) and `equivalence_group` (for failover; FR-FAIL-03);
- `context_window` and `max_output_tokens`, each with source and check date;
- capabilities (modalities, for example image input), **each with `verified: true|false`, source, and check date**. Unverified means unsupported for eligibility (FR-ROUTE-05);
- `tokenizer_ref` (which `Tokenizer` backend counts for this model, and its fidelity) and `price_ref` (price-table entry);
- provider prompt caching: whether supported, minimum prefix, discount. Verified-only, otherwise unknown (FR-CTX-05);
- `enabled`.

The **label mapping** (logged label → catalogue model, with fidelity) is a separate reference file used by the as-logged baseline. `default`, `workflow`, and null labels stay unmapped unless the data owner explains them (FR-ACCT-07, A-16).

---

## 5. Other external-facing ports

| Port | Network backends (future, opt-in) | Offline backends | Rule |
|---|---|---|---|
| `Tokenizer` | provider token-counting endpoints | approximation; exact local tokenizers (Stage 7) | Every count carries its fidelity. Network counting is off in tests. |
| `Embedder` | hosted embedding APIs | fake; local models (Stage 8). Downloading weights needs network once, at setup. | Persian-capable; ID and version recorded. |
| `Judge` | LLM judge built on a `ModelClient` | fake; imported human labels | Opt-in; cost reported as evaluation cost or overhead. |

All network backends have the same privacy rule as live providers: content leaves the machine, so they are opt-in.
