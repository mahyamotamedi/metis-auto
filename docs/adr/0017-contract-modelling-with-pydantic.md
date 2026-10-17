# ADR-0017: Contracts are pydantic v2 models — frozen, strict about field names, with a privacy class on every field

- Status: **decided** (library and conventions). The exact version is **provisional** until the lockfile exists (Stage 5/6).
- Date: 2026-10-17
- Relates to: MP§5 Stage 4, ADR-0001, ADR-0009 (§3.3: `contracts`, `ports`, `domain` may use "the contract-modelling library chosen in Stage 4"), ADR-0010, ADR-0012, ADR-0015, QA-PRIV, QA-LAT, QA-TEST, FR-OBS-02
- Detail: [contracts.md](../architecture/contracts.md)

## Context

Stage 4 expresses the internal contracts as typed models. The models must:
1. **validate minimally** at construction: shape, formats (IDs, fingerprints, currency), and internal consistency (a computed cost has a price version; a hit names its entry). Policy rules stay in `domain`;
2. **serialise to and from JSON** without hand-written code, because events, manifests, cache entries, and recorded responses are persisted (ADR-0012, ADR-0014);
3. **express tagged unions** (`ModelResult` = response | error | no answer; event payloads by type) and **generic tri-state components** (present / absent / unknown, P-6);
4. **carry per-field metadata** (a privacy class and a description) that a test can read, so "no content in events" is checked mechanically (ADR-0012 point 3);
5. be **immutable**, since contracts are values passed between pure policies;
6. stay cheap enough for the request path (QA-LAT: overhead ≤ 100 ms p95, provisional);
7. be importable from `contracts`, `ports`, and `domain` with no I/O (ADR-0009 §3.3).

## Decision

1. **pydantic v2** (`BaseModel`) for every contract.
2. **One base class**, `ContractModel`: `frozen=True` (immutable) and `extra="forbid"` (an unknown or misspelt field is an error, not silently dropped). Sequences are typed as tuples so instances are deeply immutable, except `dict` fields, which are shallowly mutable by Python's rules and must not be mutated.
3. **Lax (default) validation mode**, so JSON strings parse into `datetime`, `Decimal`, and enums. Strict mode is not used: its JSON-mode coercion rules would need verifying field type by field type, and lax mode is enough for "minimal validation".
4. **Every field is declared with `field(privacy, description)`**, a thin wrapper over `pydantic.Field` that stores the privacy class in `json_schema_extra`. `contracts/privacy.py` reads it statically, and the tests require a class on every field.
5. **Discriminated unions** (`Field(discriminator=...)`) for `ModelResult` and event payloads. A **generic** `Component[T]` for tri-state request components.
6. **Version used now:** pydantic **2.10.3** on CPython 3.13.5, the versions installed on the development machine (checked 2026-10-17 by running the test suite: 250 pass, 240 of them contract tests). The requirement goes into `pyproject.toml` in Stage 5/6 as `pydantic>=2.10,<3`, and the lockfile pins one tested version. PyPI lists **2.14.1** as the latest release, uploaded 2026-10-11, with Python 3.13 among its classifiers (checked 2026-10-17, https://pypi.org/project/pydantic/). **Re-verify:** run the contract tests under the locked version before Stage 5 code depends on it.
7. **Hot-path escape hatch, not used now:** if the Stage 5 overhead measurement shows that validation matters, `model_construct` (no validation) may be used for contracts built *inside* the pipeline from already-validated parts. That needs a measurement and a note in the module reference. Contracts that arrive from outside (requests, persisted records) are always validated.

## Alternatives considered

- **Standard-library `dataclasses`.** No dependency, and fast. But validation, JSON parsing of nested types (`datetime`, `Decimal`, enums, unions), discriminated unions, and per-field metadata would all be hand-written, roughly a small serialisation library of our own. It would also be untested code in the most widely used package. Rejected.
- **attrs + cattrs.** Mature, with validators and structured (un)serialisation. Two libraries to learn and configure instead of one; tagged unions need custom hooks. No advantage over pydantic for this project. Rejected.
- **msgspec `Struct`.** Very fast encoding and decoding, with tagged unions. But it validates on *decode*, not on construction in Python, so a policy could build an invalid contract unnoticed; and it supports only a narrow set of validators. Rejected for now. It stays a candidate for a high-volume event encoder in the online phase, behind the `EventSink` port.
- **`TypedDict` / plain dicts.** No runtime checks at all. Rejected.
- **Generated models from JSON Schema or protobuf.** Useful for a cross-language wire format (the future gateway, Q-15), but internal contracts are Python-only (FR-API-03). Rejected; pydantic can export JSON Schema later if a wire format needs one.

## Consequences

- `contracts`, `ports`, and `domain` depend on pydantic. It is the only third-party dependency allowed there (repository_structure.md §3.3). It does no I/O.
- `pyproject.toml` (Stage 5/6) declares `pydantic>=2.10,<3`. The lockfile pins a version that the tests have run under.
- Until `pyproject.toml` exists, `tests/conftest.py` puts `src/` on `sys.path` (TODO, Stage 5).
- A pydantic major-version change would touch every contract. The `<3` bound makes that a deliberate upgrade.
- Policy configs in `domain` (each policy owns its typed config, configuration.md §3 rule 5) use the same base class for consistency.
