"""Offline evaluation: replay, baselines, metrics, judges, experiment runner.

Runs the real application pipeline with injected adapters and data sources
(built by wiring and passed in), computes metrics and event aggregates, and
records reproducible run manifests.

May import: application, domain, settings, ports, contracts.
Traces: FR-EVAL-01..09, FR-OBS-05, ADR-0002, ADR-0006, QA-REPRO.
"""
