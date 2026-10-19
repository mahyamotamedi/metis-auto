"""Reference-data reader (CMP-19; configuration.md §1, providers.md §4).

Responsibility: read the versioned reference files in ``config/reference/``
(model catalogue, price table, provider endpoints, baselines, tokenizers,
compressors)
into contracts, and check them against each other. Enforces the
no-fabrication rule at the file level: prices are decimal strings with a
source and check date; a limit or capability counts only with evidence (the
contracts check that); every tokenizer states its fidelity and evidence.

Price rows (Stage 7 schema, token_accounting.md §4): ``price_ref``, optional
context ``tier`` with ``min_input_tokens`` / ``max_input_tokens`` (and
``max_input_tokens_uncertain_up_to``), and amounts keyed by token type
(``input``, ``output``, ``cached_input``, ``cache_write``); ``cache_write``
may be a table of variants (``{ "ttl-5m" = "…", "ttl-1h" = "…" }``). Unknown
keys are errors.
Called by: settings.loader. Calls: nothing internal beyond contracts.
"""

from __future__ import annotations

import tomllib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from metis_auto.contracts import (
    CatalogueEntry,
    ModelCatalogue,
    PriceEntry,
    PriceTable,
    Sourced,
    TokenType,
)

from .model import (
    BaselineTable,
    CompressorTable,
    EndpointTable,
    LabelMapping,
    ReferenceData,
    ReferenceSettings,
    TokenizerTable,
)

PRICE_KEYS = {
    t.value: t
    for t in (
        TokenType.INPUT,
        TokenType.OUTPUT,
        TokenType.CACHED_INPUT,
        TokenType.CACHE_WRITE,
    )
}
TIER_KEYS = (
    "tier",
    "min_input_tokens",
    "max_input_tokens",
    "max_input_tokens_uncertain_up_to",
)


class ReferenceDataError(ValueError):
    """A reference file is malformed or inconsistent with another one."""


def load_reference(config_dir: Path, paths: ReferenceSettings) -> ReferenceData:
    catalogue = read_catalogue(config_dir / paths.catalogue)
    prices = read_prices(config_dir / paths.prices)
    endpoints = (
        read_endpoints(config_dir / paths.endpoints) if paths.endpoints else None
    )
    baselines = (
        read_baselines(config_dir / paths.baselines) if paths.baselines else None
    )
    tokenizers = (
        read_tokenizers(config_dir / paths.tokenizers) if paths.tokenizers else None
    )
    label_mapping = (
        read_label_mapping(config_dir / paths.label_mapping)
        if paths.label_mapping
        else None
    )
    compressors = (
        read_compressors(config_dir / paths.compressors) if paths.compressors else None
    )
    data = ReferenceData(
        catalogue, prices, endpoints, baselines, tokenizers, label_mapping, compressors
    )
    check_consistency(data)
    return data


def read_catalogue(path: Path) -> ModelCatalogue:
    """``version`` plus ``[[models]]`` tables. An omitted limit is unknown."""
    raw = _read(path)
    entries = []
    for model in raw.get("models", []):
        model = {"context_window": {}, "max_output_tokens": {}, **model}
        entries.append(CatalogueEntry.model_validate(model))
    return _validated(path, ModelCatalogue, version=raw.get("version"), entries=entries)


def read_prices(path: Path) -> PriceTable:
    """``version``, ``currency``, ``per_tokens``, optional ``effective_from``,
    ``[evidence]``, and ``[[prices]]`` rows (see the module docstring)."""
    raw = _read(path)
    evidence = _validated(path, Sourced, **raw.get("evidence", {}))
    currency, per_tokens = raw.get("currency"), raw.get("per_tokens")
    entries = []
    for row in raw.get("prices", []):
        unknown = set(row) - {"price_ref", *TIER_KEYS, *PRICE_KEYS}
        if unknown:
            raise ReferenceDataError(
                f"{path.name}: {row.get('price_ref')}: unknown keys {sorted(unknown)}"
            )
        common = {
            "price_ref": row["price_ref"],
            "per_tokens": per_tokens,
            "currency": currency,
            "effective_from": raw.get("effective_from"),
            "evidence": evidence,
            **{k: row[k] for k in TIER_KEYS if k in row},
        }
        for key, token_type in PRICE_KEYS.items():
            if key not in row:
                continue
            variants = row[key] if isinstance(row[key], dict) else {None: row[key]}
            for ttl, value in variants.items():
                amount = _decimal(path, row["price_ref"], key, value)
                entries.append(
                    _validated(
                        path,
                        PriceEntry,
                        token_type=token_type,
                        amount=amount,
                        cache_ttl=ttl,
                        **common,
                    )
                )
    return _validated(path, PriceTable, version=raw.get("version"), entries=entries)


