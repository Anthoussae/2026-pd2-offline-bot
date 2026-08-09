"""SafetyMonitor: the death latch and the chicken thresholds, all simulated.

Per the M4 death policy (R27/Q6) there is no live death test — the monitor's
entire death behavior is 'send nothing and alert', which simulation covers
completely. These tests also pin the cycle-level guarantees: a dead player
means no input of any kind afterward, and death always beats chicken.
"""

from __future__ import annotations

import pytest

from pd2bot import offsets
from pd2bot.cycle import CycleConfig, GameCycle
from pd2bot.perception import oog, uistate
from pd2bot.perception.player import Player
from pd2bot.perception.world import Area
from pd2bot.safety import (
    ChickenExit,
    DeathHalt,
    SafetyConfig,
    SafetyInterrupt,
    SafetyMonitor,
)
from tests.test_cycle import FakeClock, ScriptedClient

TOWN = Area(level_no=1, position=(1000, 1000), size=(20, 20))
WILDS = Area(level_no=3, position=(1000, 1000), size=(100, 100))


def make_player(
    hp: int = 900, max_hp: int = 1000, mana: int = 400, max_mana: int = 500,
    mode: int = 1,
) -> Player:
    return Player(
        name="MaqiuDoubing", level=90, act=1, position=(5000, 5000), mode=mode,
        hp=hp, max_hp=max_hp, mana=mana, max_mana=max_mana,
        stamina=300, max_stamina=300, experience=0, gold=0, gold_stash=0,
        strength=100, dexterity=100, vitality=300, energy=100,
    )


class Vitals:
    """Mutable stand-in for the live reads."""

    def __init__(self, player: Player | None = None, area: Area = WILDS) -> None:
        self.player = player if player is not None else make_player()
        self.area = area
        self.alerts = 0
        self.reads = 0

    def monitor(self, config: SafetyConfig, clock=None) -> SafetyMonitor:
        def alert() -> None:
            self.alerts += 1

        def read_player(_session):
            self.reads += 1
            return self.player

        return SafetyMonitor(
            session=None,
            config=config,
            read_player_fn=read_player,
            read_area_fn=lambda s: self.area,
            alert=alert,
            **({} if clock is None else {"clock": clock}),
        )


# -- death --------------------------------------------------------------------


@pytest.mark.parametrize("mode", [offsets.PLAYER_MODE_DEATH, offsets.PLAYER_MODE_DEAD])
def test_dead_mode_halts_and_alerts(mode):
    vitals = Vitals(make_player(mode=mode))
    monitor = vitals.monitor(SafetyConfig())
    with pytest.raises(DeathHalt):
        monitor.tick()
    assert monitor.halted
    assert vitals.alerts == 1


def test_zero_hp_halts_even_with_living_mode():
    vitals = Vitals(make_player(hp=0, mode=1))
    with pytest.raises(DeathHalt):
        vitals.monitor(SafetyConfig()).tick()


def test_latch_is_permanent_and_alerts_once():
    vitals = Vitals(make_player(mode=offsets.PLAYER_MODE_DEAD))
    monitor = vitals.monitor(SafetyConfig())
    with pytest.raises(DeathHalt):
        monitor.tick()
    # The world "recovers" (new game, healthy player) — the latch must not.
    vitals.player = make_player()
    with pytest.raises(DeathHalt):
        monitor.tick()
    assert vitals.alerts == 1  # the alert does not spam


def test_death_beats_chicken():
    """hp 0 satisfies both; the latch must win (and set halted)."""
    vitals = Vitals(make_player(hp=0, mode=offsets.PLAYER_MODE_DEAD))
    monitor = vitals.monitor(SafetyConfig(life_chicken_pct=99.0))
    with pytest.raises(DeathHalt):
        monitor.tick()
    assert monitor.halted


# -- chicken ------------------------------------------------------------------


def test_life_chicken_fires_outside_town():
    vitals = Vitals(make_player(hp=450, max_hp=1000))
    with pytest.raises(ChickenExit, match="life 450/1000"):
        vitals.monitor(SafetyConfig(life_chicken_pct=50.0)).tick()


def test_life_chicken_quiet_above_threshold():
    vitals = Vitals(make_player(hp=501, max_hp=1000))
    vitals.monitor(SafetyConfig(life_chicken_pct=50.0)).tick()  # no raise


def test_mana_chicken_independent_of_life():
    vitals = Vitals(make_player(hp=1000, max_hp=1000, mana=10, max_mana=500))
    with pytest.raises(ChickenExit, match="mana 10/500"):
        vitals.monitor(SafetyConfig(life_chicken_pct=0, mana_chicken_pct=90.0)).tick()


def test_chicken_suppressed_in_town_by_default():
    vitals = Vitals(make_player(hp=100, max_hp=1000), area=TOWN)
    vitals.monitor(SafetyConfig(life_chicken_pct=50.0)).tick()  # no raise


