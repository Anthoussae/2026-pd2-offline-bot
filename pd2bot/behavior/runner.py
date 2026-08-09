"""The run_games callback boundary: idle-bail counting and the loud halts.

`cycle.run_games(callback)` is the M4 integration point and its internals
are out of P4's scope, so everything idle-specific happens on THIS side of
the boundary. An `IdleBail` is typed as a `ChickenExit` (see engine.py), so
the untouched cycle already does the right immediate thing — leave the game,
keep cycling. What the cycle must NOT do is book it as a vitals problem,
and that is this module's job: count idle bails separately and halt loudly
when they repeat, because a bot that keeps standing around in Hell has a
bug, and a bug must surface, not hide among chickens.

One known imperfection, accepted and worth knowing (flagged at the P4
report): because IdleBail passes through the cycle's ChickenExit handler, it
also increments the cycle's own consecutive-chicken counter. With both
thresholds at their default 2, consecutive idle bails halt HERE first with
the honest message; a mixed sequence (one real chicken, then one idle bail)
can trip the cycle's vitals backstop instead, whose message then
misattributes — the printed per-game "chicken:" line naming the idle bail
is the disambiguator. Fixing that fully needs a one-line cycle.py change,
which is a P5-gate decision, not a P4 liberty.

The other loud halt here is `StashFull`, and it is the opposite kind of
event: not a bug to find but a wall to stop at. See `StashFullHalt`.
"""

from __future__ import annotations

from collections.abc import Callable

from pd2bot.behavior.engine import BehaviorEngine, IdleBail
from pd2bot.cycle import CycleError
from pd2bot.perception.memory import GameSession
from pd2bot.safety import ChickenExit, DeathHalt
from pd2bot.town import StashFull, TownError


class IdleLoopHalt(CycleError):
    """Idle-bailed too many times: an idle loop is a bug. Loop-halting."""


class TownStepFailed(ChickenExit):
    """A town-layer step failed; leave and try a fresh game.

    Named for the LAYER, not the preamble, because stage B's second attempt
    proved the difference matters: the failure was the waypoint step, and a
    class called `PreambleFailed` reported it as a preamble problem. The
    handling was right and the label was not.

    A `ChickenExit` subclass for the same reason `IdleBail` is one: the
    cycle's existing handler already does the right immediate thing (leave
    the game, keep cycling) and this module owns the counting. It is not a
    vitals problem, so the runner books it separately — and says so to the
    cycle as well, via `is_vitals` (R115), so its vitals backstop cannot
    halt over a preamble failure and blame the character's health.
    """

    is_vitals = False


class TownStepHalt(CycleError):
    """A town step failed twice running. Structural, not luck. Halting."""


class RunFailed(ChickenExit):
    """The run raised something nobody anticipated. Leave, try again.

    The catch-all, and it exists because the named cases kept not being
    enough — four different exception types escaped `run_games` and ended
    a session before this was written. Unattended running cannot depend
    on someone remembering to extend a list of survivable errors.

    Not a vitals problem either (R115): whatever went wrong, the one
    thing we know is that it was not the character's health.
    """

    is_vitals = False


class RunHalt(CycleError):
    """The same unexpected failure twice running. Halting."""


class StashFullHalt(CycleError):
    """The stash would not take the inventory. Loop-halting, on purpose.

    This is the one failure the bot genuinely cannot work around. It can
    drop junk (the cleanse) and it can stop picking more up, but it cannot
    make room in a full stash — that needs a human deciding what to keep.
    Cycling into another game would just hit the same wall one preamble
    later, with a fuller inventory each time.

    Halting rather than leaving the game is deliberate. `StashFull` is
    raised from the town preamble, so the character is standing in town,
    which is the safest place in the game and exactly where the human wants
    to arrive: panels open, stash there, nothing hunting them. Same shape as
    the death halt's "leave the game as it is for the human" (R27/Q6),
    minus the permanence — there is nothing to latch, the next session
    starts clean once the stash has room.
    """


def _shout(banner: str, reason: str, advice: str) -> None:  # pragma: no cover
    print("\n" + "!" * 66)
    print(f"!!  {banner}: {reason}")
    print(f"!!  {advice}")
    print("!" * 66 + "\n", flush=True)
    try:
        import winsound

        for _ in range(3):
            winsound.Beep(523, 300)
            winsound.Beep(392, 300)
    except Exception:
        pass


def _default_alert(reason: str) -> None:  # pragma: no cover - exercised live
    _shout("IDLE LOOP", reason, "This is a bug to find, not a threshold to tune.")


def _default_stash_alert(reason: str) -> None:  # pragma: no cover - live only
    _shout(
        "STASH FULL",
        reason,
        "The bot cannot make room. Clear stash space, then start it again.",
    )


