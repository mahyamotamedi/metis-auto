"""Decision-router settings (ADR-XXXX (system-one-decision-router)): defaults off, chain
validation, runtime-only approvals, loopback-only local servers, and the machine-local
dataset path. Hermetic: works on a copy of ``config/``."""

import shutil
from pathlib import Path, PureWindowsPath

import pytest

from metis_auto.settings import (
    RouterMode,
    RouterSettings,
    SettingsError,
    SystemOneHttpBackendSettings,
    load_settings,
    repo_root,
)


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(
        repo_root() / "config", target, ignore=shutil.ignore_patterns("local.toml")
    )
    return target


def load(cfg: Path, **kwargs):
    kwargs.setdefault("environ", {})
    kwargs.setdefault("dotenv", None)
    kwargs.setdefault("runtime", None)
    return load_settings(config_dir=cfg, **kwargs)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_keep_the_router_off_and_everything_disabled(cfg):
    router = load(cfg).settings.router
    assert router.mode == RouterMode.OFF and router.active_chain() == ()
    assert router.deadline_ms == 60
    assert router.real_data_approved is False and router.allow_unpriced is False
    assert all(not b.enabled for b in router.backends.values())
    assert router.backends["jev_metis"].model == "jev-latest"
    assert router.backends["jev_metis"].price_ref == "metis-jev-latest"
    assert router.backends["mizan_http"].type == "systemone_http"


def test_environment_override_switches_the_mode(cfg):
    env = {
        "METIS__ROUTER__MODE": "local",
        "METIS__ROUTER__BACKENDS__THX01__ENABLED": "true",
    }
    router = load(cfg, environ=env).settings.router
    assert router.mode == RouterMode.LOCAL and router.active_chain() == ("thx01",)


def test_an_active_mode_needs_its_chain_enabled(cfg):
    with pytest.raises(SettingsError, match="not enabled"):
        load(cfg, overrides={"router.mode": "local"})


def test_local_mode_never_uses_a_hosted_backend():
    backends = RouterSettings().backends
    enabled = {k: v.model_copy(update={"enabled": True}) for k, v in backends.items()}
    with pytest.raises(ValueError, match="local backends only"):
        RouterSettings(
            mode="local", backends=enabled, chains={"local": ("thx01", "jev_metis")}
        )
    with pytest.raises(ValueError, match="hosted backends only"):
        RouterSettings(
            mode="hosted", backends=enabled, chains={"hosted": ("jev_metis", "thx01")}
        )
    with pytest.raises(ValueError, match="start with a local"):
        RouterSettings(
            mode="hybrid_local_first",
            backends=enabled,
            chains={"hybrid_local_first": ("jev_metis", "thx01")},
        )
    ok = RouterSettings(mode="hybrid_hosted_first", backends=enabled)
    assert ok.active_chain() == ("jev_metis", "thx01")


@pytest.mark.parametrize(
    "chains",
    [{"local": ("missing",)}, {"local": ("thx01", "thx01")}, {"turbo": ("thx01",)}],
)
def test_chains_name_known_backends_and_modes(chains):
    with pytest.raises(ValueError):
        RouterSettings(chains=chains)


@pytest.mark.parametrize(
    "url", ["https://example.com:8080", "http://192.168.1.5:8080", "ftp://127.0.0.1"]
)
def test_local_systemone_servers_are_loopback_only(url):
    with pytest.raises(ValueError, match="loopback|127.0.0.1"):
        SystemOneHttpBackendSettings(base_url=url)


def test_loopback_urls_are_accepted():
    for url in ("http://127.0.0.1:8080/", "http://localhost:8095", "http://[::1]:80"):
        assert SystemOneHttpBackendSettings(base_url=url).base_url == url.rstrip("/")


@pytest.mark.parametrize("key", ["real_data_approved", "allow_unpriced"])
def test_approvals_are_refused_in_committed_layers(cfg, tmp_path, key):
    defaults = cfg / "defaults.toml"
    text = defaults.read_text(encoding="utf-8")
    write(defaults, text.replace("[router]\n", f"[router]\n{key} = true\n", 1))
    with pytest.raises(SettingsError, match="local.toml"):
        load(cfg)
    shutil.copy(repo_root() / "config" / "defaults.toml", defaults)
    exp = write(tmp_path / "exp.toml", f"[router]\n{key} = false\n")
    with pytest.raises(SettingsError):
        load(cfg, experiment=exp)


@pytest.mark.parametrize("key", ["real_data_approved", "allow_unpriced"])
def test_approvals_are_accepted_from_runtime_layers(cfg, tmp_path, key):
    rt = write(tmp_path / "local.toml", f"[router]\n{key} = true\n")
    assert getattr(load(cfg, runtime=rt).settings.router, key) is True
    env = {f"METIS__ROUTER__{key.upper()}": "true"}
    assert getattr(load(cfg, environ=env).settings.router, key) is True


def test_dataset_root_is_machine_local_and_outside_the_hash(cfg, tmp_path):
    base = load(cfg)
    assert base.settings.data.full_data_root == "data/full_data/raw"
    windows_root = str(PureWindowsPath("C:/Users/someone/Desktop/metis-data"))
    moved = load(cfg, environ={"METIS__DATA__FULL_DATA_ROOT": windows_root})
    assert moved.settings.data.full_data_root == windows_root
    assert moved.config_hash == base.config_hash
    exp = write(tmp_path / "exp.toml", '[data]\nfull_data_root = "elsewhere"\n')
    with pytest.raises(SettingsError):
        load(cfg, experiment=exp)


