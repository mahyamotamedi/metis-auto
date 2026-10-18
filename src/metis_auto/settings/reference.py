"""Reference-data reader (CMP-19; configuration.md §1, providers.md §4).

Responsibility: read the versioned reference files in ``config/reference/``
(model catalogue, price table, provider endpoints, baselines) into contracts,
and check them against each other. Enforces the no-fabrication rule at the
file level: prices are decimal strings with a source and check date; a limit
or capability counts only with evidence (the contracts check that).

Price rows the current ``PriceTable`` cannot represent (context-length tiers,
cache writes) are parsed and kept in ``pending_prices``. **All** rows of such
a model are kept aside, so its costs come out "not computed" rather than
wrongly priced at one tier, until Stage 7 extends the price schema.
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
    EndpointTable,
    PendingPriceRow,
    ReferenceData,
    ReferenceSettings,
)

TOKEN_TYPES = {t.value: t for t in TokenType}
STANDARD_TIER = "standard"


class ReferenceDataError(ValueError):
    """A reference file is malformed or inconsistent with another one."""


def load_reference(config_dir: Path, paths: ReferenceSettings) -> ReferenceData:
    catalogue = read_catalogue(config_dir / paths.catalogue)
    prices, pending = read_prices(config_dir / paths.prices)
    endpoints = (
        read_endpoints(config_dir / paths.endpoints) if paths.endpoints else None
    )
    baselines = (
        read_baselines(config_dir / paths.baselines) if paths.baselines else None
    )
    data = ReferenceData(catalogue, prices, endpoints, baselines, pending)
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


def read_prices(path: Path) -> tuple[PriceTable, tuple[PendingPriceRow, ...]]:
    """``version``, ``currency``, ``per_tokens``, ``[evidence]``, and
    ``[[prices]]`` rows of ``price_ref`` plus decimal-string amounts keyed by
    token type. Rows with a ``context_tier`` or an unsupported amount key go
    to ``pending_prices`` with every other row of the same ``price_ref``."""
    raw = _read(path)
    evidence = _validated(path, Sourced, **raw.get("evidence", {}))
    currency, per_tokens = raw.get("currency"), raw.get("per_tokens")
    rows = raw.get("prices", [])

    def amounts(row: dict[str, Any]) -> dict[str, Decimal]:
        meta = {"price_ref", "context_tier", "min_context_tokens", "max_context_tokens"}
        return {k: _decimal(path, row, k) for k in row if k not in meta}

    deferred = {
        row["price_ref"]
        for row in rows
        if row.get("context_tier") or set(amounts(row)) - set(TOKEN_TYPES)
    }
    entries, pending = [], []
    for row in rows:
        if row["price_ref"] in deferred:
            pending.append(
                PendingPriceRow(
                    price_ref=row["price_ref"],
                    context_tier=row.get("context_tier", STANDARD_TIER),
                    min_context_tokens=row.get("min_context_tokens"),
                    max_context_tokens=row.get("max_context_tokens"),
                    amounts=amounts(row),
                )
            )
            continue
        for token_type, amount in amounts(row).items():
            entries.append(
                PriceEntry(
                    price_ref=row["price_ref"],
                    token_type=TOKEN_TYPES[token_type],
                    amount=amount,
                    per_tokens=per_tokens,
                    currency=currency,
                    evidence=evidence,
                )
            )
    table = _validated(path, PriceTable, version=raw.get("version"), entries=entries)
    return table, tuple(pending)


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


def check_consistency(data: ReferenceData) -> None:
    """Cross-file rules: every ``price_ref`` has price rows (input and output,
    or pending rows); every catalogue provider has an endpoint when endpoints
    are configured; every baseline names a catalogue model."""
    priced: dict[str, set[TokenType]] = {}
    for entry in data.prices.entries:
        priced.setdefault(entry.price_ref, set()).add(entry.token_type)
    pending = {row.price_ref for row in data.pending_prices}
    model_ids = {e.model_id for e in data.catalogue.entries}
    for entry in data.catalogue.entries:
        ref = entry.price_ref
        if ref is not None and ref not in pending:
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


def _decimal(path: Path, row: dict[str, Any], key: str) -> Decimal:
    value = row[key]
    if not isinstance(value, str):
        raise ReferenceDataError(
            f"{path.name}: {row.get('price_ref')}.{key} must be a decimal string "
            '(e.g. "0.055"), not a TOML number, so it stays exact'
        )
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ReferenceDataError(
            f"{path.name}: {row.get('price_ref')}.{key} is not a decimal"
        ) from None


def _validated(path: Path, model: type, **values: Any) -> Any:
    try:
        return model.model_validate(values)
    except ValueError as exc:
        raise ReferenceDataError(f"{path.name}: {exc}") from None