class BehaviorRunner:
    """Wraps the engine as the `run_games` callback, counting idle bails.

    A fresh engine is built per game (states are stateful and single-use);
    the runner itself persists across games, which is exactly what lets it
    count. The count resets on a run that completes — the idle threshold is
    about an idle LOOP, and a loop that broke is not a loop.
    """

    def __init__(
        self,
        engine_factory: Callable[[GameSession], BehaviorEngine],
        *,
        idle_bail_max: int = 2,  # consecutive; an idle loop is a bug (R47.9)
        town_fail_max: int = 2,  # consecutive; twice is not bad luck
        run_fail_max: int = 2,  # consecutive unexpected errors
        alert: Callable[[str], None] = _default_alert,
        stash_alert: Callable[[str], None] = _default_stash_alert,
        announce: Callable[[str], None] | None = None,
    ) -> None:
        self._engine_factory = engine_factory
        # Say the result IN THE GAME before the cycle leaves it (R164).
        #
        # The operator is watching the game, not the console — the same
        # reasoning that made drills announce themselves in chat (R95) —
        # and a run that simply stops leaves them guessing whether it is
        # thinking, stuck, or finished. This is the only moment it can be
        # said: the cycle leaves the game the instant this callback
        # returns, and chat needs a game to be typed into.
        self._announce = announce
        self._idle_bail_max = idle_bail_max
        self._town_fail_max = town_fail_max
        self._run_fail_max = run_fail_max
        self._alert = alert
        self._stash_alert = stash_alert
        self.idle_bails = 0  # consecutive, not lifetime
        self.town_failures = 0  # consecutive, not lifetime
        self.run_failures = 0  # consecutive, not lifetime

    def _say(self, outcome: str, detail: str = "") -> None:
        """Announce the run's result in chat. Never fatal — a message that
        cannot be delivered must not cost the run it is reporting on."""
        if self._announce is None:
            return
        try:
            self._announce(
                f"RUN OVER — {outcome}" + (f": {detail[:120]}" if detail else "")
                + " — back to the terminal"
            )
        except Exception:  # noqa: BLE001 - reporting must not raise
            pass

    def __call__(self, session: GameSession) -> None:
        """The callback `cycle.run_games` invokes once per created game."""
        engine = self._engine_factory(session)
        outcome, detail, announce = "COMPLETE", "", True
        try:
            engine.run()
            report = getattr(engine, "report", None)
            detail = report.summary() if report is not None else ""
        except StashFull as exc:
            outcome, detail = "STASH FULL", str(exc)
            # Not a crash and not a cycle-and-retry: a wall. Convert the
            # town layer's exception into the loop-halting kind BEFORE it
            # reaches `run_games`, which would otherwise let a plain
            # TownError propagate as an unhandled traceback.
            reason = f"the regular stash would not take the inventory ({exc})"
            self._stash_alert(reason)
            raise StashFullHalt(reason) from exc
        except TownError as exc:
            # Everything else the town layer raises. Found the hard way on
            # the first stage-B attempt: an `ensure_materials_tab` refusal
            # propagated out of `run_games` and killed the process with a
            # traceback, leaving the character in a Hell game with the
            # stash panel open. That is the same escape shape as review
            # 002's InputRefused and StashFull — fixing the two named cases
            # and leaving the parent class to escape was half a fix.
            #
            # Counted rather than halted-on-sight because the two kinds
            # look identical from here: P3 saw plenty of transient preamble
            # failures (a mis-click, an NPC dialog that opened late) which a
            # fresh game fixes by itself, and a structural one repeats. So
            # leave, retry once, and halt loudly when it happens again.
            outcome, detail = "TOWN STEP FAILED", str(exc)
            self.town_failures += 1
            if self.town_failures >= self._town_fail_max:
                reason = (
                    f"a town step failed {self.town_failures} games in a "
                    f"row — this is not bad luck (last: {exc})"
                )
                self._alert(reason)
                raise TownStepHalt(reason) from exc
            raise TownStepFailed(str(exc)) from exc
        except DeathHalt:
            # Permanent, and it MUST reach the cycle untouched. No
            # announcement either: after a detected death the bot sends no
            # input of any kind, ever, and chat is input. The one place
            # where saying nothing is the whole point.
            announce = False
            raise
        except CycleError:
            outcome = "HALTED"
            raise
        except IdleBail as exc:
            outcome, detail = "IDLE BAIL", str(exc).splitlines()[0]
            self.idle_bails += 1
            if self.idle_bails >= self._idle_bail_max:
                reason = (
                    f"idle-bailed {self.idle_bails} runs in a row — an idle "
                    f"loop is a bug, not a vitals problem (last: {exc})"
                )
                self._alert(reason)
                raise IdleLoopHalt(reason) from exc
            raise  # the cycle's ChickenExit path leaves the game, routinely
        except ChickenExit as exc:
            outcome, detail = "CHICKEN", str(exc)
            raise  # a real vitals chicken: the cycle books it, not us
        except Exception as exc:
            # ANYTHING else the run raised. This clause exists because the
            # named ones kept not being enough: InputRefused escaped and
            # ended a session (review 002), then StashFull did, then the
            # parent TownError did, and then `SkillSwitchFailed` did — four
            # times, one class at a time, each fix leaving the next one able
            # to walk out. A bot meant to run unattended cannot have a list
            # of survivable errors that someone must remember to extend.
            #
            # So the default flips: everything is survivable except what is
            # explicitly not (the two above). An unexpected error costs the
            # game, not the session — and if it repeats it is structural, so
            # the second one halts loudly rather than cycling forever.
            outcome, detail = "FAILED", f"{type(exc).__name__}: {exc}"
            self.run_failures += 1
            if self.run_failures >= self._run_fail_max:
                reason = (
                    f"the run failed {self.run_failures} games in a row with "
                    f"{type(exc).__name__}: {exc}"
                )
                self._alert(reason)
                raise RunHalt(reason) from exc
            raise RunFailed(f"{type(exc).__name__}: {exc}") from exc
        else:
            self.idle_bails = 0
            self.town_failures = 0
            self.run_failures = 0
        finally:
            # In the `finally` so it happens on every path, and BEFORE the
            # exception finishes propagating — the cycle leaves the game
            # the moment this callback returns, and chat needs a game.
            if announce:
                self._say(outcome, detail)
