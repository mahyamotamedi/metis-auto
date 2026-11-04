"""The paid benchmark end to end over MOCKED HTTP (ADR-0053): plan with no
call, every refusal listed, generation
through E4 with replay-first, spend-guarded, recorded live clients, a rerun
that replays at no cost, two judges in both orders (plain chat, strict JSON,
no ``response_format``), labels and the spot-check files. A SYNTHETIC golden
store, key and transport; no database, no network, no spend."""

from __future__ import annotations

import csv
import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("openai")
import httpx2  # noqa: E402

from metis_auto.evaluation.sampling.config import LiveApproval  # noqa: E402
from metis_auto.settings import load_settings  # noqa: E402
from metis_auto.wiring.benchmark import Benchmark, BenchmarkRefused  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KEY = "sk-SYNTHETIC-not-a-key"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
RECORDS = ["gv2-syn-1", "gv2-syn-2", "gv2-syn-3", "gv2-syn-4"]
JUDGES = ["gpt-4o-mini", "deepseek-v4-flash"]

OWNER_VALUES = """
[gates]
metis_allows_samples = true
metis_answer_ref = "SYNTHETIC test fixture"

[spend_share]
summaries_dir = "reports/spend/ledgers"
expected_machines = ["syn-me"]
max_age_hours = 24

[run]
hard_cap_usd = "0.5"
max_output_tokens = 64
order_seed = "syn-order"

[judges]
models = ["gpt-4o-mini", "deepseek-v4-flash"]
max_output_tokens = 16
instruction_language = "en"

[labels]
acceptable_score = 0.5
cheap_arms = ["gpt-5-nano"]
"""


def _without_owner_values(text: str) -> str:
    """The committed config (owner values set 2026-11-04) with every owner value
    removed and the Metis gate closed: the shape of the unset file."""
    drop = {"run", "judges", "labels"}
    keep, section = [], ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.strip("[]")
        name = stripped.split("=")[0].strip()
        is_value = "=" in stripped and not stripped.startswith("#")
        if is_value and (
            section in drop
            or (
                section == "spend_share"
                and name in ("expected_machines", "max_age_hours")
            )
            or (section == "gates" and name == "metis_answer_ref")
        ):
            continue
        if is_value and section == "gates" and name == "metis_allows_samples":
            line = "metis_allows_samples = false"
        keep.append(line)
    return "\n".join(keep) + "\n"


def _config(owner: bool) -> str:
    text = (ROOT / "config/evaluation/benchmark.toml").read_text(encoding="utf-8")
    text = text.replace(
        'shareable_ids = "reports/evaluation/golden_v2/golden_v2_shareable.parquet"',
        'shareable_ids = "syn/shareable.parquet"',
    )
    if not owner:
        return _without_owner_values(text)
    head, _, _ = text.partition("[gates]")
    tail = text.split("[spot_check]", 1)[1]
    return head + OWNER_VALUES + "\n[spot_check]" + tail


@pytest.fixture
def root(tmp_path):
    (tmp_path / "config/evaluation").mkdir(parents=True)
    shutil.copy(
        ROOT / "config/evaluation/golden_answers.toml",
        tmp_path / "config/evaluation/golden_answers.toml",
    )
    (tmp_path / "syn").mkdir()
    pd.DataFrame(
        {
            "record_id": RECORDS,
            "owner_cohort": ["User A", "User B", "Remaining accounts", "User A"],
            "stratum": [
                json.dumps({"language_group": g})
                for g in ("persian", "english", "mixed", "persian")
            ],
            "target_message_id": [f"syn-m-{i}" for i in range(4)],
        }
    ).to_parquet(tmp_path / "syn/shareable.parquet", index=False)
    return tmp_path


class Store:
    """SYNTHETIC golden-v2 store (the database's shape, no database)."""

    def request_inputs(self, dataset_id):
        assert dataset_id == "golden-v2"
        out = []
        for i, r in enumerate(RECORDS):
            rows = [
                {
                    "position": 0,
                    "kind": "bot_instruction",
                    "role": None,
                    "content": "[SYNTHETIC] You are a helpful shop assistant.",
                    "metadata": {},
                },
                {
                    "position": 1,
                    "kind": "target_user_message",
                    "role": "user",
                    "content": f"[SYNTHETIC] سؤال شماره {i}؟",
                    "metadata": {},
                },
            ]
            out.append(
                {
                    "record_id": r,
                    "bot_id": "bot-syn",
                    "stratum": {},
                    "rows": rows,
                    "kinds": ["bot_instruction", "target_user_message"],
                }
            )
        return out

    def answers(self, run_id, record_ids):
        return {r: f"[SYNTHETIC] reference answer {r}" for r in record_ids}


