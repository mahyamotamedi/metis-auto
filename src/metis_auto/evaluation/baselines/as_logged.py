"""As-logged baseline (CMP-22; evaluation.md §5, ADR-0002).

Responsibility: the cost of what the logged model actually did, computed from
the case without a pipeline run: logged label → catalogue model (with
fidelity), tokens on the assumed prompt composition, price from the table.
Unmapped labels (``default``, ``workflow``, null) → "not computed".
The premium baseline is a ``fixed_model`` pipeline built by wiring.
Called by: evaluation.metrics (Stage 8). Calls: domain.accounting.

Status: skeleton. TODO(Stage 7/8): needs the label-mapping schema (O-3).
"""

from __future__ import annotations

from metis_auto.contracts import Cost, ModelCatalogue, PriceTable, ReplayCase


def as_logged_cost(
    case: ReplayCase, catalogue: ModelCatalogue, prices: PriceTable
) -> Cost:
    raise NotImplementedError("TODO(Stage 7/8): label mapping and composition")
