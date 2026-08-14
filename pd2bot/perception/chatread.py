"""Reading the chat line the client last displayed — the return channel.

`pd2bot.input.chat` types INTO the game; this reads back OUT of it, so a human
watching the game can answer without alt-tabbing to a console. The address it
reads (`offsets.CHAT_LAST_LINE`) was derived by content scan in T40 and
re-derived, then exercised, in T41: three rounds of call-and-response, 3/3
rapid messages captured with the console-close counter agreeing they were
sent.

Two properties of that buffer shape everything here:

  it holds the LAST line, whoever said it — including the bot's own
  messages, which is why every listener filters its own prefix out; and

  it is not reliably clean text — D2 writes colour escapes (0xFF) into chat
  strings, and the first T41 run died decoding one. Everything returned here
  is stripped to printable ASCII, because this text gets echoed back through
  `Chat` one character at a time and chat.py's whole reason for existing is
  that no character is sent whose meaning was not considered.

Deliberately NOT here: anything that acts on what it reads. Reading is
perception; turning a chat line into a bot action is a command channel with
its own trust question (whitelist, not parsing), and that is a separate,
explicit decision — deferred by the user, 2026-07-31.

This module does not replace T41's own copy of the read: a drill records what
was actually run, and rewriting it later would forge that record.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from pd2bot import offsets
from pd2bot.perception.memory import GameSession

# Every message the bot says carries this (drill.py stamps it). A listener
# that does not skip its own voice hears itself ask the question.
BOT_PREFIX = "[claude]"

# ...which it did, on the first live run of S1 (2026-07-31): the bot read
# back its own closing question as
#
#     'laude] or (C) leave it where it is and add a confirm dialog?'
#
# - the same line, two bytes to the left - and confidently answered itself.
# The cited address is not the first byte of the line; it is a fixed address
# that USUALLY coincides with it, because the colour escape D2 writes in
# front is usually the same length. When it is not, everything read shifts.
#
# So identity cannot rest on the prefix surviving at position 0. A line is
# ours when it is very nearly something we just said - a small drift, not a
# coincidence. The bound keeps a genuine short reply safe: a user typing
# "overflow menu" is a substring of the question that was asked, but not
# within DRIFT_SLACK characters of its whole length.
DRIFT_SLACK = 8
_SPOKEN_MEMORY = 8


class ChatDrift(RuntimeError):
    """Raised by callers that cannot tolerate a shifted read."""


def last_line(session: GameSession) -> str:
    """The last chat line the client displayed: printable ASCII, or ''.

    An unreadable buffer is '' rather than an exception — the same posture as
    the rest of perception, where a torn read mid-frame is a normal state and
    the next poll gets it.
    """
    try:
        raw = session.cstring(
            session.client(offsets.CHAT_LAST_LINE), offsets.CHAT_LAST_LINE_MAX
        )
    except Exception:
        return ""
    return "".join(char for char in raw if 32 <= ord(char) < 127).strip()


class ChatListener:
    """Yields chat lines written by the HUMAN, newest last.

    Change-detection, not a queue: the client keeps one line, so a new
    message is "the buffer changed to something that is not ours". The
    consequence is honest and worth stating — two identical messages in a row
    read as one — and it is why callers ask for distinct answers rather than
    pretending the ambiguity is not there.
    """

    def __init__(
        self,
        session: GameSession,
        *,
        read: Callable[[GameSession], str] = last_line,
        ignore_prefix: str = BOT_PREFIX,
        console_open: Callable[[], bool] | None = None,
    ) -> None:
        self.session = session
        self._read = read
        self._ignore_prefix = ignore_prefix
        self._spoken: deque[str] = deque(maxlen=_SPOKEN_MEMORY)
        self.last_seen = self._read(session)
        # The independent gate. Content tests ask "is this line ours?", which
        # is a judgement about bytes that have already drifted once. This asks
        # something the buffer cannot lie about: did a human open the chat
        # console and close it again? Nothing the bot says moves that flag on
        # the user's behalf, so a reply that never had a submission behind it
        # is not a reply. Optional — a caller with no UI array can omit it.
        self._console_open = console_open
        self._console_was_open = bool(console_open()) if console_open else False
        self._submissions = 0
        self._held: str | None = None

    @property
    def submissions(self) -> int:
        """Console open->closed edges seen but not yet spent on a message."""
        return self._submissions

    def remember(self, text: str) -> None:
        """Record something the bot just said, so it is never heard back.

        Callers must call this for every message they send. The prefix check
        alone is not enough (see DRIFT_SLACK): S1 heard its own question with
        the first two characters shorn off and answered it.
        """
        self._spoken.append(text)

    def _is_our_echo(self, line: str) -> bool:
        if line.startswith(self._ignore_prefix):
            return True
        return any(
            line in spoken and len(spoken) - len(line) <= DRIFT_SLACK
            for spoken in self._spoken
        )

    def resync(self) -> None:
        """Adopt the current line as the baseline, and forget what is pending.

        Called after the bot speaks: its own message is now in the buffer,
        and without this the next poll reports it as something new. Anything
        held or counted from before the question is dropped too — a reply has
        to come after the question, or it is not an answer to it.
        """
        self.last_seen = self._read(self.session)
        if self._console_open is not None:
            self._console_was_open = bool(self._console_open())
        self._submissions = 0
        self._held = None

    def poll(self) -> str | None:
        """The newest human line since the last call, or None.

        Order matters. The submission edge is read BEFORE the buffer, and a
        new line is held rather than dropped when no submission has been
        counted yet — the game writes the line and clears the console flag in
        some order we do not control, and a line discarded on the wrong side
        of that race would never come back.
        """
        if self._console_open is not None:
            now_open = bool(self._console_open())
            if self._console_was_open and not now_open:
                self._submissions += 1
            self._console_was_open = now_open

        line = self._read(self.session)
        if line != self.last_seen:
            self.last_seen = line
            if line and not self._is_our_echo(line):
                self._held = line

        if self._held is None:
            return None
        if self._console_open is not None and self._submissions == 0:
            return None  # no human pressed anything; keep holding
        held, self._held = self._held, None
        self._submissions = 0
        return held
