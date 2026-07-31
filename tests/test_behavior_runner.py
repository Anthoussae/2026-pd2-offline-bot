"""The callback boundary: idle bails counted apart from vitals chickens."""

import pytest

from pd2bot.behavior.engine import IdleBail
from pd2bot.behavior.runner import BehaviorRunner, IdleLoopHalt, StashFullHalt
from pd2bot.cycle import CycleError
from pd2bot.safety import ChickenExit
from pd2bot.town import StashFull


class ScriptedEngine:
    """run() raises the next scripted exception, or completes quietly."""

    def __init__(self, outcome):
        self.outcome = outcome

    def run(self):
        if self.outcome is not None:
            raise self.outcome


def runner(script, alerts=None):
    """A BehaviorRunner whose per-game engines follow `script`."""
    outcomes = list(script)
    return BehaviorRunner(
        lambda session: ScriptedEngine(outcomes.pop(0)),
        alert=(alerts.append if alerts is not None else lambda r: None),
    )


def test_first_idle_bail_propagates_as_a_chicken():
    r = runner([IdleBail("stood around")])
    with pytest.raises(IdleBail):
        r(session=None)
    assert r.idle_bails == 1


def test_second_consecutive_idle_bail_halts_loudly():
    alerts = []
    r = runner([IdleBail("one"), IdleBail("two")], alerts)
    with pytest.raises(IdleBail):
        r(None)
    with pytest.raises(IdleLoopHalt, match="idle-bailed 2 runs in a row"):
        r(None)
    assert len(alerts) == 1
    assert "bug" in alerts[0]


def test_idle_loop_halt_is_loop_halting_not_a_chicken():
    # CycleError halts run_games' loop; a ChickenExit would keep it cycling.
    assert issubclass(IdleLoopHalt, CycleError)
    assert not issubclass(IdleLoopHalt, ChickenExit)


def test_a_completed_run_resets_the_count():
    r = runner([IdleBail("one"), None, IdleBail("two"), IdleBail("three")])
    with pytest.raises(IdleBail):
        r(None)
    r(None)  # completes; the loop is broken, so it was not a loop
    assert r.idle_bails == 0
    with pytest.raises(IdleBail):
        r(None)
    with pytest.raises(IdleLoopHalt):
        r(None)


def test_vitals_chickens_pass_through_uncounted():
    r = runner([ChickenExit("hp low"), ChickenExit("hp low")])
    for _ in range(2):
        with pytest.raises(ChickenExit):
            r(None)
    assert r.idle_bails == 0  # a real chicken is not an idle bail


def test_vitals_chicken_does_not_reset_the_idle_count():
    r = runner([IdleBail("one"), ChickenExit("hp"), IdleBail("two")])
    with pytest.raises(IdleBail):
        r(None)
    with pytest.raises(ChickenExit):
        r(None)
    with pytest.raises(IdleLoopHalt):
        r(None)  # still the second idle bail without a completed run between


# -- the full stash: a wall, not a bug --------------------------------------------


def stash_runner(script, alerts):
    outcomes = list(script)
    return BehaviorRunner(
        lambda session: ScriptedEngine(outcomes.pop(0)),
        alert=lambda r: None,
        stash_alert=alerts.append,
    )


def test_a_full_stash_halts_the_loop_loudly():
    """`StashFull` used to escape as an unhandled TownError and end the
    session with a traceback — the same escape shape as review 002's
    InputRefused. It is a real stop, but it should look like one."""
    alerts = []
    r = stash_runner([StashFull("3 items left in the inventory")], alerts)
    with pytest.raises(StashFullHalt, match="would not take the inventory"):
        r(None)
    assert len(alerts) == 1
    # The alert names the cause AND carries the town layer's own detail, so
    # the human reading it knows which stash and how many items.
    assert "would not take the inventory" in alerts[0]
    assert "3 items left in the inventory" in alerts[0]


def test_stash_full_halt_is_loop_halting_not_a_chicken():
    # Cycling into another game would hit the same wall one preamble later,
    # with a fuller inventory each time. There is no version of this the bot
    # can fix by itself, so the loop must stop rather than retry.
    assert issubclass(StashFullHalt, CycleError)
    assert not issubclass(StashFullHalt, ChickenExit)


def test_a_full_stash_does_not_count_as_an_idle_bail():
    alerts = []
    r = stash_runner([StashFull("full")], alerts)
    with pytest.raises(StashFullHalt):
        r(None)
    assert r.idle_bails == 0
