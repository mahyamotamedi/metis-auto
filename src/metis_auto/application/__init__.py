"""Request orchestration: the single in-process entry point.

Runs cache lookup, routing, context build, and the attempt loop (cascade,
failover, retries), emitting an event at every decision point. Receives
concrete collaborators through ports; makes no decisions itself.

May import: domain, ports, contracts.
Traces: FR-API-01, FR-CASC, FR-FAIL, FR-OBS-01.
"""
