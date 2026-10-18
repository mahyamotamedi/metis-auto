"""Run the walking skeleton: synthetic requests through the real pipeline,
offline, with fakes. Prints content-free metadata only.

    python scripts/run_walking_skeleton.py [--events runs/walking_skeleton/events.jsonl]

The fingerprint key is a fresh random key per run, so fingerprints are not
comparable across runs. TODO(Stage 6): read it from the environment through
settings (ADR-0015). Thin wrapper: all logic is in metis_auto.wiring.
"""

from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

from metis_auto.adapters.sinks import InMemoryEventSink, JsonLinesEventSink
from metis_auto.wiring.walking_skeleton import build_walking_skeleton, demo_requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=Path, help="write events as JSON Lines")
    args = parser.parse_args()

    sink = JsonLinesEventSink(args.events) if args.events else InMemoryEventSink()
    pipeline = build_walking_skeleton(secrets.token_bytes(32), sink=sink)
    for request in demo_requests():
        response = pipeline.handle(request)
        print(
            response.metadata.model_dump_json(
                include={
                    "request_id",
                    "served_by",
                    "final_model_id",
                    "cache_tier",
                    "attempt_ids",
                    "failure",
                }
            ),
            json.dumps(
                {"status": response.status, "cost": response.metadata.total_cost.status}
            ),
        )
    sink.close()


if __name__ == "__main__":
    main()
