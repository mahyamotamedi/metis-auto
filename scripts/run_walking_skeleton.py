"""Run the walking skeleton: synthetic requests through the real pipeline,
offline, with fakes. Prints content-free metadata only.

    python scripts/run_walking_skeleton.py [--events runs/walking_skeleton/events.jsonl]

Settings: config/defaults.toml + config/profiles/walking_skeleton.toml, then
config/local.toml, .env, and METIS__* overrides (ADR-0019). The fingerprint
key is METIS_FINGERPRINT_KEY when set; otherwise a fresh random key per run,
so fingerprints are not comparable across runs (A-44). No secrets needed.
Thin wrapper: all logic is in metis_auto.wiring.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from metis_auto.adapters.sinks import InMemoryEventSink, JsonLinesEventSink
from metis_auto.wiring.from_settings import fingerprint_key, pipeline_config
from metis_auto.wiring.walking_skeleton import (
    build_walking_skeleton,
    demo_requests,
    skeleton_settings,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=Path, help="write events as JSON Lines")
    args = parser.parse_args()

    loaded = skeleton_settings(hermetic=False)
    logging.basicConfig(level=loaded.settings.logging.level)
    print(json.dumps({"config_hash": loaded.config_hash, "layers": loaded.layers}))

    sink = JsonLinesEventSink(args.events) if args.events else InMemoryEventSink()
    pipeline = build_walking_skeleton(
        fingerprint_key(loaded),
        config=pipeline_config(loaded),
        sink=sink,
        config_hash=loaded.config_hash,
    )
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
