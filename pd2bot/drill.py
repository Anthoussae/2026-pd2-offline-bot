"""The live-test harness: every in-game calibration and drill runs one
protocol, so a lesson paid for once stays fixed.

Why this exists (the tuition receipts): R57 lost a run to a missing
re-arm (capture 2 fired on the cursor still resting from capture 1);
R59's announcements fired once into an empty room while its command sat
queued; two launches expired because a patience window was hardcoded
short. Each fix lived in one throwaway script and had to be rewritten in
the next. This module is those fixes, factored, plus the user's protocol
(2026-07-30):

    every test has an id (T<n>), a short title, and a kind
    on the user's first window-in:  TEST <id> — <title> [<kind>]
                                    the instructions, one line at a time
                                    an input warning (hands-off or you-drive)
                                    TEST LIVE
    the body runs
    at the end:                     TEST <id> CONCLUDED — <status>
    every run appends one row to docs/drill-log.md (the human-readable
    record; the instruction log stays the request protocol)

Drill bodies are small functions taking a `DrillRun` and returning a
one-line result summary; raising fails the run with the exception as the
summary. Statuses: PASS / FAILED / ABORTED / NOT STARTED.
"""

from __future__ import annotations

import ctypes
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pd2bot import offsets
from pd2bot.chat import Chat
from pd2bot.menuinput import MenuInput
from pd2bot.perception import uistate
from pd2bot.perception.chatread import ChatListener
from pd2bot.perception.items import CarriedItem, read_carried_items
from pd2bot.perception.memory import GameSession
from pd2bot.perception.player import read_player
from pd2bot.window import GameWindow

DEFAULT_LOG = Path("docs/drill-log.md")
PROJECT_STATE = Path("docs/project-state.md")

# The in-chat keywords (M5 P6 R169). Deliberately a WHITELIST of exact
# tokens, not parsing: acting on read chat is a command channel, and the
# recorded decision (chatread's docstring, deferred 2026-07-31) was that
# a command channel gets a whitelist or it gets nothing. These two are
# the whole vocabulary, matched against the stripped, lowercased line,
# and only ever consulted while a test is running or waiting to start.
ABORT_WORDS = frozenset({"abort", "abort test"})
OK_WORDS = frozenset({"ok", "ok!", "okay"})


def project_state(path: Path = PROJECT_STATE) -> str:
    """The current 'M5 P6' scope, read from docs/project-state.md.

    One file, read at run time, so the banner and the log row can never
    disagree with each other or lag behind a phase transition the way a
    hardcoded constant would. Absent or unparseable file = empty scope —
    a drill run outside any project structure is still a drill run.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    milestone = re.search(r"\*\*Milestone:\*\*\s*(M\d+)", text)
    phase = re.search(r"\*\*Phase:\*\*\s*(P\d+)", text)
    return " ".join(m.group(1) for m in (milestone, phase) if m)

# Cancelling a live drill used to be impossible: the bridge runs one
# elevated child at a time, and the agent's own shell is not elevated, so
# "stop this test" meant either waiting out the timeouts or Ctrl+C-ing the
# bridge itself and restarting it (R79). A file both sides can reach fixes
# that — the agent drops it, every waiting loop notices within a tick.
CANCEL_FILE = Path(os.environ.get("LOCALAPPDATA", ".")) / "pd2bot-bridge" / "drill-cancel"


def request_cancel() -> None:
    """Ask any running drill to stop at its next check."""
    CANCEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    CANCEL_FILE.write_text("cancel", encoding="utf-8")


def clear_cancel() -> None:
    """Remove a stale cancel request, so the next drill is not born dead."""
    CANCEL_FILE.unlink(missing_ok=True)


# Staleness is cleared ONCE per process, not per drill: a suite shares a
# process, and clearing per drill would let drill 2 wipe the cancel the
# user just requested and carry on regardless.
_cleared_stale_cancel = False


_LOG_HEADER = """# Drill log

One row per live-test run (harness: `pd2bot/drill.py`). Statuses:
PASS / FAILED / ABORTED / NOT STARTED. The instruction log carries the
full request context; this file is the quick mechanical record.

