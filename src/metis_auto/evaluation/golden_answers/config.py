"""The run settings, validated (pure). Everything that changes an answer is here
and in the settings hash, so two runs with the same hash used the same settings."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from metis_auto.evaluation.golden_answers.request import LAYOUT_VERSION

RETRYABLE = frozenset({"timeout", "rate_limited", "unavailable", "connection"})
"""Error classes worth another attempt. Content filter, context overflow, invalid
request (including an unknown model, HTTP 404) and auth are recorded, not retried."""


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class AnswerSettings:
    dataset_id: str
    model_id: str
    reasoning_effort: str | None
    max_output_tokens: int
    context_window: int
    model_output_limit: int
    retry_max_attempts: int
    backoff_seconds: tuple[float, ...]
    pilot_size: int
    limits_source: str
    limits_checked_on: str

    @property
    def settings_hash(self) -> str:
        """Over the values that shape a request or its handling; not over the
        pilot size, which only chooses which records go first."""
        payload = {
            "model_id": self.model_id,
            "reasoning_effort": self.reasoning_effort,
            "max_output_tokens": self.max_output_tokens,
            "retry_max_attempts": self.retry_max_attempts,
            "backoff_seconds": list(self.backoff_seconds),
            "layout": LAYOUT_VERSION,
            "dataset_id": self.dataset_id,
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode()).hexdigest()

    def manifest(self) -> dict[str, Any]:
        """Content-free description of the settings, for the run manifest."""
        return {
            "dataset_id": self.dataset_id,
            "model_id": self.model_id,
            "reasoning_effort": self.reasoning_effort,
            "max_output_tokens": self.max_output_tokens,
            "context_window": self.context_window,
            "model_output_limit": self.model_output_limit,
            "limits_source": self.limits_source,
            "limits_checked_on": self.limits_checked_on,
            "retry_max_attempts": self.retry_max_attempts,
            "backoff_seconds": list(self.backoff_seconds),
            "pilot_size": self.pilot_size,
            "layout": LAYOUT_VERSION,
            "settings_hash": self.settings_hash,
        }


def parse_settings(raw: Mapping[str, Any]) -> AnswerSettings:
    run, limits, retry = raw["run"], raw["model_limits"], raw["retry"]
    out = AnswerSettings(
        dataset_id=run["dataset_id"],
        model_id=run["model_id"],
        reasoning_effort=run.get("reasoning_effort"),
        max_output_tokens=run["max_output_tokens"],
        context_window=limits["context_window"],
        model_output_limit=limits["max_output_tokens"],
        retry_max_attempts=retry["max_attempts"],
        backoff_seconds=tuple(float(x) for x in retry["backoff_seconds"]),
        pilot_size=raw["pilot"]["size"],
        limits_source=limits["source"],
        limits_checked_on=str(limits["checked_on"]),
    )
    if not 0 < out.max_output_tokens <= out.model_output_limit:
        raise SettingsError("max_output_tokens must be within the model's output limit")
    if out.max_output_tokens >= out.context_window:
        raise SettingsError("max_output_tokens must be below the context window")
    if out.retry_max_attempts < 1:
        raise SettingsError("retry.max_attempts must be at least 1")
    if len(out.backoff_seconds) < out.retry_max_attempts - 1:
        raise SettingsError("retry.backoff_seconds needs one wait per retry")
    if out.pilot_size < 1:
        raise SettingsError("pilot.size must be at least 1")
    return out
