"""Partyline: the two-way in-game chat channel, named and switchable.

The pieces existed for a milestone before the name did — `chat.py` types
into the game (console-verified, R41), `chatread.py` reads the human's
replies back (T40/T41), and sims S1/S2 proved the conversation loop is
worth being on the human end of. This module is the facade the user asked
for (M5 P6 R169): one place that says whether the channel is ON, one
place that speaks with the bot's voice, and one CLI the workflow hooks
can call.

**The toggle governs notifications, not tests.** A Drill Kit test's
OK-gate cannot function on a muted channel, and a test the user
explicitly sanctioned is not the interruption the toggle guards against.
So `enabled()` is consulted by the notify path (and any future ambient
chatter), never by the drill harness.

Enabled is the DEFAULT (user decision, same request). The flag file
marks the opposite state, so a missing file — fresh machine, wiped
LOCALAPPDATA — fails toward the user's chosen default rather than
toward silence.

The notify path (`--notify`) is what the Claude Code Stop hook calls
via the elevated bridge when the agent finishes a terminal turn. Every
one of its guards fails SILENT and exit-0 on purpose: a notification
that could not be delivered is a non-event, not an error — the user
checks the terminal eventually, and a hook that starts failing loudly
would punish exactly the workflow it exists to speed up. The guards:

- the toggle (off = say nothing);
- freshness (`--stamp`): the bridge runs one command at a time, so
  alerts queued behind a long test would otherwise arrive as a burst
  of stale "your turn" messages minutes later;
- the game itself: attached, in a game, window foreground, no blocking
  panel — `Chat`'s own send guard enforces the last three, and they are
  precisely the user's condition ("if I am tabbed into PD2 ... and the
  chat function would not be disruptive").

Toggling:
    python -m pd2bot.partyline --on / --off / --status
    powershell -File tools\\partyline.ps1 -On / -Off / -Status
(or just tell the agent "partyline on/off").
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from pd2bot.input.chat import Chat
from pd2bot.perception.chatread import BOT_PREFIX, ChatListener
from pd2bot.perception.memory import GameSession

# The one flag. Lives beside the bridge queue because both are
# machine-local workflow state, not project state — a git clone on
# another machine must not carry this machine's mute with it.
FLAG_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "pd2bot-bridge"
OFF_FLAG = FLAG_DIR / "partyline-off"

# A queued notification older than this is not news, it is history.
DEFAULT_MAX_AGE_S = 30.0


def enabled() -> bool:
    """Is the channel on? Absent flag = ON (the user's chosen default)."""
    return not OFF_FLAG.exists()


def set_enabled(on: bool) -> None:
    if on:
        OFF_FLAG.unlink(missing_ok=True)
    else:
        FLAG_DIR.mkdir(parents=True, exist_ok=True)
        OFF_FLAG.write_text("partyline muted by the user\n", encoding="utf-8")


class Partyline:
    """Speak and listen on the in-game channel, with one voice.

    Thin on purpose: `Chat` already owns the send guards and
    `ChatListener` the echo filtering. This class only guarantees the
    two stay consistent — everything said is prefixed AND remembered, so
    the listener can never hear the bot's own voice as a reply (the S1
    lesson, kept in one place instead of at every call site).
    """

    def __init__(self, session: GameSession) -> None:
        self.session = session
        self.chat = Chat(session)
        self.listener = ChatListener(session)

    def say(self, text: str) -> None:
        message = f"{BOT_PREFIX} {text}"
        self.chat.say(message)
        self.listener.remember(message)
        self.listener.resync()

    def poll(self) -> str | None:
        return self.listener.poll()


def notify(message: str, *, stamp: float | None = None,
           max_age_s: float = DEFAULT_MAX_AGE_S) -> bool:
    """Best-effort one-liner to the user in game. True if delivered.

    Every guard fails silent — see the module docstring for why.
    """
    if not enabled():
        return False
    if stamp is not None and time.time() - stamp > max_age_s:
        return False  # stale: queued behind something long; drop it
    try:
        Partyline(GameSession()).say(message)
        return True
    except Exception:  # noqa: BLE001 - not attached / not in game / not
        return False   # foreground / panel open: all mean "not now"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--notify", metavar="MSG",
                       help="best-effort in-game message; silent no-op "
                            "when muted, stale, or the game is not ready")
    group.add_argument("--on", action="store_true")
    group.add_argument("--off", action="store_true")
    group.add_argument("--status", action="store_true")
    parser.add_argument("--stamp", type=float, default=None,
                        help="epoch seconds when the event happened; "
                             "notifications older than "
                             f"{DEFAULT_MAX_AGE_S:.0f}s are dropped")
    args = parser.parse_args(argv)

    if args.on:
        set_enabled(True)
        print("partyline ON")
    elif args.off:
        set_enabled(False)
        print(f"partyline OFF ({OFF_FLAG})")
    elif args.status:
        print(f"partyline {'ON' if enabled() else 'OFF'} (flag: {OFF_FLAG})")
    else:
        delivered = notify(args.notify, stamp=args.stamp)
        print(f"notify: {'delivered' if delivered else 'skipped'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
