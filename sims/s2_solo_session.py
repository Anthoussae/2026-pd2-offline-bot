"""S2 - the S1 exchange, on a solo project, and it does not speak until asked.

Two changes from S1, one cosmetic and one structural.

Cosmetic: the fiction is a person working alone. No release date, no testers,
no one else's profile to lose - the pressure in a solo project comes from
having to live with your own decision, so the question is about which
approach the author wants to maintain, not about who is waiting.

Structural: the confirmation cannot be sent before a reply arrives, and
"a reply" now means something a human demonstrably did. S1's first run read
its own question back (drifted two bytes past the prefix check) and answered
itself. The content filter that fixed it is still a judgement about bytes
that have already proven they can shift, so this run adds an independent
gate: the chat console must have been opened and closed - a submission -
since the question was asked. Nothing the bot says can move that flag.

If no reply comes, S2 says so and stops. It never guesses.

Re-runnable as-is; same wording every time, so runs are comparable.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m sims.s2_solo_session
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(errors="backslashreplace")  # the T41 lesson

from pd2bot import offsets  # noqa: E402
from pd2bot.chatread import ChatListener  # noqa: E402
from pd2bot.drill import DrillRun  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402

WINDOW_IN_PATIENCE_S = 600.0
REPLY_TIMEOUT_S = 420.0  # longer than S1: nothing here is allowed to give up early
POLL_S = 0.05
BEAT_S = 1.2
SETTLE_S = 1.0

TITLE = "R3 - Backups: how should the snapshot files be named?"

STATEMENT_LINES = (
    "The backup script writes every snapshot to backup.db, so each run "
    "overwrites the last one.",
    "I want to keep history now, and the naming is what restore will have to "
    "search through.",
    "Whichever way it goes, I am the one maintaining it, so I would rather "
    "pick the boring option.",
)

QUESTION_LINES = (
    "Do you want (A) timestamped names, (B) a numbered ring of five, or (C) "
    "hashes plus an index?",
)

CHOICES = {
    "a": "(A) timestamped snapshot names",
    "b": "(B) a numbered ring of five",
    "c": "(C) hash-named files with an index",
}
KEYWORDS = {
    "timestamp": "a",
    "date": "a",
    "time": "a",
    "ring": "b",
    "numbered": "b",
    "number": "b",
    "five": "b",
    "hash": "c",
    "index": "c",
}


def interpret(reply: str) -> str:
    """Map a reply onto a choice, or echo it back when it is something else.

    Echoing the unrecognised case verbatim is the point: an assistant that
    silently rounds an unexpected answer to the nearest button is worse than
    one that repeats what it heard.
    """
    bare = "".join(char for char in reply.lower() if char.isalnum())
    if bare in CHOICES:
        return CHOICES[bare]
    if bare.startswith("option") and bare[6:] in CHOICES:
        return CHOICES[bare[6:]]
    for keyword, choice in KEYWORDS.items():
        if keyword in reply.lower():
            return CHOICES[choice]
    return f"your answer: {reply}"


def main() -> int:
    run = DrillRun(GameSession())
    listener = ChatListener(
        run.session,
        console_open=lambda: run.panel_open(offsets.UI_CHAT_CONSOLE),
    )

    def say(text: str, **kwargs) -> bool:
        """Say it, and remember having said it (so it is never heard back)."""
        listener.remember(f"[claude] {text}")
        return run.say(text, **kwargs)

    if not say(TITLE, patience_s=WINDOW_IN_PATIENCE_S):
        print("never delivered - the user did not window in", flush=True)
        return 1
    for line in STATEMENT_LINES + QUESTION_LINES:
        run.sleep(BEAT_S)
        say(line)

    run.sleep(SETTLE_S)
    listener.resync()  # the question is the baseline; the answer comes after

    deadline = run.clock() + REPLY_TIMEOUT_S
    reply = None
    while run.clock() < deadline and reply is None:
        run.check_cancel()
        reply = listener.poll()
        run.sleep(POLL_S)

    if reply is None:
        print("no reply within the window", flush=True)
        say("No answer yet - I will leave this one open.")
        return 1

    print(f"reply: {reply!r} (after {listener.submissions + 1} submission)", flush=True)
    say(f"Feedback accepted - working on {interpret(reply)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
