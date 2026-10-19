"""The data layer: the only code that knows where and how data is stored.

Sample-file loader (sample quirks handled here), tested pairing heuristic
with pairing-quality flags, synthetic-data generator; later the full-dataset
loader and database repositories. Never imports experiments/sample_eda.

Sub-packages: sample, synthetic, replay_cases (skeletons until Stage 9).
May import: ports, contracts.
Traces: FR-DATA-01..08, FR-REQ-03..05, ADR-0008.
"""
