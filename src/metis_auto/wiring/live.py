"""Live model client factory (CMP-20; ADR-0018, ADR-0021, Stage 7.5).

Responsibility: build the one live ``ModelClient`` stack, recording(live), from
settings, after ``live_permission`` allows it: the OpenAI-compatible adapter
gets one route per enabled endpoint (base URL and generation-limit field from
``config/reference/endpoints-*.toml``) and the API key, which leaves the
secret holder only here. The recording decorator appends every live result to
``paths.recorded_dir``. The spend guard and the persistent ledger are added
by ``build_pipeline_from_settings`` for any live client.

The adapter needs the optional extra ``live`` (``openai``); it is imported only
when a live client is actually built, so offline runs never need it.
Called by: scripts (``live_wrapper_check.py``, ``chat.py``), ``wiring.chat``,
tests. Calls: settings, wiring.from_settings, adapters.providers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from metis_auto.adapters.providers import RecordingModelClient
from metis_auto.ports import ModelClient
from metis_auto.settings import (
    ApiFormat,
    EndpointStatus,
    LoadedSettings,
    SettingsError,
)

from .from_settings import live_permission


def live_overrides(
    model_id: str | None = None,
    *,
    allow_unknown_window: bool = False,
    single_attempt: bool = False,
) -> dict[str, Any]:
    """Caller overrides (layer 6) for a live run: the experiment's key
    (``counterfactual_source = live``), and optionally a fixed target model,
    the diagnostic unknown-window switch, and one attempt per request. The
    runtime's key (``live.enabled``) can only come from ``config/local.toml``
    or the environment."""
    overrides: dict[str, Any] = {"experiment.counterfactual_source": "live"}
    if model_id is not None:
        overrides["pipeline.routing.policy"] = "fixed_model"
        overrides["pipeline.routing.fixed_model.model_id"] = model_id
    if allow_unknown_window:
        overrides["pipeline.routing.eligibility.allow_unknown_context_window"] = True
    if single_attempt:
        overrides["pipeline.attempts.max_attempts"] = 1
    return overrides


def build_live_client(
    loaded: LoadedSettings,
    run_id: str,
    *,
    http_client_factory: Callable[[], Any] | None = None,
) -> ModelClient:
    """recording(OpenAI-compatible live client). Refuses, listing every
    reason, unless ``live_permission`` allows live calls."""
    permission = live_permission(loaded)
    if not permission.allowed:
        raise SettingsError("live calls refused: " + "; ".join(permission.reasons))
    endpoints = loaded.reference.endpoints
    if endpoints is None:
        raise SettingsError("live calls need [reference] endpoints")
    try:
        from metis_auto.adapters.providers.openai_compat import (
            EndpointRoute,
            OpenAICompatibleClient,
        )
    except ImportError:
        raise SettingsError(
            "live calls need the optional extra 'live' (the openai package): "
            "pip install -e '.[live]' or the dev lock"
        ) from None
    routes = {
        e.family: EndpointRoute(
            family=e.family,
            base_url=e.base_url,
            max_tokens_param=e.max_tokens_param.value,
        )
        for e in endpoints.endpoints
        if e.status == EndpointStatus.ENABLED
        and e.api_format == ApiFormat.OPENAI_CHAT_COMPLETIONS
        and e.max_tokens_param is not None
    }
    api_key = loaded.secrets.metis_api_key
    assert api_key is not None  # live_permission checked it
    client = OpenAICompatibleClient(
        api_key=api_key.get_secret_value(),
        catalogue=loaded.reference.catalogue,
        endpoints=routes,
        http_client_factory=http_client_factory,
        request_options=request_options(loaded),
    )
    path = loaded.path(loaded.settings.paths.recorded_dir) / f"live-{run_id}.jsonl"
    return RecordingModelClient(client, path, run_id=run_id)


def request_options(loaded: LoadedSettings) -> dict[str, dict[str, Any]]:
    """``[model_options]`` → extra request-body fields per model. Each model
    must be in the catalogue, and each option allowed by its family's
    endpoint (``request_options`` in ``endpoints-*.toml``)."""
    entries = {e.model_id: e for e in loaded.reference.catalogue.entries}
    endpoints = loaded.reference.endpoints
    built: dict[str, dict[str, Any]] = {}
    for model_id, options in loaded.settings.model_options.items():
        entry = entries.get(model_id)
        if entry is None:
            raise SettingsError(f"model_options: unknown model {model_id!r}")
        endpoint = endpoints.get(entry.provider) if endpoints else None
        allowed = set(endpoint.request_options) if endpoint else set()
        body: dict[str, Any] = {}
        for name, value in options.model_dump(mode="json", exclude_none=True).items():
            if name not in allowed:
                raise SettingsError(
                    f"model_options.{model_id}.{name}: not supported by the "
                    f"{entry.provider!r} endpoint"
                )
            if name == "thinking":
                body["thinking"] = {"type": value}
        if body:
            built[model_id] = body
    return built
