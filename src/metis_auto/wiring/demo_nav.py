"""The demo's visible back-tracking (UI spec Stage 5, owner requirement 1b).

Responsibility: what the step indicator and the change controls show, as plain
view models (no Streamlit, UI-R02). The router itself, and the address-bar
mapping, are in ``wiring.demo_workspace``.

- Journey A is four steps: Start > Chatbot > Settings > Chat. The step the user
  is on is highlighted; every earlier step is a control that goes back to it
  (the chats stay, UI-SB03). Creating a chatbot (S03) belongs to the Chatbot
  step. Direct chat has no steps; it has one way back to the start.
- The chat workspace of a chatbot offers "change chatbot" and "change settings"
  without ending the conversation (every conversation is kept per bot).

Arrow glyphs are CSS (mirrored in RTL), not text, so a label never carries a
direction.

Traceability: FR-FIN-02 (demo UI), UI-S01..S06, UI-SB03, owner requirement
2026-11-03 (browser Back and visible back-tracking).
Called by: scripts/demo_pages/workspace.py.
Calls: wiring.demo_workspace.
"""

from __future__ import annotations

from dataclasses import dataclass

from metis_auto.wiring.demo_workspace import DemoWorkspace, Journey, Screen
from metis_auto.wiring.ui_config import Text

STEP_ORDER = (Screen.ENTRY, Screen.BOTS, Screen.SETTINGS, Screen.CHAT)
"""The steps of Journey A; S03 (create) counts as the chatbot step."""
_LABELS = {
    Screen.ENTRY: "nav_step_entry",
    Screen.BOTS: "nav_step_bots",
    Screen.SETTINGS: "nav_step_settings",
    Screen.CHAT: "nav_step_chat",
}


@dataclass(frozen=True)
class Step:
    screen: Screen
    label: str
    state: str  # "done" (a control) | "active" | "todo"

    @property
    def clickable(self) -> bool:
        return self.state == "done"


def _position(screen: Screen) -> int:
    return STEP_ORDER.index(Screen.BOTS if screen == Screen.CREATE else screen)


def journey_steps(ws: DemoWorkspace, t: Text) -> tuple[Step, ...]:
    """The indicator of Journey A (empty for the entry screen and direct chat)."""
    if ws.journey != Journey.CHATBOT:
        return ()
    here = _position(ws.screen)
    return tuple(
        Step(
            step,
            t(_LABELS[step]),
            "active" if i == here else "done" if i < here else "todo",
        )
        for i, step in enumerate(STEP_ORDER)
    )


@dataclass(frozen=True)
class ChangeControl:
    key: str  # the widget key suffix
    screen: Screen
    label: str
    icon: str


def chat_controls(ws: DemoWorkspace, t: Text) -> tuple[ChangeControl, ...]:
    """The controls above a chat: chatbot workspace -> change chatbot, change
    settings; direct chat -> back to the start."""
    if ws.journey == Journey.CHATBOT:
        return (
            ChangeControl("bot", Screen.BOTS, t("ws_change_bot"), "swap_horiz"),
            ChangeControl("settings", Screen.SETTINGS, t("ws_change_settings"), "tune"),
        )
    if ws.journey == Journey.DIRECT:
        return (ChangeControl("start", Screen.ENTRY, t("ws_back_start"), "arrow_back"),)
    return ()
