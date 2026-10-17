"""Test-session setup.

TODO(Stage 5): remove the ``sys.path`` lines once ``pyproject.toml`` exists and
the package is installed in editable mode (ADR-0001, repository_structure §1).
Until then they make ``metis_auto`` (src layout) and the synthetic fixtures
importable without installing anything.
"""

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
for _path in (_TESTS.parent / "src", _TESTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
