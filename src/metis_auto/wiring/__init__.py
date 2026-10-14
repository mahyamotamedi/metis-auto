"""Composition root: builds concrete objects from settings.

Factories assembling pipelines, runners, and data sources. The only package
that combines application with concrete adapters and data_access. No logic.

May import: every metis_auto package.
Traces: QA-REPL, FR-DATA-02.
"""