| Test | Run | Date | Scope | Title | Kind | Status | Result |
|---|---|---|---|---|---|---|---|
"""


@dataclass(frozen=True)
class Drill:
    test_id: str  # "T11" — stable per test definition; runs share it
    title: str
    kind: str  # "human calibration" | "bot control" | "perception" | "hybrid"
    instructions: tuple[str, ...]
    sends_input: bool = False  # True -> the hands-off warning is printed
    start_patience_s: float = 600.0  # how long to wait for the user to window in
    # True for tests that can run from the menus (no character exposed):
    # they begin immediately after the briefing. Everything else waits
    # in-game for the user to type OK — an in-game test starts when the
    # person whose character is standing there says so, not when the
    # announcement happens to finish (M5 P6 R169).
    menu_ok: bool = False


class DrillAborted(RuntimeError):
    """A body raises this for a clean, expected abort (logged ABORTED)."""


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _read_cursor() -> tuple[int, int]:
    point = _POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


class DrillRun:
    """What a drill body gets to work with: chat, cursor, panels, and the
    capture primitives whose defects have already been paid for."""

    def __init__(
        self,
        session: GameSession,
        *,
        chat: Chat | None = None,
        window: GameWindow | None = None,
        ui_array: int | None = None,
        cursor: Callable[[], tuple[int, int]] = _read_cursor,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        cancel_file: Path = CANCEL_FILE,
        listener: ChatListener | None = None,
    ) -> None:
        self.session = session
        self.chat = chat if chat is not None else Chat(session)
        self.window = window if window is not None else GameWindow(session.process_id)
        self.ui_array = (
            ui_array if ui_array is not None else uistate.find_ui_array(session)
        )
        self.cursor = cursor
        self.clock = clock
        self.sleep = sleep
        self._cancel_file = cancel_file
        self.cancelled = False
        self._unclaimed: str | None = None
        # The return channel: how "abort" and "OK" typed in game reach the
        # harness. Guarded at every use rather than trusted — the drill
        # must keep working when chat cannot be read, because the cancel
        # FILE is the fallback that always exists.
        self._listener = listener
        if listener is None:
            try:
                self._listener = ChatListener(
                    session,
                    console_open=lambda: uistate.read_ui_state(
                        session, self.ui_array
                    ).is_open(offsets.UI_CHAT_CONSOLE),
                )
            except Exception:  # noqa: BLE001 - no chat read: file cancel only
                self._listener = None

    # -- cancellation -----------------------------------------------------------

    def _chat_line(self) -> str | None:
        """The newest unclaimed human chat line, normalized.

        `ChatListener.poll` yields each line exactly ONCE, and two
        different consumers watch the same channel: `check_cancel` (for
        abort words, from every wait) and `await_ok` (for the start
        gate). A naive poll in each would race — whichever asked first
        would swallow the line the other was waiting for, and an "ok"
        eaten by a cancel check is a test that never starts. So polled
        lines are HELD here until a keyword consumer claims them; a line
        that matches nothing simply waits to be replaced by the next.
        """
        if self._listener is not None:
            try:
                line = self._listener.poll()
            except Exception:  # noqa: BLE001 - a torn read is not an abort
                line = None
            if line is not None:
                self._unclaimed = line.strip().lower()
        return self._unclaimed

    def _claim_chat_line(self) -> None:
        self._unclaimed = None

    def check_cancel(self) -> None:
        """Abort if a cancel has been requested. Called from every wait.

        Two ways to ask, same result: the cancel FILE (works from any
        terminal, survives everything) and typing "abort" / "abort test"
        into the game's own chat — the user is watching the game, and
        alt-tabbing to a terminal to stop a test that is misbehaving in
        front of them was a round trip that aged badly (M5 P6 R169).

        Sticky once seen: a suite shares one DrillRun, and a cancel means
        "stop the testing", not "skip to the next test".
        """
        if not self.cancelled and self._chat_line() in ABORT_WORDS:
            self._claim_chat_line()
            self.cancelled = True
            raise DrillAborted("aborted from in-game chat")
        if self.cancelled or self._cancel_file.exists():
            self.cancelled = True
            raise DrillAborted("cancelled by request")

    def heard(self, words: frozenset[str]) -> bool:
        """Did the user just type one of `words` in chat? Claims the line.

        For TEST-SCOPED vocabulary — a completion word like T52's END,
        declared by the drill that needs it. Still a whitelist in the
        chatread sense: exact lowercased tokens, consulted only while the
        test runs, never parsing. The general command channel remains a
        separate, deferred trust decision.
        """
        if self._chat_line() in words:
            self._claim_chat_line()
            return True
        return False

    def await_ok(self, *, timeout_s: float) -> bool:
        """Wait for the user to type OK in game chat. True when they do.

        The abort words work here too (check_cancel runs every poll), so
        a test can be refused at the gate, not just stopped mid-flight.
        """
        deadline = self.clock() + timeout_s
        while self.clock() < deadline:
            self.check_cancel()
            if self._chat_line() in OK_WORDS:
                self._claim_chat_line()
                return True
            self.sleep(0.2)
        return False

    def in_game(self) -> bool:
        """Is a character standing in the world (not the menus)? Guarded:
        an unreadable client counts as the menus, because the OK-gate this
        feeds exists to protect a character that provably exists."""
        try:
            return bool(uistate.is_in_game(self.session))
        except Exception:  # noqa: BLE001
            return False

    # -- talking to the user ----------------------------------------------------

    def say(self, text: str, patience_s: float = 60.0) -> bool:
        """Chat `text` (auto-prefixed), retrying while the game is not
        foreground. Also printed to stdout so the bridge transcript is a
        complete record of what the user was told."""
        message = f"[claude] {text}"
        print(f"chat> {message}", flush=True)
        # Remembered by the listener BEFORE sending, so the return channel
        # can never hear this message as a human reply — the prefix check
        # alone lost that bet once (S1: the buffer shifted two bytes and
        # the bot answered its own question).
        if self._listener is not None:
            try:
                self._listener.remember(message)
            except Exception:  # noqa: BLE001
                pass
        deadline = self.clock() + patience_s
        while self.clock() < deadline:
            self.check_cancel()
            try:
                self.chat.say(message)
                return True
            except Exception:
                self.sleep(1.0)
        print("chat> (never delivered)", flush=True)
        return False

    def player_is_dead(self) -> bool:
        """A conservative read of the death state, for send decisions.

        The `SafetyMonitor` latch is per-instance and the harness has no
        monitor, so this reads the same condition directly. It exists so the
        rule survives here too: after a death the bot sends NOTHING, ever.
        """
        try:
            player = read_player(self.session)
        except Exception:
            return True  # unreadable: assume the worst and send nothing
        if player is None:
            return False  # menus or loading, not death
        return (
            player.mode in (offsets.PLAYER_MODE_DEATH, offsets.PLAYER_MODE_DEAD)
            or player.hp <= 0
        )

    def make_chat_possible(
        self, *, may_send_input: bool, timeout_s: float = 25.0
    ) -> bool:
        """Clear the way for a chat message, and say whether it worked.

        Chat refuses while a panel is open (R89) — and a failing drill tends
        to end with exactly that, because the step that failed was usually
        mid-panel. So the one message the user most needs, "this test is
        over, you can stop waiting", was the one that could not be
        delivered: T27 died with Akara's dialog up and its conclusion came
        out `(never delivered)` (user request, R95).

        A drill that already sends input may press ESC to clear the way; a
        read-only one must not, so it waits for the human instead — the
        no-input contract is not worth breaking for a status message.
        """
        def blocked() -> bool:
            # Fails OPEN: this helper only clears the way, it is not the
            # gate. If the UI array cannot be read we still attempt the
            # message, and `Chat`'s own guard — which reads the same array —
            # makes the real decision about whether a key may be sent.
            try:
                return uistate.read_ui_state(self.session, self.ui_array).blocks_input
            except Exception:
                return False

        if not blocked():
            return True
        if may_send_input and not self.player_is_dead():
            menu = MenuInput(self.session, ui_array=self.ui_array)
            for _ in range(6):
                if not blocked():
                    return True
                try:
                    menu.press_escape()
                except Exception:
                    pass  # refused (focus, state) — the wait below still applies
                self.sleep(0.5)
            return not blocked()
        deadline = self.clock() + timeout_s
        while self.clock() < deadline and blocked():
            self.sleep(0.3)
        return not blocked()

    def wait_until(
        self,
        condition: Callable[[], bool],
        *,
        timeout_s: float = 300.0,
        poll_s: float = 0.15,
    ) -> bool:
        """Wait for `condition` in SILENCE — no chat, no keys, nothing sent.

        `announce_until` cannot be used once a panel is on screen: it repeats
        a chat message, and chat opens with Enter, which an NPC dialog reads
        as choosing an option (R89). A calibration that talks its way through
        a dialog is a calibration that changes what it is measuring. So drills
        that work inside panels brief the user up front and then go quiet,
        watching instead of prompting."""
        deadline = self.clock() + timeout_s
        while self.clock() < deadline:
            self.check_cancel()
            if condition():
                return True
            self.sleep(poll_s)
        return False

    def announce_until(
        self,
        text: str,
        condition: Callable[[], bool],
        *,
        repeat_every_s: float = 40.0,
        timeout_s: float = 300.0,
    ) -> bool:
        """Repeat `text` periodically until `condition` holds (the R59 fix:
        a one-shot announcement fired into an empty room strands a drill)."""
        next_say = 0.0
        deadline = self.clock() + timeout_s
        while self.clock() < deadline:
            self.check_cancel()
            if condition():
                return True
            if self.clock() >= next_say:
                self.say(text, patience_s=10.0)
                next_say = self.clock() + repeat_every_s
            self.sleep(0.3)
        return False

    # -- perception shortcuts -----------------------------------------------------

    def panel_open(self, panel_id: int) -> bool:
        return uistate.read_ui_state(self.session, self.ui_array).is_open(panel_id)

    def inventory_container(self) -> dict[int, CarriedItem]:
        """{unit_id: item} for the RAW inventory container — charm space
        included, because calibration probes need to see it."""
        return {i.unit_id: i for i in read_carried_items(self.session).inventory}

    # -- capture primitives ----------------------------------------------------------

    def capture_hover(
        self,
        *,
        required_panel: int | None,
        last_point: tuple[int, int] | None,
        still_samples: int = 20,
        still_px: int = 3,
        rearm_px: int = 40,
        timeout_s: float = 120.0,
    ) -> tuple[int, int, float, float] | None:
        """Wait for the cursor to hold still, return (x, y, fx, fy).

        The capture cannot fire until the cursor has moved `rearm_px` away
        from `last_point` (R57), and it only samples while `required_panel`
        is open and the cursor is inside the client rect.

        `last_point=None` used to mean "armed immediately", and that was the
        R57 defect wearing a different hat (R86). The FIRST capture of a
        drill is precisely when the hand is resting on something the user
        has just clicked — the NPC they opened the dialog with — so an
        immediately-armed capture returns that click point, silently, as a
        plausible-looking calibration. T18 and T20 both did exactly this;
        T18's "trade/repair row" was really Charsi's portrait, 488 px off,
        and it took three failed live runs to catch. So None now means
        "arm against wherever the cursor is right now": every capture
        demands a deliberate move onto the target, and the worst case is
        that a user already on the target moves off and back."""
        rect = self.window.client_rect()
        history: list[tuple[int, int]] = []
        if last_point is None:
            last_point = self.cursor()
        armed = False
        deadline = self.clock() + timeout_s
        while self.clock() < deadline:
            self.check_cancel()
            if required_panel is not None and not self.panel_open(required_panel):
                history.clear()
                self.sleep(0.1)
                continue
            x, y = self.cursor()
            if not rect.contains(x, y):
                history.clear()
                self.sleep(0.1)
                continue
            if not armed:
                if max(abs(x - last_point[0]), abs(y - last_point[1])) > rearm_px:
                    armed = True
                else:
                    self.sleep(0.1)
                    continue
            history.append((x, y))
            if len(history) > still_samples:
                history.pop(0)
            if (
                len(history) == still_samples
                and max(abs(a - history[0][0]) for a, _ in history) <= still_px
                and max(abs(b - history[0][1]) for _, b in history) <= still_px
            ):
                fx = (x - rect.left) / rect.width
                fy = (y - rect.top) / rect.height
                return x, y, fx, fy
            self.sleep(0.1)
        return None

    def await_new_inventory_item(
        self,
        known_ids: set[int],
        prompt: str,
        *,
        timeout_s: float = 300.0,
        repeat_every_s: float = 40.0,
    ) -> CarriedItem | None:
        """Repeat `prompt` until an item not in `known_ids` appears in the
        inventory container; the landed cell then comes from memory, never
        from anyone counting squares (the R58 lesson)."""
        found: list[CarriedItem] = []

        def check() -> bool:
            for uid, item in self.inventory_container().items():
                if uid not in known_ids:
                    found.append(item)
                    return True
            return False

        if self.announce_until(
            prompt, check, repeat_every_s=repeat_every_s, timeout_s=timeout_s
        ):
            return found[0]
        return None


# -- the log --------------------------------------------------------------------


def _next_run_number(log_path: Path, test_id: str) -> int:
    if not log_path.exists():
        return 1
    prefix = f"| {test_id} |"
    return sum(
        1 for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ) + 1


def append_log_row(
    log_path: Path,
    drill: Drill,
    status: str,
    result: str,
    *,
    date: str | None = None,
    scope: str | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(_LOG_HEADER, encoding="utf-8")
    run = _next_run_number(log_path, drill.test_id)
    stamp = date if date is not None else time.strftime("%Y-%m-%d %H:%M")
    where = scope if scope is not None else project_state()
    clean = " ".join(result.split())  # keep the table one row tall
    row = (
        f"| {drill.test_id} | {run} | {stamp} | {where or '-'} | {drill.title} "
        f"| {drill.kind} | {status} | {clean} |\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(row)


# -- the runner ---------------------------------------------------------------------


def run_drill(
    drill: Drill,
    body: Callable[[DrillRun], str],
    *,
    session: GameSession | None = None,
    run: DrillRun | None = None,
    log_path: Path = DEFAULT_LOG,
    scope: str | None = None,
) -> str:
    """Execute one drill under the standard protocol. Returns the status.

    The header say doubles as the foreground detector: chat can only
    deliver while the user is in the game, so the moment the header lands
    is exactly 'the user has windowed in'.
    """
    if run is None:
        run = DrillRun(session if session is not None else GameSession())

    global _cleared_stale_cancel
    if not _cleared_stale_cancel:
        clear_cancel()  # a stale request must not kill the first run
        _cleared_stale_cancel = True
    status, result = "NOT STARTED", "the user never windowed into the game"
    started = False
    # The whole protocol sits inside the guard, not just the body: waiting
    # for the user to window in is exactly when a cancel is most likely,
    # and an abort there escaped the runner entirely in the first cut.
    if scope is None:
        scope = project_state()
    try:
        started = run.say(
            f"TEST {drill.test_id} — {drill.title} [{drill.kind}]"
            + (f" ({scope})" if scope else ""),
            patience_s=drill.start_patience_s,
        )
        if started:
            for line in drill.instructions:
                run.say(line)
            if drill.sends_input:
                run.say(
                    "The bot WILL SEND INPUT during this test — hands off "
                    "keyboard and mouse."
                )
            else:
                run.say("Read-only: the bot sends nothing; you drive.")
            # The start gate (M5 P6 R169): an IN-GAME test begins when the
            # person whose character is standing there says so. Menu-capable
            # tests (`menu_ok`) skip it, as does a client sitting in the
            # menus — there is no exposed character for the gate to protect,
            # and demanding chat that cannot be typed would deadlock.
            if not drill.menu_ok and run.in_game():
                run.say("Test ready — type OK in chat to begin.")
                if not run.await_ok(timeout_s=drill.start_patience_s):
                    run.say(f"TEST {drill.test_id} never began — no OK received.")
                    append_log_row(
                        log_path, drill, "NOT STARTED",
                        "announced, but the user never typed OK", scope=scope,
                    )
                    print(
                        f"\nTEST {drill.test_id} CONCLUDED — NOT STARTED: "
                        "no OK received", flush=True,
                    )
                    return "NOT STARTED"
            run.say("TEST LIVE")
            result = body(run)
            status = "PASS"
    except DrillAborted as exc:
        status, result = "ABORTED", str(exc)
    except Exception as exc:  # noqa: BLE001 - the log wants every failure
        status, result = "FAILED", f"{type(exc).__name__}: {exc}"

    if started:
        try:
            # Getting this message THROUGH matters as much as sending it
            # (user request, R95): the user is watching the game, not the
            # console, and a drill that ends without saying so leaves them
            # waiting on a bot that stopped minutes ago. A failing drill
            # usually ends mid-panel, and chat refuses while a panel is open
            # — so clear the way first, by ESC if this drill was already
            # sending input, by waiting if it was not.
            run.make_chat_possible(may_send_input=drill.sends_input)
            # Name the test in the chat line, not just in the transcript
            # (user request, R85): a suite announces several conclusions into
            # the same chat window, and "CONCLUDED — FAILED" on its own
            # leaves the person watching to work out which test that was.
            # A cancelled run should not spend thirty seconds announcing it,
            # and must not raise the cancel again on the way out.
            patience = 3.0 if run.cancelled else 30.0
            run.say(f"TEST {drill.test_id} CONCLUDED — {status}", patience_s=patience)
            if status != "PASS":
                # The reason too, trimmed: enough to decide what to do next
                # without alt-tabbing to read the transcript.
                run.say(f"T{drill.test_id[1:]} reason: {result[:160]}", patience_s=patience)
        except DrillAborted:
            pass
        except Exception as exc:  # noqa: BLE001 - never let reporting mask the result
            print(f"(could not announce the conclusion in game: {exc})", flush=True)

    print(f"\nTEST {drill.test_id} CONCLUDED — {status}: {result}", flush=True)
    append_log_row(log_path, drill, status, result, scope=scope)
    return status
