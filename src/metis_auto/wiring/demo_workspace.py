"""The demo's application shell as state (UI spec Stage 3, §1, §3, §4.3-4.4, §5, §7).

Responsibility: everything the pages need to know about where the user is and
what they have set, with no Streamlit import (UI-R02):

- the router: the current journey (none, chatbot, direct), the screen (entry
  S01, settings S04, chat S05/S06), the selected bot, and the brand link back
  to the entry screen (UI-H02, a query parameter consumed once);
- one real ``ChatSession`` per (journey, bot), kept for the whole session, so
  switching bots or screens loses nothing (UI-A31, UI-SB04; in memory now,
  files are Stage 5); conversations of a session (UI-A30, UI-B02), each with
  the history the session sends when it is reopened;
- the three optimisation switches as the real session's configuration
  (UI-SB01..SB03: the state is read from the session, never copied), with the
  failure text of a switch that cannot change (UI-A22);
- per-bot settings (the bot's session) apart from user-level state: the
  banner's dismissal, the settings highlight, the live/fake mode (UI-SB05);
- the view models of the entry cards (UI-E03), the setting cards (UI-A20),
  the bot list (UI-A01's shape: label and facts, never content), the direct
  chat banner (UI-B04) and the model selector (UI-B02, UI-SB07).

The bots are the SYNTHETIC presets for now (``synthetic_bots``); Stage 4 swaps
the data source (``BotProfile`` stays). Demo components behind the switches are
placeholders, never evidence (ADR-0023). Every text comes from the strings
table; numbers and model ids are LTR-isolated.

Traceability: FR-FIN-02 (demo UI), FR-FEAT-03 (Persian first-class), UI-A20..A24,
UI-A30..A32, UI-B01..B05, UI-SB01..SB07, UI-E01..E05.
Called by: scripts/demo_ui.py, scripts/demo_pages/workspace.py, wiring.savings_panel.
Calls: wiring.chat, wiring.demo_ui, wiring.ui_style (ltr).
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from metis_auto.settings import LoadedSettings, SettingsError
from metis_auto.wiring.chat import (
    ChatSession,
    ClientFactory,
    CompressionMode,
    CompressorFactory,
    RoutingMode,
    SettingsLoader,
    TurnReport,
)
from metis_auto.wiring.demo_ui import Preset, text_direction
from metis_auto.wiring.ui_config import Text

TITLE_MAX = 40
"""Characters of a conversation's first message shown in the list."""
LRI, PDI = "⁦", "⁩"
SCREEN_PARAM = "screen"
ENTRY_VALUE = "entry"
COMPRESSOR_LIBRARY = "llmlingua"


class Journey(StrEnum):
    NONE = "none"
    CHATBOT = "chatbot"
    DIRECT = "direct"


class Screen(StrEnum):
    ENTRY = "entry"  # UI-S01
    SETTINGS = "settings"  # UI-S04
    CHAT = "chat"  # UI-S05 (chatbot) and UI-S06 (direct)


def _ltr(value: object) -> str:
    return f"{LRI}{value}{PDI}"


# --- bots (SYNTHETIC now; Stage 4 swaps the source) ---------------------------------


@dataclass(frozen=True)
class BotProfile:
    """What a chat needs from a bot. Content (instructions, documents) goes to
    the model only; the listing shows ``label`` and ``facts`` (UI-R05)."""

    key: str
    label: str
    language: str  # "fa" | "en"
    rag: bool
    instructions: str
    documents: tuple[str, ...]
    suggested: tuple[str, ...] = ()


def synthetic_bots(presets: Sequence[Preset]) -> tuple[BotProfile, ...]:
    """The SYNTHETIC presets as bots; the label carries the marker."""
    return tuple(
        BotProfile(
            key=p.key,
            label=f"[SYNTHETIC] {p.title}",
            language="fa" if text_direction(p.instructions) == "rtl" else "en",
            rag=bool(p.documents),
            instructions=p.instructions,
            documents=p.documents,
            suggested=p.suggested,
        )
        for p in presets
    )