class Wrapper:
    """Mock Metis wrapper: judge prompts get strict JSON, others an answer."""

    def __init__(self):
        self.bodies = []

    def handler(self, request):
        body = json.loads(request.content)
        self.bodies.append(body)
        system = body["messages"][0]["content"]
        judging = '{"choice": "first"}' in system
        text = '{"choice": "first"}' if judging else "[SYNTHETIC] arm answer"
        return httpx2.Response(
            200,
            json={
                "id": "syn",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": text},
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 8,
                    "total_tokens": 128,
                    "prompt_tokens_details": {"cached_tokens": 0},
                },
            },
        )

    def factory(self):
        return lambda: httpx2.Client(transport=httpx2.MockTransport(self.handler))


def _bench(root, tmp_path, owner=True):
    (root / "config/evaluation/benchmark.toml").write_text(_config(owner), "utf-8")
    paths = {
        "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
        "paths.recorded_dir": str(tmp_path / "recorded"),
    }

    def load(overrides):
        return load_settings(
            overrides={**overrides, **paths, "live.enabled": True},
            environ={"METIS_API_KEY": KEY},
            dotenv=None,
            runtime=None,
        )

    return Benchmark(root=root, load=load, store=Store(), now=lambda: NOW)


APPROVAL = LiveApproval(
    approved_by="owner-syn",
    run_id="run-syn",
    cap_usd=Decimal("0.5"),
    sample_conversations_approved=True,
)


def test_plan_counts_and_prices_with_no_call(root, tmp_path):
    bench = _bench(root, tmp_path)
    plan = bench.plan(with_db=True, machine="syn-me")
    assert plan["makes_calls"] is False and plan["records"] == 4
    assert plan["callable_arms"] == ["gpt-5-nano", "gpt-4o-mini", "deepseek-v4-flash"]
    refused = {a["model"]: a["reason"] for a in plan["arms"] if not a["callable"]}
    assert set(refused) == {"gpt-4.1-nano", "mimo-v2.5"}
    assert plan["generation"]["calls"] == 12
    assert plan["generation"]["lower_bound_usd"] is not None
    assert plan["generation"]["ceiling_usd"] is not None
    assert plan["judging"]["calls"] == 4 * 3 * 2 * 2
    assert plan["judging"]["ceiling_usd"] is not None
    assert plan["budget"]["team_total_known"] == "0"
    assert plan["reference_answers_found"] == 4
    assert "SYNTHETIC" not in json.dumps(plan)  # content-free


def test_paid_steps_refuse_with_every_reason(root, tmp_path):
    bench = _bench(root, tmp_path, owner=False)
    with pytest.raises(BenchmarkRefused) as err:
        bench.generate(run_id="run-syn", machine="syn-me", approval=None)
    reasons = err.value.reasons
    assert any("Metis has not allowed" in r for r in reasons)
    assert any("no owner approval" in r for r in reasons)
    for key in (
        "run.hard_cap_usd",
        "run.max_output_tokens",
        "run.order_seed",
        "spend_share.expected_machines",
        "spend_share.max_age_hours",
    ):
        assert f"set by owner: {key}" in reasons
    with pytest.raises(BenchmarkRefused) as err:
        bench.judge(run_id="run-syn", machine="syn-me", approval=None)
    assert "set by owner: judges.models" in err.value.reasons


