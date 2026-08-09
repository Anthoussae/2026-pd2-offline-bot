"""The chicken watchdog: a second process that presses ESC and nothing else.

No game and no real clock — the whole state machine is injected, which
is the same discipline `SafetyMonitor` and `Navigator` are tested under.
The assertions that matter most are the negative ones: what it must
NOT do when the character is dead, and what it must not claim when the
ESC did not actually pause anything.
"""

from __future__ import annotations

import json

import pytest

from pd2bot import offsets
from pd2bot.perception.player import Player
from pd2bot.perception.world import Area
from pd2bot.safety.watchdog import (
    DEATH_CONFIRMATIONS,
    HEARTBEAT_STALE_AFTER_S,
    LATCH_STALE_AFTER_S,
    THRESHOLD_GAP_PCT,
    Watchdog,
    WatchdogConfig,
    active_latch,
    clear_latch,
    heartbeat_age,
    read_latch,
    watchdog_is_alive,
    write_heartbeat,
    write_latch,
)

WILDS = Area(level_no=3, position=(0, 0), size=(100, 100))
TOWN = Area(level_no=1, position=(0, 0), size=(20, 20))


def make_player(hp=1000, max_hp=1000, mana=400, max_mana=500, mode=1) -> Player:
    return Player(
        name="MaqiuDoubing", level=90, act=1, position=(5000, 5000), mode=mode,
        hp=hp, max_hp=max_hp, mana=mana, max_mana=max_mana,
        stamina=300, max_stamina=300, experience=0, gold=0, gold_stash=0,
        strength=100, dexterity=100, vitality=300, energy=100,
    )


class Rig:
    """A scripted client: vitals we can move, an ESC that may or may not
    pause, and a wall clock that only advances when we say so."""

    def __init__(self, tmp_path, player=None, area=WILDS, esc_works=True) -> None:
        self.player = player if player is not None else make_player()
        self.area = area
        self.esc_works = esc_works
        self.esc_raises: Exception | None = None
        self.presses = 0
        self.paused = False
        self.alerts: list[str] = []
        self.now = 1_000_000.0
        self.heartbeat = tmp_path / "watchdog-heartbeat"
        self.latch = tmp_path / "watchdog-latch"

    def press(self) -> None:
        self.presses += 1
        if self.esc_raises is not None:
            raise self.esc_raises
        if self.esc_works:
            self.paused = True

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def watchdog(self, config: WatchdogConfig | None = None) -> Watchdog:
        return Watchdog(
            session=None,
            config=config if config is not None else WatchdogConfig(life_pct=30.0),
            press_escape=self.press,
            read_player_fn=lambda s: self.player,
            read_area_fn=lambda s: self.area,
            esc_menu_open=lambda: self.paused,
            alert=self.alerts.append,
            # Both channels land in one list: the tests care THAT the
            # operator is told, not which severity carried it. The
            # severity itself is pinned separately — anything reachable
            # from inside the poll loop must use `say`, because `alert`
            # beeps and a beep blocks (2026-08-08).
            say=self.alerts.append,
            clock=lambda: self.now,
            wall=lambda: self.now,
            sleep=self.sleep,
            heartbeat_path=self.heartbeat,
            latch_path=self.latch,
        )


# -- firing --------------------------------------------------------------------


def test_it_fires_when_life_crosses(tmp_path):
    rig = Rig(tmp_path, make_player(hp=200))  # 20% of 1000
    dog = rig.watchdog()
    dog.tick()
    assert rig.presses == 1
    assert dog.fired
    assert read_latch(rig.latch)["reason"] == "life"


def test_it_is_quiet_above_the_threshold(tmp_path):
    rig = Rig(tmp_path, make_player(hp=800))
    rig.watchdog().tick()
    assert rig.presses == 0
    assert read_latch(rig.latch) is None


def test_it_does_not_keep_pressing_at_a_paused_game(tmp_path):
    rig = Rig(tmp_path, make_player(hp=200))
    dog = rig.watchdog()
    for _ in range(5):
        dog.tick()
    assert rig.presses == 1


