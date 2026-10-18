"""Settings loader: layers, precedence, layer rules, secrets, config hash
(ADR-0019, configuration.md §3). Hermetic: every test passes ``environ`` and
``dotenv`` explicitly and works on a copy of ``config/``. All secret values
are synthetic."""

import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from metis_auto.settings import (
    SettingsError,
    load_settings,
    read_dotenv,
    read_secrets,
    repo_root,
)

SYNTHETIC_API_KEY = "SYNTHETIC-not-a-real-metis-key-0001"
SYNTHETIC_FP_HEX = "53594e5448455449432d66696e6765727072696e742d6b65792d2d2d2d303031"


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    """A copy of the repository's config directory, without any local.toml."""
    target = tmp_path / "config"
    shutil.copytree(
        repo_root() / "config", target, ignore=shutil.ignore_patterns("local.toml")
    )
    return target


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def load(cfg: Path, **kwargs):
    kwargs.setdefault("environ", {})
    kwargs.setdefault("dotenv", None)
    kwargs.setdefault("runtime", None)
    return load_settings(config_dir=cfg, **kwargs)


def test_defaults_load_and_record_their_layer(cfg):
    loaded = load(cfg)
    assert loaded.layers == ("defaults:config/defaults.toml",)
    assert loaded.settings.live.enabled is False
    assert loaded.settings.budget.lifetime_cap == Decimal("20")
    assert loaded.settings.budget.run_cap == Decimal("1")
    assert loaded.config_hash.startswith("cfg1:")
    assert loaded.root == cfg.parent


def test_precedence_defaults_experiment_runtime_env_overrides(cfg, tmp_path):
    exp = write(
        tmp_path / "exp.toml", '[experiment]\nname = "from-experiment"\nseed = 1\n'
    )
    rt = write(
        tmp_path / "rt.toml", '[experiment]\nseed = 2\n[logging]\nlevel = "DEBUG"\n'
    )
    loaded = load(
        cfg,
        experiment=exp,
        runtime=rt,
        environ={"METIS__EXPERIMENT__SEED": "3", "METIS__LOGGING__LEVEL": "WARNING"},
        overrides={"logging.level": "ERROR"},
    )
    s = loaded.settings
    assert s.experiment.name == "from-experiment"  # only the experiment set it
    assert s.experiment.seed == 3  # env beats runtime beats experiment
    assert s.logging.level == "ERROR"  # explicit overrides beat env
    kinds = [layer.split(":")[0] for layer in loaded.layers]
    assert kinds == ["defaults", "experiment", "runtime", "env", "overrides"]


def test_process_environment_beats_dotenv(cfg, tmp_path):
    dotenv = write(tmp_path / ".env", "METIS__EXPERIMENT__SEED=5\n")
    assert load(cfg, dotenv=dotenv).settings.experiment.seed == 5
    loaded = load(cfg, dotenv=dotenv, environ={"METIS__EXPERIMENT__SEED": "6"})
    assert loaded.settings.experiment.seed == 6


def test_runtime_file_found_by_env_var_or_local_toml(cfg, tmp_path):
    write(cfg / "local.toml", "[experiment]\nseed = 11\n")
    found = load_settings(config_dir=cfg, environ={}, dotenv=None)
    assert found.settings.experiment.seed == 11
    other = write(tmp_path / "other.toml", "[experiment]\nseed = 12\n")
    env = {"METIS_RUNTIME_CONFIG": str(other)}
    chosen = load_settings(config_dir=cfg, environ=env, dotenv=None)
    assert chosen.settings.experiment.seed == 12


def test_env_values_are_toml_literals_or_strings(cfg):
    loaded = load(
        cfg,
        environ={
            "METIS__LIVE__ENABLED": "true",
            "METIS__BUDGET__WARN_AT": "[0.25, 0.75]",
            "METIS__BUDGET__RUN_CAP": '"0.5"',
            "METIS__EXPERIMENT__NAME": "plain-text",
        },
    )
    s = loaded.settings
    assert s.live.enabled is True
    assert s.budget.warn_at == (0.25, 0.75)
    assert s.budget.run_cap == Decimal("0.5")
    assert s.experiment.name == "plain-text"


def test_unknown_keys_are_errors(cfg):
    with pytest.raises(SettingsError):
        load(cfg, overrides={"budget.run_capp": "1"})


@pytest.mark.parametrize("cap", ["20.01", "100"])
def test_lifetime_cap_can_never_exceed_the_ceiling(cfg, cap):
    with pytest.raises(SettingsError, match="ceiling"):
        load(cfg, overrides={"budget.lifetime_cap": cap})


