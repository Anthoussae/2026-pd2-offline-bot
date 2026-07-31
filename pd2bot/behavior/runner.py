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
from pd2bot.memory import GameSession
from pd2bot.safety import ChickenExit
from pd2bot.town import StashFull, TownError


class IdleLoopHalt(CycleError):
    """Idle-bailed too many times: an idle loop is a bug. Loop-halting."""


class PreambleFailed(ChickenExit):
    """The town preamble failed; leave and try a fresh game.

    A `ChickenExit` subclass for the same reason `IdleBail` is one: the
    cycle's existing handler already does the right immediate thing (leave
    the game, keep cycling) and this module owns the counting. It is not a
    vitals problem, so the runner books it separately.
    """


class PreambleHalt(CycleError):
    """The preamble failed twice running. Structural, not luck. Halting."""


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
        preamble_fail_max: int = 2,  # consecutive; twice is not bad luck
        alert: Callable[[str], None] = _default_alert,
        stash_alert: Callable[[str], None] = _default_stash_alert,
    ) -> None:
        self._engine_factory = engine_factory
        self._idle_bail_max = idle_bail_max
        self._preamble_fail_max = preamble_fail_max
        self._alert = alert
        self._stash_alert = stash_alert
        self.idle_bails = 0  # consecutive, not lifetime
        self.preamble_failures = 0  # consecutive, not lifetime

    def __call__(self, session: GameSession) -> None:
        """The callback `cycle.run_games` invokes once per created game."""
        engine = self._engine_factory(session)
        try:
            engine.run()
        except StashFull as exc:
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
            self.preamble_failures += 1
            if self.preamble_failures >= self._preamble_fail_max:
                reason = (
                    f"the town preamble failed {self.preamble_failures} "
                    f"games in a row — this is not bad luck (last: {exc})"
                )
                self._alert(reason)
                raise PreambleHalt(reason) from exc
            raise PreambleFailed(str(exc)) from exc
        except IdleBail as exc:
            self.idle_bails += 1
            if self.idle_bails >= self._idle_bail_max:
                reason = (
                    f"idle-bailed {self.idle_bails} runs in a row — an idle "
                    f"loop is a bug, not a vitals problem (last: {exc})"
                )
                self._alert(reason)
                raise IdleLoopHalt(reason) from exc
            raise  # the cycle's ChickenExit path leaves the game, routinely
        else:
            self.idle_bails = 0
            self.preamble_failures = 0
