"""A thin command-line chat over the real pipeline (Stage 7.5).

    python scripts/chat.py --fake                    # offline, fake answers
    python scripts/chat.py --model gpt-4o-mini       # live (if enabled)
    python scripts/chat.py --model gpt-5-nano --instructions "Be brief."

Keeps the history (sent every turn, P-8), routes every message to one fixed
test model, and after each answer prints: served by, model and the
provider-reported model, tokens (with fidelity), cost, the premium-baseline
estimate, the savings decomposition (message and session), Metis overhead,
and the budget used vs the 20 USD lifetime cap.

Commands: /model <id>, /models, /reset (forget history), /budget, /help, /quit.

Live calls need both keys: this script asks for ``live`` (unless --fake);
config/local.toml must set ``[live] enabled = true``, and METIS_API_KEY must
be in .env. Use only your own or synthetic messages (ADR-0018). Every live
call goes through the spend guard, the persistent ledger
(data/spend/ledger.jsonl), and the recording decorator (data/recorded/).
Thin wrapper: the logic is in metis_auto.wiring.chat.
"""

from __future__ import annotations

import argparse
import sys

from metis_auto.settings import SettingsError
from metis_auto.wiring.chat import ChatSession, format_report

HELP = "commands: /model <id>, /models, /reset, /budget, /help, /quit"


def main() -> int:
    parser = argparse.ArgumentParser(description="Chat over the Metis-Auto pipeline")
    parser.add_argument("--model", default="gpt-4o-mini", help="fixed target model")
    parser.add_argument("--fake", action="store_true", help="offline fake answers")
    parser.add_argument("--instructions", default=None, help="system instructions")
    parser.add_argument(
        "--allow-unknown-window",
        action="store_true",
        help="diagnostics: allow models whose context window is unknown (Grok)",
    )
    args = parser.parse_args()

    try:
        session = ChatSession(
            args.model,
            live=not args.fake,
            instructions=args.instructions,
            allow_unknown_window=args.allow_unknown_window,
        )
    except (SettingsError, ValueError) as exc:
        print(f"cannot start: {exc}")
        if not args.fake:
            print("try --fake for an offline session, or see the docstring")
        return 1
    mode = "FAKE (offline)" if args.fake else "LIVE (budgeted)"
    print(f"{mode} chat, model {session.model_id}, run {session.run_id}. {HELP}")

    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.startswith("/"):
            if _command(session, line):
                return 0
            continue
        response, report = session.ask(line)
        print(f"\nassistant> {response.answer if response.answer else '(no answer)'}")
        print(format_report(report))
        if report.live_stopped:
            print("Live calls are stopped for this run; restart the chat.")
            return 1


def _command(session: ChatSession, line: str) -> bool:
    """Run a /command; True means quit."""
    name, _, arg = line.partition(" ")
    if name in ("/quit", "/exit"):
        return True
    if name == "/help":
        print(HELP)
    elif name == "/models":
        for e in session.loaded.reference.catalogue.entries:
            window = e.context_window.value or "unknown"
            note = "" if e.enabled else " (disabled)"
            print(f"  {e.model_id:<18} window {window}{note}")
    elif name == "/model":
        try:
            session.switch_model(arg.strip())
            print(f"model: {session.model_id}")
        except (SettingsError, ValueError) as exc:
            print(f"cannot switch: {exc}")
    elif name == "/reset":
        session.reset()
        print("history cleared")
    elif name == "/budget":
        print(session.budget() or "no budget configured")
    else:
        print(f"unknown command; {HELP}")
    return False


if __name__ == "__main__":
    sys.exit(main())