def test_the_latch_is_written_before_the_press(tmp_path):
    """If this process dies between the two, the bot must still learn a
    watchdog chicken happened — so the order is not cosmetic."""
    rig = Rig(tmp_path, make_player(hp=200))
    rig.esc_raises = RuntimeError("the process died here")
    dog = rig.watchdog()
    dog.tick()
    assert read_latch(rig.latch)["reason"] == "life"


def test_a_refused_press_is_retried_not_fatal(tmp_path):
    rig = Rig(tmp_path, make_player(hp=200))
    rig.esc_raises = RuntimeError("not foreground")
    dog = rig.watchdog()
    dog.tick()
    assert rig.presses > 1
    assert any("refused" in a for a in rig.alerts)


def test_it_presses_again_when_the_esc_menu_did_not_open(tmp_path):
    """A blocking panel eats the first ESC — it closes the PANEL, and the
    game is not paused at all. Verified, never assumed."""
    rig = Rig(tmp_path, make_player(hp=200), esc_works=False)
    dog = rig.watchdog()
    dog.tick()
    assert rig.presses > 1


def test_it_gives_up_loudly_rather_than_pressing_for_ever(tmp_path):
    rig = Rig(tmp_path, make_player(hp=200), esc_works=False)
    dog = rig.watchdog()
    dog.tick()
    assert rig.presses <= 5
    assert any("never opened" in a for a in rig.alerts)
    assert dog.fired  # it stops; the operator has been told


def test_mana_is_the_zero_risk_live_test_path(tmp_path):
    """Same code path as life, which is the point — `safety.py` uses the
    identical trick so the canary can run in town at no risk."""
    rig = Rig(tmp_path, make_player(hp=1000, mana=10, max_mana=500))
    rig.watchdog(WatchdogConfig(life_pct=0.0, mana_pct=90.0)).tick()
    assert rig.presses == 1
    assert read_latch(rig.latch)["reason"] == "mana"


# -- death: the assertion that matters most ------------------------------------


@pytest.mark.parametrize("mode", [offsets.PLAYER_MODE_DEATH, offsets.PLAYER_MODE_DEAD])
def test_it_sends_nothing_at_all_when_the_character_is_dead(tmp_path, mode):
    """R27/Q6, unchanged: the game is left exactly as the human needs to
    see it. A watchdog pressing keys at a corpse is guessing after the
    guess already went wrong."""
    rig = Rig(tmp_path, make_player(hp=0, mode=mode))
    dog = rig.watchdog()
    for _ in range(DEATH_CONFIRMATIONS):  # corroborated, not believed on one read
        dog.tick()
    assert rig.presses == 0
    assert dog.stopped
    assert read_latch(rig.latch)["reason"] == "death"


def test_death_stops_the_loop(tmp_path):
    rig = Rig(tmp_path, make_player(mode=offsets.PLAYER_MODE_DEAD))
    dog = rig.watchdog()
    dog.run(until=lambda: dog.stopped)
    assert rig.presses == 0


def test_a_death_below_the_threshold_still_sends_nothing(tmp_path):
    """Both conditions true at once; death must win, as it does in the
    monitor."""
    rig = Rig(tmp_path, make_player(hp=0, mode=offsets.PLAYER_MODE_DEAD))
    dog = rig.watchdog()
    for _ in range(DEATH_CONFIRMATIONS):
        dog.tick()
    assert rig.presses == 0
    assert read_latch(rig.latch)["reason"] == "death"


# -- the quiet paths -----------------------------------------------------------


def test_no_player_is_normal_not_an_error(tmp_path):
    rig = Rig(tmp_path)
    rig.player = None
    rig.watchdog().tick()
    assert rig.presses == 0
    assert heartbeat_age(rig.heartbeat, rig.now) is not None


def test_town_is_exempt_by_default(tmp_path):
    rig = Rig(tmp_path, make_player(hp=100), area=TOWN)
    rig.watchdog().tick()
    assert rig.presses == 0


def test_town_can_be_included_for_the_canary(tmp_path):
    rig = Rig(tmp_path, make_player(hp=100), area=TOWN)
    rig.watchdog(WatchdogConfig(life_pct=30.0, in_town=True)).tick()
    assert rig.presses == 1


