"""Demo cache seed from the sample (CMP-20; DEMO ONLY, ADR-0023; brief §8).

Responsibility: pick a few first-turn sample questions that have one clean
logged answer, and store each answer in the pipeline's cache under the demo
seed's message-only key (``RequestPipeline.seed_demo_entry``). The logged
answers stay in this process's memory and cache: they are shown locally when
a typed message matches exactly, and are **never sent to a provider** (the
seed is a cache, not a prompt). The questions are returned so the terminal
chat can list them locally on request; nothing here prints or logs content.
Selection is deterministic: the loader's file order, first-turn cases with
pairing ``clean``, a non-empty answer, no attachments, not a greeting (the
configured phrase list), at most ``limit``.
Reads ``data/sample_data/raw/`` read-only through ``data_access`` (only
wiring may build it). Called by: wiring.chat. Calls: wiring.experiments
(``sample_cases``), application.pipeline, domain.features.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from metis_auto.application.measurement import Fingerprinter
from metis_auto.application.pipeline import RequestPipeline
from metis_auto.contracts import Component, ComponentState, PairingFlag, Request
from metis_auto.domain.features import is_greeting
from metis_auto.settings import LoadedSettings, SettingsError

from .experiments import SAMPLE_PATH, sample_cases
from .from_settings import pipeline_config


def seed_from_sample(
    loaded: LoadedSettings,
    pipeline: RequestPipeline,
    *,
    limit: int = 5,
    path: Path | None = None,
) -> tuple[str, ...]:
    """Seed up to ``limit`` logged answers; returns the seeded questions
    (content: keep them local). ``path`` lets tests use a synthetic file."""
    sample = path or loaded.root / SAMPLE_PATH
    if not sample.is_file():
        raise SettingsError(
            f"the demo seed needs the sample file {sample} (read-only); it is "
            "optional: leave the seed off"
        )
    greeting = pipeline_config(loaded).features.greeting
    # Opaque refs only; the key is never kept (the seed key uses the
    # pipeline's own fingerprinter).
    cases = sample_cases(loaded, Fingerprinter(secrets.token_bytes(32)), sample)
    seeded: list[str] = []
    for case in cases.cases:
        if len(seeded) >= limit:
            break
        request = case.request
        if (
            case.turn_index != 0
            or case.pairing_flag != PairingFlag.CLEAN
            or len(case.references) != 1
            or not case.references[0].text.strip()
            or request.history.state != ComponentState.ABSENT
            or request.attachments.state != ComponentState.ABSENT
            or not request.message.strip()
            or is_greeting(request.message, greeting)
            or request.message in seeded
        ):
            continue
        seed_request = Request(
            message=request.message,
            history=Component.absent(),
            attachments=Component.absent(),
        )
        if pipeline.seed_demo_entry(seed_request, case.references[0].text):
            seeded.append(request.message)
    return tuple(seeded)