def test_router_settings_change_the_config_hash(cfg):
    base = load(cfg).config_hash
    other = load(cfg, overrides={"router.deadline_ms": 80}).config_hash
    assert base != other


def test_jev_price_is_the_dated_metis_row_with_output_at_zero(cfg):
    from decimal import Decimal

    loaded = load(cfg)
    table = loaded.reference.router_prices
    assert table.version == "prices-metis-router-2026-11-02"
    amounts = {e.token_type.value: e.amount for e in table.entries}
    assert amounts == {"input": Decimal("0.0462"), "output": Decimal("0")}
    assert all(e.evidence.checked_on.isoformat() == "2026-11-02" for e in table.entries)
    assert all("docs.metisai.ir/pricing" in e.evidence.source for e in table.entries)
    assert loaded.reference.versions()["router_prices"] == table.version


def test_an_unknown_router_price_ref_is_refused(cfg):
    with pytest.raises(SettingsError, match="router price table"):
        load(cfg, overrides={"router.backends.jev_metis.price_ref": "metis-typo"})


def test_a_router_price_without_an_output_row_is_refused(cfg):
    path = cfg / "reference" / "prices-metis-router-2026-11-02.toml"
    text = path.read_text(encoding="utf-8").replace('output = "0.0000"\n', "")
    write(path, text)
    with pytest.raises(Exception, match="lacks"):
        load(cfg)


# --- question sets (ADR-XXXX (system-one-decision-router) point 9) --------------------


def test_routing_question_sets_load_in_both_languages_with_ten_intent_options(cfg):
    from metis_auto.contracts import QuestionLanguage

    table = load(cfg).reference.router_questions
    en = table.get("routing_qs_v1", QuestionLanguage.ENGLISH)
    fa = table.get("routing_qs_v1", QuestionLanguage.PERSIAN)
    assert (
        [q.id for q in en.questions]
        == [q.id for q in fa.questions]
        == [
            "complexity",
            "needs_reasoning",
            "cheap_model_ok",
            "intent",
            "depends_on_history",
        ]
    )
    intent = en.get("intent")
    assert len(intent.options) == 10
    assert "summarisation" not in intent.option_names
    assert "media_request" not in intent.option_names
    assert set(table.intent_mapping) == set(intent.option_names)
    assert "summarization_extraction" in table.intent_mapping["writing"]
    assert "media_generation" in table.intent_mapping["other"]


def _questions_file(cfg: Path) -> Path:
    return cfg / "reference" / "router-questions-v1.toml"


def test_more_than_ten_options_is_refused(cfg):
    path = _questions_file(cfg)
    text = path.read_text(encoding="utf-8")
    extra = '  { name = "eleventh", description = "One too many" },\n]'
    text = text.replace(
        '  { name = "other", description = "Anything else, including image or media '
        'requests" },\n]',
        '  { name = "other", description = "Anything else, including image or media '
        'requests" },\n' + extra,
        1,
    )
    write(path, text)
    with pytest.raises(Exception, match="at most 10"):
        load(cfg)


def test_language_variants_must_match(cfg):
    path = _questions_file(cfg)
    text = path.read_text(encoding="utf-8")
    write(
        path, text.replace('id = "depends_on_history"', 'id = "history_dependent"', 1)
    )
    with pytest.raises(Exception, match="language variants differ"):
        load(cfg)


def test_an_unknown_question_set_is_refused(cfg):
    with pytest.raises(SettingsError, match="no"):
        load(cfg, overrides={"router.question_set": "routing_qs_v9"})


# --- router model assets (ADR-XXXX (system-one-decision-router) point 7, R5) ----------


def test_a_thx01_backend_must_name_a_thx01_asset(cfg):
    assert load(cfg).settings.router.backends["thx01"].asset == "thx01"
    with pytest.raises(SettingsError, match="not a thx01 row"):
        load(cfg, overrides={"router.backends.thx01.asset": "mizan-1.5-4b-q4-k-m"})
    with pytest.raises(SettingsError, match="not a thx01 row"):
        load(cfg, overrides={"router.backends.thx01.asset": "missing"})


def test_the_router_asset_table_is_versioned_with_the_reference_data(cfg):
    loaded = load(cfg)
    assert loaded.reference.versions()["routers"] == loaded.reference.routers.version
    assert loaded.settings.paths.router_assets == "data/routers"


def test_the_gate_reads_the_mapping_questions_by_default(cfg):
    """Q-61 (owner, 2026-11-03): the confidence gate reads complexity,
    needs_reasoning and cheap_model_ok, not the 10-option intent question."""
    from metis_auto.domain.routing import DecisionRouterConfig
    from metis_auto.wiring.routers import cascade_config

    loaded = load(cfg)
    router = loaded.settings.router
    assert router.confidence_questions == "mapping"
    config = cascade_config(router, DecisionRouterConfig())
    assert config.confidence_questions == (
        "complexity",
        "needs_reasoning",
        "cheap_model_ok",
    )
    every = router.model_copy(update={"confidence_questions": "all"})
    assert cascade_config(every, DecisionRouterConfig()).confidence_questions is None


def test_jev_posts_to_the_typesafe_wrapper_over_https_only(cfg):
    from metis_auto.settings import JevMetisBackendSettings

    jev = load(cfg).settings.router.backends["jev_metis"]
    assert jev.base_url == "https://api.metisai.ir/typesafe"
    with pytest.raises(ValueError, match="https"):
        JevMetisBackendSettings(base_url="http://api.metisai.ir/typesafe")
