"""The routing dev slice: 100–200 seeded, stratified records of the full
dataset for developing and evaluating the decision router
(ADR-XXXX (system-one-decision-router)).

Pure: configuration, selection under soft quotas and hard caps, strata,
record building and the ``Request`` mapping, content-free reports, the review
sheet and label import. Reading the dataset is ``data_access.full``;
composition is ``wiring.router_slice``. Guide:
docs/evaluation/router_dev_slice_v1.md.
"""