def test_ceiling_may_be_set_only_in_defaults(cfg, tmp_path):
    rt = write(tmp_path / "rt.toml", '[budget]\nlifetime_ceiling = "100"\n')
    with pytest.raises(SettingsError, match="only in defaults"):
        load(cfg, runtime=rt)
    with pytest.raises(SettingsError, match="only in defaults"):
        load(cfg, environ={"METIS__BUDGET__LIFETIME_CEILING": '"100"'})


def test_run_cap_may_not_exceed_lifetime_cap(cfg):
    with pytest.raises(SettingsError, match="run_cap"):
        load(cfg, overrides={"budget.lifetime_cap": "2", "budget.run_cap": "3"})


@pytest.mark.parametrize("section", ["live", "budget", "paths", "dev"])
def test_an_experiment_may_not_set_runtime_sections(cfg, tmp_path, section):
    key = {
        "live": "enabled = true",
        "budget": 'run_cap = "0.5"',
        "paths": 'run_dir = "x"',
        "dev": "ephemeral_fingerprint_key = false",
    }
    exp = write(tmp_path / "exp.toml", f"[{section}]\n{key[section]}\n")
    with pytest.raises(SettingsError, match="experiment may not set"):
        load(cfg, experiment=exp)


@pytest.mark.parametrize(
    "key", ["metis_api_key", "password", "fingerprint_key", "db_password"]
)
def test_secret_like_keys_are_refused_in_every_layer(cfg, tmp_path, key):
    rt = write(tmp_path / "rt.toml", f'[database]\n{key} = "x"\n')
    with pytest.raises(SettingsError, match="looks like a secret"):
        load(cfg, runtime=rt)
    with pytest.raises(SettingsError, match="looks like a secret"):
        load(cfg, overrides={f"database.{key}": "x"})


def test_secrets_are_read_from_env_and_hidden(cfg):
    loaded = load(
        cfg,
        environ={
            "METIS_API_KEY": SYNTHETIC_API_KEY,
            "METIS_FINGERPRINT_KEY": SYNTHETIC_FP_HEX,
        },
    )
    assert loaded.secrets.metis_api_key.get_secret_value() == SYNTHETIC_API_KEY
    assert loaded.secrets.fingerprint_key.get_secret_value() == bytes.fromhex(
        SYNTHETIC_FP_HEX
    )
    assert loaded.secrets.presence() == {
        "metis_api_key": True,
        "fingerprint_key": True,
        "database_password": False,
    }
    for text in (
        repr(loaded),
        str(loaded.secrets),
        loaded.secrets.model_dump_json(),
        loaded.settings.model_dump_json(),
    ):
        assert SYNTHETIC_API_KEY not in text
        assert SYNTHETIC_FP_HEX not in text


def test_secrets_never_change_the_config_hash(cfg):
    plain = load(cfg).config_hash
    keyed = load(cfg, environ={"METIS_API_KEY": SYNTHETIC_API_KEY}).config_hash
    assert plain == keyed


def test_config_hash_ignores_locations_but_tracks_behaviour(cfg):
    base = load(cfg).config_hash
    assert load(cfg, overrides={"paths.run_dir": "elsewhere"}).config_hash == base
    assert load(cfg, overrides={"logging.level": "DEBUG"}).config_hash == base
    assert load(cfg, overrides={"experiment.seed": 7}).config_hash != base
    changed = load(cfg, overrides={"pipeline.cache.ttl_seconds": 60}).config_hash
    assert changed != base


def test_empty_api_key_means_unset():
    assert read_secrets({"METIS_API_KEY": "  "}).metis_api_key is None


@pytest.mark.parametrize("value", ["not-hex", "ab" * 31])
def test_bad_fingerprint_key_is_refused_without_echoing_it(value):
    with pytest.raises(SettingsError) as info:
        read_secrets({"METIS_FINGERPRINT_KEY": value})
    assert value not in str(info.value)


def test_dotenv_reader(tmp_path):
    path = write(
        tmp_path / ".env",
        '# comment\n\nA=1\nexport B = two  # trailing\nC="quoted # kept"\nD=\n',
    )
    assert read_dotenv(path) == {"A": "1", "B": "two", "C": "quoted # kept", "D": ""}
    assert read_dotenv(tmp_path / "missing") == {}
    with pytest.raises(SettingsError):
        read_dotenv(write(tmp_path / "bad.env", "no equals sign\n"))


def test_the_repository_env_example_is_placeholders_only():
    values = read_dotenv(repo_root() / ".env.example")
    assert values == {"METIS_API_KEY": ""}  # every other line is commented out
