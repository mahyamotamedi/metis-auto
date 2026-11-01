"""Build review sets and rubrics for human validation (nothing is labelled here).

Committed copies (reports/full_eda/review/) carry IDs and derived features only.
Text-bearing copies go to runs/full_eda/review_local/ (git-ignored). Seeded.

    python scripts/full_eda_review_sets.py
"""

from __future__ import annotations

import glob
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

SEED = 20261030
RAW = Path("data/full_data/raw/data")
PUB = Path("reports/full_eda/review")
LOC = Path("runs/full_eda/review_local")


def texts_for(ids: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(glob.glob(str(RAW / "chat_message-*.parquet"))):
        t = pq.read_table(f, columns=["message_id", "content"]).to_pandas()
        t = t[t["message_id"].isin(ids)]
        out.update(zip(t["message_id"], t["content"], strict=False))
    return out


def emit(
    name: str, df: pd.DataFrame, id_cols: list[str], label_cols: list[str]
) -> None:
    PUB.mkdir(parents=True, exist_ok=True)
    LOC.mkdir(parents=True, exist_ok=True)
    pub = df.drop(columns=[c for c in df.columns if c.startswith("text_")])
    for lc in label_cols:
        pub[lc] = ""
        df[lc] = ""
    pub.to_csv(PUB / f"{name}.csv", index=False)
    df.to_csv(LOC / f"{name}_with_text.csv", index=False)
    print(name, len(df))


def main() -> int:
    r = pd.read_parquet("data/derived/full_eda/requests.parquet")
    um = r[r["u_content_state"] == "text"]
    # 1. Language label validation: 40 per heuristic label (all if fewer).
    parts = [
        g.sample(min(40, len(g)), random_state=SEED) for _, g in um.groupby("u_lang")
    ]
    lang = pd.concat(parts)[["user_message_id", "u_lang", "u_n_chars"]].rename(
        columns={"u_lang": "heuristic_label", "u_n_chars": "n_chars"}
    )
    t = texts_for(set(lang["user_message_id"]))
    lang["text_content"] = lang["user_message_id"].map(t)
    emit(
        "language_validation",
        lang,
        ["user_message_id"],
        ["reviewer_language", "reviewer_confident", "notes"],
    )
    # 2. History dependence: short follow-up USER messages at turn >= 1.
    fu = um[(um["turn"] >= 1) & (um["u_n_chars"] <= 40)].sample(150, random_state=SEED)[
        ["user_message_id", "session_id", "turn", "u_n_chars"]
    ]
    ids = set(fu["user_message_id"])
    t = texts_for(ids)
    fu["text_content"] = fu["user_message_id"].map(t)
    emit(
        "history_dependence",
        fu,
        ["user_message_id"],
        ["dependency_type", "needs_previous_turn", "notes"],
    )
    # 3. Semantic-cache pair validity from lexical candidates.
    pr = pd.read_parquet("runs/full_eda/semantic_candidate_pairs.parquet")
    if len(pr):
        pr = pr.sample(min(200, len(pr)), random_state=SEED)
        t = texts_for(set(pr["message_id_a"]) | set(pr["message_id_b"]))
        pr["text_a"] = pr["message_id_a"].map(t)
        pr["text_b"] = pr["message_id_b"].map(t)
        emit(
            "semantic_pair_validity",
            pr,
            ["message_id_a", "message_id_b"],
            ["safe_to_reuse_answer", "hard_negative_type", "notes"],
        )
    # 4. Answer-quality review: 100 billed answers stratified by configured model.
    q = r[
        (r["a_content_state"] == "text")
        & r["bot_provider_model"].notna()
        & ~r["bot_provider_name"].isin(["imagination", "workflow"])
    ]
    q = q.groupby("bot_provider_model", group_keys=False).apply(
        lambda g: g.sample(min(10, len(g)), random_state=SEED), include_groups=False
    )
    q = (
        q.assign(
            bot_provider_model=q.index.map(lambda i: r.loc[i, "bot_provider_model"])
        )
        if "bot_provider_model" not in q
        else q
    )
    q = q[["ai_message_id", "user_message_id", "bot_provider_model", "turn"]].head(150)
    t = texts_for(set(q["ai_message_id"]) | set(q["user_message_id"].dropna()))
    q["text_request"] = q["user_message_id"].map(t)
    q["text_answer"] = q["ai_message_id"].map(t)
    emit(
        "answer_quality",
        q,
        ["ai_message_id"],
        ["correct", "relevant", "language_ok", "format_ok", "notes"],
    )
    chk = subprocess.run(
        ["git", "check-ignore", str(LOC / "language_validation_with_text.csv")],
        capture_output=True,
        text=True,
    )
    print("local copies git-ignored:", bool(chk.stdout.strip()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
