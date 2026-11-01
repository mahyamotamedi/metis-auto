"""Request/response pairing with a pairing-quality flag (FR-REQ-03).

The export has no request or call ID, so a response is paired with the preceding
user message **by order** (timestamp, then source order). This is a heuristic
reconstruction, not a verified call linkage. Flags on each AI message:

- ``clean``: the previous conversational message is exactly one USER message.
- ``consecutive_user``: two or more USER messages precede it; only the last is
  paired and the earlier ones are *skipped* user messages.
- ``multiple_answers``: the previous conversational message is another AI message.
- ``no_preceding_user``: no conversational message precedes it.

SYSTEM and TOOL messages are not conversational and are ignored when finding the
predecessor; their count is kept.
"""

from __future__ import annotations

import pandas as pd

CONVERSATIONAL = ("USER", "AI")


def pair_session_messages(msgs: pd.DataFrame) -> pd.DataFrame:
    """Pair AI messages with their preceding USER message.

    ``msgs`` must hold one or more sessions with columns ``session_id``,
    ``message_id``, ``type``, ``order`` (a sortable position within the session).
    Returns one row per AI message: ``session_id``, ``ai_message_id``,
    ``user_message_id`` (may be missing), ``pair_flag``, ``n_skipped_user``.
    """
    rows: list[dict[str, object]] = []
    for sid, g in msgs.sort_values(["session_id", "order"]).groupby(
        "session_id", sort=False
    ):
        convo = g[g["type"].isin(CONVERSATIONAL)]
        types = convo["type"].tolist()
        ids = convo["message_id"].tolist()
        for i, t in enumerate(types):
            if t != "AI":
                continue
            row = {
                "session_id": sid,
                "ai_message_id": ids[i],
                "user_message_id": None,
                "pair_flag": "no_preceding_user",
                "n_skipped_user": 0,
            }
            if i > 0 and types[i - 1] == "USER":
                row["user_message_id"] = ids[i - 1]
                j = i - 2
                while j >= 0 and types[j] == "USER":
                    j -= 1
                skipped = (i - 2) - j
                row["n_skipped_user"] = skipped
                row["pair_flag"] = "consecutive_user" if skipped else "clean"
            elif i > 0:
                row["pair_flag"] = "multiple_answers"
            rows.append(row)
    return pd.DataFrame(rows)