def read_endpoints(path: Path) -> EndpointTable:
    raw = _read(path)
    return _validated(
        path, EndpointTable, version=raw.get("version"), endpoints=raw.get("endpoints")
    )


def read_baselines(path: Path) -> BaselineTable:
    raw = _read(path)
    return _validated(
        path, BaselineTable, version=raw.get("version"), baselines=raw.get("baselines")
    )


def read_tokenizers(path: Path) -> TokenizerTable:
    """``version`` plus ``[[tokenizers]]`` specs (token_accounting.md §2)."""
    raw = _read(path)
    return _validated(
        path,
        TokenizerTable,
        version=raw.get("version"),
        tokenizers=raw.get("tokenizers"),
    )


def read_compressors(path: Path) -> CompressorTable:
    """``version`` plus ``[[compressors]]`` specs (Demo milestone)."""
    raw = _read(path)
    return _validated(
        path,
        CompressorTable,
        version=raw.get("version"),
        compressors=raw.get("compressors"),
    )


def read_label_mapping(path: Path) -> LabelMapping:
    """``version``, ``dataset``, and ``[[labels]]`` rows (Stage 8)."""
    raw = _read(path)
    mapping = _validated(
        path,
        LabelMapping,
        version=raw.get("version"),
        dataset=raw.get("dataset"),
        labels=raw.get("labels"),
    )
    labels = [e.label for e in mapping.labels]
    if len(labels) != len(set(labels)):
        raise ReferenceDataError(f"{path.name}: a label is listed twice")
    return mapping


def check_consistency(data: ReferenceData) -> None:
    """Cross-file rules: every ``price_ref`` has input and output prices;
    every catalogue provider has an endpoint when endpoints are configured;
    every baseline names a catalogue model; every ``tokenizer_ref`` is in the
    tokenizer table when one is configured."""
    priced: dict[str, set[TokenType]] = {}
    for entry in data.prices.entries:
        priced.setdefault(entry.price_ref, set()).add(entry.token_type)
    model_ids = {e.model_id for e in data.catalogue.entries}
    for entry in data.catalogue.entries:
        if (
            data.tokenizers is not None
            and entry.tokenizer_ref is not None
            and data.tokenizers.get(entry.tokenizer_ref) is None
        ):
            raise ReferenceDataError(
                f"{entry.model_id}: tokenizer_ref {entry.tokenizer_ref!r} is not in "
                "the tokenizer table"
            )
        ref = entry.price_ref
        if ref is not None:
            missing = {TokenType.INPUT, TokenType.OUTPUT} - priced.get(ref, set())
            if missing:
                raise ReferenceDataError(
                    f"{entry.model_id}: price_ref {ref!r} lacks "
                    f"{sorted(t.value for t in missing)} prices; omit price_ref to "
                    "mark the price unknown"
                )
        if data.endpoints is not None and data.endpoints.get(entry.provider) is None:
            raise ReferenceDataError(
                f"{entry.model_id}: no endpoint for provider {entry.provider!r}"
            )
    if data.label_mapping is not None:
        for row in data.label_mapping.labels:
            if row.model_id is not None and row.model_id not in model_ids:
                raise ReferenceDataError(
                    f"label {row.label!r} maps to {row.model_id!r}, which is not "
                    "in the catalogue"
                )
    if data.baselines is not None:
        for baseline in data.baselines.baselines:
            if baseline.model_id is not None and baseline.model_id not in model_ids:
                raise ReferenceDataError(
                    f"baseline {baseline.name!r} names {baseline.model_id!r}, "
                    "which is not in the catalogue"
                )


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        raise ReferenceDataError(f"reference file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ReferenceDataError(f"{path}: {exc}") from None


def _decimal(path: Path, price_ref: str, key: str, value: Any) -> Decimal:
    if not isinstance(value, str):
        raise ReferenceDataError(
            f"{path.name}: {price_ref}.{key} must be a decimal string "
            '(e.g. "0.055"), not a TOML number, so it stays exact'
        )
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ReferenceDataError(
            f"{path.name}: {price_ref}.{key} is not a decimal"
        ) from None


def _validated(path: Path, model: type, **values: Any) -> Any:
    try:
        return model.model_validate(values)
    except ValueError as exc:
        raise ReferenceDataError(f"{path.name}: {exc}") from None
