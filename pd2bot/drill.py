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
    at the end:                     TEST CONCLUDED — <status>
    every run appends one row to docs/drill-log.md (the human-readable
    record; the instruction log stays the request protocol)

Drill bodies are small functions taking a `DrillRun` and returning a
one-line result summary; raising fails the run with the exception as the
summary. Statuses: PASS / FAILED / ABORTED / NOT STARTED.
"""

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pd2bot import uistate
from pd2bot.chat import Chat
from pd2bot.items import CarriedItem, read_carried_items
from pd2bot.memory import GameSession
from pd2bot.window import GameWindow

DEFAULT_LOG = Path("docs/drill-log.md")

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

| Test | Run | Date | Title | Kind | Status | Result |
|---|---|---|---|---|---|---|
"""


@dataclass(frozen=True)
class Drill:
    test_id: str  # "T11" — stable per test definition; runs share it
    title: str
    kind: str  # "human calibration" | "bot control" | "perception" | "hybrid"
    instructions: tuple[str, ...]
    sends_input: bool = False  # True -> the hands-off warning is printed
    start_patience_s: float = 600.0  # how long to wait for the user to window in


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

    # -- cancellation -----------------------------------------------------------

    def check_cancel(self) -> None:
        """Abort if a cancel has been requested. Called from every wait.

        Sticky once seen: a suite shares one DrillRun, and a cancel means
        "stop the testing", not "skip to the next test".
        """
        if self.cancelled or self._cancel_file.exists():
            self.cancelled = True
            raise DrillAborted("cancelled by request")

    # -- talking to the user ----------------------------------------------------

    def say(self, text: str, patience_s: float = 60.0) -> bool:
        """Chat `text` (auto-prefixed), retrying while the game is not
        foreground. Also printed to stdout so the bridge transcript is a
        complete record of what the user was told."""
        message = f"[claude] {text}"
        print(f"chat> {message}", flush=True)
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

        Carries both paid-for fixes: the capture cannot fire until the
        cursor has moved `rearm_px` away from `last_point` (R57), and it
        only samples while `required_panel` is open and the cursor is
        inside the client rect."""
        rect = self.window.client_rect()
        history: list[tuple[int, int]] = []
        armed = last_point is None
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
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(_LOG_HEADER, encoding="utf-8")
    run = _next_run_number(log_path, drill.test_id)
    stamp = date if date is not None else time.strftime("%Y-%m-%d %H:%M")
    clean = " ".join(result.split())  # keep the table one row tall
    row = (
        f"| {drill.test_id} | {run} | {stamp} | {drill.title} | {drill.kind} "
        f"| {status} | {clean} |\n"
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
    try:
        started = run.say(
            f"TEST {drill.test_id} — {drill.title} [{drill.kind}]",
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
            run.say("TEST LIVE")
            result = body(run)
            status = "PASS"
    except DrillAborted as exc:
        status, result = "ABORTED", str(exc)
    except Exception as exc:  # noqa: BLE001 - the log wants every failure
        status, result = "FAILED", f"{type(exc).__name__}: {exc}"

    if started:
        try:
            # A cancelled run should not spend thirty seconds announcing it,
            # and must not raise the cancel again on the way out.
            run.say(
                f"TEST CONCLUDED — {status}",
                patience_s=3.0 if run.cancelled else 30.0,
            )
        except DrillAborted:
            pass

    print(f"\nTEST {drill.test_id} CONCLUDED — {status}: {result}", flush=True)
    append_log_row(log_path, drill, status, result)
    return status