def test_death_is_checked_even_in_town(tmp_path):
    rig = Rig(tmp_path, make_player(mode=offsets.PLAYER_MODE_DEAD), area=TOWN)
    dog = rig.watchdog()
    for _ in range(DEATH_CONFIRMATIONS):
        dog.tick()
    assert dog.stopped


# -- the heartbeat -------------------------------------------------------------


def test_the_heartbeat_advances_every_tick(tmp_path):
    rig = Rig(tmp_path)
    dog = rig.watchdog()
    dog.tick()
    first = json.loads(rig.heartbeat.read_text())["at"]
    rig.now += 1.0
    dog.tick()
    assert json.loads(rig.heartbeat.read_text())["at"] > first


def test_the_heartbeat_is_written_on_the_death_tick_too(tmp_path):
    """The bot must be able to tell "the watchdog is gone" apart from
    "the watchdog saw a death and stood down"."""
    rig = Rig(tmp_path, make_player(mode=offsets.PLAYER_MODE_DEAD))
    rig.watchdog().tick()
    assert watchdog_is_alive(rig.heartbeat, rig.now)


def test_an_absent_heartbeat_reads_as_not_alive(tmp_path):
    assert not watchdog_is_alive(tmp_path / "nothing-here")


def test_a_stale_heartbeat_reads_as_not_alive(tmp_path):
    path = tmp_path / "hb"
    write_heartbeat(path, now=1000.0)
    assert watchdog_is_alive(path, now=1000.0 + HEARTBEAT_STALE_AFTER_S - 0.1)
    assert not watchdog_is_alive(path, now=1000.0 + HEARTBEAT_STALE_AFTER_S + 0.1)


def test_a_corrupt_heartbeat_reads_as_not_alive(tmp_path):
    path = tmp_path / "hb"
    path.write_text("not json at all", encoding="utf-8")
    assert not watchdog_is_alive(path)


# -- the latch, and its staleness ----------------------------------------------


def test_a_stale_latch_from_a_previous_session_is_cleared_at_startup(tmp_path):
    """The cancel-file lesson: a sticky file nobody clears becomes a bot
    that cannot act and cannot say why."""
    rig = Rig(tmp_path)
    write_latch("life", rig.latch, now=rig.now - 10_000)
    rig.watchdog()  # construction alone clears it
    assert read_latch(rig.latch) is None


def test_clearing_happens_once_and_does_not_wipe_our_own_latch(tmp_path):
    rig = Rig(tmp_path, make_player(hp=200))
    dog = rig.watchdog()
    dog.tick()
    dog.tick()
    assert read_latch(rig.latch) is not None


def test_an_old_latch_is_not_active(tmp_path):
    path = tmp_path / "latch"
    write_latch("life", path, now=1000.0)
    assert active_latch(path, now=1000.0 + LATCH_STALE_AFTER_S - 1) is not None
    assert active_latch(path, now=1000.0 + LATCH_STALE_AFTER_S + 1) is None


def test_an_undateable_latch_is_not_trusted(tmp_path):
    path = tmp_path / "latch"
    path.write_text(json.dumps({"reason": "life"}), encoding="utf-8")
    assert active_latch(path) is None


def test_no_latch_is_no_latch(tmp_path):
    assert active_latch(tmp_path / "nothing") is None


def test_clear_latch_is_safe_when_there_is_nothing_to_clear(tmp_path):
    clear_latch(tmp_path / "nothing")  # must not raise


# -- the threshold gap ---------------------------------------------------------


def test_the_default_threshold_sits_below_the_bots(monkeypatch):
    """A backstop that fires first is not a backstop: the bot's own leave
    is graceful and live-verified, and should win whenever it can."""
    from pd2bot.behavior import combat
    from pd2bot.safety import watchdog as module

    monkeypatch.setattr(
        combat, "load_class_config",
        lambda path: type("C", (), {"chicken_life_pct": 35.0})(),
    )
    assert module.default_threshold() == 35.0 - THRESHOLD_GAP_PCT


