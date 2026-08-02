"""The Narrator: format, lazy file creation, spans that explain waits.

Wall-clock stamps and durations come from injected clocks, so every
assertion here is exact. The coarseness contract itself is asserted where
it can be measured: the sim's line-count test (test_behavior_sim).
"""

import time

import pytest

from pd2bot.narrate import Narrator, noop


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


WALL = time.gmtime(45296)  # 1970-01-01 12:34:56


def make(tmp_path, wall=WALL):
    lines = []
    clock = Clock()
    narrator = Narrator(
        tmp_path / "logs", clock=clock, wall=lambda: wall, echo=lines.append
    )
    return narrator, clock, lines


def test_file_is_named_for_the_run_start_and_created_lazily(tmp_path):
    narrator, _, _ = make(tmp_path)
    assert narrator.path.name == "run-19700101-123456.log"
    assert not narrator.path.exists()  # nothing narrated, nothing on disk
    narrator.narrate("hello")
    assert narrator.path.exists()


def test_lines_are_wall_clock_stamped(tmp_path):
    narrator, _, echoed = make(tmp_path)
    narrator.narrate("waypoint: taken")
    narrator.narrate("clearance: begun")
    content = narrator.path.read_text(encoding="utf-8")
    assert content == (
        "12:34:56  waypoint: taken\n12:34:56  clearance: begun\n"
    )
    assert echoed == ["waypoint: taken", "clearance: begun"]


def test_span_stamps_the_completion_with_its_duration(tmp_path):
    narrator, clock, echoed = make(tmp_path)
    with narrator.span("heal") as done:
        clock.advance(3.8)
        done("verified", "vitals read full")
    assert echoed == ["heal: verified after 3.8s (vitals read full)"]


def test_span_without_details_still_reports_the_wait(tmp_path):
    narrator, clock, echoed = make(tmp_path)
    with narrator.span("settle"):
        clock.advance(5.0)
    assert echoed == ["settle: done after 5.0s"]


def test_span_narrates_a_failure_and_reraises(tmp_path):
    # The dawdle a human asks about is usually the one that ended badly.
    narrator, clock, echoed = make(tmp_path)
    with pytest.raises(ValueError):
        with narrator.span("heal"):
            clock.advance(6.0)
            raise ValueError("no akara")
    assert echoed == ["heal: FAILED after 6.0s (ValueError)"]


def test_noop_swallows_everything():
    assert noop("anything") is None
