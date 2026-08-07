"""T78's pure logic: the acquisition scorecard. The drill needs a game;
its report and its construction do not."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drills.t78_acquire import make_drill, summarise  # noqa: E402


def row(uid, picked, attempts, latency, kind=606, pos=(10, 10)):
    return {
        "unit_id": uid, "kind": kind, "position": pos,
        "picked": picked, "attempts": attempts, "latency_s": latency,
    }


def test_the_scorecard_counts_lifts_and_names_the_pickit_gap():
    text = "\n".join(summarise([
        row(1, True, 1, 0.3),
        row(2, False, 8, 10.0),
    ]))
    assert "1/2 lifted" in text
    assert "pickit not consulted" in text, "the whole point of the drill"
    assert "NOT lifted after 8 attempt(s)" in text


def test_the_scorecard_reports_mean_latency_of_successes_only():
    text = "\n".join(summarise([
        row(1, True, 1, 0.20),
        row(2, True, 1, 0.40),
        row(3, False, 8, 12.0),   # must not drag the mean
    ]))
    assert "mean lift latency (successes): 0.30s" in text


def test_the_scorecard_survives_a_run_that_lifted_nothing():
    text = "\n".join(summarise([row(1, False, 8, 12.0)]))
    assert "0/1 lifted" in text
    assert "mean lift latency" not in text  # no successes to average


def test_the_drill_builds_and_sends_input():
    drill, _ = make_drill()
    assert drill.test_id == "T78"
    assert drill.sends_input is True
