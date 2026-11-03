"""The demo's local files: user-made chatbots and conversation history (UI spec
Stage 5: UI-A10, UI-A31, UI-R11).

Responsibility: read and write two kinds of small JSON files under one root
folder, ``runs/demo/`` (git-ignored; the files may hold the user's own text, so
nothing here logs, prints or puts them in an error):

- ``bots/<id>.json``: a chatbot made on the create screen (name, instructions,
  knowledge passages);
- ``conversations/<journey>__<bot>__<n>.json``: one file per conversation (the
  messages of one chat, so the history survives a demo restart).

A file that is missing, unreadable or not what we wrote is skipped and counted,
never raised: the page shows "n files could not be read" (UI-K05). Writes are
atomic (temporary file, then rename) so a crash cannot leave half a file.

Traceability: UI-A10, UI-A31, UI-R11, FR-FIN-02 (demo UI).
Called by: wiring.demo_workspace, scripts/demo_ui.py.
Calls: nothing in the package (pure file input and output).
"""

from __future__ import annotations

import json
import os
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMAT_VERSION = 1
BOT_ID_PREFIX = "mine-"
"""A user-made bot's key starts with this, so it never clashes with ``bot-007``
(a dataset label) or a synthetic preset key."""
NAME_MAX = 60
INSTRUCTIONS_MAX = 8000
PASSAGE_MAX = 8000
PASSAGES_MAX = 10
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_BOT_ID = re.compile(rf"^{BOT_ID_PREFIX}[0-9a-f]{{8}}$")


def default_root() -> Path:
    """``<checkout>/runs/demo``; tests replace this function."""
    return Path(__file__).resolve().parents[3] / "runs" / "demo"


@dataclass(frozen=True)
class UserBot:
    """A chatbot the user made (UI-A10). Local only; ``name`` is shown, the
    instructions and passages go to the model and nowhere else."""

    id: str
    name: str
    instructions: str
    passages: tuple[str, ...]

    def __repr__(self) -> str:
        return f"UserBot({self.id})"


@dataclass(frozen=True)
class StoredConversation:
    number: int
    messages: tuple[dict[str, Any], ...]


class BotFormError(ValueError):
    """The create form cannot be saved; ``code`` is a strings-table suffix."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def clean_passages(passages: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(p.strip() for p in passages if p and p.strip())


def validate_bot(
    name: str, instructions: str, passages: list[str] | tuple[str, ...]
) -> UserBot:
    """The form's rules (UI-A10): a name, instructions or at least one passage,
    and the size limits. Raises ``BotFormError`` with a strings key suffix."""
    name = " ".join((name or "").split())
    instructions = (instructions or "").strip()
    kept = clean_passages(passages)
    if not name:
        raise BotFormError("name")
    if len(name) > NAME_MAX:
        raise BotFormError("name_long")
    if not instructions and not kept:
        raise BotFormError("empty")
    if len(instructions) > INSTRUCTIONS_MAX or any(len(p) > PASSAGE_MAX for p in kept):
        raise BotFormError("long")
    if len(kept) > PASSAGES_MAX:
        raise BotFormError("many")
    return UserBot("", name, instructions, kept)


def _safe(part: str) -> str:
    return _UNSAFE.sub("_", part)[:80] or "_"


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != FORMAT_VERSION:
        return None
    return data


class DemoStore:
    """The two folders under one root. Every method that reads returns the
    number of files it had to skip as its second value."""

    def __init__(
        self,
        root: Path,
        *,
        new_id: Callable[[], str] = lambda: secrets.token_hex(4),
    ) -> None:
        self.root = Path(root)
        self._new_id = new_id

    def __repr__(self) -> str:
        return "DemoStore()"

    # --- bots (UI-A10) ---

    @property
    def _bots(self) -> Path:
        return self.root / "bots"

    def save_bot(
        self, name: str, instructions: str, passages: list[str] | tuple[str, ...]
    ) -> UserBot:
        checked = validate_bot(name, instructions, passages)
        bot = UserBot(
            f"{BOT_ID_PREFIX}{self._new_id()}",
            checked.name,
            checked.instructions,
            checked.passages,
        )
        _write(
            self._bots / f"{bot.id}.json",
            {
                "version": FORMAT_VERSION,
                "id": bot.id,
                "name": bot.name,
                "instructions": bot.instructions,
                "passages": list(bot.passages),
            },
        )
        return bot

    def load_bots(self) -> tuple[list[UserBot], int]:
        found: list[UserBot] = []
        skipped = 0
        for path in sorted(self._bots.glob("*.json")) if self._bots.is_dir() else []:
            data = _read(path)
            try:
                if data is None or not _BOT_ID.match(str(data["id"])):
                    raise ValueError
                checked = validate_bot(
                    str(data["name"]),
                    str(data["instructions"]),
                    [str(p) for p in data["passages"]],
                )
                found.append(
                    UserBot(
                        data["id"],
                        checked.name,
                        checked.instructions,
                        checked.passages,
                    )
                )
            except (KeyError, TypeError, ValueError, BotFormError):
                skipped += 1
        return found, skipped

    # --- conversations (UI-A31) ---

    @property
    def _conversations(self) -> Path:
        return self.root / "conversations"

    def _conversation_path(self, journey: str, bot: str | None, number: int) -> Path:
        return self._conversations / (
            f"{_safe(journey)}__{_safe(bot or 'direct')}__{number}.json"
        )

    def save_conversation(
        self,
        journey: str,
        bot: str | None,
        number: int,
        messages: list[dict[str, Any]],
    ) -> None:
        """One file per conversation; only role, text and the model id of an
        answer are kept (no cost report, no trace)."""
        kept = []
        for m in messages:
            item = {"role": str(m["role"]), "text": str(m["text"])}
            model = getattr(m.get("report"), "model_id", None) or m.get("model")
            if item["role"] == "assistant" and model:
                item["model"] = str(model)
            kept.append(item)
        _write(
            self._conversation_path(journey, bot, number),
            {
                "version": FORMAT_VERSION,
                "journey": journey,
                "bot": bot,
                "number": number,
                "messages": kept,
            },
        )

    def delete_conversation(self, journey: str, bot: str | None, number: int) -> None:
        self._conversation_path(journey, bot, number).unlink(missing_ok=True)

    def load_conversations(
        self, journey: str, bot: str | None
    ) -> tuple[list[StoredConversation], int]:
        """The saved conversations of one (journey, bot), numbered as saved."""
        prefix = f"{_safe(journey)}__{_safe(bot or 'direct')}__"
        found: dict[int, StoredConversation] = {}
        skipped = 0
        folder = self._conversations
        for path in sorted(folder.glob(f"{prefix}*.json")) if folder.is_dir() else []:
            data = _read(path)
            try:
                if data is None or data["journey"] != journey or data["bot"] != bot:
                    raise ValueError
                number = int(data["number"])
                messages = tuple(
                    {
                        k: str(m[k])
                        for k in ("role", "text", "model")
                        if k in m and m[k] is not None
                    }
                    for m in data["messages"]
                )
                if number < 1 or any(
                    m.get("role") not in ("user", "assistant") or "text" not in m
                    for m in messages
                ):
                    raise ValueError
                found[number] = StoredConversation(number, messages)
            except (KeyError, TypeError, ValueError):
                skipped += 1
        return [found[n] for n in sorted(found)], skipped
