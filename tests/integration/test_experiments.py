"""Experiment framework end to end (Stage 8 exit criterion), offline, SYNTHETIC.

A cache strategy and a routing candidate are each added with one interface
and one config entry, and their results come out in the same comparison
format. Events, results, extras, and manifests hold no content.
"""

import pytest
from fixtures.synthetic import sample_shaped

from metis_auto.contracts import (
    EvaluationResult,
    Event,
    MetricName,
    MetricState,
    RunManifest,
)
from metis_auto.evaluation.runner import markdown, rows
from metis_auto.settings import SettingsError, load_settings
from metis_auto.wiring.experiments import ExperimentError, prepare

CACHE = """
[experiment]
id = "exp-cache-900"
kind = "cache_candidates"
counterfactual_source = "logged_match"
metrics = ["candidate_hit_rate", "hit_correctness", "judge_score"]
[experiment.data]
missing_key = "absent"
[experiment.strategy]
slot = "candidate_index"
builtin = "exact"
[experiment.strategy.params]
bases = ["msg_only", "full"]
message_treatments = ["literal", "nfkc_casefold_ws"]
"""

ROUTE = """
[experiment]
id = "exp-route-900"
kind = "pipeline_replay"
counterfactual_source = "{source}"
[experiment.data]
missing_key = "absent"
[experiment.strategy]
slot = "routing_policy"
file = "candidate.py"
object = "FirstEligible"
version = "0.1"
"""

CANDIDATE = '''
"""A SYNTHETIC test candidate: the first eligible model, by catalogue order."""
from metis_auto.contracts import PolicyRef
from metis_auto.domain.routing.base import PolicyChoice


class FirstEligible:
    def __init__(self, params):
        self.params = params

    @property
    def ref(self):
        return PolicyRef(name="first_eligible", version="0.1")

    def choose(self, features, eligible):
        return PolicyChoice(reason_code="first_eligible", model_id=eligible[0].model_id)
'''


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "experiments"
    (root / "caching" / "exp-cache-900-t").mkdir(parents=True)
    (root / "routing" / "exp-route-900-t").mkdir(parents=True)
    data = sample_shaped.write(tmp_path / "sample.json")
    return tmp_path, root, data


def run(config, root, data, tmp_path, **kw):
    prepared = prepare(
        config,
        environ={},
        dotenv=None,
        runtime=None,
        experiments_root=root,
        run_root=tmp_path / "runs",
        data_path=data,
        **kw,
    )
    try:
        out = prepared.runner.run(prepared.cases.cases, prepared.cases.exclusions)
    finally:
        prepared.sink.close()
    manifest = RunManifest.model_validate_json(
        (out.run_dir / "manifest.json").read_text()
    )
    return out, manifest


def overall(result: EvaluationResult):
    return {
        (m.name, m.key_variant, m.scope, m.baseline): m
        for m in result.results[0].metrics
    }


def assert_content_free(run_dir):
    for name in ("events.jsonl", "results.json", "extras.json", "manifest.json"):
        assert sample_shaped.S not in (run_dir / name).read_text(encoding="utf-8"), name


def test_cache_candidates_run(env):
    tmp_path, root, data = env
    config = root / "caching" / "exp-cache-900-t" / "config.toml"
    config.write_text(CACHE)
    out, manifest = run(config, root, data, tmp_path)
    m = overall(out.result)

    def rate(v, s):
        return m[(MetricName.CANDIDATE_HIT_RATE, v, s, None)]

    n = out.result.results[0].n_cases
    assert n == 7 and out.result.cases_covered == 5
    assert rate("msg_only.lit.strict", "session").value == pytest.approx(1 / n)
    assert rate("msg_only.lit.strict", "global").value == pytest.approx(2 / n)
    assert rate("full.lit.strict", "global").value == 0  # history differs
    correctness = m[(MetricName.HIT_CORRECTNESS, "msg_only.lit.strict", "global", None)]
    assert correctness.state == MetricState.UNMEASURED
    declared = m[(MetricName.JUDGE_SCORE, None, None, None)]
    assert declared.reason == "not_produced_by_runner"
    table = out.extras["variant_table"]["msg_only.lit.strict"]
    assert table["hits_cross_session"] == 1 and table["ineligible_attachments"] == 1
    assert out.extras["lexical_repeats"]["literal"]["repeat_groups"] == 1
    assert (
        manifest.data_hash.startswith("sha256:")
        and manifest.ordering_rule == "logged_time"
    )
    assert "candidate:exact" in manifest.versions.policies
    events = [
        Event.model_validate_json(line)
        for line in (out.run_dir / "events.jsonl").read_text().splitlines()
    ]
    assert (
        events[0].event_type == "run_started"
        and events[-1].event_type == "run_finished"
    )
    assert_content_free(out.run_dir)


