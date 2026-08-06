"""P6/P7: the layer and perception events.

Covers the families the operator asked for that do not live in the action
funnel: stash deposits, NPC interaction (requested vs accidental), the
waypoint sequence, area transitions, chicken and death, and the item
lifecycle.
"""

from pd2bot import offsets
from pd2bot.player import Player
from pd2bot.runlog import RunLog, load
from pd2bot.safety import ChickenExit, DeathHalt, SafetyConfig, SafetyMonitor
from pd2bot.world import Area


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def log_for(tmp_path):
    return RunLog("t", root=tmp_path, clock=Clock(), wall=lambda: 1786000000.0)


def player(hp=1737, mana=402, mode=1):
    return Player(
        name="N", level=91, act=1, position=(10006, 8002), mode=mode,
        hp=hp, max_hp=2000, mana=mana, max_mana=500,
        stamina=0, max_stamina=0, experience=0, gold=0, gold_stash=0,
        strength=0, dexterity=0, vitality=0, energy=0,
    )


def only(events, kind):
    matches = [e for e in events if e["kind"] == kind]
    assert len(matches) == 1, f"expected one {kind}, got {[e['kind'] for e in events]}"
    return matches[0]


# -- chicken and death: the two moments most worth a precise record -------------


def test_a_chicken_records_the_vitals_that_caused_it(tmp_path):
    log = log_for(tmp_path)
    monitor = SafetyMonitor(
        None, SafetyConfig(life_chicken_pct=35.0, chicken_in_town=True),
        read_player_fn=lambda s: player(hp=600),
        read_area_fn=lambda s: Area(level_no=20, position=(0, 0), size=(8, 8)),
        alert=lambda: None, runlog=log,
    )
    try:
        monitor.tick()
    except ChickenExit:
        pass
    event = only(load(log.directory), "chicken")
    assert event["reason"] == "life"
    assert event["hp"] == 600 and event["max_hp"] == 2000
    assert event["threshold"] == 35.0
    assert event["mana"] == 402          # both vitals, as asked
    assert event["area"] == 20


def test_a_death_is_recorded_before_the_latch_halts_everything(tmp_path):
    log = log_for(tmp_path)
    monitor = SafetyMonitor(
        None, SafetyConfig(),
        read_player_fn=lambda s: player(hp=0, mode=offsets.PLAYER_MODE_DEAD),
        read_area_fn=lambda s: Area(level_no=20, position=(0, 0), size=(8, 8)),
        alert=lambda: None, runlog=log,
    )
    try:
        monitor.tick()
    except DeathHalt:
        pass
    event = only(load(log.directory), "death")
    assert event["hp"] == 0


def test_the_monitors_logging_can_never_endanger_the_monitor(tmp_path):
    """The last line of defence must not be at risk from its own
    instrumentation, least of all on the tick it is halting the bot."""

    class Exploding:
        enabled = True

        def event(self, kind, /, **fields):
            raise RuntimeError("disk gone")

    monitor = SafetyMonitor(
        None, SafetyConfig(),
        read_player_fn=lambda s: player(hp=0, mode=offsets.PLAYER_MODE_DEAD),
        read_area_fn=lambda s: None,
        alert=lambda: None, runlog=Exploding(),
    )
    try:
        monitor.tick()
    except DeathHalt:
        pass  # the RIGHT exception — not the logger's
    assert monitor.halted
