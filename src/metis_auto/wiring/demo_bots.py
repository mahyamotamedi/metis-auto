"""The demo's real bots as content-free cards (UI spec Stage 4: UI-A01..A05, A33).

Responsibility: read the local database's bot table through ``data_access`` and
return ``BotCard`` records (a stable label ``bot-001`` ranked by traffic, and
derived facts), keep each bot's real id inside this module, and hand a chat the
bot's instructions and passages only when a ``ChatSession`` is built.

Licence (UI-R05, ADR-0030): the dataset may not be redistributed. A card holds
no id, no instruction and no passage text; ``BotDirectory`` and ``BotProfile``
print no content; ``content()`` is the only door to it and it feeds the model
request, never a page, a log or an error. Live use of this content needs the
owner's approval (``real_data_reasons``).

Passages for a typed question are Option A (UI-A33): the chunk set of the bot's
most recent logged AI turn that has retrieved chunks, read once per bot and kept
for the session. Bots without RAG send instructions only. Option B (search over
the bot's chunk pool) is not built.

Workflow bots (provider ``workflow``, no token billing in the export) are not
LLM bots and are not listed; their number is shown. The language of the
instructions is the existing heuristic label (``analysis.text_features``), so it
is a signal, not ground truth.

Traceability: FR-FIN-02 (demo UI), UI-A01..A06, UI-A33, UI-R05, UI-R06, A-84.
Called by: wiring.demo_workspace, scripts/demo_ui.py.
Calls: data_access.postgres.repository, wiring.database, wiring.demo_ui
(live_check), analysis.text_features.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from metis_auto.analysis.text_features import language_label
from metis_auto.settings import LoadedSettings, SettingsError
from metis_auto.wiring.demo_ui import live_check
from metis_auto.wiring.ui_config import Text

PAGE_SIZE = 50
"""Bots shown at a time in the list (about 600 bots; "more" adds a page)."""
NON_LLM_PROVIDERS = frozenset({"workflow"})
"""Provider names of bots that are not LLM bots (full EDA: 29.7% of requests
belong to workflow/default bots with no token billing). Checked 2026-11-03."""
LANGUAGES = ("fa", "en", "mixed", "other", "none")
_LABEL_TO_LANGUAGE = {"fa": "fa", "en": "en", "fa_en_mixed": "mixed", "empty": "none"}
LABEL_PREFIX = "bot-"
LOGGED_TURN = "dataset_positions"
"""The context layout a real bot's request is sent in (A-84)."""


class BotSource(Protocol):
    """What the directory needs from a store (the database, or a test stand-in)."""

    def directory_rows(self) -> list[Mapping[str, Any]]: ...

    def instructions(self, bot_id: str) -> str | None: ...

    def rag_texts(self, bot_id: str) -> list[str]: ...


class BotContentError(RuntimeError):
    """The bot's instructions or passages could not be read. No detail: a
    database message may name a user or a host."""


