"""System-One decision backends (``ports.BaseRouter``;
ADR-XXXX (system-one-decision-router)).

R1: the scripted fake. Later phases add Jev via Metis and the LLM backup
(R6), THX-01 in-process and a local ``/v1/systemone`` client (R5), and the
recording and replay decorators. Heavy libraries (``thx01``, ``torch``,
``transformers``, ``onnxruntime``) are imported only inside their own adapter
module, never here (tested).
"""

from .fake import FakeDecisionBackend, answer_for, local_zero_cost, neutral_answer

__all__ = [
    "FakeDecisionBackend",
    "answer_for",
    "local_zero_cost",
    "neutral_answer",
]