def test_an_unreadable_class_config_still_leaves_it_armed(monkeypatch):
    from pd2bot.behavior import combat
    from pd2bot.safety import watchdog as module

    def explode(path):
        raise OSError("no config here")

    monkeypatch.setattr(combat, "load_class_config", explode)
    assert module.default_threshold() == WatchdogConfig().life_pct


# -- taking the window back ----------------------------------------------------
#
# press_escape guards on foreground and nothing else, so a watchdog that
# never refocuses cannot save a character while the operator is
# alt-tabbed - which is exactly when nobody is watching.


class FocusRig(Rig):
    def __init__(self, tmp_path, focused=True, **kw) -> None:
        super().__init__(tmp_path, **kw)
        self.focused = focused
        self.focus_calls = 0
        self.focus_raises: Exception | None = None

    def ensure_focus(self) -> bool:
        self.focus_calls += 1
        if self.focus_raises is not None:
            raise self.focus_raises
        return self.focused

    def press(self) -> None:
        # The real guard: refuses unless the window is ours.
        if not self.focused:
            self.presses += 1
            raise RuntimeError("the game window is not in the foreground")
        super().press()

    def watchdog(self, config: WatchdogConfig | None = None) -> Watchdog:
        dog = super().watchdog(config)
        dog._ensure_focus = self.ensure_focus
        return dog


def test_it_takes_the_window_before_pressing(tmp_path):
    rig = FocusRig(tmp_path, player=make_player(hp=200))
    rig.watchdog().tick()
    assert rig.focus_calls >= 1
    assert rig.presses == 1


def test_a_lost_window_is_retaken_and_then_the_esc_lands(tmp_path):
    """The scenario this exists for: focus is elsewhere when vitals
    cross, and the watchdog must get it back rather than give up."""
    rig = FocusRig(tmp_path, focused=False, player=make_player(hp=200))

    def regain() -> bool:
        rig.focus_calls += 1
        rig.focused = True  # the refocus works on the first try
        return True

    dog = rig.watchdog()
    dog._ensure_focus = regain
    dog.tick()
    assert dog.fired
    assert rig.presses == 1


def test_a_focus_failure_does_not_stop_the_attempt(tmp_path):
    """Best effort: if the window cannot be taken we still press, because
    the press reports its own refusal and the loop retries."""
    rig = FocusRig(tmp_path, focused=False, player=make_player(hp=200))
    dog = rig.watchdog()
    dog.tick()
    assert rig.focus_calls > 1  # tried on every attempt
    assert rig.presses > 1  # and pressed anyway, each time
    assert any("could not take the game window" in a for a in rig.alerts)


def test_a_raising_focus_helper_is_not_fatal(tmp_path):
    rig = FocusRig(tmp_path, player=make_player(hp=200))
    rig.focus_raises = OSError("no window")
    dog = rig.watchdog()
    dog.tick()
    assert rig.presses >= 1
    assert any("focus attempt failed" in a for a in rig.alerts)


def test_no_focus_helper_is_still_a_working_watchdog(tmp_path):
    """Drills and sims wire none; the watchdog must not require one."""
    rig = Rig(tmp_path, make_player(hp=200))
    dog = rig.watchdog()
    assert dog._ensure_focus is None
    dog.tick()
    assert rig.presses == 1


# -- blindness: what a failed read must and must not do ------------------------
#
# 2026-08-08, live: the loop had no handler, so the FIRST read error -
# during the waypoint area change, ~16 s in - killed the process. The bot
# caught it (the dead-man switch worked and it left the game cleanly),
# but the safety layer was simply gone.


class BlindRig(Rig):
    def __init__(self, tmp_path, fail_times=1, **kw) -> None:
        super().__init__(tmp_path, **kw)
        self.fail_times = fail_times
        self.reads = 0

    def read_player(self, _session):
        self.reads += 1
        if self.reads <= self.fail_times:
            raise OSError("could not read memory (torn read during a load)")
        return self.player

    def watchdog(self, config: WatchdogConfig | None = None) -> Watchdog:
        dog = super().watchdog(config)
        dog._read_player = self.read_player
        return dog