@dataclass(frozen=True)
class BotProfile:
    """What a chat needs from a bot. Content (instructions, documents) goes to
    the model only; the listing shows ``label`` and facts (UI-R05). A real bot's
    content is loaded on first use, once (``content``)."""

    key: str
    label: str
    language: str  # "fa" | "en" | ...
    rag: bool
    instructions: str
    documents: tuple[str, ...]
    suggested: tuple[str, ...] = ()
    real: bool = False
    loader: Callable[[], tuple[str, tuple[str, ...]]] | None = field(
        default=None, repr=False, compare=False
    )
    _loaded: dict[str, tuple[str, tuple[str, ...]]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def content(self) -> tuple[str, tuple[str, ...]]:
        """(instructions, documents) for the model request. A real bot reads
        them once; a synthetic one holds them."""
        if self.loader is None:
            return self.instructions, self.documents
        if "content" not in self._loaded:
            try:
                self._loaded["content"] = self.loader()
            except Exception as exc:  # noqa: BLE001 - never show a database message
                raise BotContentError(type(exc).__name__) from None
        return self._loaded["content"]


@dataclass(frozen=True)
class BotCard:
    """Derived facts of one bot (UI-A01, UI-A04). No id, no content."""

    label: str
    rank: int
    language: str
    rag: bool
    rag_top_k: int | None
    memory: bool
    summariser: bool
    model: str | None
    instruction_chars: int
    sessions: int
    requests: int


class BotDirectory:
    """The listed bots and, privately, their real ids."""

    def __init__(
        self,
        cards: Sequence[BotCard] = (),
        *,
        ids: Mapping[str, str] | None = None,
        source: BotSource | None = None,
        excluded_workflow: int = 0,
        error: str | None = None,
    ) -> None:
        self.cards = tuple(cards)
        self.excluded_workflow = excluded_workflow
        self.error = error
        self._ids = dict(ids or {})
        self._source = source
        self._profiles: dict[str, BotProfile] = {}

    def __repr__(self) -> str:
        return f"BotDirectory({len(self.cards)} bots)"

    @property
    def available(self) -> bool:
        return self.error is None

    def card(self, label: str) -> BotCard | None:
        return next((c for c in self.cards if c.label == label), None)

    def profile(self, label: str) -> BotProfile:
        """The chat profile of a listed bot; its content is read on first use."""
        if label not in self._ids or self._source is None:
            raise ValueError(f"unknown bot {label!r}")
        if label not in self._profiles:
            card = self.card(label)
            assert card is not None
            self._profiles[label] = BotProfile(
                key=label,
                label=label,
                language=card.language,
                rag=card.rag,
                instructions="",
                documents=(),
                real=True,
                loader=_content_loader(self._source, self._ids[label], card.rag),
            )
        return self._profiles[label]


def _content_loader(source: BotSource, bot_id: str, rag: bool):
    def load() -> tuple[str, tuple[str, ...]]:
        instructions = source.instructions(bot_id) or ""
        documents = tuple(source.rag_texts(bot_id)) if rag else ()
        return instructions, documents

    return load


def _language(instructions: str) -> str:
    if not instructions.strip():
        return "none"
    return _LABEL_TO_LANGUAGE.get(language_label(instructions), "other")


def load_directory(source_factory: Callable[[], BotSource]) -> BotDirectory:
    """Build the directory; a store that cannot be read gives the unavailable
    state (the page shows "start the local database"), never an exception."""
    try:
        source = source_factory()
        rows = source.directory_rows()
    except Exception as exc:  # noqa: BLE001 - the text may name a user or host
        return BotDirectory(error=type(exc).__name__)
    used = [r for r in rows if (r["sessions"] or 0) > 0]
    workflow = sum(1 for r in used if r["provider_name"] in NON_LLM_PROVIDERS)
    kept = []
    for r in used:
        if r["provider_name"] in NON_LLM_PROVIDERS:
            continue
        has_text = bool((r["instructions"] or "").strip())
        rag = r["corpus_ids_state"] == "ok"
        if has_text or rag:
            kept.append(r)
    kept.sort(key=lambda r: (-(r["requests"] or 0), -(r["sessions"] or 0), r["bot_id"]))
    cards, ids = [], {}
    for rank, r in enumerate(kept, start=1):
        text = r["instructions"] or ""
        label = f"{LABEL_PREFIX}{rank:03d}"
        rag = r["corpus_ids_state"] == "ok"
        mode = r["summarizer_mode"]
        cards.append(
            BotCard(
                label=label,
                rank=rank,
                language=_language(text),
                rag=rag,
                rag_top_k=r["rag_top_k"] if rag else None,
                memory=bool(r["memory_enabled"]),
                summariser=mode not in (None, "", "IGNORE"),
                model=r["provider_model"] or None,
                instruction_chars=len(text) if text.strip() else 0,
                sessions=int(r["sessions"] or 0),
                requests=int(r["requests"] or 0),
            )
        )
        ids[label] = r["bot_id"]
    return BotDirectory(cards, ids=ids, source=source, excluded_workflow=workflow)


class PostgresBotSource:
    """The local database as a ``BotSource`` (through ``data_access`` only). Each
    read opens its own engine and disposes it, so no connection is held between
    the list and a chat."""

    def __init__(self, engine_factory: Callable[[], Any] | None = None) -> None:
        if engine_factory is None:
            from metis_auto.wiring.database import engine_from_settings

            engine_factory = engine_from_settings
        self._factory = engine_factory

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        engine = self._factory()
        try:
            with engine.connect() as conn:
                yield conn
        finally:
            engine.dispose()

    def directory_rows(self) -> list[Mapping[str, Any]]:
        from metis_auto.data_access.postgres import repository as repo

        with self._connect() as conn:
            return repo.bot_directory_rows(conn)

    def instructions(self, bot_id: str) -> str | None:
        from metis_auto.data_access.postgres import repository as repo

        with self._connect() as conn:
            return repo.bot_instructions(conn, bot_id)

    def rag_texts(self, bot_id: str) -> list[str]:
        from metis_auto.data_access.postgres import repository as repo

        with self._connect() as conn:
            return repo.latest_rag_texts(conn, bot_id)


# --- search and filters (UI-A02) ----------------------------------------------------


def filter_cards(
    cards: Sequence[BotCard],
    *,
    query: str = "",
    language: str | None = None,
    rag: bool | None = None,
    memory: bool | None = None,
    has_instructions: bool | None = None,
) -> tuple[BotCard, ...]:
    """Search over the label (never over content) and the four filters, keeping
    the traffic order. ``None`` means no filter."""
    needle = re.sub(r"\s+", "", query).lower()
    out = []
    for c in cards:
        if needle and needle not in c.label.lower():
            continue
        if language is not None and c.language != language:
            continue
        if rag is not None and c.rag != rag:
            continue
        if memory is not None and c.memory != memory:
            continue
        if (
            has_instructions is not None
            and (c.instruction_chars > 0) != has_instructions
        ):
            continue
        out.append(c)
    return tuple(out)


# --- live with a real bot (UI-R05, UI-R06) -------------------------------------------


Loader = Callable[[dict[str, Any]], LoadedSettings]


def real_data_reasons(load: Loader, t: Text) -> tuple[str, ...]:
    """Every reason a live call carrying a real bot's content may not start:
    the usual live reasons (``live.enabled``, the key, the caps) and the owner's
    ``golden_answers.real_data_approved``. Empty means all three are present."""
    _allowed, reasons = live_check(load)
    out = list(reasons)
    try:
        approved = load({}).settings.golden_answers.real_data_approved
    except SettingsError:
        approved = False  # live_check already says why settings cannot load
    if not approved:
        out.append(t("live_real_needs_approval"))
    return tuple(out)