def test_chicken_in_town_override_fires():
    vitals = Vitals(make_player(hp=100, max_hp=1000), area=TOWN)
    with pytest.raises(ChickenExit):
        vitals.monitor(
            SafetyConfig(life_chicken_pct=50.0, chicken_in_town=True)
        ).tick()


def test_death_checked_even_in_town():
    vitals = Vitals(make_player(mode=offsets.PLAYER_MODE_DEAD), area=TOWN)
    with pytest.raises(DeathHalt):
        vitals.monitor(SafetyConfig()).tick()


def test_menus_are_quiet():
    vitals = Vitals()
    vitals.player = None  # not in a game
    vitals.monitor(SafetyConfig()).tick()  # no raise


def test_disabled_thresholds_never_fire():
    vitals = Vitals(make_player(hp=1, max_hp=1000, mana=0, max_mana=500))
    vitals.monitor(SafetyConfig(life_chicken_pct=0, mana_chicken_pct=0)).tick()


# -- cycle integration -----------------------------------------------------------


@pytest.fixture
def rig(monkeypatch):
    def build(**config_kwargs):
        client = ScriptedClient(oog.Screen.CHAR_SELECT)
        clock = FakeClock()
        monkeypatch.setattr(uistate, "is_in_game", lambda s: client.is_in_game())
        monkeypatch.setattr(
            uistate,
            "read_ui_state",
            lambda s, ui=None: uistate.UIState(
                frozenset({offsets.UI_ESCMENU_MAIN}) if client.esc_menu else frozenset()
            ),
        )
        from pd2bot.perception import world

        monkeypatch.setattr(
            world, "read_area", lambda s: WILDS if client.is_in_game() else None
        )
        cycle = GameCycle(
            session=None,
            menu_input=client,
            config=CycleConfig(**config_kwargs),
            observe=client.observe,
            read_difficulty=client.read_difficulty,
            clock=clock,
            sleep=clock.sleep,
        )
        return cycle, client

    return build


def test_chicken_leaves_and_the_loop_continues(rig):
    cycle, client = rig()
    calls = []

    def run(session):
        calls.append(True)
        if len(calls) == 1:
            raise ChickenExit("life 40/100 (40%) <= 50% threshold")

    report = cycle.run_games(run, max_games=2)

    assert len(report.outcomes) == 2
    assert report.outcomes[0].chickened and report.outcomes[0].left
    assert report.outcomes[0].error is None
    assert not report.outcomes[1].chickened
    assert report.completed == 1  # chickened cycles are not "clean", by design


def test_consecutive_chickens_halt_the_loop(rig):
    """PD2 carries vitals between games: below-threshold at entry would
    chicken forever. The backstop must stop the merry-go-round loudly."""
    cycle, client = rig()

    def always_chicken(session):
        raise ChickenExit("life 40/100 (40%) <= 50% threshold")

    report = cycle.run_games(always_chicken, max_games=10)

    assert len(report.outcomes) == 2  # default max_consecutive_chickens
    assert all(o.chickened and o.left for o in report.outcomes)
    assert "in a row" in report.outcomes[-1].error
    assert not client.is_in_game()  # it still left the last game safely


def test_a_non_vitals_exit_never_feeds_the_vitals_backstop(rig):
    """R115. The backstop exists for ONE cause and says so in its message.

    PD2 carries HP and mana between games, so a character below the
    threshold chickens out of every game forever — hence a counter and a
    halt that tells the operator to heal. But `IdleBail`, `TownStepFailed`
    and `RunFailed` are all `ChickenExit` subclasses (they want the
    cycle's leave-and-continue handling) and every one of them was
    feeding that counter. A hang could halt the loop with "heal the
    character", which is a wrong answer delivered confidently.
    """

    class NotVitals(ChickenExit):
        is_vitals = False

    cycle, client = rig()

    def never_a_vitals_problem(session):
        raise NotVitals("the bot stood still for 30s")

    report = cycle.run_games(never_a_vitals_problem, max_games=4)

    assert len(report.outcomes) == 4, "the vitals backstop halted a non-vitals loop"
    assert all(o.chickened and o.left for o in report.outcomes)
    assert all(o.error is None for o in report.outcomes)
    assert all(not o.vitals for o in report.outcomes)
    # And the report says which kind it was, rather than calling it all
    # CHICKEN — three of the four were unreadable that way.
    assert "LEFT EARLY" in report.summary() and "CHICKEN" not in report.summary()


def test_the_mixed_sequence_that_used_to_misattribute(rig):
    # One real chicken, then a non-vitals exit. With both counted, this
    # tripped the vitals backstop and blamed the character's health for a
    # bug. The vitals streak must not survive a non-vitals game.
    class NotVitals(ChickenExit):
        is_vitals = False

    cycle, _ = rig()
    calls = []

    def one_then_the_other(session):
        calls.append(True)
        raise ChickenExit("life low") if len(calls) == 1 else NotVitals("stuck")

    report = cycle.run_games(one_then_the_other, max_games=3)

    assert len(report.outcomes) == 3, "halted on a mixed sequence"
    assert [o.vitals for o in report.outcomes] == [True, False, False]


