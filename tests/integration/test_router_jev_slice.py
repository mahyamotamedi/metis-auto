"""Jev on the dev slice (owner 2026-11-03, after Metis's written OK, Q-55), on
the SYNTHETIC miniature slice over a MOCKED Metis transport: refused without
``real_data_approved`` (no request sent), then answered with it, charged to a
ledger through the spend guard, the reported version kept, and the cost view
pricing the same logged tokens on today's, the rules' and the router's model.
The plan prints a bound and every blocking reason with no call. No network, no
key, no spend."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

pytest.importorskip("pyarrow")

from fixtures.synthetic import contract_examples as ex  # noqa: E402
from integration.test_router_slice_build import make_repo, make_slice  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from metis_auto.adapters.routers.jev_metis import JevMetisBackend  # noqa: E402
from metis_auto.adapters.system import FakeClock, InMemorySpendLedger  # noqa: E402
from metis_auto.contracts import Money, QuestionLanguage  # noqa: E402
from metis_auto.evaluation.router_eval import (  # noqa: E402
    DIFFERENCE_COLUMNS,
    differences,
)
from metis_auto.settings import load_settings  # noqa: E402
from metis_auto.wiring.router_eval import (  # noqa: E402
    evaluate,
    hosted_plan,
    shadow_rows,
)

ANSWERS = {
    "complexity": {"type": "score", "score": 0.0, "confidence": 0.9},
    "needs_reasoning": {"type": "noul", "noul": 0.05},
    "cheap_model_ok": {"type": "noul", "noul": 0.95},
    "intent": {"type": "choice", "choice": "chitchat", "confidence": 0.9},
    "depends_on_history": {"type": "noul", "noul": 0.1},
}


def hermetic(approved):
    def load(overrides):
        extra = {"router.real_data_approved": True} if approved else {}
        return load_settings(
            environ={}, dotenv=None, runtime=None, overrides={**overrides, **extra}
        )

    return load


@pytest.fixture(scope="module")
def records(tmp_path_factory):
    repo, data, _ = make_repo(tmp_path_factory.mktemp("jev-slice"))
    sl = make_slice(repo, data)
    sl.build()
    return sl.frozen_records()


class Metis:
    """Mock Metis TypeSafe wrapper: every state gets the same 'cheap' answers."""

    def __init__(self):
        self.requests = []

    def handler(self, request):
        self.requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "jev-1.14.0",
                "answers": ANSWERS,
                "usage": {"input_tokens": 700, "output_tokens": 170},
            },
        )

    def backends(self):
        loaded = load_settings(environ={}, dotenv=None, runtime=None)
        questions = loaded.reference.router_questions.get(
            "routing_qs_v1", QuestionLanguage.ENGLISH
        )

        def make(clock):
            return {
                "jev_metis": JevMetisBackend(
                    FakeClock(ex.NOW),
                    name="jev_metis",
                    base_url="https://api.metisai.ir/typesafe",
                    model="jev-latest",
                    api_key=SecretStr("sk-SYNTHETIC-not-a-key"),
                    prices=loaded.reference.router_prices,
                    price_ref="metis-jev-latest",
                    questions=questions,
                    transport=httpx.MockTransport(self.handler),
                )
            }

        return make


def _ledger():
    return InMemorySpendLedger(Money(amount=Decimal("0.05"), currency="USD"))


def test_without_real_data_approval_no_state_leaves(records):
    metis = Metis()
    rows = shadow_rows(
        hermetic(False),
        records,
        backend="jev",
        offline=True,
        spend_ledger=_ledger(),
        backends=metis.backends(),
    )
    assert metis.requests == []
    assert {r.decision_status for r in rows} <= {"failed", "skipped"}
    assert all(r.decision_cost_usd is None for r in rows)


def test_jev_on_the_slice_is_charged_and_priced(records):
    metis = Metis()
    ledger = _ledger()
    out = evaluate(
        hermetic(True),
        records,
        backend="jev",
        offline=True,
        spend_ledger=ledger,
        backends=metis.backends(),
    )
    asked = len(metis.requests)
    assert asked > 0
    assert Decimal(out["decision_cost_usd"]) > 0
    assert ledger.remaining().amount == Decimal("0.05") - Decimal(
        out["decision_cost_usd"]
    )
    assert out["model_revisions"] == {"jev-1.14.0": asked}
    costs = out["costs"]
    assert costs["evidence"].startswith("cost simulation")
    block = costs["logged_tokens"]["all"]
    assert block["records"] == len(records)
    assert set(block["total_usd"]) == {"today", "rules", "router"}
    reasoning = costs["with_expected_reasoning"]["all"]
    assert Decimal(reasoning["total_usd"]["router"]) >= Decimal(
        block["total_usd"]["router"]
    )
    text = json.dumps(out)
    assert "SYNTHETIC" not in text  # content-free output
    # the answering totals exclude Jev's own calls; the net view adds them
    net = out["net_of_decision_cost"]["logged_tokens"]
    assert Decimal(net["router_incl_decision_usd"]) == Decimal(
        block["total_usd"]["router"]
    ) + Decimal(out["decision_cost_usd"])
    skips = out["skips"]
    assert set(skips) == {
        "skipped_by_path_and_reason",
        "rules_no_model_by_reason",
        "rules_no_model_exclusions",
    }


def test_rows_sink_and_differences_are_content_free(records):
    metis = Metis()
    sink: list = []
    evaluate(
        hermetic(True),
        records,
        backend="jev",
        offline=True,
        spend_ledger=_ledger(),
        backends=metis.backends(),
        rows_sink=sink,
    )
    assert len(sink) == len(records)
    skipped = [r for r in sink if r.decision_status == "skipped"]
    assert all(r.skip_reason is not None for r in skipped)
    for d in differences(sink):
        assert tuple(d) == DIFFERENCE_COLUMNS
        assert d["rules_model"] != d["jev_model"]
        assert "SYNTHETIC" not in json.dumps(d)


def test_the_plan_bounds_cost_and_lists_every_reason(records):
    plan = hosted_plan(hermetic(False)({}), records)
    assert plan["makes_calls"] is False and plan["calls"] == len(records)
    assert Decimal(plan["upper_bound_usd"]) > 0
    assert not plan["allowed"]
    joined = " ".join(plan["blocked_because"])
    assert "real_data_approved is false" in joined
    assert "METIS_API_KEY" in joined
