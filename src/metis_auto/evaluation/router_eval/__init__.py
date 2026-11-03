"""Shadow evaluation of the decision router (exp-route-013, R8; pure).

``ShadowRow`` is one request's content-free outcome under the rules alone and
under the decision router; ``summarise`` turns rows into the R8 comparison
(tier mix, agreement, confidence, gate share, path mix, latency) per split,
balanced and traffic-weighted, Persian first; ``against_labels`` scores rows
against tier labels (L4 synthetic in CI; L1/L3 later). Traces: FR-EVAL-04/06,
FR-ROUTE-03/04, QA-PRIV, ADR-0047.
"""

from .metrics import (
    GATE_KEEP_SHARE,
    LANGUAGE_ORDER,
    ShadowRow,
    against_labels,
    answer_distributions,
    propose_gate,
    summarise,
)

__all__ = [
    "GATE_KEEP_SHARE",
    "LANGUAGE_ORDER",
    "ShadowRow",
    "against_labels",
    "answer_distributions",
    "propose_gate",
    "summarise",
]
