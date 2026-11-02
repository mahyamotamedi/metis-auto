"""The per-model dispatching client (one live stack over several adapters)."""

import pytest

from metis_auto.adapters.providers import FakeModelClient, ModelDispatchClient
from metis_auto.contracts import (
    AnswerSource,
    ComponentName,
    InputPart,
    ModelInvocation,
    PartRole,
)
from metis_auto.ports import ModelClient


class Tagged(FakeModelClient):
    def __init__(self, source=AnswerSource.FAKE):
        super().__init__()
        self.seen: list[str] = []
        self._source = source

    @property
    def source(self):
        return self._source

    def invoke(self, invocation):
        self.seen.append(invocation.model_id)
        return super().invoke(invocation)


def _invocation(model_id):
    return ModelInvocation(
        request_id="req-1",
        attempt_id="att-1",
        attempt_kind="primary",
        model_id=model_id,
        parts=(
            InputPart(
                role=PartRole.USER, text="[SYNTHETIC]", component=ComponentName.MESSAGE
            ),
        ),
    )


def test_each_model_goes_to_its_client():
    a, b = Tagged(), Tagged()
    client = ModelDispatchClient({"m-a": a, "m-b": b})
    assert isinstance(client, ModelClient)
    client.invoke(_invocation("m-b"))
    client.invoke(_invocation("m-a"))
    assert (a.seen, b.seen) == (["m-a"], ["m-b"])
    assert client.source == AnswerSource.FAKE


def test_an_unrouted_model_is_a_configuration_error():
    client = ModelDispatchClient({"m-a": Tagged()})
    with pytest.raises(ValueError, match="no client"):
        client.invoke(_invocation("m-x"))


def test_clients_must_share_one_source_and_exist():
    with pytest.raises(ValueError, match="one source"):
        ModelDispatchClient({"m-a": Tagged(), "m-b": Tagged(AnswerSource.LIVE)})
    with pytest.raises(ValueError, match="at least one"):
        ModelDispatchClient({})
