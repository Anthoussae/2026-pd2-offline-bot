"""The live-test harness: protocol messages, statuses, and the run log.

The fakes replace chat and the clock; what is under test is the protocol
the user specified (header -> instructions -> warning -> TEST LIVE ->
TEST CONCLUDED), the failure statuses, and the log rows.
"""

from types import SimpleNamespace

import pytest

from pd2bot.drill import Drill, DrillAborted, DrillRun, append_log_row, run_drill
from pd2bot.window import ClientRect

RECT = ClientRect(left=0, top=0, width=1536, height=864)


class FakeChat:
    """Records delivered messages; refuses the first `refusals` attempts
    (the game not being foreground yet)."""

    def __init__(self, refusals=0):
        self.refusals = refusals
        self.delivered = []

    def say(self, text):
        if self.refusals > 0:
            self.refusals -= 1
            raise RuntimeError("not foreground")
        self.delivered.append(text)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_run(chat=None, cursor=None):
    clock = FakeClock()
    return DrillRun(
        session=object(),
        chat=chat if chat is not None else FakeChat(),
        window=SimpleNamespace(client_rect=lambda: RECT),
        ui_array=0,
        cursor=cursor if cursor is not None else lambda: (0, 0),
        clock=clock,
        sleep=clock.sleep,
    )


DRILL = Drill(
    test_id="T99",
    title="Fake drill",
    kind="human calibration",
    instructions=("Do the thing.", "Then the other thing."),
)


def test_protocol_messages_in_order(tmp_path):
    chat = FakeChat()
    run = make_run(chat)
    run_drill(DRILL, lambda r: "all good", run=run, log_path=tmp_path / "log.md")
    texts = chat.delivered
    assert texts[0] == "[claude] TEST T99 — Fake drill [human calibration]"
    assert texts[1] == "[claude] Do the thing."
    assert texts[2] == "[claude] Then the other thing."
    assert "Read-only" in texts[3]  # sends_input is False
    assert texts[4] == "[claude] TEST LIVE"
    assert texts[5] == "[claude] TEST CONCLUDED — PASS"


def test_bot_control_drills_warn_hands_off(tmp_path):
    chat = FakeChat()
    drill = Drill("T98", "Bot drill", "bot control", ("Stand clear.",), sends_input=True)
    run_drill(drill, lambda r: "ok", run=make_run(chat), log_path=tmp_path / "log.md")
    assert any("HANDS OFF" in t.upper() for t in chat.delivered)


def test_header_retries_until_the_user_windows_in(tmp_path):
    chat = FakeChat(refusals=3)  # foreground arrives on the 4th attempt
    run_drill(DRILL, lambda r: "ok", run=make_run(chat), log_path=tmp_path / "log.md")
    assert chat.delivered[0].startswith("[claude] TEST T99")


def test_never_foregrounded_logs_not_started(tmp_path):
    chat = FakeChat(refusals=10_000)
    log = tmp_path / "log.md"
    body_ran = []
    status = run_drill(
        DRILL, lambda r: body_ran.append(1), run=make_run(chat), log_path=log
    )
    assert status == "NOT STARTED"
    assert body_ran == []
    assert "| T99 | 1 |" in log.read_text(encoding="utf-8")
    assert "NOT STARTED" in log.read_text(encoding="utf-8")


def test_body_exception_logs_failed(tmp_path):
    log = tmp_path / "log.md"

    def body(run):
        raise ValueError("the grid was upside down")

    status = run_drill(DRILL, body, run=make_run(), log_path=log)
    assert status == "FAILED"
    text = log.read_text(encoding="utf-8")
    assert "FAILED" in text and "the grid was upside down" in text


def test_drill_aborted_logs_aborted(tmp_path):
    def body(run):
        raise DrillAborted("user asked to stop")

    status = run_drill(DRILL, body, run=make_run(), log_path=tmp_path / "log.md")
    assert status == "ABORTED"


def test_run_numbers_increment_per_test_id(tmp_path):
    log = tmp_path / "log.md"
    append_log_row(log, DRILL, "PASS", "first", date="2026-07-30")
    append_log_row(log, DRILL, "PASS", "second", date="2026-07-30")
    other = Drill("T50", "Other", "perception", ())
    append_log_row(log, other, "PASS", "other first", date="2026-07-30")
    text = log.read_text(encoding="utf-8")
    assert "| T99 | 1 |" in text and "| T99 | 2 |" in text
    assert "| T50 | 1 |" in text


