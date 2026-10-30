"""Settings loader (CMP-19; configuration.md, ADR-0019).

Responsibility: read the configuration layers, merge them by precedence,
enforce which layer may set what, read secrets, load reference data, and
compute the config hash. Returns a frozen ``LoadedSettings``.

Precedence, lowest first (ADR-0019):
1. policy code defaults (each policy's typed config in ``domain``; applied by
   wiring, not here);
2. ``config/defaults.toml`` (versioned application defaults);
3. an experiment file (optional; ``experiments/<area>/<EXP-ID>/config.toml``);
4. a runtime file (untracked; ``METIS_RUNTIME_CONFIG`` or ``config/local.toml``);
5. environment overrides ``METIS__<SECTION>__<KEY>=value`` (process environment
   first, then ``.env``);
6. explicit overrides passed by the caller (``{"budget.run_cap": "0.5"}``).

Secrets come only from the environment or ``.env`` (``METIS_API_KEY``,
``METIS_FINGERPRINT_KEY``, ``METIS_DB_PASSWORD``), never from a TOML file.
Called by: scripts, wiring, tests. Calls: settings.reference.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import SecretBytes, SecretStr

from .model import HASH_EXCLUDED_SECTIONS, LoadedSettings, Secrets, Settings
from .reference import load_reference

CONFIG_DIR_ENV = "METIS_CONFIG_DIR"
RUNTIME_CONFIG_ENV = "METIS_RUNTIME_CONFIG"
OVERRIDE_PREFIX = "METIS__"
SECRET_ENV = {
    "metis_api_key": "METIS_API_KEY",
    "fingerprint_key": "METIS_FINGERPRINT_KEY",
    "database_password": "METIS_DB_PASSWORD",
}
MIN_FINGERPRINT_KEY_BYTES = 32  # ADR-0015 amendment 1

DEFAULTS_ONLY = {("budget", "lifetime_ceiling")}
"""Keys only ``config/defaults.toml`` may set: raising them is a reviewed
commit plus a decision record, never a local edit (ADR-0018)."""
NOT_IN_EXPERIMENT = ("live", "budget", "paths", "dev")
"""Sections an experiment file may not set: the runtime decides what this
machine allows (configuration.md §3 rules 1 and 2)."""
SECRET_NAMES = {"api_key", "password", "secret", "fingerprint_key", "token"}
SECRET_SUFFIXES = ("_api_key", "_password", "_secret")
"""Leaf key names refused in every settings layer: secrets never go in files
or overrides (configuration.md §3 rule 7)."""

_AUTO: Any = object()


class SettingsError(ValueError):
    """A configuration error: names the layer and key, never a secret value."""


def repo_root() -> Path:
    """The checkout root (``src/metis_auto/settings/loader.py`` → four up).
    Only meaningful for an editable install; images set ``METIS_CONFIG_DIR``."""
    return Path(__file__).resolve().parents[3]


def default_config_dir(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    if env.get(CONFIG_DIR_ENV):
        return Path(env[CONFIG_DIR_ENV])
    return repo_root() / "config"


def load_settings(
    *,
    experiment: Path | str | None = None,
    runtime: Path | str | None = _AUTO,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    dotenv: Path | str | None = _AUTO,
    config_dir: Path | str | None = None,
) -> LoadedSettings:
    """Load, merge, and validate every layer.

    ``environ`` defaults to ``os.environ``; ``dotenv`` and ``runtime`` default
    to ``<repo>/.env`` and ``METIS_RUNTIME_CONFIG`` or ``config/local.toml`` when
    present. Pass ``environ={}, dotenv=None, runtime=None`` for a hermetic
    load (tests, the walking skeleton's fixed configuration).
    """
    process_env = dict(os.environ if environ is None else environ)
    cfg_dir = Path(config_dir) if config_dir else default_config_dir(process_env)
    root = cfg_dir.parent

    dotenv_path = root / ".env" if dotenv is _AUTO else dotenv
    file_env = read_dotenv(Path(dotenv_path)) if dotenv_path else {}
    env = {**file_env, **process_env}  # the process environment wins

    layers: list[tuple[str, dict[str, Any]]] = []
    defaults_path = cfg_dir / "defaults.toml"
    layers.append((f"defaults:{_rel(defaults_path, root)}", _read_toml(defaults_path)))
    if experiment is not None:
        path = Path(experiment)
        layers.append((f"experiment:{_rel(path, root)}", _read_toml(path)))
    runtime_path = _runtime_path(runtime, env, cfg_dir)
    if runtime_path is not None:
        layers.append((f"runtime:{_rel(runtime_path, root)}", _read_toml(runtime_path)))
    env_layer = _env_overrides(env)
    if env_layer:
        layers.append(("env", env_layer))
    if overrides:
        layers.append(("overrides", _dotted_to_nested(overrides)))

    merged: dict[str, Any] = {}
    for name, data in layers:
        _check_layer(name, data)
        merged = _deep_merge(merged, data)
    try:
        settings = Settings.model_validate(merged)
    except ValueError as exc:
        raise SettingsError(f"invalid settings: {exc}") from None

    reference = load_reference(cfg_dir, settings.reference)
    return LoadedSettings(
        settings=settings,
        secrets=read_secrets(env),
        reference=reference,
        config_hash=config_hash(settings, reference.versions()),
        layers=tuple(name for name, _ in layers),
        root=root,
    )


def config_hash(settings: Settings, reference_versions: Mapping[str, str]) -> str:
    """``cfg1:`` + 16 hex of SHA-256 over canonical JSON of the non-secret,
    non-local settings plus the reference version IDs (configuration.md §3
    rule 6). Settings hold no content, so a plain hash is enough (ADR-0015
    covers content only). Secrets are not part of ``Settings`` at all."""
    payload = {
        "settings": settings.model_dump(
            mode="json", exclude=set(HASH_EXCLUDED_SECTIONS)
        ),
        "reference_versions": dict(reference_versions),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "cfg1:" + hashlib.sha256(canonical.encode()).hexdigest()[:16]


def read_secrets(env: Mapping[str, str]) -> Secrets:
    """Secrets from the merged environment. An empty value means unset.
    Error messages never include a value."""
    values: dict[str, Any] = {}
    for name, var in SECRET_ENV.items():
        raw = env.get(var, "").strip()
        if not raw:
            continue
        if name == "fingerprint_key":
            try:
                key = bytes.fromhex(raw)
            except ValueError:
                raise SettingsError(f"{var} must be hex-encoded") from None
            if len(key) < MIN_FINGERPRINT_KEY_BYTES:
                raise SettingsError(
                    f"{var} must be at least {MIN_FINGERPRINT_KEY_BYTES} bytes "
                    f"({2 * MIN_FINGERPRINT_KEY_BYTES} hex characters)"
                )
            values[name] = SecretBytes(key)
        else:
            values[name] = SecretStr(raw)
    return Secrets(**values)


def read_dotenv(path: Path) -> dict[str, str]:
    """Minimal ``.env`` reader: ``KEY=value`` lines, ``#`` comments, optional
    ``export``, optional matching quotes, ``value  # comment`` when unquoted.
    A missing file is empty. No interpolation."""
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key.replace("_", "").isalnum():
            raise SettingsError(f"{path.name} line {number}: expected KEY=value")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        found[key] = value
    return found


def _runtime_path(
    runtime: Path | str | None, env: Mapping[str, str], cfg_dir: Path
) -> Path | None:
    if runtime is not _AUTO:
        return Path(runtime) if runtime else None
    if env.get(RUNTIME_CONFIG_ENV):
        return Path(env[RUNTIME_CONFIG_ENV])
    local = cfg_dir / "local.toml"
    return local if local.is_file() else None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        raise SettingsError(f"config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{path}: {exc}") from None


def _parse_env_value(raw: str) -> Any:
    """A TOML literal when it parses (``true``, ``1.5``, ``[0.5, 0.8]``,
    ``"text"``), otherwise the raw string."""
    try:
        return tomllib.loads(f"v = {raw}")["v"]
    except tomllib.TOMLDecodeError:
        return raw


def _env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
    flat = {
        ".".join(key[len(OVERRIDE_PREFIX) :].lower().split("__")): _parse_env_value(v)
        for key, v in env.items()
        if key.startswith(OVERRIDE_PREFIX) and len(key) > len(OVERRIDE_PREFIX)
    }
    return _dotted_to_nested(flat)


def _dotted_to_nested(flat: Mapping[str, Any]) -> dict[str, Any]:
    nested: dict[str, Any] = {}
    for dotted, value in flat.items():
        parts = [p for p in dotted.split(".") if p]
        if not parts:
            raise SettingsError(f"empty override key: {dotted!r}")
        node = nested
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise SettingsError(f"override {dotted!r} conflicts with another")
        node[parts[-1]] = value
    return nested


def _leaf_paths(data: Mapping[str, Any], prefix: tuple[str, ...] = ()):
    for key, value in data.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping) and value:
            yield from _leaf_paths(value, path)
        else:
            yield path


def _check_layer(name: str, data: Mapping[str, Any]) -> None:
    kind = name.split(":", 1)[0]
    for path in _leaf_paths(data):
        dotted = ".".join(path)
        leaf = path[-1].lower()
        if leaf in SECRET_NAMES or leaf.endswith(SECRET_SUFFIXES):
            raise SettingsError(
                f"{name}: {dotted!r} looks like a secret; secrets come only from "
                "the environment or .env"
            )
        if kind != "defaults" and path[:2] in DEFAULTS_ONLY:
            raise SettingsError(f"{name}: {dotted!r} may be set only in defaults.toml")
        if kind != "experiment" and path[:2] == ("experiment", "strategy"):
            raise SettingsError(
                f"{name}: {dotted!r} may be set only in an experiment file "
                "(candidate code never loads from defaults or runtime layers)"
            )
        if kind == "experiment" and path[0] in NOT_IN_EXPERIMENT:
            raise SettingsError(
                f"{name}: an experiment may not set {path[0]!r} (runtime decides)"
            )


def _deep_merge(base: dict[str, Any], top: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in top.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()