def test_clean_run_resets_the_chicken_streak(rig):
    cycle, client = rig()
    calls = []

    def alternating(session):
        calls.append(True)
        if len(calls) % 2 == 1:
            raise ChickenExit("life low")

    report = cycle.run_games(alternating, max_games=4)

    assert len(report.outcomes) == 4  # never halted: streak resets on clean
    assert [o.chickened for o in report.outcomes] == [True, False, True, False]
    assert report.outcomes[-1].error is None


def test_death_halts_loop_with_no_further_input(rig):
    cycle, client = rig()

    def run(session):
        raise DeathHalt("MaqiuDoubing is dead")

    input_log_before = None

    def spy_run(session):
        nonlocal input_log_before
        input_log_before = list(client.log)
        run(session)

    report = cycle.run_games(spy_run, max_games=3)

    assert len(report.outcomes) == 1
    assert report.outcomes[0].error.startswith("DEAD:")
    assert not report.outcomes[0].left
    # The one guarantee that matters: nothing was sent after the death —
    # the input log is exactly what it was when the callback started.
    assert client.log == input_log_before
    assert client.is_in_game()  # the game was left untouched


# -- poll(): the same judgement, offered mid-block -----------------------------
#
# 2026-08-07: a `walk_to` blocked for 24 s and the monitor, which ran
# only between ticks, never looked. `poll()` is what blocking callers
# call; it must agree with `tick()` about everything except which
# exception it raises.


class VirtualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_poll_and_tick_agree_on_a_chicken():
    config = SafetyConfig(life_chicken_pct=50.0)
    ticked = Vitals(make_player(hp=300))
    polled = Vitals(make_player(hp=300))

    with pytest.raises(ChickenExit) as by_tick:
        ticked.monitor(config).tick()
    with pytest.raises(SafetyInterrupt) as by_poll:
        polled.monitor(config).poll()

    assert by_poll.value.verdict.kind == "life"
    assert str(by_poll.value) == str(by_tick.value)


def test_poll_and_tick_agree_on_silence():
    config = SafetyConfig(life_chicken_pct=50.0)
    healthy = Vitals(make_player(hp=900))
    healthy.monitor(config).tick()
    healthy.monitor(config).poll()  # neither raises


def test_poll_sets_the_death_latch_like_tick_does():
    vitals = Vitals(make_player(mode=offsets.PLAYER_MODE_DEAD))
    monitor = vitals.monitor(SafetyConfig())
    with pytest.raises(SafetyInterrupt) as raised:
        monitor.poll()
    assert raised.value.verdict.is_death
    assert monitor.halted
    assert vitals.alerts == 1
    # And the latch outranks everything afterwards, on either path.
    with pytest.raises(DeathHalt):
        monitor.tick()


def test_a_latched_monitor_interrupts_immediately_without_reading():
    vitals = Vitals(make_player(mode=offsets.PLAYER_MODE_DEAD))
    monitor = vitals.monitor(SafetyConfig())
    with pytest.raises(SafetyInterrupt):
        monitor.poll()
    reads = vitals.reads
    for _ in range(5):
        with pytest.raises(SafetyInterrupt):
            monitor.poll()
    assert vitals.reads == reads  # the latch answers without touching memory


def test_poll_is_rate_limited():
    """It is called from a 10 Hz walk loop; it must not read memory at
    10 Hz to answer. The cost of the interval is chicken latency, which
    is why it is small and configurable rather than absent."""
    clock = VirtualClock()
    vitals = Vitals(make_player(hp=900))
    monitor = vitals.monitor(
        SafetyConfig(life_chicken_pct=50.0, poll_interval_s=0.2), clock=clock
    )
    for _ in range(10):
        monitor.poll()
        clock.now += 0.05  # 10 polls across 0.5 virtual seconds
    assert 1 <= vitals.reads <= 4, vitals.reads


def test_rate_limiting_delays_a_chicken_by_no_more_than_the_interval():
    clock = VirtualClock()
    vitals = Vitals(make_player(hp=900))
    monitor = vitals.monitor(
        SafetyConfig(life_chicken_pct=50.0, poll_interval_s=0.2), clock=clock
    )
    monitor.poll()  # primes the limiter
    vitals.player = make_player(hp=100)  # the crossing happens now
    elapsed = 0.0
    while True:
        clock.now += 0.05
        elapsed += 0.05
        try:
            monitor.poll()
        except SafetyInterrupt:
            break
        assert elapsed < 1.0, "never noticed"
    assert elapsed <= 0.2 + 1e-9


def test_poll_respects_the_town_exemption():
    vitals = Vitals(make_player(hp=100), area=TOWN)
    vitals.monitor(SafetyConfig(life_chicken_pct=50.0)).poll()  # no raise


def test_poll_says_nothing_when_there_is_no_player():
    vitals = Vitals()
    vitals.player = None
    vitals.monitor(SafetyConfig(life_chicken_pct=50.0)).poll()
