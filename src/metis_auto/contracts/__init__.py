"""Typed data models passed between components (Stage 4).

Requests, routing decisions, model responses, token usage, cost, events, run
records. Shape validation only; no behaviour, I/O, or provider/wire formats.
Every field carries a privacy classification.

May import: nothing internal.
Traces: FR-REQ-01/02, FR-OBS-02/03, FR-API-03.
"""
