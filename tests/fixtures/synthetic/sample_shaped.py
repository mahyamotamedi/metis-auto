"""SYNTHETIC data in the sample file's *shape* (Stage 8 loader tests).

Every string is marked ``[SYNTHETIC]``; nothing is copied from the sample.
The shape mirrors what the sample loader must handle (contracts.md §4):
categories with sessions, ``user``/``bot`` roles, answer-side ``model``,
``provider``, ``instructions``, optional ``rag`` and ``input``, user-side
``attachments``, nulls that occur together, an empty instruction string,
answers with no preceding user message, consecutive user messages, several
answers to one user message, and a trailing unanswered message.
"""

from __future__ import annotations

import json
from pathlib import Path

S = "[SYNTHETIC]"
INSTR = f"{S} You are a shop assistant. پاسخ کوتاه بده."


def bot(
    text,
    *,
    model="gpt-4o-mini",
    provider="openai_chat_completion",
    instructions=INSTR,
    ts="2026-05-01T10:00:05",
    **extra,
):
    m = {
        "role": "bot",
        "content": f"{S} {text}",
        "timestamp": ts,
        "model": model,
        "provider": provider,
        "instructions": instructions,
    }
    m.update(extra)
    return m


def user(text, ts="2026-05-01T10:00:00", **extra):
    m = {"role": "user", "content": f"{S} {text}", "timestamp": ts}
    m.update(extra)
    return m


def sessions() -> list[dict]:
    ctx = {"query": f"{S} q", "context": [f"{S} doc one", f"{S} doc two"]}
    return [
        {
            "category": f"{S} category A",
            "sessions": [
                {  # clean pairs; a repeated question; retrieved context
                    "session_id": "syn-0001",
                    "created_at": "2026-05-01T09:59:00",
                    "session_len": 4,
                    "user_turns": 2,
                    "bot_turns": 2,
                    "messages": [
                        user("سلام، سفارش من کی می‌رسد؟", "2026-05-01T10:00:00"),
                        bot("answer one", ts="2026-05-01T10:00:03", rag=ctx),
                        user("سلام، سفارش من کی می‌رسد؟", "2026-05-01T10:01:00"),
                        bot("answer one", ts="2026-05-01T10:01:03", rag=ctx),
                    ],
                },
                {  # opening bot message; consecutive users; two answers; nulls
                    "session_id": "syn-0002",
                    "created_at": "2026-05-02T09:00:00",
                    "session_len": 6,
                    "user_turns": 3,
                    "bot_turns": 3,
                    "messages": [
                        bot("welcome", ts="2026-05-02T09:00:00"),
                        user("first", "2026-05-02T09:00:10"),
                        user("سلام، سفارش من کی می‌رسد؟", "2026-05-02T09:00:20"),
                        bot(
                            "answer two a",
                            ts="2026-05-02T09:00:25",
                            model=None,
                            provider=None,
                            instructions=None,
                        ),
                        bot(
                            "answer two b",
                            ts="2026-05-02T09:00:26",
                            model=None,
                            provider=None,
                            instructions=None,
                        ),
                        user("thanks   bye", "2026-05-02T09:01:00"),
                    ],
                },
            ],
        },
        {
            "category": f"{S} category B",
            "sessions": [
                {  # attachments; structured input; empty instructions
                    "session_id": "syn-0003",
                    "created_at": "2026-05-03T08:00:00",
                    "session_len": 4,
                    "user_turns": 2,
                    "bot_turns": 2,
                    "messages": [
                        user(
                            "look at this",
                            "2026-05-03T08:00:00",
                            attachments=[
                                {"contentType": "IMAGE", "content": f"{S} locator"}
                            ],
                        ),
                        bot(
                            "an image answer",
                            ts="2026-05-03T08:00:04",
                            model="claude-sonnet-4-6",
                            provider="anthropic",
                            instructions="",
                        ),
                        user("THANKS bye", "2026-05-03T08:01:00"),
                        bot(
                            "bye",
                            ts="2026-05-03T08:01:02",
                            model="default",
                            provider="workflow",
                            input={"items": [{"kind": "x"}]},
                        ),
                    ],
                },
            ],
        },
    ]


def write(path: Path) -> Path:
    path.write_text(json.dumps(sessions(), ensure_ascii=False), encoding="utf-8")
    return path
