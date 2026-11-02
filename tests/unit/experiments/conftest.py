"""Load candidate code from ``experiments/`` by file path, as scripts do.

Experiment folders are not packages (their names hold hyphens), so tests load a
file with ``importlib`` the way ``wiring.experiments.load_candidate`` does.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

EXPERIMENTS = Path(__file__).resolve().parents[3] / "experiments"


def _load(relative: str):
    path = EXPERIMENTS / relative
    name = "test_experiment_" + relative.replace("/", "_").replace("-", "_")[:-3]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def load_experiment():
    return _load
