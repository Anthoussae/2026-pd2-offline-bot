"""T79's pure logic: the controlled label-state verdict and its gate.

The drill needs a game; the comparison that decides the finding does not
— and it is the half that must not pass on the easy case (T72)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drills.t79_label_state import droppable, sufficient, verdict  # noqa: E402
from pd2bot import offsets  # noqa: E402


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
    assert "no meaningful label-state difference" in text


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


def test_the_gate_needs_a_real_pile_in_both_states():
    # >= 3 per state (run 1's n=1 OFF result must not PASS again).
    on = [row(True, False) for _ in range(3)]
    off = [row(False, True) for _ in range(3)]
    ok, why = sufficient(on + off)
    assert ok and "ON (3)" in why and "OFF (3)" in why

    ok, why = sufficient(on + [row(False, True)])   # OFF only n=1
    assert not ok and "INCOMPLETE" in why

    ok, _ = sufficient(on)                          # ON only
    assert not ok

    ok, _ = sufficient(
        [row(True, False, 0) for _ in range(3)]
        + [row(False, True, 0) for _ in range(3)]   # no pile (crowd 0)
    )
    assert not ok


def test_droppable_excludes_the_tomes_the_cube_and_potions():
    from dataclasses import dataclass

    @dataclass
    class FakeCarried:
        _items: list

        @property
        def main_inventory(self):
            return self._items

    @dataclass
    class Itm:
        unit_id: int
        kind: int

    tome = next(iter(offsets.UNMOVABLE_KINDS))
    potion = next(iter(offsets.POTION_KINDS))
    items = [Itm(1, 999), Itm(2, tome), Itm(3, potion), Itm(4, 888)]
    kept = {i.unit_id for i in droppable(FakeCarried(items))}
    assert kept == {1, 4}, "only the non-hazard items are droppable"


def test_droppable_caps_the_pile():
    from dataclasses import dataclass

    @dataclass
    class FakeCarried:
        @property
        def main_inventory(self):
            return [type("I", (), {"unit_id": i, "kind": 900 + i})() for i in range(20)]

    assert len(droppable(FakeCarried(), limit=8)) == 8
