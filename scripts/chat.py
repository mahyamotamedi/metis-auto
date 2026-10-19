"""A thin command-line chat over the real pipeline (Stage 7.5; Demo milestone A).

    python scripts/chat.py --fake                          # offline, sticky v1
    python scripts/chat.py --fake --instructions "[SYNTHETIC] Shop bot."
    python scripts/chat.py --fake --retrieved docs.txt     # blocks split by ---
    python scripts/chat.py                                 # live (if enabled)
    python scripts/chat.py --model gpt-4o-mini             # fixed model

Keeps the history (sent every turn, P-8, with who produced each answer) and
after each answer prints: the routing decision and its reason (anchored,
stayed, re-routed, greeting, escalated), the features it read, served by,
model and the provider-reported model, the cache lookups, tokens (with
fidelity), cost, the premium-baseline estimate, the savings decomposition
(routing, compression, cache, provider cache; message and session),
compression, Metis overhead, the budget, and the current settings.

Commands:
  /mode sticky | per_request          routing mode (sticky = sticky routing v1)
  /model <id>                          fixed routing to one model; /models lists them
  /compress off | on | fake            LLMLingua-2 (EXPERIMENTAL) or a labelled fake
  /botcache on | off                   DEMO bot-level cache scope (shared by users)
  /seed on | off | list                DEMO seed of logged sample answers (local only)
  /thinking on | off                   DeepSeek thinking (on = provider default)
  /newuser                             another user of the same bot
  /instructions <text>                 change the bot's instructions
  /degrade                             fake mode: truncate the next answer (escalation)
  /reset, /budget, /settings, /help, /quit

Live calls need both keys: this script asks for ``live`` (unless --fake);
config/local.toml must set ``[live] enabled = true``, and METIS_API_KEY must
be in .env. Use only your own or synthetic messages (ADR-0018): never paste
sample conversations. The demo seed's logged answers are shown locally and
never sent to a provider. Every live call goes through the spend guard, the
persistent ledger (data/spend/ledger.jsonl), and the recording decorator
(data/recorded/). Thin wrapper: the logic is in metis_auto.wiring.chat.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from metis_auto.settings import SettingsError
from metis_auto.wiring.chat import (
    ChatSession,
    CompressionMode,
    RoutingMode,
    format_report,
)

HELP = __doc__.split("Commands:")[1].split("Live calls")[0].rstrip()
ON_OFF = {"on": True, "off": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="Chat over the Metis-Auto pipeline")
    parser.add_argument("--model", default=None, help="fixed target model")
    parser.add_argument(
        "--mode",
        choices=[m.value for m in RoutingMode if m != RoutingMode.FIXED],
        default=RoutingMode.STICKY_V1.value,
        help="routing mode when no --model is given",
    )
    parser.add_argument("--fake", action="store_true", help="offline fake answers")
    parser.add_argument("--instructions", default=None, help="bot instructions")
    parser.add_argument(
        "--retrieved",
        type=Path,
        default=None,
        help="a text file of retrieved documents, separated by lines of ---",
    )
    parser.add_argument(
        "--allow-unknown-window",
        action="store_true",
        help="diagnostics: allow models whose context window is unknown (Grok)",
    )
    args = parser.parse_args()

    retrieved: list[str] = []
    if args.retrieved is not None:
        text = args.retrieved.read_text(encoding="utf-8")
        retrieved = [b.strip() for b in text.split("\n---\n") if b.strip()]
    try:
        session = ChatSession(
            args.model,
            live=not args.fake,
            instructions=args.instructions,
            retrieved=retrieved,
            allow_unknown_window=args.allow_unknown_window,
            routing=None if args.model else RoutingMode(args.mode),
        )
    except (SettingsError, ValueError) as exc:
        print(f"cannot start: {exc}")
        if not args.fake:
            print("try --fake for an offline session, or see the docstring")
        return 1
    kind = "FAKE (offline)" if args.fake else "LIVE (budgeted)"
    print(f"{kind} chat, run {session.run_id}. /help for commands.")
    print("settings: " + ", ".join(f"{k} {v}" for k, v in session.settings().items()))

    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.startswith("/"):
            try:
                if _command(session, line):
                    return 0
            except (SettingsError, ValueError) as exc:
                print(f"cannot do that: {exc}")
            continue
        response, report = session.ask(line)
        print(f"\nassistant> {response.answer if response.answer else '(no answer)'}")
        print(format_report(report))
        if report.live_stopped:
            print("Live calls are stopped for this run; restart the chat.")
            return 1


def _toggle(arg: str) -> bool:
    if arg not in ON_OFF:
        raise ValueError("say on or off")
    return ON_OFF[arg]


def _command(session: ChatSession, line: str) -> bool:
    """Run a /command; True means quit."""
    name, _, arg = line.partition(" ")
    arg = arg.strip()
    if name in ("/quit", "/exit"):
        return True
    if name == "/help":
        print(HELP)
    elif name == "/models":
        for e in session.loaded.reference.catalogue.entries:
            window = e.context_window.value or "unknown"
            note = "" if e.enabled else " (disabled)"
            print(f"  {e.model_id:<18} tier {e.tier}  window {window}{note}")
    elif name == "/model":
        session.switch_model(arg)
        print(f"fixed routing: {session.model_id}")
    elif name == "/mode":
        modes = {"sticky": RoutingMode.STICKY_V1, "sticky_v1": RoutingMode.STICKY_V1}
        modes["per_request"] = RoutingMode.PER_REQUEST
        if arg not in modes:
            raise ValueError("say sticky or per_request")
        session.set_routing(modes[arg])
        print(f"routing mode: {session.routing.value}")
    elif name == "/compress":
        modes = {"on": CompressionMode.LLMLINGUA2, "off": CompressionMode.OFF}
        modes["fake"] = CompressionMode.FAKE
        if arg not in modes:
            raise ValueError("say on, off, or fake")
        if modes[arg] == CompressionMode.LLMLINGUA2:
            print("loading LLMLingua-2 (EXPERIMENTAL; a few seconds on CPU) ...")
        session.set_compression(modes[arg])
        print(f"compression: {session.compression.value}")
    elif name == "/botcache":
        session.set_bot_cache(_toggle(arg))
        print(
            "cache scope: "
            + (
                "bot-level [DEMO setting, not the serving default]"
                if session.bot_cache
                else "session"
            )
        )
    elif name == "/seed":
        if arg == "list":
            questions = session.seeded or ()
            print(
                f"{len(questions)} seeded questions (SAMPLE CONTENT: local only; "
                "never paste them into docs, commits, or a live chat):"
            )
            for q in questions:
                print(f"  - {q}")
        else:
            session.set_seed(_toggle(arg))
            count = len(session.seeded or ())
            print(
                f"demo seed: {'on' if session.seed else 'off'} ({count} logged "
                "first-turn answers; served on an exact match, shown locally only)"
            )
    elif name == "/thinking":
        session.set_deepseek_thinking(_toggle(arg))
        state = "on (provider default)" if session.deepseek_thinking else "off"
        print(f"DeepSeek thinking: {state}")
    elif name == "/newuser":
        session.new_user()
        print(f"new user {session.users} of the same bot (history cleared)")
    elif name == "/instructions":
        session.set_instructions(arg or None)
        print("instructions " + ("set" if arg else "cleared"))
    elif name == "/degrade":
        session.degrade_next()
        print("the next model answer will come back truncated (fake mode)")
    elif name == "/reset":
        session.reset()
        print("history cleared")
    elif name == "/budget":
        print(session.budget() or "no budget configured")
    elif name == "/settings":
        print(", ".join(f"{k} {v}" for k, v in session.settings().items()))
    else:
        print("unknown command; /help lists them")
    return False


if __name__ == "__main__":
    sys.exit(main())
