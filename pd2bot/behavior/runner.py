"""The run_games callback boundary: idle-bail counting and the loud halt.

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
"""

from __future__ import annotations

from collections.abc import Callable

from pd2bot.behavior.engine import BehaviorEngine, IdleBail
from pd2bot.cycle import CycleError
from pd2bot.memory import GameSession


class IdleLoopHalt(CycleError):
    """Idle-bailed too many times: an idle loop is a bug. Loop-halting."""


def _default_alert(reason: str) -> None:  # pragma: no cover - exercised live
    print("\n" + "!" * 66)
    print(f"!!  IDLE LOOP: {reason}")
    print("!!  This is a bug to find, not a threshold to tune.")
    print("!" * 66 + "\n", flush=True)
    try:
        import winsound

        for _ in range(3):
            winsound.Beep(523, 300)
            winsound.Beep(392, 300)
    except Exception:
        pass


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
        alert: Callable[[str], None] = _default_alert,
    ) -> None:
        self._engine_factory = engine_factory
        self._idle_bail_max = idle_bail_max
        self._alert = alert
        self.idle_bails = 0  # consecutive, not lifetime

    def __call__(self, session: GameSession) -> None:
        """The callback `cycle.run_games` invokes once per created game."""
        engine = self._engine_factory(session)
        try:
            engine.run()
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
