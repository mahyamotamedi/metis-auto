"""Pure decision logic: policies decide, the pipeline coordinates.

Feature extraction, language detection, normalisation, routing policies,
cache key composition and validity, context policies, unsatisfactory-response
detectors, token and cost accounting. Each policy owns its typed config. No
I/O, clocks, network, or provider specifics; unpromoted experimental
strategies stay in experiments/.

May import: ports, contracts.
Traces: FR-FEAT, FR-ROUTE, FR-XCACHE, FR-SCACHE, FR-CTX, FR-CASC, FR-ACCT.
"""
