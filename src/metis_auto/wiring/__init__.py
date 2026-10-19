"""Composition root: builds concrete objects from settings.

Factories assembling pipelines (``pipeline``), the walking skeleton
(``walking_skeleton``), and later runners and data sources. The only package
that combines application with concrete adapters and data_access. Maps
configured names to promoted components; no other logic.

May import: every metis_auto package.
Traces: QA-REPL, FR-DATA-02.
"""
