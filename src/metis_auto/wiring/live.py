"""Live model client factory (CMP-20; ADR-0018, ADR-0021, Stage 7.5).

Responsibility: build the one live ``ModelClient`` stack, recording(live), from
settings, after ``live_permission`` allows it: the OpenAI-compatible adapter
gets one route per enabled endpoint (base URL and generation-limit field from
``config/reference/endpoints-*.toml``) and the API key, which leaves the
secret holder only here. The recording decorator appends every live result to
``paths.recorded_dir``. The spend guard and the persistent ledger are added
by ``build_pipeline_from_settings`` for any live client.

The adapter needs the optional extra ``live`` (``openai``); it is imported only
when a live client is actually built, so offline runs never need it. An
enabled ``google_genai`` endpoint (none is: Gemini is "deferred") adds the
Gemini native adapter (standard library only) behind a per-model dispatching
client, with each model's ``thinking_budget`` (ADR-XXXX
(gemini-native-adapter)).
Called by: scripts (``live_wrapper_check.py``, ``chat.py``), ``wiring.chat``,
tests. Calls: settings, wiring.from_settings, adapters.providers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from metis_auto.adapters.providers import ModelDispatchClient, RecordingModelClient
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
    model_options: dict[str, dict[str, Any]] | None = None,
    gemini_transport: Callable[[Any], Any] | None = None,
) -> ModelClient:
    """recording(OpenAI-compatible live client), or recording(dispatch) over
    it and the Gemini native client when a ``google_genai`` endpoint is
    enabled. Refuses, listing every reason, unless ``live_permission`` allows
    live calls. ``model_options`` replaces ``[model_options]`` for the
    OpenAI-compatible client (a task that sets its own request options,
    already checked by ``request_options``). ``gemini_transport`` exists for
    tests (fake HTTP); production uses the adapter's urllib transport."""
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
    client: ModelClient = OpenAICompatibleClient(
        api_key=api_key.get_secret_value(),
        catalogue=loaded.reference.catalogue,
        endpoints=routes,
        http_client_factory=http_client_factory,
        request_options=model_options
        if model_options is not None
        else request_options(loaded),
    )
    gemini_routes = {
        e.family: e.base_url
        for e in endpoints.endpoints
        if e.status == EndpointStatus.ENABLED and e.api_format == ApiFormat.GOOGLE_GENAI
    }
    if gemini_routes:
        # Imported only when a Gemini endpoint is enabled (none is: the row
        # is "deferred" until an owner-approved live check).
        from metis_auto.adapters.providers.gemini_native import GeminiNativeClient

        gemini = GeminiNativeClient(
            api_key=api_key.get_secret_value(),
            catalogue=loaded.reference.catalogue,
            routes=gemini_routes,
            thinking_budgets=thinking_budgets(loaded),
            transport=gemini_transport,
        )
        by_model: dict[str, ModelClient] = {
            e.model_id: client
            for e in loaded.reference.catalogue.entries
            if e.provider in routes
        }
        by_model |= dict.fromkeys(gemini.model_ids, gemini)
        client = ModelDispatchClient(by_model)
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
        if endpoint is not None and endpoint.api_format == ApiFormat.GOOGLE_GENAI:
            allowed.add("thinking_budget")  # the native adapter's own field
        body: dict[str, Any] = {}
        for name, value in options.model_dump(mode="json", exclude_none=True).items():
            if name not in allowed:
                raise SettingsError(
                    f"model_options.{model_id}.{name}: not supported by the "
                    f"{entry.provider!r} endpoint"
                )
            if name == "thinking":
                body["thinking"] = {"type": value}
            elif name == "reasoning_effort":
                body["reasoning_effort"] = value
            # thinking_budget: not a body field here; see ``thinking_budgets``.
        if body:
            built[model_id] = body
    return built


def thinking_budgets(loaded: LoadedSettings) -> dict[str, int]:
    """``[model_options] thinking_budget`` per model, for the Gemini native
    adapter, after the same checks as ``request_options``. A Gemini model
    without one is refused by the adapter (ADR-XXXX (gemini-native-adapter))."""
    request_options(loaded)
    return {
        model_id: options.thinking_budget
        for model_id, options in loaded.settings.model_options.items()
        if options.thinking_budget is not None
    }
