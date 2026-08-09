"""T80 — the in-process safety interrupt, against the real client.

**What this exists to prove.** On 2026-08-07 the bot blocked inside a
single `walk_to` for 24 seconds while a pack killed the character: the
safety monitor only ran between ticks, so it never looked, and the
chicken never fired. The fix makes a walk poll safety from inside every
loop it waits in, and return on a wall clock regardless. Offline tests
pin both. This drill is the same two claims against the actual game,
with the actual navigator, the actual monitor and the actual click path.

**Why it is zero risk.** It runs in TOWN and it fires on MANA, which is
the live-test path `pd2bot/safety.py` was built with — "the code path is
identical to life chicken, which is the point: testing one tests both".
Nothing here can hurt the character: the interrupt is caught by the
drill, so the game is never even left. The only input sent is ordinary
travel clicks, in town, exactly as the town preamble already sends.

Two rounds:

1. **The cap.** One `walk_to` to a far town point, with nothing
   watching. It must hand control back inside the budget instead of
   walking the whole way — that is what the reflex ladder and the abort
   channel need, and it is what did not exist when the character died.
2. **The interrupt.** The same walk, with a real `SafetyMonitor` armed
   partway through. It must raise from INSIDE the walk, promptly. The
   arming moment stands in for the HP crossing — the quantity being
   measured is the same one: condition true → bot notices.

## How it ends

On its own, seconds after you type GO. Abort: 'abort' in chat,
tools\\drill-cancel.ps1, ESC, or take the mouse.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t80_safety_interrupt
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.navigate import (  # noqa: E402
    WALK_BUDGET_SECONDS,
    Navigator,
    live_navigator,
    pick_reachable_target,
)
from pd2bot.safety import (  # noqa: E402
    SafetyConfig,
    SafetyInterrupt,
    SafetyMonitor,
)
from pd2bot.units import player_unit, unit_position  # noqa: E402

GO_WORDS = frozenset({"go", "go!"})
GO_TIMEOUT_S = 180.0
# How long into the walk the monitor is armed. Long enough that the walk
# is provably in flight (the character has moved), short enough that the
# round is over in seconds.
ARM_AFTER_S = 1.0
# What counts as prompt. The offline measurement is 0.100 s worst case;
# this is generous against real memory reads and a real click path, and
# it is still two orders of magnitude under the 24 s that killed the
# character. A round that only just passes is worth reading, so the
# actual number is always printed.
PROMPT_S = 1.0
# The cap plus room for one poll and one memory read.
CAP_SLACK_S = 1.5


def _position(run: DrillRun):
    unit = player_unit(run.session)
    position = (
        unit_position(run.session, unit, offsets.UNIT_TYPE_PLAYER)
        if unit is not None
        else None
    )
    if position is None:
        raise RuntimeError("player position unreadable — not in a game?")
    return position


def _await_go(run: DrillRun, timeout_s: float = GO_TIMEOUT_S) -> bool:
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            return True
        run.sleep(0.2)
    return False


def _far_target(navigator: Navigator, start):
    """Somewhere genuinely walkable, far enough that the walk takes time."""
    target, radius = pick_reachable_target(navigator.grid(), start, distance=60)
    if target is None:
        raise RuntimeError(
            f"no reachable target within 60 subtiles of {start} — stand "
            "somewhere with open ground around you and re-run"
        )
    return target, radius


def verdict(cap_seconds: float, latency: float | None, moved: int) -> tuple[str, str]:
    """PASS/FAIL and why. Pure, so the criteria are testable offline.

    Both rounds must pass. The interrupt round additionally requires that
    the character actually MOVED before the monitor was armed — without
    that, a walk that never started would pass by raising instantly, and
    this drill would be testing nothing at all. That is the failure shape
    this project keeps paying for, so it is a criterion rather than a
    comment.
    """
    problems = []
    if cap_seconds > WALK_BUDGET_SECONDS + CAP_SLACK_S:
        problems.append(
            f"the walk held the caller for {cap_seconds:.2f}s against a "
            f"{WALK_BUDGET_SECONDS:.1f}s budget"
        )
    if latency is None:
        problems.append("no SafetyInterrupt was raised from inside the walk")
    elif latency > PROMPT_S:
        problems.append(f"the interrupt took {latency:.2f}s to arrive")
    if moved < 1:
        problems.append(
            f"the character moved {moved} subtiles before the monitor was "
            "armed — the walk was not in flight, so nothing was proven"
        )
    if problems:
        return "FAIL", "; ".join(problems)
    return "PASS", (
        f"cap returned in {cap_seconds:.2f}s (budget {WALK_BUDGET_SECONDS:.1f}s); "
        f"interrupt arrived {latency:.2f}s after arming, from inside a walk "
        f"that had already moved {moved} subtiles"
    )


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T80",
        title="the in-process safety interrupt — a blocking walk cannot starve the chicken",
        kind="safety",
        sends_input=True,
        instructions=(
            "ZERO RISK, and worth reading why: this runs in TOWN and fires",
            "on MANA, which is the live-test path safety.py was built with",
            "— the same code path as the life chicken. The interrupt is",
            "caught by the drill, so the game is not even left. The only",
            "input is ordinary travel clicks.",
            "Stand in town with open ground around you (the Rogue camp",
            "courtyard is ideal) and type GO.",
            "Your character will walk a short way twice, and stop.",
            "Abort: 'abort' in chat, drill-cancel, ESC, or take the mouse.",
        ),
    )

    def body(run: DrillRun) -> str:
        store = MapStore()
        run.say("Stand in town with room to walk, then type GO.")
        if not _await_go(run):
            raise RuntimeError("no GO — nothing was measured")

        # -- round 1: the cap, with nothing watching -----------------------
        plain = live_navigator(run.session, store)
        start = _position(run)
        target, radius = _far_target(plain, start)
        print(f"round 1 — the cap: {start} -> {target} ({radius} subtiles)", flush=True)

        began = run.clock()
        result = plain.walk_to(target)
        cap_seconds = run.clock() - began
        print(
            f"  walk_to returned after {cap_seconds:.2f}s, capped={result.capped}, "
            f"at {result.arrived_at} ({result.clicks} click(s))",
            flush=True,
        )
        run.check_cancel()

        # -- round 2: the interrupt, with a real monitor -------------------
        # Armed PART WAY IN, so the walk is provably in flight when the
        # condition becomes true. A 99% mana threshold is true the moment
        # it is consulted, which is what makes the arming moment — not the
        # vitals — the thing being timed.
        monitor = SafetyMonitor(
            run.session,
            SafetyConfig(
                life_chicken_pct=0.0,  # life is NOT armed: nothing can chicken on HP
                mana_chicken_pct=99.0,
                chicken_in_town=True,
            ),
        )
        armed_at: list[float] = []
        moved_by_arming: list[int] = [0]
        walk_start = _position(run)
        # Set immediately before the walk. A holder rather than a plain
        # local because `poll` closes over it and must never read it
        # unset — the walk is the only thing that calls poll, so the
        # ordering is safe, but a holder says so instead of relying on it.
        began2 = [0.0]

        def poll() -> None:
            if run.clock() - began2[0] < ARM_AFTER_S:
                return
            if not armed_at:
                armed_at.append(run.clock())
                here = _position(run)
                moved_by_arming[0] = max(
                    abs(here[0] - walk_start[0]), abs(here[1] - walk_start[1])
                )
                print(
                    f"  armed at +{armed_at[0] - began2[0]:.2f}s, character has "
                    f"moved {moved_by_arming[0]} subtile(s)",
                    flush=True,
                )
            monitor.poll()

        guarded = live_navigator(run.session, store, safety_poll=poll)
        back = _position(run)
        target2, radius2 = _far_target(guarded, back)
        print(
            f"round 2 — the interrupt: {back} -> {target2} ({radius2} subtiles), "
            f"monitor armed {ARM_AFTER_S:.1f}s in",
            flush=True,
        )

        began2[0] = run.clock()
        latency = None
        try:
            guarded.walk_to(target2)
            print("  the walk RETURNED — no interrupt was raised", flush=True)
        except SafetyInterrupt as interrupt:
            latency = run.clock() - armed_at[0] if armed_at else 0.0
            print(
                f"  SafetyInterrupt after {run.clock() - began2[0]:.2f}s of "
                f"walking — {latency:.2f}s after arming: {interrupt}",
                flush=True,
            )

        status, why = verdict(cap_seconds, latency, moved_by_arming[0])
        if status == "FAIL":
            raise RuntimeError(why)
        return why

    return drill, body


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
