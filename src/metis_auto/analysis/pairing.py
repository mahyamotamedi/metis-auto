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

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

CONVERSATIONAL = ("USER", "AI")


@dataclass(frozen=True)
class Pair:
    ai_message_id: str
    user_message_id: str | None
    pair_flag: str
    n_skipped_user: int


def pair_ordered(types: Sequence[str], ids: Sequence[str]) -> list[Pair]:
    """Pairs for one session's USER/AI messages, already in order."""
    out: list[Pair] = []
    for i, t in enumerate(types):
        if t != "AI":
            continue
        user, flag, skipped = None, "no_preceding_user", 0
        if i > 0 and types[i - 1] == "USER":
            user = ids[i - 1]
            j = i - 2
            while j >= 0 and types[j] == "USER":
                j -= 1
            skipped = (i - 2) - j
            flag = "consecutive_user" if skipped else "clean"
        elif i > 0:
            flag = "multiple_answers"
        out.append(Pair(ids[i], user, flag, skipped))
    return out


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
        for pair in pair_ordered(convo["type"].tolist(), convo["message_id"].tolist()):
            rows.append(
                {
                    "session_id": sid,
                    "ai_message_id": pair.ai_message_id,
                    "user_message_id": pair.user_message_id,
                    "pair_flag": pair.pair_flag,
                    "n_skipped_user": pair.n_skipped_user,
                }
            )
    return pd.DataFrame(rows)
