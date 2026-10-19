"""Recording decorator (ADR-0014): live results are appended; nothing else is
written; a failed write never raises (the call is already paid). Offline."""

import logging

from fixtures.synthetic import contract_examples as ex

from metis_auto.adapters.providers import FakeModelClient, RecordingModelClient
from metis_auto.adapters.providers.recording import read_records
from metis_auto.contracts import AnswerSource, ModelInvocation, ModelResult
from metis_auto.ports import ModelClient


class _Live:
    """A fake that claims to be live (synthetic answers, no network)."""

    def __init__(self):
        self._fake = FakeModelClient()

    @property
    def source(self) -> AnswerSource:
        return AnswerSource.LIVE

    def invoke(self, invocation: ModelInvocation) -> ModelResult:
        return self._fake.invoke(invocation)


def test_live_results_are_appended(tmp_path):
    path = tmp_path / "rec" / "live-run.jsonl"
    client = RecordingModelClient(_Live(), path, run_id="run-1")
    assert isinstance(client, ModelClient) and client.source == AnswerSource.LIVE
    first = client.invoke(ex.model_invocation())
    client.invoke(ex.model_invocation())
    records = read_records(path)
    assert len(records) == 2
    assert records[0]["v"] == 1 and records[0]["run_id"] == "run-1"
    assert records[0]["result"]["text"] == first.text
    assert records[0]["invocation"]["model_id"] == ex.model_invocation().model_id


def test_non_live_sources_are_not_recorded(tmp_path):
    path = tmp_path / "x.jsonl"
    RecordingModelClient(FakeModelClient(), path).invoke(ex.model_invocation())
    assert not path.exists()


def test_a_failed_write_is_logged_without_content_and_not_raised(tmp_path, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    client = RecordingModelClient(_Live(), blocker / "sub" / "x.jsonl")
    with caplog.at_level(logging.ERROR):
        result = client.invoke(ex.model_invocation())
    assert result.text  # the answer still comes back
    assert "recording failed" in caplog.text
    assert ex.MARKER not in caplog.text
