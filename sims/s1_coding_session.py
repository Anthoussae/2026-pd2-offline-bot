"""S1 - what a coding-session exchange FEELS like from inside the game.

Not a drill and not a test: nothing here is measured, nothing is logged to
docs/drill-log.md, and there is no pass or fail. T40 and T41 established that
the two-way chat channel works; this asks the different question of whether
it is any good to be on the human end of - whether a question arrives with
enough context to answer it while standing in town, and whether the reply
loop feels like a conversation or like operating a machine.

So the drill protocol is deliberately absent. No TEST banner, no kind, no
instructions block, no CONCLUDED line. The user asked to see it immersively,
and every one of those lines would announce that this is an exercise.

The content is fiction - a settings-page decision from no real project -
chosen to be mundane, self-contained, and answerable in one word. Re-runnable
as-is: same script, same wording, so two runs are comparable.

ASCII only, throughout. The read path strips to printable ASCII (chatread),
and anything typed must survive the same round trip.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m sims.s1_coding_session
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(errors="backslashreplace")  # the T41 lesson

from pd2bot.drill import DrillRun  # noqa: E402
from pd2bot.perception.chatread import ChatListener  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402

WINDOW_IN_PATIENCE_S = 600.0
REPLY_TIMEOUT_S = 300.0
POLL_S = 0.05
BEAT_S = 1.2  # a pause between lines, so it reads as speech and not a dump

TITLE = "R7 - Settings page: where should 'Reset to defaults' live?"

# Sent one line at a time rather than as one blob: chat.py splits at 100
# characters wherever the count lands, which cut a sentence at "sits at the
# top, right / next to Save". Fine for a drill, wrong for something whose
# entire purpose is how it reads.
STATEMENT_LINES = (
    "The settings panel has grown to four sections, and Reset still sits at "
    "the top next to Save.",
    "Two testers hit it this week when they meant Save, and one lost a full "
    "profile.",
    "I would like to fix the placement before Friday's release.",
)

QUESTION_LINES = (
    "Which do you want: (A) the bottom of the page under a divider, (B) an "
    "overflow menu,",
    "or (C) leave it where it is and add a confirm dialog?",
)

CHOICES = {
    "a": "(A) moving it to the bottom, under a divider",
    "b": "(B) tucking it into the overflow menu",
    "c": "(C) leaving it in place behind a confirm dialog",
}
# A one-word answer is what was asked for, but people answer in words too.
KEYWORDS = {
    "bottom": "a",
    "divider": "a",
    "overflow": "b",
    "menu": "b",
    "confirm": "c",
    "dialog": "c",
    "leave": "c",
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
    listener = ChatListener(run.session)

    def say(text: str, **kwargs) -> bool:
        """Say it, and remember having said it.

        The remembering is not bookkeeping: run 1 of S1 read its own closing
        question back (shifted two bytes, so the prefix check missed it) and
        answered itself before the user could type a word.
        """
        listener.remember(f"[claude] {text}")  # the prefix DrillRun.say adds
        return run.say(text, **kwargs)

    if not say(TITLE, patience_s=WINDOW_IN_PATIENCE_S):
        print("never delivered - the user did not window in", flush=True)
        return 1
    for line in STATEMENT_LINES + QUESTION_LINES:
        run.sleep(BEAT_S)
        say(line)
    run.sleep(1.0)  # let the buffer settle before adopting it as the baseline
    listener.resync()  # the question is in the buffer now; do not hear it

    deadline = run.clock() + REPLY_TIMEOUT_S
    reply = None
    while run.clock() < deadline and reply is None:
        run.check_cancel()
        reply = listener.poll()
        run.sleep(POLL_S)

    if reply is None:
        say("No answer yet - I will hold off on this one.")
        print("no reply within the window", flush=True)
        return 1

    print(f"reply: {reply!r}", flush=True)
    say(f"Feedback accepted - working on {interpret(reply)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
