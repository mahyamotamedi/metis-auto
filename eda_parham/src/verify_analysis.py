"""Meaningful pairing/leakage checks and executed artifact consistency."""
import copy
import hashlib
import json
from pathlib import Path
import pandas as pd
from eda_utils import flatten


def verify(root):
    root = Path(root)
    # Ambiguous user/bot blocks, orphan bot and unanswered user must be preserved.
    def msg(role, content, second):
        m = dict(role=role, content=content, timestamp=f"2026-01-01T00:00:{second:02d}")
        if role == "bot":
            m.update(model="synthetic", provider="synthetic", instructions="not executable")
        return m
    messages = [msg("bot", "orphan", 0), msg("user", "تحلیل کن و سپس مقایسه کن", 1),
                msg("user", "قالب جدول باشد", 2), msg("bot", "response A", 3),
                msg("bot", "response B", 4), msg("user", "unanswered", 5)]
    data = [dict(category="synthetic", sessions=[dict(session_id="test", created_at="2026-01-01T00:00:00",
           session_len=len(messages), user_turns=3, bot_turns=3, messages=messages)])]
    _, _, p, q, _ = flatten(data)
    assert len(p) == 3
    assert p.status.tolist() == ["ambiguous_block", "ambiguous_block", "unanswered"]
    assert p.response_count.tolist() == [2, 2, 0]
    assert (q.issue == "orphan_response").sum() == 1
    assert "response A" not in p.iloc[0].history_raw
    altered = copy.deepcopy(data)
    altered[0]["sessions"][0]["messages"][3]["content"] = "```python\nimport future_answer\n``` اثبات فرمول"
    altered[0]["sessions"][0]["messages"][3]["instructions"] = "new future instruction"
    altered[0]["sessions"][0]["messages"][3]["rag"] = dict(query="future", context=["future context"])
    _, _, future, _, _ = flatten(altered)
    feature_cols = ["language", "has_code", "has_json", "has_formula", "needs_context", "request_type", "complexity_heuristic", "history_chars"]
    assert p.iloc[:2][feature_cols].equals(future.iloc[:2][feature_cols]), "Future bot leaked into current routing"
    s = pd.read_csv(root / "outputs/sessions.csv")
    m = pd.read_csv(root / "outputs/messages.csv")
    pairs = pd.read_csv(root / "outputs/request_response_pairs.csv")
    assert len(pairs) == (m.role == "user").sum()
    assert s.actual_message_count.sum() == len(m)
    assert not m.duplicated(["session_key", "message_index"]).any()
    trace = pd.read_csv(root / "outputs/cache_replay_trace.csv")
    matched = trace.matched_response_available_at.notna()
    assert (pd.to_datetime(trace.loc[matched, "matched_response_available_at"], utc=True) <
            pd.to_datetime(trace.loc[matched, "request_timestamp"], utc=True)).all(), "Cache used a future or simultaneous response"
    manifest = json.loads((root / "outputs/run_manifest.json").read_text(encoding="utf-8"))
    for kind in ["data", "pdf"]:
        assert hashlib.sha256(Path(manifest[kind + "_path"]).read_bytes()).hexdigest() == manifest[kind + "_sha256"]
    nbpath = root / "notebooks/eda.ipynb"
    if nbpath.exists():
        notebook = json.loads(nbpath.read_text(encoding="utf-8"))
        assert not any(o.get("output_type") == "error" for c in notebook["cells"] for o in c.get("outputs", []))
    return True


if __name__ == "__main__":
    verify(Path(__file__).resolve().parents[1])
    print("Pairing, future-response leakage, input hashes and output consistency verified.")
