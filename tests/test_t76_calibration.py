"""T76's pure logic: classification, crowding, attribution, the verdict.

The drill itself needs a game. These do not — and they are the parts
that decide what the drill is allowed to CONCLUDE, which is exactly the
half that has burned this project before (T72 scored a reproduced
failure as PASS; review 001).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drills.t76_pickup_calibration import (  # noqa: E402
    arrangement_of,
    attribute,
    classify,
    compare_offsets,
    crowding,
    sufficient,
)

CODES = {
    606: "hp5", 611: "mp5", 530: "rvs",   # potions
    634: "r10", 702: "r18",               # runes
    572: "gcv", 576: "gpv", 616: "skz",   # gems and skulls
    618: "cm1", 619: "cm2",               # charms — 619 is T65's 245-probe miss
    445: "utu",                           # armour
}


def test_classes_come_from_the_game_s_own_codes():
    assert classify(606, CODES) == "potion"
    assert classify(530, CODES) == "potion"
    assert classify(634, CODES) == "rune"
    assert classify(572, CODES) == "gem"
    assert classify(616, CODES) == "gem"
    # The one T65 put 245 probes into without a single hit.
    assert classify(619, CODES) == "charm"
    assert classify(445, CODES) == "other"


def test_an_unknown_kind_is_not_guessed_at():
    # R144: a numeric guess is how the bot picked up a Wire Fleece
    # believing it was a Kraken Shell.
    assert classify(9999, CODES) == "unknown"


def test_crowding_counts_only_what_is_close_enough_to_overlap():
    assert crowding((100, 100), [(101, 100), (100, 102), (140, 140)]) == 2
    assert crowding((100, 100), []) == 0


def test_attribution_separates_the_target_from_its_neighbour():
    before = {1: None, 2: None}
    assert attribute(before, {1: None, 2: None}, 1) == ("nothing", None)
    assert attribute(before, {2: None}, 1) == ("target", 1)
    # The case the whole drill exists to see: we clicked 1 and 2 vanished.
    assert attribute(before, {1: None}, 1) == ("neighbour", 2)


def test_the_verdict_says_shifted_when_the_winner_moves_with_crowding():
    results = [
        {"arrangement": "solo", "item_class": "rune", "winning_offset": [0, -28]},
        {"arrangement": "pile", "item_class": "rune", "winning_offset": [0, -48]},
    ]
    text = "\n".join(compare_offsets(results))
    assert "SHIFTED with crowding" in text
    assert "hypothesis SUPPORTED" in text


def test_the_verdict_says_stable_when_the_winner_holds():
    results = [
        {"arrangement": "solo", "item_class": "potion", "winning_offset": [0, -28]},
        {"arrangement": "pile", "item_class": "potion", "winning_offset": [0, -28]},
    ]
    text = "\n".join(compare_offsets(results))
    assert "STABLE across crowding" in text
    assert "hypothesis WEAKENED" in text


def test_the_verdict_refuses_to_conclude_from_one_arrangement():
    results = [
        {"arrangement": "solo", "item_class": "potion", "winning_offset": [0, -28]},
    ]
    assert "inconclusive" in "\n".join(compare_offsets(results))


def test_a_target_that_never_came_up_is_reported_not_hidden():
    results = [
        {"arrangement": "pile", "item_class": "charm", "winning_offset": None},
        {"arrangement": "solo", "item_class": "charm", "winning_offset": [0, -48]},
    ]
    text = "\n".join(compare_offsets(results))
    assert "never came up" in text


def test_the_drill_cannot_pass_on_the_easy_case_alone():
    """The T72 lesson, in the criteria rather than in a comment: a
    calibration that measured only solo rounds would license exactly the
    wrong fix."""
    solo_only = [
        {"arrangement": "solo", "item_class": "potion", "winning_offset": [0, -28]},
        {"arrangement": "solo", "item_class": "rune", "winning_offset": [0, -48]},
    ]
    ok, why = sufficient(solo_only)
    assert not ok and "INCOMPLETE" in why


def test_two_classes_measured_both_ways_is_enough():
    results = [
        {"arrangement": a, "item_class": c, "winning_offset": [0, -28]}
        for c in ("potion", "rune")
        for a in ("solo", "pile")
    ]
    ok, why = sufficient(results)
    assert ok and "2 class(es)" in why


def test_the_arrangement_is_measured_from_the_floor_not_asked_for():
    """Run 1's staging failure: the drill demanded exact counts, the
    census disagreed with the operator, and BOTH crowded rounds were
    skipped. Crowding is a property of the floor, so measure it."""
    assert arrangement_of(0) == "solo"
    assert arrangement_of(1) == "pair"
    assert arrangement_of(2) == "pile"
    assert arrangement_of(7) == "pile"


def test_one_class_measured_both_ways_is_not_enough():
    results = [
        {"arrangement": a, "item_class": "potion", "winning_offset": [0, -28]}
        for a in ("solo", "pile")
    ]
    ok, _ = sufficient(results)
    assert not ok
