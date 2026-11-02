"""R-B2 run helpers: the chunks frame, ordinary input tokens and cost per request,
one scenario's evaluation and its ``LeverResult`` (final plan R-B2; H-1,
FR-CTX-02, QA-REPRO). Pure over frames; ``scripts/run_pipeline_b_day2.py`` does
the file IO and passes the interim split. Outputs are content-free aggregates.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
TOKENS_ONLY = "tokens only, quality not measured / hypothetical reconstruction"


def _sibling(name: str) -> Any:
    key = f"metis_exp_ctx_002_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


version = _sibling("version")


def build_chunks(req: pd.DataFrame, chunk_table: pd.DataFrame) -> pd.DataFrame:
    """One row per chunk occurrence of the requests in ``req``, in request order
    then logged chunk order. ``chunk_table`` is the derived chunk table
    (``message_id``, ``chunk_id``, ``n_chars``, ``h_exact``). The scope is the
    requesting user plus the bot."""
    key = pd.DataFrame(
        {
            "message_id": req["ai_message_id"].to_numpy(),
            "req": req.index,
            "order": range(len(req)),
            "session": req["session_id"].to_numpy(),
            "scope": (
                req["user_id"].astype(str) + "\x1f" + req["bot_id"].astype(str)
            ).to_numpy(),
            "turn": req["turn"].to_numpy(),
        }
    )
    ch = chunk_table[["message_id", "chunk_id", "n_chars", "h_exact"]].copy()
    ch["pos"] = range(len(ch))
    out = ch.merge(key, on="message_id", how="inner", validate="many_to_one")
    out = out.sort_values(["order", "pos"], kind="stable").reset_index(drop=True)
    out = out.rename(columns={"h_exact": "content_hash"})
    out["content_hash"] = (
        out["content_hash"].astype(object).where(out["content_hash"].notna(), None)
    )
    return out[list(version.CHUNK_COLUMNS)]


def request_inputs(
    req: pd.DataFrame, items: pd.DataFrame, separate_models: frozenset[str]
) -> pd.DataFrame:
    """Add ``input_tokens_ordinary`` (cached-token convention) and
    ``input_cost_ordinary`` (sum of recorded ``costBreakdown.input_tokens``).
    The cost is unknown unless every token item of the message has it."""
    out = req.copy()
    out["input_tokens_ordinary"] = [
        version.ordinary_input_tokens(i, c, m, separate_models)
        for i, c, m in zip(
            out["a_bill_inputTokens"],
            out["a_bill_cachedInputTokens"],
            out["bot_provider_model"],
            strict=True,
        )
    ]
    tok = items[items["inputTokens"].fillna(0) > 0]
    cost = tok.groupby("message_id")["costBreakdown.input_tokens"]
    complete = cost.apply(lambda s: s.notna().all())
    total = cost.sum(min_count=1).where(complete)
    out["input_cost_ordinary"] = out["ai_message_id"].map(total)
    return out


def _visible(window: int | None) -> Any:
    if window is None:
        return lambda k: True
    return lambda k: k <= window


def evaluate(
    req: pd.DataFrame,
    chunks: pd.DataFrame,
    *,
    pointer_tokens: int,
    window: int | None,
    ledger: bool,
    tpc: float,
) -> dict[str, Any]:
    """One scenario. ``window`` 0 is the conservative default (nothing visible),
    ``n`` assumes chunks from the last ``n`` turns are visible, ``None`` assumes
    everything earlier in the session is (upper bound)."""
    policy = version.CrossTurnChunkPolicy(
        pointer_tokens, _visible(window), ledger, chunks=chunks, tokens_per_char=tpc
    )
    decisions, after = policy.run(req)
    return {
        "name": policy.name + (".all" if window is None else f".k{window}"),
        "scenario": {
            "pointer_tokens": pointer_tokens,
            "visible_window": "all" if window is None else window,
            "session_ledger": ledger,
            "tokens_per_char": tpc,
        },
        "summary": version.summarise(decisions, after, req),
        "after": after,
    }


def _dec(value: float) -> Decimal:
    return Decimal(f"{value + 0.0:.9f}")


def lever_result_json(
    res: dict[str, Any],
    req: pd.DataFrame,
    *,
    seed: int,
    code_commit: str,
    python_version: str,
    created_at: datetime,
    period_bounds: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]] | None = None,
    extra_assumptions: Sequence[str] = (),
) -> str:
    """The scenario's ``LeverResult`` (baseline ``as_logged``) as JSON text."""
    from metis_auto.analysis.lever_result import LeverResult, build_manifest
    from metis_auto.analysis.levers import BLOCKS, ReplayContext, summarise_slices

    after = res["after"]
    slices = summarise_slices(req, after)
    slices["traffic_weighted"] = dict(slices["all"])
    s = res["summary"]
    slices["context_tokens"] = {
        "removed": _dec(s["tokens"]["removed"]),
        "added": _dec(s["tokens"]["added"]),
        "saved": _dec(s["tokens"]["saved"]),
        "supported_input": _dec(s["tokens"]["supported_input"]),
        "n_requests_changed": Decimal(s["n_requests_changed"]),
    }
    if s["tokens"]["supported_input"]:
        slices["context_tokens"]["saved_share"] = _dec(
            s["tokens"]["saved"] / s["tokens"]["supported_input"]
        )
    known = slices["llm_only"]
    ctx = ReplayContext(
        period_bounds=dict(period_bounds or {}),
        price_table={"version": "recorded-units"},
        catalogue={},
        seed=seed,
    )
    sc = res["scenario"]
    config = {"lever": "rb2-cross-turn-chunk-policy", **sc, "interim": True}
    window = sc["visible_window"]
    ledger = "ledger" if sc["session_ledger"] else "pointer"
    result = LeverResult(
        lever_id=f"rb2.cross-turn.k-{window}.ptr-{sc['pointer_tokens']}.{ledger}",
        step="context",
        version=res["name"],
        n_requests=len(req),
        n_eligible=int(req["llm_request"].astype(bool).sum()),
        baseline="as_logged",
        baseline_cost={b: known[f"baseline:{b}"] for b in BLOCKS},
        saving={b: known[f"saving:{b}"] for b in BLOCKS},
        slices=slices,
        evidence_class="hypothetical reconstruction",
        correctness_state="unmeasured",
        assumptions=(
            TOKENS_ONLY,
            "visibility is assumed (history policy unidentified, EDA section 2)",
            f"chunk tokens = chars x {sc['tokens_per_char']:.4f} (EDA turn-0 slope)",
            "removed tokens priced at the request's recorded ordinary input rate; "
            "provider-cached input not repriced",
            "fees and output unchanged; within-message copies left to S-6",
            "timestamps are naive (Q-06)",
            *extra_assumptions,
        ),
        manifest=build_manifest(
            config,
            ctx,
            code_commit=code_commit,
            python_version=python_version,
            created_at=created_at,
        ),
    )
    return result.to_json()
