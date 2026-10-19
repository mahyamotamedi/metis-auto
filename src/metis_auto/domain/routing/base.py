"""Routing policy interface (FR-ROUTE-03).

``RoutingPolicy`` is the swap point for routing strategies: candidates in
experiments/routing/ implement it until promoted (repository_structure §6.2),
and wiring maps a configured name to a promoted implementation (QA-REPL).
Pure types only. Used by: domain.routing.policy, domain.routing.fixed_model.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from metis_auto.contracts import CatalogueEntry, PolicyRef, RequestFeatures


class RequestedModelMode(StrEnum):
    """FR-ROUTE-06 (open). Only ``ignore`` is implemented."""

    IGNORE = "ignore"
    HONOUR_IF_ELIGIBLE = "honour_if_eligible"
    HONOUR = "honour"


@dataclass(frozen=True)
class PolicyChoice:
    """A policy's answer: a model, or a tier to pick the cheapest model from.
    Internal to domain.routing; ``route`` turns it into a ``RoutingDecision``."""

    reason_code: str
    model_id: str | None = None
    tier: int | None = None
    features_used: tuple[str, ...] = ()
    chain: tuple[str, ...] | None = None
    """Escalation chain chosen by the policy; None = ``RoutingConfig.chain``."""
    anchor_model_id: str | None = None
    """Sticky routing: the session's anchor before this request."""


class RoutingPolicy(Protocol):
    """A pure routing policy: one choice among the eligible models."""

    @property
    def ref(self) -> PolicyRef: ...

    def choose(
        self, features: RequestFeatures, eligible: tuple[CatalogueEntry, ...]
    ) -> PolicyChoice | None:
        """A choice among ``eligible`` (never empty), or None for no target."""
        ...
