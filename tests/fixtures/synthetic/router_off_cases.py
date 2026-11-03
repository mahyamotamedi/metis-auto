"""SYNTHETIC cases for the router-off regression test
(ADR-XXXX (system-one-decision-router) point 12, R4).

``run_cases`` drives the real pipeline, built from the committed defaults with
fakes only, through a fixed set of SYNTHETIC requests under several routing
policies, and returns one sha256 per policy over every event and response, as
canonical JSON bytes. ``router_off_golden.json`` holds the digests captured
from the code **before** the decision-router cascade existed (R3 state); the
test re-runs the cases on the current code with ``router.mode = "off"`` and
requires identical bytes.

Regenerate the golden file only on purpose, when a change outside the router
legitimately alters events (``python tests/fixtures/synthetic/router_off_cases.py``),
and say so in progress.md.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from metis_auto.adapters.providers import FakeModelClient
from metis_auto.adapters.sinks import InMemoryEventSink
from metis_auto.adapters.stores import InMemoryCacheStore
from metis_auto.adapters.system import FakeClock, SequentialIdSource
from metis_auto.contracts import (
    AttachmentRef,
    Component,
    Modality,
    Request,
    Role,
    RunMode,
    Turn,
)

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "router_off_golden.json"
SYNTHETIC = "[SYNTHETIC]"
POLICIES = ("fixed_model", "rule_based", "sticky", "decision_router")
KEY = b"SYNTHETIC-TEST-KEY--metis-auto--not-a-secret--0001"


def requests() -> tuple[Request, ...]:
    """Greeting, Persian question, code, long message, attachment, follow-ups,
    an unknown component, and an exact repeat (cache hit)."""
    first = Request(
        message=f"{SYNTHETIC} سلام",
        history=Component.absent(),
        instructions=Component.present(f"{SYNTHETIC} You answer shop questions."),
        retrieved=Component.absent(),
        attachments=Component.absent(),
        structured_input=Component.absent(),
        session_ref="sess-off-1",
    )
    question = first.model_copy(
        update={
            "message": f"{SYNTHETIC} ساعت کاری فروشگاه در روزهای تعطیل چیست؟",
            "history": Component.present(
                (
                    Turn(role=Role.USER, text=first.message),
                    Turn(role=Role.ASSISTANT, text=f"{SYNTHETIC} سلام، بفرمایید."),
                )
            ),
        }
    )
    code = first.model_copy(
        update={
            "message": f"{SYNTHETIC} Fix this:\n```python\nprint(1/0)\n```",
            "session_ref": "sess-off-2",
        }
    )
    long = first.model_copy(
        update={
            "message": f"{SYNTHETIC} " + "Please compare the two plans. " * 90,
            "session_ref": "sess-off-3",
        }
    )
    attachment = first.model_copy(
        update={
            "message": f"{SYNTHETIC} What is in this picture?",
            "attachments": Component.present((AttachmentRef(modality=Modality.IMAGE),)),
            "session_ref": "sess-off-4",
        }
    )
    unknown = Request(message=f"{SYNTHETIC} Thanks!", session_ref="sess-off-5")
    short_follow = question.model_copy(
        update={
            "message": f"{SYNTHETIC} ok",
            "history": Component.present(
                (
                    *question.history.value,
                    Turn(role=Role.USER, text=question.message),
                    Turn(role=Role.ASSISTANT, text=f"{SYNTHETIC} ۹ تا ۱۷."),
                )
            ),
        }
    )
    return (first, question, code, long, attachment, unknown, short_follow, question)


def run_policy(policy: str) -> str:
    """sha256 over every event and response of the cases under ``policy``."""
    from metis_auto.settings import load_settings
    from metis_auto.wiring.from_settings import pipeline_config
    from metis_auto.wiring.pipeline import build_pipeline

    loaded = load_settings(
        environ={},
        dotenv=None,
        runtime=None,
        overrides={"pipeline.routing.policy": policy},
    )
    sink = InMemoryEventSink()
    pipeline = build_pipeline(
        pipeline_config(loaded),
        model_client=FakeModelClient(),
        cache_store=InMemoryCacheStore(),
        sink=sink,
        fingerprint_key=KEY,
        run_id="run-router-off",
        run_mode=RunMode.REPLAYED,
        clock=FakeClock(_now(), step_ms=0.5),
        ids=SequentialIdSource("run-router-off"),
    )
    digest = hashlib.sha256()
    for request in requests():
        response = pipeline.handle(request)
        digest.update(response.model_dump_json().encode("utf-8"))
    for event in sink.events:
        digest.update(event.model_dump_json().encode("utf-8"))
    return digest.hexdigest()


def _now():
    from datetime import UTC, datetime

    return datetime(2026, 10, 17, 9, 30, tzinfo=UTC)


def run_cases() -> dict[str, str]:
    return {policy: run_policy(policy) for policy in POLICIES}


if __name__ == "__main__":
    digests = run_cases()
    GOLDEN.write_text(json.dumps(digests, indent=2) + "\n", encoding="utf-8")
    json.dump(digests, sys.stdout, indent=2)
    print()
