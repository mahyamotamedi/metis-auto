"""EXP-CTX-001 within-message chunk dedup (final plan S-6; FR-CTX-02, X5).

Every frame here is SYNTHETIC: made-up message IDs, chunk IDs and fingerprints,
no content. The version lives in ``experiments/``, which ``metis_auto`` never
imports, so it is loaded by file path (as ``wiring.experiments`` does).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from metis_auto.analysis.levers import ReplayContext, StepVersion

ROOT = Path(__file__).resolve().parents[3]
VERSION_FILE = ROOT / "experiments/context/exp-ctx-001-within-message-dedup/version.py"


@pytest.fixture(scope="module")
def version():
    name = "exp_ctx_001_version_under_test"
    spec = importlib.util.spec_from_file_location(name, VERSION_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(name, None)


def _chunks(rows: list[tuple[str, str, str | None, int]]) -> pd.DataFrame:
    """SYNTHETIC chunk rows: (message_id, chunk_id, h_exact, n_chars)."""
    return pd.DataFrame(rows, columns=["message_id", "chunk_id", "h_exact", "n_chars"])


def _requests(message_ids: list[str]) -> pd.DataFrame:
    """SYNTHETIC requests frame with the columns the version reads or keeps."""
    return pd.DataFrame(
        {
            "ai_message_id": message_ids,
            "llm_request": True,
            "block_fees": 0.002,
            "block_token_cost": 1.0,
        },
        index=pd.Index([10 + i for i in range(len(message_ids))]),
    )


CTX = ReplayContext(period_bounds={}, price_table={}, catalogue={}, seed=0)


def test_duplicate_chunk_counted_once(version):
    # SYNTHETIC: m1 holds hA three times (two under the same chunk ID, one under
    # another ID) and hB once; m2 holds hA once, which is not a duplicate of m1's.
    chunks = _chunks(
        [
            ("m1", "c1", "hA", 100),
            ("m1", "c1", "hA", 100),
            ("m1", "c9", "hA", 100),
            ("m1", "c2", "hB", 50),
            ("m2", "c1", "hA", 100),
        ]
    )
    per_msg = version.within_message_duplicates(chunks)
    m1, m2 = per_msg.loc["m1"], per_msg.loc["m2"]
    assert m1["n_chunks"] == 4
    assert m1["n_dup_exact"] == 2  # hA is kept once, its two copies are dropped
    assert m1["dup_chars_exact"] == 200
    assert m2["n_dup_exact"] == 0  # no dedup across messages

    dedup = version.WithinMessageDedup(chunks)
    assert isinstance(dedup, StepVersion)
    assert dedup.step == "context"
    req = _requests(["m1", "m2", "m3"])  # m3 logs no chunks
    out = dedup.apply(req, CTX)
    assert out.index.equals(req.index)
    assert out["ctx_dup_chunks_exact"].tolist() == [2, 0, 0]
    assert out["ctx_dup_chars_exact"].tolist() == [200, 0, 0]
    # No saving is written until the chars -> token_cost conversion is decided.
    pd.testing.assert_series_equal(out["block_token_cost"], req["block_token_cost"])
    pd.testing.assert_series_equal(out["block_fees"], req["block_fees"])


def test_same_id_different_hash_is_not_a_duplicate(version):
    # SYNTHETIC, Review Focus 4: chunk c1 changed text (a corpus update) inside
    # one message. Same ID, different h_exact: never a safe drop.
    chunks = _chunks(
        [
            ("m1", "c1", "hA", 100),
            ("m1", "c1", "hB", 120),
            ("m1", "c2", None, 0),  # no text: never a duplicate
            ("m1", "c3", None, 0),
        ]
    )
    per_msg = version.within_message_duplicates(chunks)
    assert per_msg.loc["m1", "n_chunks"] == 4
    assert per_msg.loc["m1", "n_with_text"] == 2
    assert per_msg.loc["m1", "n_dup_exact"] == 0
    assert per_msg.loc["m1", "dup_chars_exact"] == 0
    out = version.WithinMessageDedup(chunks).apply(_requests(["m1"]), CTX)
    assert out["ctx_dup_chunks_exact"].tolist() == [0]


def test_exact_and_normalised_duplicates_reported_separately(version):
    # SYNTHETIC: in m1, row 2 differs from row 1 only after normalize_safe
    # (different h_exact, same h_norm); row 3 is an exact copy of row 1.
    rows = [
        ("m1", "c1", "hA", "nX", 100),
        ("m1", "c2", "hA2", "nX", 101),
        ("m1", "c3", "hA", "nX", 100),
        ("m2", "c1", "hB", "nY", 40),
    ]
    chunks = pd.DataFrame(
        rows, columns=["message_id", "chunk_id", "h_exact", "h_norm", "n_chars"]
    )
    m1 = version.within_message_duplicates(chunks).loc["m1"]
    assert (m1["n_dup_exact"], m1["dup_chars_exact"]) == (1, 100)
    assert (m1["n_dup_norm"], m1["dup_chars_norm"]) == (2, 201)
    assert m1["n_dup_norm_only"] == 1
    out = version.WithinMessageDedup(chunks).apply(_requests(["m1", "m2"]), CTX)
    assert out["ctx_dup_chunks_exact"].tolist() == [1, 0]  # the only drop candidates
    assert out["ctx_dup_chunks_norm"].tolist() == [2, 0]

    # Without a normalised fingerprint the figure is "not computed", never 0.
    plain = chunks.drop(columns="h_norm")
    per_msg = version.within_message_duplicates(plain)
    assert per_msg["n_dup_exact"].tolist() == [1, 0]
    assert per_msg["n_dup_norm"].isna().all()
    out = version.WithinMessageDedup(plain).apply(_requests(["m1", "m3"]), CTX)
    assert out["ctx_dup_chunks_norm"].isna().all()

    # A text row whose h_norm is missing makes its message's figure unknown.
    gap = chunks.astype({"h_norm": object})
    gap.loc[3, "h_norm"] = None
    per_msg = version.within_message_duplicates(gap)
    assert per_msg.loc["m1", "n_dup_norm"] == 2
    assert pd.isna(per_msg.loc["m2", "n_dup_norm"])


def test_summary_reports_all_and_llm_only(version):
    # SYNTHETIC: one LLM and one workflow request, each with 4 chunk rows,
    # 2 of them exact copies; one LLM request with no chunks.
    chunks = _chunks(
        [("m1", "c1", "hA", 10)] * 3
        + [("m1", "c2", "hB", 5)]
        + [("w1", "c1", "hA", 10)] * 3
        + [("w1", "c2", "hB", 5)]
    )
    req = _requests(["m1", "w1", "m3"]).assign(
        llm_request=[True, False, True], split=["tune", "tune", "report"]
    )
    out = version.WithinMessageDedup(chunks).apply(req, CTX)
    s = version.summarise(out, by="split").set_index(["split", "scope"])
    # Over all requests: workflow chunk rows are in the denominator only.
    tune_all, tune_llm = s.loc[("tune", "all")], s.loc[("tune", "llm_only")]
    assert (tune_all["requests"], tune_all["chunk_rows"]) == (2, 8)
    assert (tune_all["dup_rows_exact"], tune_all["dup_row_share_exact"]) == (2, 0.25)
    assert (tune_llm["requests"], tune_llm["chunk_rows"]) == (1, 4)
    assert tune_llm["dup_row_share_exact"] == 0.5
    assert tune_llm["dup_char_share_exact"] == 20 / 35
    assert tune_llm["requests_with_dup_share"] == 1.0
    report = s.loc[("report", "llm_only")]
    assert (report["requests"], report["chunk_rows"]) == (1, 0)
    assert pd.isna(report["dup_row_share_exact"])  # no chunks: unknown, not 0
    assert pd.isna(tune_llm["dup_row_share_norm"])  # no h_norm: not computed
    assert {"all", "llm_only"} == set(s.index.get_level_values("scope"))
    assert "__total__" in set(s.index.get_level_values("split"))


def _script():
    path = ROOT / "scripts/derive_chunk_norm_fingerprints.py"
    spec = importlib.util.spec_from_file_location("derive_chunk_norm_fp", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_norm_fingerprints_match_the_ingest_and_group_variants():
    from metis_auto.analysis.text_features import fingerprint, normalize_safe

    # SYNTHETIC texts, made up for this test.
    texts = pd.Series(
        ["SYNTHETIC chunk  one", "synthetic chunk one", "SYNTHETIC two", "", None]
    )
    table = _script().norm_fingerprints(texts)
    assert list(table.columns) == ["h_exact", "h_norm"]
    assert len(table) == 3  # distinct non-empty texts only
    assert table["h_exact"].is_unique
    assert set(table["h_exact"]) == {fingerprint(t) for t in texts[:3]}
    by_exact = table.set_index("h_exact")["h_norm"]
    assert by_exact[fingerprint(texts[0])] == by_exact[fingerprint(texts[1])]
    assert by_exact[fingerprint(texts[2])] == fingerprint(normalize_safe(texts[2]))
