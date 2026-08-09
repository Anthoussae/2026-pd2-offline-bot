"""The safety monitor: chicken out while alive, stop dead when not.

Two reflexes, both user decisions (R27), both evaluated every tick, death
always first:

**The death latch.** If the player's unit mode reads Death/Dead or hp reads
zero, the monitor latches permanently: it fires a loud local alert and from
that moment refuses to evaluate anything ever again — and the cycle, on
seeing DeathHalt, sends no input of any kind, not even leave-game. The game
is left exactly as the human needs to see it. There is deliberately no
recovery path: corpse retrieval and death recovery are deferred work, and a
bot that guesses after its character died has already guessed wrong once.

**Chicken.** Kolbot's percentage thresholds (mined from ToolsThread.js):
life at/below the threshold outside town -> leave the game immediately.
Offline SP makes this stronger than it sounds: ESC *pauses* the game
instantly, so the exit is effectively complete the moment the keypress
lands — the subsequent menu clicks happen in a paused world. Mana chicken
exists mostly as the zero-risk live test path (cast something in town with
`chicken_in_town` on and a 99% threshold), but the code path is identical
to life chicken, which is the point: testing one tests both.

The monitor observes and *signals*; the cycle owns all input. ChickenExit
is routine (the cycle leaves and continues); DeathHalt is terminal.

**Two raisers, one evaluation.** `tick()` is the per-tick check the
engine has always made. `poll()` is the same judgement offered to code
that is *currently blocking* — a walk, mainly — and it raises
`SafetyInterrupt` instead, for reasons that class documents. They share
`_evaluate` because two copies of the thresholds would drift, and the
copy that mattered would be whichever one was wrong.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from pd2bot import offsets
from pd2bot.perception.memory import GameSession
from pd2bot.perception.player import Player, read_player
from pd2bot.perception.world import Area, read_area
from pd2bot.runlog import NullRunLog


class DeathHalt(RuntimeError):
    """The character is dead. Permanent: no input may follow, ever."""


class ChickenExit(RuntimeError):
    """Leave the game now, routinely and without drama.

    Named for the vitals case because that is what it was built for, and
    it became the type for everything that wants the cycle's leave-and-
    keep-going handling: an idle loop, a failed town step, an unexpected
    run error. That reuse is deliberate and worth keeping — the cycle's
    handler is live-verified and none of those want their own copy of it.

    `is_vitals` is what the reuse cost, paid back (R115). PD2 carries HP
    and mana between games, so a character below the threshold chickens
    out of every game forever; `cycle.run_games` counts consecutive
    chickens and halts to break that loop, telling the operator to heal.
    Three of the four subclasses are not vitals problems at all, and
    every one of them was feeding that counter — so a hang or a failed
    preamble could trip a backstop whose message says "heal the
    character". Subclasses that are not about vitals set this False and
    the cycle leaves them to their own counters, which are the ones that
    can describe them honestly.
    """

    is_vitals = True


@dataclass(frozen=True)
class Verdict:
    """What the vitals say, separated from how it gets raised.

    `tick()` and `poll()` must never be able to disagree about whether
    the character is in trouble — two copies of the thresholds would
    drift, and only one of them would be the copy that mattered on the
    day it counted. So there is one evaluation and two raisers over it.
    """

    kind: str  # "death" | "life" | "mana"
    message: str
    hp: int = 0
    max_hp: int = 0
    mana: int = 0
    max_mana: int = 0
    pct: float = 0.0

    @property
    def is_death(self) -> bool:
        return self.kind == "death"


class SafetyInterrupt(BaseException):
    """A safety condition detected DURING a blocking call.

    Derives from `BaseException`, and that *is* the class — it exists for
    no other reason. The path out of a blocking walk runs through several
    broad `except Exception` handlers: the navigator's own unstick guard
    and click audit, the town layer's recovery and its station wrapper.
    Every one of them is correct about its own concern, and every one of
    them would swallow a chicken. A safety signal any handler can absorb
    is not a safety signal.

    This is deliberately NOT the type the rest of the bot handles. The
    engine converts it back into the real `ChickenExit`/`DeathHalt` at
    the tick boundary — the same place the monitor already raises them —
    so the cycle's live-verified handling never has to know this exists.

    Paid for on 2026-08-07: a `walk_to` blocked for 24 s while a pack
    killed the character, and the monitor, which only ran between ticks,
    never got to look.
    """

    def __init__(self, verdict: Verdict) -> None:
        super().__init__(verdict.message)
        self.verdict = verdict


@dataclass(frozen=True)
class SafetyConfig:
    life_chicken_pct: float = 50.0  # 0 disables
    mana_chicken_pct: float = 0.0  # off by default; the live-test path
    chicken_in_town: bool = False  # True only for the zero-risk live test
    # How often `poll()` is allowed to actually read memory. Callers poll
    # it from loops that already run at 10 Hz (the walk loop), and vitals
    # do not move fast enough to justify reading twice as often as the
    # game updates them. The cost of this number is chicken latency:
    # worst case, a threshold crossing waits this long to be noticed.
    poll_interval_s: float = 0.2


def _default_alert() -> None:  # pragma: no cover - exercised live, not in tests
    """Loud and local: the operator is at this machine by definition."""
    print("\n" + "!" * 66)
    print("!!  THE CHARACTER IS DEAD — bot halted, no further input will be sent.")
    print("!!  The game is untouched. A human takes it from here.")
    print("!" * 66 + "\n", flush=True)
    try:
        import winsound

        for _ in range(4):
            winsound.Beep(880, 350)
            winsound.Beep(440, 350)
    except Exception:
        pass  # no sound device is no reason to fail the halt


class SafetyMonitor:
    """Per-tick vitals watchdog. Raises; never sends input itself."""

    def __init__(
        self,
        session: GameSession,
        config: SafetyConfig | None = None,
        *,
        read_player_fn: Callable[[GameSession], Player | None] = read_player,
        read_area_fn: Callable[[GameSession], Area | None] = read_area,
        alert: Callable[[], None] = _default_alert,
        runlog: object | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        self.config = config if config is not None else SafetyConfig()
        self._read_player = read_player_fn
        self._read_area = read_area_fn
        self._alert = alert
        self._clock = clock
        # When `poll()` last actually read memory. See `poll`.
        self._last_poll: float | None = None
        # The run event log. Chicken and death are the two moments an
        # operator most wants a precise record of, and until now the
        # reason was a printed string that survived only if a drill
        # happened to capture stdout. Defaults to the null sink; the
        # SESSION owns the monitor, so the wiring repoints this per run.
        self.runlog = runlog if runlog is not None else NullRunLog()
        self.halted = False

    def _record(self, kind: str, **fields) -> None:
        """Write one safety event. Never raises: the monitor is the last
        line of defence and must not be endangered by its own logging,
        least of all on the tick it is halting the bot."""
        try:
            area = self._read_area(self.session)
            if area is not None:
                fields.setdefault("area", area.level_no)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.runlog.event(kind, **fields)
        except Exception:  # noqa: BLE001
            return

    def _evaluate(self, where: str) -> Verdict | None:
        """Read the vitals and judge them. The single source of truth.

        Owns the side effects that must happen exactly once per verdict —
        setting the latch, the alert, the log record — so that whichever
        raiser is called, they happen the same way. `where` distinguishes
        a tick-boundary check from one made inside a blocking call, which
        is the difference the run log has to be able to show.
        """
        if self.halted:
            # The latch: once dead, always dead, no matter what memory says
            # now — a re-created game must not resurrect the bot's confidence.
            return Verdict("death", "halted earlier; a human must restart the bot")

        player = self._read_player(self.session)
        if player is None:
            return None  # menus or loading: nothing to guard yet

        if (
            player.mode in (offsets.PLAYER_MODE_DEATH, offsets.PLAYER_MODE_DEAD)
            or player.hp <= 0
        ):
            self.halted = True
            self._alert()
            self._record(
                "death", reason="player mode/hp reads dead", where=where,
                mode=player.mode, hp=player.hp, max_hp=player.max_hp,
            )
            return Verdict(
                "death",
                f"{player.name} is dead (mode {player.mode}, hp {player.hp}) — "
                "halting permanently; the game is untouched",
                hp=player.hp, max_hp=player.max_hp,
            )

        if not self.config.chicken_in_town:
            area = self._read_area(self.session)
            if area is not None and area.level_no in offsets.TOWN_AREAS:
                return None

        if self.config.life_chicken_pct > 0 and player.max_hp > 0:
            pct = 100.0 * player.hp / player.max_hp
            if pct <= self.config.life_chicken_pct:
                self._record(
                    "chicken", reason="life", where=where, hp=player.hp,
                    max_hp=player.max_hp, pct=round(pct, 1),
                    threshold=self.config.life_chicken_pct,
                    mana=player.mana, max_mana=player.max_mana,
                )
                return Verdict(
                    "life",
                    f"life {player.hp}/{player.max_hp} ({pct:.0f}%) <= "
                    f"{self.config.life_chicken_pct:.0f}% threshold",
                    hp=player.hp, max_hp=player.max_hp,
                    mana=player.mana, max_mana=player.max_mana,
                    pct=round(pct, 1),
                )

        if self.config.mana_chicken_pct > 0 and player.max_mana > 0:
            pct = 100.0 * player.mana / player.max_mana
            if pct <= self.config.mana_chicken_pct:
                self._record(
                    "chicken", reason="mana", where=where, hp=player.hp,
                    max_hp=player.max_hp, mana=player.mana,
                    max_mana=player.max_mana, pct=round(pct, 1),
                    threshold=self.config.mana_chicken_pct,
                )
                return Verdict(
                    "mana",
                    f"mana {player.mana}/{player.max_mana} ({pct:.0f}%) <= "
                    f"{self.config.mana_chicken_pct:.0f}% threshold",
                    hp=player.hp, max_hp=player.max_hp,
                    mana=player.mana, max_mana=player.max_mana,
                    pct=round(pct, 1),
                )
        return None

    def tick(self) -> None:
        """Check vitals once. Raises DeathHalt (latched) or ChickenExit."""
        verdict = self._evaluate("tick")
        if verdict is None:
            return
        if verdict.is_death:
            raise DeathHalt(verdict.message)
        raise ChickenExit(verdict.message)

    def poll(self) -> None:
        """The same check, for callers that are in the middle of blocking.

        Raises `SafetyInterrupt` rather than the usual pair, because the
        code between here and the tick loop catches `Exception` in
        several places and would otherwise absorb it — see the class.
        The engine converts it back at the boundary.

        Rate-limited internally so it can be dropped straight into a
        10 Hz poll loop without doubling the memory reads. The latch is
        exempt: once dead, refusing to answer is not an option.
        """
        if self.halted:
            raise SafetyInterrupt(
                Verdict("death", "halted earlier; a human must restart the bot")
            )
        now = self._clock()
        if (
            self._last_poll is not None
            and now - self._last_poll < self.config.poll_interval_s
        ):
            return
        self._last_poll = now
        verdict = self._evaluate("poll")
        if verdict is not None:
            raise SafetyInterrupt(verdict)
