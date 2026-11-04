"""The ``RunTracker`` port (sprint T-2): a plain mapping in, a run ID out.

Ports may not import ``analysis`` (ADR-0009), so the port takes ``Mapping``."""

from collections.abc import Mapping

from metis_auto.ports.tracking import RunTracker


class _Fake:
    def log_result(self, result: Mapping[str, object]) -> str:
        return "run-1"


def test_a_plain_object_with_log_result_is_a_run_tracker():
    assert isinstance(_Fake(), RunTracker)
    assert _Fake().log_result({"lever_id": "x"}) == "run-1"


def test_an_object_without_log_result_is_not():
    assert not isinstance(object(), RunTracker)
