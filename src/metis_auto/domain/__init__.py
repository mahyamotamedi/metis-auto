"""Pure decision logic: policies decide, the pipeline coordinates.

Feature extraction, language detection, normalisation, routing policies,
cache key composition and validity, context policies, unsatisfactory-response
detectors, token and cost accounting. Each policy owns its typed config. No
I/O, clocks, network, or provider specifics; unpromoted experimental
strategies stay in experiments/.

May import: contracts (S3-2, ADR-0009 amendment 2026-10-17). Measurements
that need a port are taken by application and passed in as data (P-1).
Traces: FR-FEAT, FR-ROUTE, FR-XCACHE, FR-SCACHE, FR-CTX, FR-CASC, FR-ACCT.
"""
