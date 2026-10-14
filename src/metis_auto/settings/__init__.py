"""Configuration loading: secrets, runtime config, experiment config, defaults.

Reads files and environment, merges layers by precedence, validates shape,
and never logs secrets (Stage 6). Knows no specific policy; wiring maps
settings onto components.

May import: contracts.
Traces: MP section 4 (configuration over code), ADR-0003.
"""
