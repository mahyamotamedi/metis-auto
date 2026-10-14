"""Infrastructure implementations of ports.

Fake, recorded, and opt-in live provider clients; fault-injecting fakes;
cache stores; event sinks; tokenizer and embedder backends. Provider SDKs and
third-party backends are imported only here. No business rules, no dataset
reading (see data_access).

May import: ports, contracts.
Traces: FR-API-02, FR-FAIL-06, FR-XCACHE-08, FR-OBS-06, ADR-0003.
"""
