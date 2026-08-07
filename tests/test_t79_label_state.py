"""T79's pure logic: the controlled label-state verdict and its gate.

The drill needs a game; the comparison that decides the finding does not
— and it is the half that must not pass on the easy case (T72)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drills.t79_label_state import sufficient, verdict  # noqa: E402


def row(labels, picked, crowd=5):
    return {"labels": labels, "picked": picked, "crowding": crowd}


def test_off_beating_on_confirms_the_lead():
    results = (
        [row(True, False) for _ in range(4)]      # labels ON: 0/4
        + [row(False, True) for _ in range(4)]    # labels OFF: 4/4
    )
    text = "\n".join(verdict(results))
    assert "CONFIRMED" in text
    assert "ensure-ON policy is a pile liability" in text


def test_no_difference_kills_the_lead():
    results = [row(True, True), row(True, True), row(False, True), row(False, True)]
    text = "\n".join(verdict(results))
    assert "not the label flag" in text


def test_on_better_is_reported_as_the_run3_outlier():
    results = (
        [row(True, True) for _ in range(4)]
        + [row(False, False) for _ in range(4)]
    )
    assert "run-3 result was the outlier" in "\n".join(verdict(results))


def test_solo_items_do_not_speak_to_the_pile_question():
    # Only crowd >= MIN_PILE_CROWD counts toward the verdict.
    results = [row(True, False, crowd=0), row(False, True, crowd=0)]
    assert "inconclusive" in "\n".join(verdict(results))


def test_the_gate_needs_a_pile_in_both_states():
    ok, why = sufficient([row(True, False), row(False, True)])
    assert ok and "labels-ON" in why and "labels-OFF" in why

    ok, why = sufficient([row(True, False), row(True, False)])   # ON only
    assert not ok and "INCOMPLETE" in why

    ok, _ = sufficient([row(True, False, 0), row(False, True, 0)])  # no pile
    assert not ok
