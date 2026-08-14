"""T41 — can the bot actually HEAR the user? A call-and-response test.

T40 found where a posted chat line lands (offsets.CHAT_LAST_LINE). This
drill asks the only question that matters next: does reading it constitute a
real channel, or does it work once in a demo and drop messages the moment it
is used in anger.

Three rounds, escalating, each ruling out a different way of being wrong:

  1. VOCABULARY   the user replies RED, GREEN or BLUE and the bot echoes it.
                  Proves the read path end to end.
  2. ENTROPY      the user replies with any 4-digit number THEY choose. A
                  fixed vocabulary could in principle be faked by guessing;
                  ten thousand possibilities cannot. This is the round that
                  actually proves reading rather than inferring.
  3. RELIABILITY  three different words, back to back, as fast as the user
                  cares to type. Rounds 1 and 2 are paced by the bot asking
                  a question; nothing real ever is. This measures the loss
                  rate, and it is the round expected to find the defect.

Round 3 counts submissions independently of what it captures, by watching
the chat console's open->closed edge (UI slot 0x05). So "I heard 2 of 3" is
distinguishable from "you only sent 2" — without that, a dropped message and
a user who typed slower than instructed produce identical evidence.

The address is RE-DERIVED by scan before it is used, rather than trusted
from T40: the bot says a nonce, scans for it, and checks that the hit lands
at the cited offset. If PD2 has been patched, or if T40's address was a
coincidence that happened to hold twice, this fails loudly at the top
instead of quietly reporting that the user never answered.

Read-only: the bot sends nothing but its own chat messages.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t41_chat_call_response
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402

# The bridge redirects stdout to a file, and PS 5.1 hands Python a cp1252
# console encoding — so printing a byte the game put in its chat buffer
# killed the first run of this drill outright (the round never happened).
# Never let reporting be the thing that fails.
sys.stdout.reconfigure(errors="backslashreplace")

POLL_S = 0.05
ROUND_TIMEOUT_S = 180.0
COLORS = ("RED", "GREEN", "BLUE")
RAPID_COUNT = 3
BOT_PREFIX = "[claude]"  # DrillRun.say stamps every bot message with this


def read_line(session) -> str:
    """The last chat line the client displayed, printable ASCII only, or ''.

    The buffer is not reliably pure text. The first live run died decoding
    it, which proves a byte >= 0x80 was in there at that moment; T40's dump
    of the *rendered* line showed D2's 0xFF colour escapes, which is the
    likely source, though it was not captured directly. Stripping is not
    cosmetic — this string gets ECHOED BACK through `Chat`, one character at
    a time, and the one thing chat.py exists to prevent is sending a
    character whose meaning we have not thought about.
    """
    try:
        raw = session.cstring(
            session.client(offsets.CHAT_LAST_LINE), offsets.CHAT_LAST_LINE_MAX
        )
    except Exception:
        return ""
    return "".join(char for char in raw if 32 <= ord(char) < 127).strip()


class Listener:
    """Watches the chat buffer for lines the USER wrote.

    Change-detection, not equality: the buffer holds whatever was said last,
    including the bot's own questions, so a new user message is 'the content
    changed to something that is not ours'. The consequence — two identical
    consecutive user messages look like one — is why every round asks for
    distinct words rather than being clever about it.
    """

    def __init__(self, run: DrillRun) -> None:
        self.run = run
        self.last_seen = read_line(run.session)
        self.console_was_open = run.panel_open(offsets.UI_CHAT_CONSOLE)
        self.submissions = 0

    def resync(self) -> None:
        """Adopt the current buffer as the baseline (call after the bot talks)."""
        self.last_seen = read_line(self.run.session)

    def collect(self, want: int, timeout_s: float = ROUND_TIMEOUT_S) -> list[str]:
        heard: list[str] = []
        deadline = self.run.clock() + timeout_s
        while self.run.clock() < deadline and len(heard) < want:
            self.run.check_cancel()

            # Count submissions independently of what we manage to read.
            console_open = self.run.panel_open(offsets.UI_CHAT_CONSOLE)
            if self.console_was_open and not console_open:
                self.submissions += 1
            self.console_was_open = console_open

            line = read_line(self.run.session)
            if line != self.last_seen:
                self.last_seen = line
                if line and not line.startswith(BOT_PREFIX):
                    heard.append(line)
                    print(f"  heard: {line!r}", flush=True)
            self.run.sleep(POLL_S)
        return heard


T41 = Drill(
    test_id="T41",
    title="Chat call-and-response: can the bot hear the user?",
    kind="human calibration",
    instructions=(
        "SETUP: in a game, in town, all panels closed. You drive; I only read.",
        "Three rounds. I ask a question in chat, you answer in chat.",
        "Round 3 is a speed test - three DIFFERENT words, as fast as you like.",
        "Nothing is at risk: this drill sends no keys and no clicks.",
    ),
    sends_input=False,
)


def _ask(run: DrillRun, listener: Listener, question: str, want: int) -> list[str]:
    run.say(question)
    listener.resync()  # our own question is now in the buffer; do not hear it
    return listener.collect(want)


def t41_body(run: DrillRun) -> str:
    session = run.session

    # -- re-derive the address, do not trust it ----------------------------
    nonce = f"t41nonce{int(time.monotonic() * 1000) % 100000}"
    run.say(nonce)
    run.sleep(0.5)
    hits = session.search(nonce.encode("ascii"))
    expected = session.client(offsets.CHAT_LAST_LINE)
    modules = session.modules()
    print(
        f"re-derivation: nonce {nonce!r} found at "
        f"{[session.describe(h, modules) for h in hits]}",
        flush=True,
    )
    # Anywhere INSIDE the buffer, not exactly at its head: the bot's own
    # messages carry the "[claude] " prefix, so the nonce sits nine bytes in.
    if not any(expected <= hit < expected + offsets.CHAT_LAST_LINE_MAX for hit in hits):
        raise RuntimeError(
            f"CHAT_LAST_LINE no longer holds the last line: expected the nonce inside "
            f"{session.describe(expected, modules)}, found it at "
            f"{[session.describe(h, modules) for h in hits] or 'nowhere'}. "
            "Re-run T40 to re-derive the offset before trusting this channel"
        )
    live = read_line(session)
    if nonce not in live:
        raise RuntimeError(f"read back {live!r} from the cited offset, expected {nonce!r} in it")
    # The raw bytes settle what the sanitiser is actually removing — bytes
    # repr is ASCII-safe, so this can never be the thing that crashes.
    try:
        print(f"buffer head: {session.raw(expected, 40)!r}", flush=True)
    except Exception as exc:
        print(f"buffer head: unreadable ({exc})", flush=True)
    print(f"re-derivation OK (pid {session.process_id}); reads back {live!r}", flush=True)

    listener = Listener(run)
    results: dict[str, str] = {}

    # -- round 1: vocabulary -----------------------------------------------
    heard = _ask(run, listener, f"ROUND 1: reply with one of {' / '.join(COLORS)}", 1)
    if not heard:
        raise RuntimeError("round 1: nothing was heard — the channel does not work")
    colour = heard[0]
    run.say(f"I heard: {colour}")
    ok_colour = colour.strip().upper() in COLORS
    results["round 1"] = f"heard {colour!r} ({'expected' if ok_colour else 'NOT one of the three'})"

    # -- round 2: entropy ---------------------------------------------------
    heard = _ask(
        run, listener, "ROUND 2: reply with ANY 4-digit number you choose", 1
    )
    if not heard:
        raise RuntimeError("round 2: nothing was heard")
    number = heard[0].strip()
    run.say(f"I heard: {number}")
    ok_number = len(number) == 4 and number.isdigit()
    results["round 2"] = f"heard {number!r} ({'4 digits' if ok_number else 'NOT 4 digits'})"

    # -- round 3: reliability ------------------------------------------------
    before = listener.submissions
    heard = _ask(
        run,
        listener,
        f"ROUND 3: send {RAPID_COUNT} DIFFERENT words back to back, fast as you like",
        RAPID_COUNT,
    )
    sent = listener.submissions - before
    run.say(f"I heard {len(heard)} of {RAPID_COUNT}: {', '.join(heard) or '(nothing)'}")
    results["round 3"] = (
        f"captured {len(heard)}/{RAPID_COUNT} ({', '.join(repr(h) for h in heard)}); "
        f"the console closed {sent} time(s)"
    )

    verdict = (
        "CHANNEL WORKS"
        if ok_colour and ok_number and len(heard) == RAPID_COUNT
        else "CHANNEL PARTIAL"
    )
    if len(heard) < RAPID_COUNT:
        verdict += (
            f" — {RAPID_COUNT - len(heard)} rapid message(s) lost"
            + (
                " (and the console-close count agrees they were sent)"
                if sent >= RAPID_COUNT
                else f" (only {sent} submission(s) seen, so some may never have been sent)"
            )
        )
    return verdict + "; " + "; ".join(f"{k}: {v}" for k, v in results.items())


SUITE = {"T41": (T41, t41_body)}

if __name__ == "__main__":
    shared = DrillRun(GameSession())
    status = run_drill(*SUITE["T41"], run=shared)
    print(f"\nsuite: T41 {status}")
    raise SystemExit(0 if status == "PASS" else 1)
