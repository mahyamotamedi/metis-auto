"""Config of the within-message dedup (``[pipeline.context.dedup]``). Kept in
its own module so ``policy`` can hold it without importing the strategy."""

from __future__ import annotations

from metis_auto.contracts import ContractModel


class DedupConfig(ContractModel):
    """DEMO selection (ADR-XXXX (demo-sprint-winners)); off by default."""

    enabled: bool = False
