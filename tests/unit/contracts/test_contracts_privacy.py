"""Privacy classes on contracts (QA-PRIV, FR-OBS-02, ADR-0012 point 3).

Two kinds of check:
- static: walk the declared types; records that leave the content boundary
  have no CONTENT field anywhere inside them;
- dynamic: serialise the synthetic examples of those records and look for the
  marker every piece of synthetic content carries.
"""

import importlib
import pkgutil

import pytest
from fixtures.synthetic.contract_examples import MARKER, all_examples
from pydantic import BaseModel

import metis_auto.contracts as contracts
from metis_auto.contracts import (
    PAYLOAD_TYPES,
    AccountedUsage,
    AttemptState,
    CacheEntry,
    CacheKeyDraft,
    CacheLookupResult,
    ChatTemplate,
    CompositionRecord,
    ContractModel,
    EvaluationResult,
    Event,
    Privacy,
    Request,
    RequestFeatures,
    ResponseMetadata,
    RoutingDecision,
    RunManifest,
    SavingsDecomposition,
)
from metis_auto.contracts._base import field
from metis_auto.contracts.privacy import content_paths, unclassified_fields


def _all_contract_models() -> list[type[BaseModel]]:
    for info in pkgutil.iter_modules(contracts.__path__):
        importlib.import_module(f"{contracts.__name__}.{info.name}")
    found, todo = [], [ContractModel]
    while todo:
        cls = todo.pop()
        for sub in cls.__subclasses__():
            todo.append(sub)
            # Parametrised generics (Component[str]) share the origin's fields.
            is_origin = sub.__pydantic_generic_metadata__["origin"] is None
            if is_origin and sub.__module__.startswith(contracts.__name__):
                found.append(sub)
    return found


MODELS = _all_contract_models()

# Records that leave the content boundary: events and everything run records,
# reports, and logs are built from (request_lifecycle.md §4).
CONTENT_FREE = [
    Event,
    *PAYLOAD_TYPES,
    RunManifest,
    EvaluationResult,
    ResponseMetadata,
    RoutingDecision,
    CacheLookupResult,
    CompositionRecord,
    AttemptState,
    RequestFeatures,
    CacheKeyDraft,
    AccountedUsage,
    SavingsDecomposition,
    ChatTemplate,
]


def test_contract_discovery_finds_the_package():
    assert len(MODELS) > 50
    assert Request in MODELS and Event in MODELS


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_field_declares_a_privacy_class(model):
    assert unclassified_fields(model) == []


@pytest.mark.parametrize("model", CONTENT_FREE, ids=lambda m: m.__name__)
def test_records_leaving_the_boundary_have_no_content_fields(model):
    assert content_paths(model) == []


def test_content_bearing_contracts_are_detected():
    # Sanity: the walker sees content where it must exist.
    request_paths = set(content_paths(Request))
    assert {"message", "history", "instructions", "retrieved"} <= request_paths
    assert {"answer", "embedding"} <= set(content_paths(CacheEntry))


def test_inherit_resolves_to_the_enclosing_class():
    # Request.traffic_source is DERIVED, so its Component.value is not content.
    assert "traffic_source" not in content_paths(Request)
    assert "traffic_source.value" not in content_paths(Request)


def test_checker_catches_content_hidden_in_a_payload():
    class Leaky(ContractModel):
        note: str = field(Privacy.CONTENT, "Synthetic leak.")

    class Payload(ContractModel):
        inner: Leaky = field(Privacy.DERIVED, "Looks harmless.")

    assert content_paths(Payload) == ["inner.note"]


def test_checker_catches_an_unclassified_field():
    class Sloppy(ContractModel):
        x: int

    assert unclassified_fields(Sloppy) == ["Sloppy.x"]


CONTENT_FREE_EXAMPLES = {
    name: ex for name, ex in all_examples().items() if type(ex) in CONTENT_FREE
}


@pytest.mark.parametrize("name", sorted(CONTENT_FREE_EXAMPLES))
def test_serialised_records_carry_no_synthetic_content(name):
    dumped = CONTENT_FREE_EXAMPLES[name].model_dump_json()
    assert MARKER not in dumped


def test_marker_check_would_see_content():
    # The dynamic check is meaningful: content-bearing examples do contain it.
    assert MARKER in all_examples()["request"].model_dump_json()
    assert len(CONTENT_FREE_EXAMPLES) >= len(PAYLOAD_TYPES)
