"""Context compressor from settings (CMP-20; Demo milestone, ADR-0023).

Responsibility: build the configured ``TextCompressor`` from the compressor
table (``config/reference/compressors.toml``): LLMLingua-2 from local,
sha256-checked files under ``paths.compressor_assets``. The heavy libraries
(extra ``compress``) are imported only here, when a compressor is actually
built, so nothing else needs them. A missing extra or file is a
``SettingsError`` that names the fix; it never downloads.
Called by: wiring.from_settings, wiring.chat, scripts/measure_overhead.py.
Calls: settings, adapters.compressors.
"""

from __future__ import annotations

from metis_auto.ports import TextCompressor
from metis_auto.settings import CompressorBackend, LoadedSettings, SettingsError


def build_compressor(loaded: LoadedSettings, ref: str) -> TextCompressor:
    table = loaded.reference.compressors
    spec = table.get(ref) if table is not None else None
    if spec is None:
        raise SettingsError(f"compressor {ref!r} is not in the compressor table")
    if spec.backend != CompressorBackend.LLMLINGUA2:
        raise SettingsError(f"compressor backend {spec.backend.value!r} unsupported")
    try:
        from metis_auto.adapters.compressors.llmlingua2 import (
            CompressorUnavailable,
            LLMLingua2Compressor,
        )
    except ImportError as exc:  # pragma: no cover - the module imports lazily
        raise SettingsError(f"compressor adapter unavailable: {exc}") from None
    directory = loaded.path(loaded.settings.paths.compressor_assets) / spec.directory
    try:
        return LLMLingua2Compressor(
            name=spec.ref,
            revision=spec.revision,
            directory=directory,
            files=[(f.name, f.sha256) for f in spec.files],
            library_version=spec.library,
        )
    except CompressorUnavailable as exc:
        raise SettingsError(f"compression unavailable: {exc}") from None
