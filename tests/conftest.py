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


@pytest.fixture(autouse=True)
def _demo_files_in_tmp(tmp_path_factory, monkeypatch):
    """The demo UI saves conversations and made chatbots under runs/demo/
    (UI-R11). No test writes there: the default folder is a temporary one, and
    on CI the real one does not exist (tests that restart a demo pass their own
    ``_test_demo_dir``)."""
    from metis_auto.wiring import demo_store

    root = tmp_path_factory.mktemp("demo")
    monkeypatch.setattr(demo_store, "default_root", lambda: root)