@dataclass(frozen=True)
class BotCardView:
    key: str
    label: str
    facts: str
    selected: bool


# --- sessions ------------------------------------------------------------------------

SessionFactory = Callable[..., ChatSession]
"""``factory(profile | None, *, live)`` -> a fresh ``ChatSession`` with the real
defaults (bot cache off, compression off, routing on)."""


def make_session_factory(
    *,
    settings_loader: SettingsLoader | None = None,
    client_factory: ClientFactory | None = None,
    compressor_factory: CompressorFactory | None = None,
    seed_path: Path | None = None,
) -> SessionFactory:
    def factory(profile: BotProfile | None, *, live: bool = False) -> ChatSession:
        return ChatSession(
            None,
            live=live,
            instructions=profile.instructions if profile else None,
            retrieved=profile.documents if profile else (),
            settings_loader=settings_loader,
            client_factory=client_factory,
            compressor_factory=compressor_factory,
            seed_path=seed_path,
        )

    return factory


def _module_present(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def context_availability(
    load: Callable[[dict[str, Any]], LoadedSettings], t: Text
) -> tuple[bool, str | None]:
    """Can the real compressor run here? (UI-A20: else the switch is disabled
    with the reason.) Checks the optional extra and that the pinned weight files
    exist; the sha256 check happens when the compressor is built."""
    if not _module_present(COMPRESSOR_LIBRARY):
        return False, t("set_context_no_extra")
    try:
        loaded = load({})
        table = loaded.reference.compressors or {}
        ref = loaded.settings.pipeline.get("context", {}).get("compression", {})
        spec = table.get(
            ref.get("compressor", "llmlingua-2-xlm-roberta-large-meetingbank")
        )
        if spec is None:
            return False, t("set_context_no_weights")
        folder = loaded.path(loaded.settings.paths.compressor_assets) / spec.directory
        if not all((folder / f.name).is_file() for f in spec.files):
            return False, t("set_context_no_weights")
    except (SettingsError, OSError, ValueError):
        return False, t("set_context_no_weights")
    return True, None


@dataclass
class Conversation:
    number: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    history: list[Any] = field(default_factory=list)
    """The session's turns while this conversation is not the open one."""


@dataclass(frozen=True)
class Switches:
    cache: bool
    context: bool
    routing: bool


@dataclass(frozen=True)
class ModelSelector:
    label: str
    options: tuple[str, ...]
    value: str
    disabled: bool
    caption: str | None


class ChatWorkspace:
    """One (journey, bot): its ``ChatSession``, conversations and settings."""

    def __init__(
        self,
        journey: Journey,
        profile: BotProfile | None,
        session: ChatSession,
        *,
        touch: Callable[[], None] = lambda: None,
    ) -> None:
        self.journey = journey
        self.profile = profile
        self.session = session
        self._touch = touch
        self.conversations: list[Conversation] = [Conversation(1)]
        self.current_number = 1
        self.reports: list[TurnReport] = []
        """Every answered message of the session, in time order (the panel's data)."""
        self.preferred_model = session.model_id
        self._method = (
            session.routing
            if session.routing != RoutingMode.FIXED
            else RoutingMode.STICKY_V1
        )

    # --- conversations (UI-A30, UI-B02) ---

    @property
    def current(self) -> Conversation:
        return next(c for c in self.conversations if c.number == self.current_number)

    @property
    def messages(self) -> list[dict[str, Any]]:
        return self.current.messages

    def ask(self, message: str) -> TurnReport:
        if self.profile is not None:
            self.session.set_instructions(self.profile.instructions or None)
            self.session.set_retrieved(self.profile.documents)
        response, report = self.session.ask(message)
        self.messages.append({"role": "user", "text": message})
        self.messages.append(
            {"role": "assistant", "text": response.answer or "", "report": report}
        )
        self.reports.append(report)
        return report

    def _save(self) -> None:
        self.current.history = list(self.session.history)

    def new_conversation(self) -> None:
        if not self.messages:
            return
        self._save()
        self.conversations.append(Conversation(len(self.conversations) + 1))
        self.current_number = len(self.conversations)
        self.session.reset()

    def open_conversation(self, number: int) -> None:
        if number == self.current_number:
            return
        target = next(c for c in self.conversations if c.number == number)
        self._save()
        self.session.history[:] = target.history
        self.current_number = number

    def title_of(self, conversation: Conversation, t: Text) -> str:
        first = next((m["text"] for m in conversation.messages), "").strip()
        if not first:
            return t("ws_conversation_n", n=_ltr(conversation.number))
        flat = re.sub(r"\s+", " ", first)
        return flat if len(flat) <= TITLE_MAX else flat[:TITLE_MAX].rstrip() + "…"

    def listing(self, t: Text) -> list[tuple[int, str, bool]]:
        """(number, title, is the open one), newest first."""
        return [
            (c.number, self.title_of(c, t), c.number == self.current_number)
            for c in reversed(self.conversations)
        ]

    def apply(self, change: Callable[[ChatSession], None]) -> str | None:
        """Run one other session change (seed, thinking, cut-off) with the same
        failure text; used by the Advanced block."""
        return self._apply(lambda: change(self.session))

    def new_user(self) -> None:
        """Another user of the same bot (Advanced): a new session and user
        reference and an empty history, in a new conversation; instructions,
        documents and the cache are kept."""
        if self.messages:
            self._save()
            self.conversations.append(Conversation(len(self.conversations) + 1))
            self.current_number = len(self.conversations)
        self.session.new_user()

    def reset_conversation(self) -> None:
        """Forget the open conversation (the cache keeps its entries)."""
        self.messages.clear()
        self.current.history = []
        self.session.reset()

    # --- titles and the status line (UI-A32, UI-B03, UI-SB06) ---

    def title(self, t: Text) -> str:
        return self.profile.label if self.profile else t("ws_direct_title")

    def status_line(self, t: Text) -> str:
        if self.switches().routing:
            return t("ws_status_routing")
        return t("ws_status_fixed", m=_ltr(self.session.model_id))

    # --- switches (UI-A20..A22, UI-SB01..SB02) ---

    def switches(self) -> Switches:
        """Read from the real session, never stored (UI-SB01)."""
        return Switches(
            cache=self.session.bot_cache,
            context=self.session.compression != CompressionMode.OFF,
            routing=self.session.routing != RoutingMode.FIXED,
        )

    def _apply(self, change: Callable[[], None]) -> str | None:
        """Run one change; the failure text when it cannot be applied (the
        session restores its previous settings itself)."""
        try:
            change()
        except Exception as exc:  # noqa: BLE001 - shown to the user
            return str(exc)
        self._touch()
        return None

    def set_cache(self, on: bool) -> str | None:
        return self._apply(lambda: self.session.set_bot_cache(on))

    def set_context(self, on: bool) -> str | None:
        mode = CompressionMode.LLMLINGUA2 if on else CompressionMode.OFF
        if on and self.switches().context:
            return None  # already on (e.g. the labelled fake chosen in Advanced)
        return self._apply(lambda: self.session.set_compression(mode))

    def set_compression_mode(self, mode: CompressionMode) -> str | None:
        """The Advanced radio: off, the labelled fake, or LLMLingua-2."""
        return self._apply(lambda: self.session.set_compression(mode))

    @property
    def routing_method(self) -> RoutingMode:
        return (
            self.session.routing
            if self.session.routing != RoutingMode.FIXED
            else self._method
        )

    def set_routing(self, on: bool) -> str | None:
        if on == self.switches().routing:
            return None
        if on:
            return self._apply(lambda: self.session.set_routing(self._method))
        return self._apply(lambda: self.session.switch_model(self.preferred_model))

    def set_routing_method(self, mode: RoutingMode) -> str | None:
        if mode == RoutingMode.FIXED:
            raise ValueError("fixed is the routing switch turned off")
        previous = self._method
        self._method = mode
        if not self.switches().routing:
            return None  # remembered for when routing is turned on
        error = self._apply(lambda: self.session.set_routing(mode))
        if error:
            self._method = previous
        return error

    def set_router_mode(self, mode: str) -> str | None:
        return self._apply(lambda: self.session.set_router_mode(mode))

    def set_preferred_model(self, model: str) -> str | None:
        previous = self.preferred_model
        self.preferred_model = model
        if self.switches().routing:
            return None  # greyed while routing decides (UI-B02)
        error = self._apply(lambda: self.session.switch_model(model))
        if error:
            self.preferred_model = previous
        return error

    def model_selector(self, t: Text) -> ModelSelector:
        options = tuple(
            e.model_id
            for e in self.session.loaded.reference.catalogue.entries
            if e.enabled
        )
        if self.switches().routing:
            return ModelSelector(
                t("ws_preferred_model"),
                options,
                self.preferred_model,
                True,
                t("ws_routing_chooses"),
            )
        return ModelSelector(t("model"), options, self.session.model_id, False, None)


# --- the application state ------------------------------------------------------------


class DemoWorkspace:
    def __init__(
        self,
        bots: Sequence[BotProfile],
        *,
        session_factory: SessionFactory,
        context_check: Callable[[ChatSession, Text], tuple[bool, str | None]]
        | None = None,
    ) -> None:
        self.bots = tuple(bots)
        self._factory = session_factory
        self._context_check = context_check or (
            lambda session, t: context_availability(lambda _o: session.loaded, t)
        )
        self.journey = Journey.NONE
        self.screen = Screen.ENTRY
        self.bot_key: str | None = None
        self.live = False
        self.banner_dismissed = False
        self.settings_focus = False
        self._chats: dict[tuple[Journey, str | None], ChatWorkspace] = {}
        self._shell: ChatSession | None = None

    # --- router ---

    def choose_journey(self, journey: Journey) -> None:
        if journey == Journey.NONE:
            self.go_entry()
            return
        self.journey = journey
        if journey == Journey.CHATBOT:
            self.bot_key = self.bot_key or self.bots[0].key
            self.screen = Screen.SETTINGS
        else:
            self.bot_key = None
            self.screen = Screen.CHAT

    def go_entry(self) -> None:
        self.journey, self.screen, self.bot_key = Journey.NONE, Screen.ENTRY, None

    def select_bot(self, key: str) -> None:
        if key not in {b.key for b in self.bots}:
            raise ValueError(f"unknown bot {key!r}")
        self.bot_key = key

    def start_chatting(self) -> None:
        self.screen = Screen.CHAT

    def chat_target(self) -> Screen:
        """Where the header's Chat tab goes: the current workspace, else S01."""
        return Screen.ENTRY if self.journey == Journey.NONE else self.screen

    def consume_query(self, params: Mapping[str, object]) -> bool:
        """The brand link (``?screen=entry``): True once when it sent us home."""
        value = params.get(SCREEN_PARAM)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value == ENTRY_VALUE:
            self.go_entry()
            return True
        return False

    # --- the chats ---

    def _profile(self) -> BotProfile | None:
        if self.journey != Journey.CHATBOT:
            return None
        return next(b for b in self.bots if b.key == self.bot_key)

    def current(self) -> ChatWorkspace:
        if self.journey == Journey.NONE:
            raise ValueError("no journey chosen: there is no chat to show")
        key = (self.journey, self.bot_key)
        if key not in self._chats:
            profile = self._profile()
            self._chats[key] = ChatWorkspace(
                self.journey,
                profile,
                self._factory(profile, live=self.live),
                touch=self._used_a_switch,
            )
        return self._chats[key]

    def header_session(self) -> ChatSession:
        """The session whose budget and mode the header shows."""
        if self.journey != Journey.NONE:
            return self.current().session
        if self._shell is None:
            self._shell = self._factory(None, live=self.live)
        return self._shell

    def ask(self, message: str) -> TurnReport:
        return self.current().ask(message)

    def new_conversation(self) -> None:
        self.current().new_conversation()

    def open_conversation(self, number: int) -> None:
        self.current().open_conversation(number)

    def set_live(self, live: bool) -> str | None:
        """Switch fake/live for the whole run (user-level). Every session is
        rebuilt, so conversations are cleared as before Stage 3; the failure
        text when live cannot start (nothing changes then)."""
        try:
            probe = self._factory(self._profile(), live=live)
        except (SettingsError, ValueError) as exc:
            return str(exc).removeprefix("live calls refused: ")
        self.live = live
        self._chats.clear()
        self._shell = None
        if self.journey != Journey.NONE:
            self._chats[(self.journey, self.bot_key)] = ChatWorkspace(
                self.journey, self._profile(), probe, touch=self._used_a_switch
            )
        else:
            self._shell = probe
        return None

    # --- user-level state (UI-SB05) ---

    def dismiss_banner(self) -> None:
        self.banner_dismissed = True

    def open_settings(self) -> None:
        self.settings_focus = True

    def _used_a_switch(self) -> None:
        self.settings_focus = False

    # --- views ---

    def bot_cards(self, t: Text) -> tuple[BotCardView, ...]:
        selected = self.bot_key if self.journey == Journey.CHATBOT else None
        return tuple(
            BotCardView(
                b.key,
                b.label,
                f"{t('ws_lang_' + b.language)} · "
                + t("ws_rag_yes" if b.rag else "ws_rag_no"),
                b.key == selected,
            )
            for b in self.bots
        )

    def context_available(self, t: Text) -> tuple[bool, str | None]:
        return self._context_check(self.current().session, t)


# --- view models: entry, settings, banner


@dataclass(frozen=True)
class EntryCard:
    journey: Journey
    icon: str
    title: str
    text: str
    cta: str


def entry_cards(t: Text) -> tuple[EntryCard, ...]:
    """The two journey cards of S01 (UI-E02, UI-E03): neutral Material icons."""
    return (
        EntryCard(
            Journey.CHATBOT,
            "smart_toy",
            t("entry_chatbot_title"),
            t("entry_chatbot_text"),
            t("entry_chatbot_cta"),
        ),
        EntryCard(
            Journey.DIRECT,
            "forum",
            t("entry_direct_title"),
            t("entry_direct_text"),
            t("entry_direct_cta"),
        ),
    )


@dataclass(frozen=True)
class SettingCard:
    key: str  # cache | context | routing
    name: str
    text: str
    on: bool
    enabled: bool
    disabled_reason: str | None
    chip: str
    caption: str | None


def setting_cards(
    ws: ChatWorkspace,
    t: Text,
    *,
    context_available: tuple[bool, str | None] | None = None,
) -> tuple[SettingCard, ...]:
    """The three cards of S04 and the sidebar (UI-A20): name, plain
    explanation, switch state and chip. Cache says that semantic matching is not
    available; context optimisation is disabled with its reason when the
    compressor cannot run (unless it is already on, so it can be turned off)."""
    state = ws.switches()
    available, reason = context_available or context_availability(
        lambda _o: ws.session.loaded, t
    )
    chip = {True: t("set_on"), False: t("set_off")}
    experimental = t("set_context_experimental")
    return (
        SettingCard(
            "cache",
            t("set_cache_name"),
            t("set_cache_text"),
            state.cache,
            True,
            None,
            chip[state.cache],
            t("set_cache_caption"),
        ),
        SettingCard(
            "context",
            t("set_context_name"),
            t("set_context_text"),
            state.context,
            available or state.context,
            None if available or state.context else reason,
            chip[state.context],
            experimental if available or state.context else None,
        ),
        SettingCard(
            "routing",
            t("set_routing_name"),
            t("set_routing_text"),
            state.routing,
            True,
            None,
            chip[state.routing],
            None,
        ),
    )


@dataclass(frozen=True)
class Banner:
    text: str
    link: str
    dismiss: str


def banner_for(ws: DemoWorkspace, t: Text) -> Banner | None:
    """The direct chat's cost-saving banner (UI-B04): shown on entering direct
    chat until dismissed; the dismissal is remembered for the session."""
    if ws.journey != Journey.DIRECT or ws.banner_dismissed:
        return None
    return Banner(
        t("ws_banner_direct"), t("ws_banner_settings"), t("ws_banner_dismiss")
    )
