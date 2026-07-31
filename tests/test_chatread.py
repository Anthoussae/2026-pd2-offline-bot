"""Chat read-back: what the bot hears, and what it refuses to hear."""

from pd2bot import offsets
from pd2bot.chatread import ChatListener, last_line
from tests.conftest import CLIENT_BASE, FakeMemory, FakeSession

BUFFER = CLIENT_BASE + offsets.CHAT_LAST_LINE


def rig(text: bytes) -> FakeSession:
    memory = FakeMemory()
    memory.write(BUFFER, text.ljust(offsets.CHAT_LAST_LINE_MAX, b"\x00"))
    return FakeSession(memory)


def write(session: FakeSession, text: bytes) -> None:
    session.memory.write(BUFFER, text.ljust(offsets.CHAT_LAST_LINE_MAX, b"\x00"))


def test_reads_the_last_line():
    assert last_line(rig(b"hello")) == "hello"


def test_stops_at_the_terminator_and_ignores_the_stale_tail():
    """The buffer is overwritten, not cleared: a short line leaves the tail
    of a longer one behind it."""
    assert last_line(rig(b"red\x00\x00\x00ot sends nothin")) == "red"


def test_strips_colour_escapes_and_other_non_ascii():
    """D2 marks colour with 0xFF. This text is echoed back through Chat one
    character at a time, so it leaves here as printable ASCII or not at all."""
    assert last_line(rig(b"\xffc4hello\xffc0")) == "c4helloc0"


def test_unreadable_buffer_is_silence_not_an_exception():
    session = FakeSession(FakeMemory())  # nothing mapped
    assert last_line(session) == ""


def test_listener_reports_a_new_human_line_once():
    session = rig(b"")
    listener = ChatListener(session)
    write(session, b"green")
    assert listener.poll() == "green"
    assert listener.poll() is None  # unchanged: not new


def test_listener_ignores_its_own_voice():
    session = rig(b"")
    listener = ChatListener(session)
    write(session, b"[claude] ROUND 1: reply with RED / GREEN / BLUE")
    assert listener.poll() is None
    write(session, b"blue")
    assert listener.poll() == "blue"


def test_resync_swallows_the_bots_own_question():
    session = rig(b"old")
    listener = ChatListener(session)
    write(session, b"[claude] a question")
    listener.resync()
    assert listener.poll() is None


def test_identical_consecutive_messages_read_as_one():
    """Documented, not fixed: one buffer holding one line cannot distinguish
    'said again' from 'still there'. Callers ask for distinct answers."""
    session = rig(b"")
    listener = ChatListener(session)
    write(session, b"yes")
    assert listener.poll() == "yes"
    write(session, b"yes")
    assert listener.poll() is None


# -- the drift (S1, 2026-07-31) ---------------------------------------------
#
# The cited address is not the first byte of the line. When D2's colour
# prefix changes length, everything read shifts, and the bot's own "[claude]"
# stamp no longer sits at position 0 — so it heard itself and answered.

QUESTION = "[claude] or (C) leave it where it is and add a confirm dialog?"


def test_hears_itself_when_the_read_has_drifted():
    """The exact S1 failure: the same line, two bytes to the left."""
    session = rig(b"")
    listener = ChatListener(session)
    listener.remember(QUESTION)
    write(session, QUESTION[2:].encode())
    assert listener.poll() is None


def test_a_short_reply_is_not_mistaken_for_an_echo():
    """'b' appears inside the question; it is still a real answer."""
    session = rig(b"")
    listener = ChatListener(session)
    listener.remember(QUESTION)
    write(session, b"b")
    assert listener.poll() == "b"


def test_a_phrase_quoted_from_the_question_is_still_heard():
    """'confirm dialog' is a substring of what was asked, but nowhere near
    its full length — a user echoing our own words back is a real answer."""
    session = rig(b"")
    listener = ChatListener(session)
    listener.remember(QUESTION)
    write(session, b"confirm dialog")
    assert listener.poll() == "confirm dialog"


def test_only_recent_messages_are_treated_as_our_own():
    session = rig(b"")
    listener = ChatListener(session)
    for index in range(12):  # older than the remembered window
        listener.remember(f"[claude] message number {index} of the exercise")
    write(session, b"claude] message number 0 of the exercise")
    assert listener.poll() == "claude] message number 0 of the exercise"


# -- the submission gate (S2) -----------------------------------------------
#
# Content tests judge bytes that have already proven they can drift. The
# console edge is independent: nothing the bot says opens and closes the chat
# console on the user's behalf, so a "reply" with no submission behind it did
# not come from a person.


class FakeConsole:
    def __init__(self) -> None:
        self.open = False

    def __call__(self) -> bool:
        return self.open

    def submit(self) -> None:
        self.open = False


def gated(text: bytes = b""):
    session = rig(text)
    console = FakeConsole()
    return session, console, ChatListener(session, console_open=console)


def test_a_line_with_no_submission_behind_it_is_not_a_reply():
    session, console, listener = gated()
    write(session, b"B")
    assert listener.poll() is None  # nobody typed anything


def test_the_held_line_is_released_once_the_console_closes():
    """The game may write the line before it clears the flag; a line dropped
    on the wrong side of that race would never come back."""
    session, console, listener = gated()
    console.open = True
    listener.poll()
    write(session, b"B")
    assert listener.poll() is None  # console still open
    console.submit()
    assert listener.poll() == "B"


def test_one_submission_is_spent_on_one_message():
    session, console, listener = gated()
    console.open = True
    listener.poll()
    console.submit()
    write(session, b"B")
    assert listener.poll() == "B"
    write(session, b"C")
    assert listener.poll() is None  # a second answer needs a second submission


def test_resync_forgets_submissions_made_before_the_question():
    session, console, listener = gated()
    console.open = True
    listener.poll()
    console.submit()  # the user said something before being asked
    listener.resync()
    write(session, b"B")
    assert listener.poll() is None