def test_a_failed_read_does_not_kill_the_loop(tmp_path):
    """The one process whose entire job is to still be running."""
    rig = BlindRig(tmp_path, fail_times=3, player=make_player(hp=200))
    dog = rig.watchdog()
    stop = {"after": 6}

    def until() -> bool:
        stop["after"] -= 1
        return stop["after"] <= 0

    dog.run(until=until)
    assert rig.reads > 3  # it kept reading after the failures
    assert dog.fired  # and still did its job once it could see


def test_a_blind_watchdog_does_not_heartbeat(tmp_path):
    """Silence is the honest signal. A heartbeat while blind would tell
    the bot it is guarded by something that cannot see."""
    rig = BlindRig(tmp_path, fail_times=99)
    dog = rig.watchdog()
    dog.tick()
    assert heartbeat_age(rig.heartbeat, rig.now) is None  # nothing written
    assert any("not heartbeating while blind" in a for a in rig.alerts)


def test_sight_restored_resumes_the_heartbeat(tmp_path):
    rig = BlindRig(tmp_path, fail_times=1)
    dog = rig.watchdog()
    dog.tick()
    assert heartbeat_age(rig.heartbeat, rig.now) is None
    dog.tick()
    assert heartbeat_age(rig.heartbeat, rig.now) is not None


def test_blindness_is_reported_but_not_spammed(tmp_path):
    rig = BlindRig(tmp_path, fail_times=99)
    dog = rig.watchdog()
    for _ in range(30):
        dog.tick()
    # Loud at the start, then rationed - an alert per tick at 5 Hz would
    # bury the one message that matters.
    assert 2 <= len(rig.alerts) <= 5


def test_an_unreadable_area_is_not_treated_as_town(tmp_path):
    """Fail toward guarding: 'unreadable' must never silently disarm the
    watchdog, least of all while perception is already struggling."""
    rig = Rig(tmp_path, make_player(hp=200))

    def explode(_session):
        raise OSError("area unreadable mid-transition")

    dog = rig.watchdog()
    dog._read_area = explode
    dog.tick()
    assert rig.presses == 1  # it guarded rather than assuming town


def test_production_arms_life_only(tmp_path):
    """The canary arms mana; a real run must not. Pinned because a stray
    mana threshold would chicken a healthy character out of every game."""
    assert WatchdogConfig().mana_pct == 0.0
    rig = Rig(tmp_path, make_player(hp=1000, mana=0, max_mana=500))
    rig.watchdog(WatchdogConfig(life_pct=30.0)).tick()
    assert rig.presses == 0  # empty mana, full life: nothing happens


# -- the heartbeat has to actually land ----------------------------------------
#
# 2026-08-08: the watchdog beat reliably for ~10 s and then stopped while
# still running and still guarding. Every failed write was swallowed, so
# the only symptom was the BOT standing down for a watchdog that was fine.


def test_the_heartbeat_is_written_atomically(tmp_path):
    """A plain write opens the destination, which collides with the two
    processes reading it 5x a second. Temp-plus-rename cannot."""
    path = tmp_path / "hb"
    assert write_heartbeat(path, now=1000.0) is True
    assert not (tmp_path / "hb.tmp").exists()  # nothing left behind
    assert heartbeat_age(path, now=1000.0) == 0.0


def test_a_failed_beat_is_reported_not_swallowed(tmp_path):
    """The miss itself is survivable. Being unable to SEE the miss is
    what turned a working watchdog into an unexplained stand-down."""
    rig = Rig(tmp_path)
    dog = rig.watchdog()
    # A directory where the file should be: writes fail, forever.
    (tmp_path / "blocked").mkdir()
    dog._heartbeat = tmp_path / "blocked"
    for _ in range(20):
        dog._beat()
    assert dog._beat_failures == 20
    assert any("could not write the heartbeat" in a for a in rig.alerts)
    assert any("still guarding" in a for a in rig.alerts)


def test_beats_landing_again_clears_the_complaint(tmp_path):
    rig = Rig(tmp_path)
    dog = rig.watchdog()
    dog._heartbeat = tmp_path / "blocked"
    (tmp_path / "blocked").mkdir()
    dog._beat()
    assert dog._beat_failures == 1
    dog._heartbeat = tmp_path / "fine"
    dog._beat()
    assert dog._beat_failures == 0


