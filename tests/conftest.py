"""Test-session setup.

``metis_auto`` is installed in editable mode (``pip install -e . --no-deps``)
and ``tests/`` is on the path through ``pythonpath`` in pyproject.toml.

Tests that need the network or API keys carry ``@pytest.mark.network`` and are
skipped unless ``--run-network`` is given (ADR-0003, QA-TEST).
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run tests marked 'network' (opt-in; may need keys and cost money)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="network test: opt in with --run-network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
