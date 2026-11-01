"""Test-session setup.

``metis_auto`` is installed in editable mode (``pip install -e . --no-deps``)
and ``tests/`` is on the path through ``pythonpath`` in pyproject.toml.

Tests that need the network or API keys carry ``@pytest.mark.network`` and are
skipped unless ``--run-network`` is given (ADR-0003, QA-TEST). Tests that need a
local PostgreSQL carry ``@pytest.mark.postgres`` and are skipped unless
``--run-postgres`` is given (ADR-0027).
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run tests marked 'network' (opt-in; may need keys and cost money)",
    )
    parser.addoption(
        "--run-postgres",
        action="store_true",
        default=False,
        help="run tests marked 'postgres' (opt-in; needs a local server)",
    )


def pytest_collection_modifyitems(config, items):
    for option, marker in (
        ("--run-network", "network"),
        ("--run-postgres", "postgres"),
    ):
        if config.getoption(option):
            continue
        skip = pytest.mark.skip(reason=f"{marker} test: opt in with {option}")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)