def test_write_heartbeat_reports_failure_rather_than_raising(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    assert write_heartbeat(blocked, now=1000.0) is False  # no exception


# -- false death: the torn read on a loading screen ----------------------------
#
# 2026-08-08, live: the watchdog latched death with hp 0, max_hp 921 and
# mode 5 - a LIVING mode. It polls at 5 Hz straight through the loading
# screen, where hp reads 0 for a moment. The false latch cost the run and
# disarmed world input, which is how it announced itself.


def test_one_torn_read_is_not_a_death(tmp_path):
    rig = Rig(tmp_path, make_player(hp=0, max_hp=921, mode=5))
    dog = rig.watchdog()
    dog.tick()
    assert not dog.stopped
    assert read_latch(rig.latch) is None


def test_a_persistent_zero_hp_is_believed(tmp_path):
    """Corroboration delays the verdict; it must not veto it."""
    rig = Rig(tmp_path, make_player(hp=0, max_hp=921, mode=5))
    dog = rig.watchdog()
    for _ in range(THREE := 3):
        dog.tick()
    assert THREE == 3
    assert dog.stopped
    assert read_latch(rig.latch)["reason"] == "death"
    assert rig.presses == 0  # and still sends nothing


def test_a_living_read_resets_the_count(tmp_path):
    """A flicker between loads must not accumulate toward a latch."""
    rig = Rig(tmp_path, make_player(hp=0, max_hp=921, mode=5))
    dog = rig.watchdog()
    dog.tick()
    dog.tick()
    rig.player = make_player(hp=900, max_hp=921, mode=5)  # alive after all
    dog.tick()
    rig.player = make_player(hp=0, max_hp=921, mode=5)
    dog.tick()
    assert not dog.stopped  # the count restarted, so two is not three


def test_a_death_MODE_still_needs_corroboration_but_arrives(tmp_path):
    rig = Rig(tmp_path, make_player(mode=offsets.PLAYER_MODE_DEAD))
    dog = rig.watchdog()
    dog.tick()
    assert not dog.stopped
    dog.tick()
    dog.tick()
    assert dog.stopped
    assert rig.presses == 0


def test_a_wholly_uninitialised_read_is_never_a_death(tmp_path):
    """max_hp 0 is not a corpse, it is a struct that has not been filled
    in yet - and no number of repeats should make it one."""
    rig = Rig(tmp_path, make_player(hp=0, max_hp=0, mode=5))
    dog = rig.watchdog()
    for _ in range(10):
        dog.tick()
    assert not dog.stopped
    assert read_latch(rig.latch) is None



def test_nothing_in_the_poll_loop_uses_the_beeping_alarm():
    """`_default_alert` beeps three times, and `winsound.Beep` blocks the
    calling thread. Anything reachable from the 5 Hz loop must therefore
    use `say`, not `alert`.

    Live 2026-08-08: a routine 30 s "still watching" line went through
    the alarm and the loop stopped dead immediately after the first one.
    Worse, the fire path alerted BEFORE its first keypress - three
    quarters of a second of siren added to the one path measured in
    health.

    Source-level because that is where the rule lives; the alternative is
    trusting that nobody reaches for `_alert` in a loop again.
    """
    import inspect

    from pd2bot.safety import watchdog as module

    # The rule is not "never alert in the loop" — it is "never alert on a
    # path that CONTINUES". `tick`'s death alarm is exempt and should be:
    # the loop stops immediately after it, and the watchdog sends nothing
    # from then on, so blocking there costs nothing at all.
    for name in ("run", "_blind", "_beat", "_take_the_window"):
        src = inspect.getsource(getattr(module.Watchdog, name))
        assert "self._alert(" not in src, (
            f"{name} beeps on a path that keeps looping"
        )

    # `_fire` may alarm once the game is paused — by then the character is
    # safe and the operator should hear it. Never before the keypress.
    fire = inspect.getsource(module.Watchdog._fire)
    before_press = fire.split("for attempt in range(MAX_PRESSES)")[0]
    assert "self._alert(" not in before_press, (
        "the fire path alerts (and beeps) before pressing ESC"
    )
    assert "self._alert(" in fire, "a completed fire must still be audible"