@pytest.mark.parametrize("source", ["fake", "logged_match"])
def test_routing_candidate_from_a_file_and_one_comparison(env, source):
    tmp_path, root, data = env
    folder = root / "routing" / "exp-route-900-t"
    (folder / "candidate.py").write_text(CANDIDATE)
    (folder / "config.toml").write_text(ROUTE.format(source=source))
    route, route_manifest = run(folder / "config.toml", root, data, tmp_path)
    assert (
        route_manifest.versions.policies["candidate:candidate.firsteligible"] == "0.1"
    )
    m = overall(route.result)
    coverage = m[(MetricName.COVERAGE, None, None, None)].value
    # fake: all but the attachment case (no verified image-capable model);
    # logged_match: only where the first eligible model is the logged one
    assert coverage == pytest.approx(6 / 7 if source == "fake" else 0.0)
    assert (MetricName.SAVINGS, None, None, "as_logged") in m
    assert_content_free(route.run_dir)
    cache_cfg = root / "caching" / "exp-cache-900-t" / "config.toml"
    cache_cfg.write_text(CACHE)
    cache, cache_manifest = run(cache_cfg, root, data, tmp_path)
    table = rows([(route_manifest, route.result), (cache_manifest, cache.result)])
    text = markdown(table)
    assert "exp-route-900" in text and "exp-cache-900" in text
    assert {r.experiment_id for r in table} == {"exp-route-900", "exp-cache-900"}


def test_candidate_files_load_only_from_experiments(env, tmp_path):
    _, root, data = env
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "candidate.py").write_text(CANDIDATE)
    config = outside / "config.toml"
    config.write_text(ROUTE.format(source="fake"))
    with pytest.raises(ExperimentError, match="under"):
        run(config, root, data, tmp_path)


def test_strategy_only_in_an_experiment_file(tmp_path):
    runtime = tmp_path / "local.toml"
    runtime.write_text(
        '[experiment.strategy]\nslot = "candidate_index"\nbuiltin = "exact"\n'
    )
    with pytest.raises(SettingsError, match="only in an experiment file"):
        load_settings(environ={}, dotenv=None, runtime=runtime)
    with pytest.raises(SettingsError):
        load_settings(
            environ={},
            dotenv=None,
            runtime=None,
            overrides={"experiment.strategy.builtin": "exact"},
        )


def test_experiment_id_naming_and_as_logged(tmp_path):
    bad = tmp_path / "exp.toml"
    bad.write_text('[experiment]\nid = "EXP-C1"\n')
    with pytest.raises(SettingsError):
        load_settings(experiment=bad, environ={}, dotenv=None, runtime=None)
    bad.write_text('[experiment]\nid = "exp-cache-001"\nbaselines = ["premium"]\n')
    with pytest.raises(SettingsError, match="as_logged"):
        load_settings(experiment=bad, environ={}, dotenv=None, runtime=None)


def test_live_runs_are_refused(env):
    tmp_path, root, data = env
    config = root / "routing" / "exp-route-900-t" / "config.toml"
    (config.parent / "candidate.py").write_text(CANDIDATE)
    config.write_text(ROUTE.format(source="live"))
    with pytest.raises(ExperimentError, match="live"):
        run(config, root, data, tmp_path)


def test_logged_match_with_the_configured_routing(env):
    tmp_path, root, data = env
    config = root / "routing" / "exp-route-900-t" / "config.toml"
    config.write_text(
        '[experiment]\nid = "exp-route-901"\ncounterfactual_source = "logged_match"\n'
        '[experiment.data]\nmissing_key = "absent"\n'
    )
    out, _ = run(config, root, data, tmp_path)
    # fixed_model gpt-4o-mini (defaults): answered only where the logged label
    # maps to gpt-4o-mini (both turns of the first synthetic session)
    assert overall(out.result)[
        (MetricName.COVERAGE, None, None, None)
    ].value == pytest.approx(2 / 7)
    assert out.extras["label_resolution"]["exact_id"] == 2