def test_generate_judge_label_and_spot_check_over_mocked_http(root, tmp_path):
    wrapper = Wrapper()
    bench = _bench(root, tmp_path)
    result = bench.generate(
        run_id="run-syn",
        machine="syn-me",
        approval=APPROVAL,
        http_client_factory=wrapper.factory(),
    )
    assert result.executed_calls == 12 and not result.halts
    sent = {b["model"] for b in wrapper.bodies}
    assert sent == {"gpt-5-nano", "gpt-4o-mini", "deepseek-v4-flash"}
    assert all("response_format" not in b for b in wrapper.bodies)
    ledger = tmp_path / "spend" / "ledger.jsonl"
    charges = ledger.read_text().splitlines()
    assert len(charges) == 12

    again = _bench(root, tmp_path).generate(
        run_id="run-syn",
        machine="syn-me",
        approval=APPROVAL,
        http_client_factory=wrapper.factory(),
    )
    assert again.executed_calls == 12
    assert len(wrapper.bodies) == 12  # every answer replayed: no new call
    assert ledger.read_text().splitlines() == charges  # and no new charge

    runs = bench.judge(
        run_id="run-syn",
        machine="syn-me",
        approval=APPROVAL,
        http_client_factory=wrapper.factory(),
    )
    assert len(runs) == 2 and all(len(r.judged) == 12 for r in runs)
    judge_bodies = wrapper.bodies[12:]
    assert len(judge_bodies) == 2 * 12 * 2
    assert {b["model"] for b in judge_bodies} == set(JUDGES)
    assert all("response_format" not in b for b in judge_bodies)
    folder = root / "runs/benchmark/run-syn/judging"
    scores = (folder / "gpt-4o-mini.scores.jsonl").read_text()
    assert (
        "SYNTHETIC" not in scores
        and "SYNTHETIC" not in (folder / "gpt-4o-mini.calls.jsonl").read_text()
    )

    summary = bench.labels(run_id="run-syn", name="p1-syn")
    assert summary["records"] == 4 and summary["labels_source"] == "benchmark:p1-syn"
    labels = pd.read_parquet(
        root / "runs/benchmark/run-syn/labels/p1-syn.labels.parquet"
    )
    assert set(labels["user_message_id"]) == {f"syn-m-{i}" for i in range(4)}

    spot = bench.spot_check(run_id="run-syn")
    assert spot["items"] == 12
    out = root / "runs/benchmark/run-syn/spot_check"
    with (out / "sheet.csv").open(encoding="utf-8-sig") as f:
        sheet = list(csv.DictReader(f))
    assert len(sheet) == 12 and "SYNTHETIC" not in json.dumps(sheet)
    assert "gpt" not in json.dumps(sheet)  # blinded: no model, no record
    assert "[SYNTHETIC] reference answer" in (out / "texts_LOCAL_ONLY.md").read_text(
        encoding="utf-8"
    )


def test_spend_guard_stops_live_calls_at_the_shared_ceiling(root, tmp_path):
    """Another machine's summary leaves almost nothing under the 92 USD
    ceiling: every live call is refused by the guard, recorded as an error,
    and the run goes on (no crash, nothing sent)."""
    _bench(root, tmp_path)  # writes the owner-set config
    text = (root / "config/evaluation/benchmark.toml").read_text("utf-8")
    text = text.replace(
        'expected_machines = ["syn-me"]', 'expected_machines = ["syn-me", "syn-other"]'
    )
    (root / "config/evaluation/benchmark.toml").write_text(text, "utf-8")
    folder = root / "reports/spend/ledgers"
    folder.mkdir(parents=True)
    (folder / "syn-other.json").write_text(
        json.dumps(
            {
                "format": "ledger-summary-v1",
                "machine": "syn-other",
                "currency": "USD",
                "total": "91.9999999",
                "charges": 1,
                "by_run": {},
                "newest_charge": None,
                "created_at": NOW.isoformat(),
                "ledger_sha256": None,
            }
        ),
        "utf-8",
    )
    wrapper = Wrapper()
    paths = {
        "paths.spend_ledger": str(tmp_path / "spend" / "ledger.jsonl"),
        "paths.recorded_dir": str(tmp_path / "recorded"),
    }
    bench = Benchmark(
        root=root,
        store=Store(),
        now=lambda: NOW,
        load=lambda o: load_settings(
            overrides={**o, **paths, "live.enabled": True},
            environ={"METIS_API_KEY": KEY},
            dotenv=None,
            runtime=None,
        ),
    )
    result = bench.generate(
        run_id="run-syn",
        machine="syn-me",
        approval=APPROVAL,
        http_client_factory=wrapper.factory(),
    )
    assert wrapper.bodies == []
    assert {r.outcome for r in result.records} == {"error"}
    assert not (tmp_path / "spend" / "ledger.jsonl").exists()
