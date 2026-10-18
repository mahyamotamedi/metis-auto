"""Synthetic-data generator (CMP-18; FR-DATA-03).

Responsibility: generate clearly synthetic sessions (every string marked
``[SYNTHETIC]``) that mirror the *shape* the data may have — Persian-dominant,
multi-turn, optional instructions, retrieved context, attachments — without
copying real content, deterministically from a seed. Implements
``ports.DataSource``. Built by: wiring.

Status: skeleton. TODO(Stage 9): generator plan and implementation.
"""

from __future__ import annotations

from collections.abc import Iterator

from metis_auto.contracts import Name, Session


class SyntheticDataSource:
    def __init__(self, seed: int) -> None:
        self._seed = seed

    @property
    def dataset(self) -> Name:
        return "synthetic_v1"

    def sessions(self) -> Iterator[Session]:
        raise NotImplementedError("TODO(Stage 9): synthetic generator")