def test_log_result_is_flattened_to_one_row(tmp_path):
    log = tmp_path / "log.md"
    append_log_row(log, DRILL, "PASS", "line one\nline two", date="2026-07-30")
    lines = [
        line for line in log.read_text(encoding="utf-8").splitlines()
        if line.startswith("| T99")
    ]
    assert len(lines) == 1 and "line one line two" in lines[0]


def test_capture_hover_requires_rearm_from_the_last_point():
    """The R57 defect, pinned: with the cursor still resting on the last
    capture, nothing may fire until it moves away."""
    positions = iter(
        [(100, 100)] * 50  # resting on the previous capture, forever
    )
    run = make_run(cursor=lambda: next(positions, (100, 100)))
    got = run.capture_hover(
        required_panel=None, last_point=(100, 100), timeout_s=5.0
    )
    assert got is None  # never re-armed, so never captured


def test_capture_hover_fires_after_move_and_stillness():
    moves = [(100, 100)] * 3 + [(400, 300)] * 60  # leave, then hold still
    positions = iter(moves)
    run = make_run(cursor=lambda: next(positions, (400, 300)))
    got = run.capture_hover(
        required_panel=None, last_point=(100, 100), timeout_s=30.0
    )
    assert got is not None
    x, y, fx, fy = got
    assert (x, y) == (400, 300)
    assert fx == pytest.approx(400 / 1536)
    assert fy == pytest.approx(300 / 864)


def test_cancel_stops_a_waiting_drill(tmp_path):
    """R79: cancelling a live drill used to mean waiting out its timeouts or
    Ctrl+C-ing the bridge itself, because the elevated child is unreachable
    from the agent's own shell. A file both sides can see fixes it."""
    cancel = tmp_path / "drill-cancel"
    chat = FakeChat(refusals=10_000)  # would otherwise wait the full patience
    clock = FakeClock()
    run = DrillRun(
        session=object(),
        chat=chat,
        window=SimpleNamespace(client_rect=lambda: RECT),
        ui_array=0,
        cursor=lambda: (0, 0),
        clock=clock,
        sleep=clock.sleep,
        cancel_file=cancel,
    )
    cancel.write_text("cancel")
    status = run_drill(DRILL, lambda r: "unreachable", run=run,
                       log_path=tmp_path / "log.md")
    assert status == "ABORTED"
    assert "cancelled by request" in (tmp_path / "log.md").read_text(encoding="utf-8")


def test_a_stale_cancel_does_not_kill_the_next_run(tmp_path, monkeypatch):
    """The failure mode of the fix: a leftover request making every later
    drill dead on arrival."""
    from pd2bot import drill as drill_module

    cancel = tmp_path / "drill-cancel"
    cancel.write_text("cancel")
    monkeypatch.setattr(drill_module, "CANCEL_FILE", cancel)
    # The staleness clear fires once per process; this test is asserting
    # that first-run behaviour, so reset the flag it keys on.
    monkeypatch.setattr(drill_module, "_cleared_stale_cancel", False)
    chat = FakeChat()
    clock = FakeClock()
    run = DrillRun(
        session=object(), chat=chat,
        window=SimpleNamespace(client_rect=lambda: RECT), ui_array=0,
        cursor=lambda: (0, 0), clock=clock, sleep=clock.sleep,
        cancel_file=cancel,
    )
    status = run_drill(DRILL, lambda r: "ran fine", run=run,
                       log_path=tmp_path / "log.md")
    assert status == "PASS"
    assert not cancel.exists()


def test_cancel_is_sticky_across_a_suite(tmp_path):
    """A cancel means 'stop the testing', not 'skip to the next test' — and
    the per-run staleness clear must not wipe it between drills."""
    cancel = tmp_path / "drill-cancel"
    clock = FakeClock()
    run = DrillRun(
        session=object(), chat=FakeChat(),
        window=SimpleNamespace(client_rect=lambda: RECT), ui_array=0,
        cursor=lambda: (0, 0), clock=clock, sleep=clock.sleep,
        cancel_file=cancel,
    )
    cancel.write_text("cancel")
    first = run_drill(DRILL, lambda r: "no", run=run, log_path=tmp_path / "log.md")
    cancel.unlink()  # even if the file goes away, the run stays cancelled
    second = run_drill(
        Drill("T97", "Next in suite", "perception", ()),
        lambda r: "no", run=run, log_path=tmp_path / "log.md",
    )
    assert first == "ABORTED" and second == "ABORTED"
