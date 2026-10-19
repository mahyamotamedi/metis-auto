"""Attempt policy (CMP-08): retry, failover, and escalation in one loop
(ADR-0013), plus unsatisfactory-response detectors. Traces: FR-CASC-*, FR-FAIL-*."""

from .detectors import (
    Detector,
    EmptyOutputDetector,
    TruncationDetector,
    is_unsatisfactory,
    run_detectors,
)
from .policy import AttemptPolicyConfig, ErrorAction, next_action

__all__ = [
    "AttemptPolicyConfig",
    "Detector",
    "EmptyOutputDetector",
    "ErrorAction",
    "TruncationDetector",
    "is_unsatisfactory",
    "next_action",
    "run_detectors",
]
