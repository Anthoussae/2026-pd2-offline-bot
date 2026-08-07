"""T78 — acquisition, with no pickit on the path: proving the seam is real.

P1 of the item-acquisition plan
(`docs/plans/2026-08-06-item-acquisition/01-separate-acquisition.md`).

The operator asked to separate detection ("which items do we want") from
acquisition ("get this known item off the floor") so the two stop
bleeding into each other. The proof that the seam is real is a drill
that acquires **junk** — items the pickit would never keep: if
acquisition can lift a unit it knows only by id and position, with no
pickit consulted, then acquisition genuinely does not depend on
detection.

It also measures what P2 will improve and what P4 will replace — the
per-item acquisition **latency** and outcome — through the same
`Actuator` seam the real run uses (`services.actuator`), so the number
here and the number in a live run are the same number.

**This test SENDS INPUT**: it drives the configured actuator at whatever
the operator dropped. With the default `ClickActuator` that is a
paced schedule of clicks per item; misses are move orders, so the
character wanders a little (each attempt re-projects).

## How it ends

On its own once every dropped item is resolved (picked or written off),
or when you type `done`. Abort: 'abort' in chat, tools\\drill-cancel.ps1,
ESC, or take the mouse.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t78_acquire
"""

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.acquire import ClickActuator  # noqa: E402
from pd2bot.behavior.engine import EngineContext  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput, InputRefused  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.units import (  # noqa: E402
    _read_ground_item,
    iter_units_of_type,
    player_unit,
    unit_position,
)

GO_WORDS = frozenset({"go", "go!"})
DONE_WORDS = frozenset({"done", "stop", "finish", "finished"})
NEAR_SUBTILES = 40
CLICK_PACE_S = 1.2
CONFIRM_WINDOW_S = 0.9   # how long to watch for the item leaving the ground
REACH_SUBTILES = 4       # RunServices.pickup_reach — click range for a pickup
CLICK_BUDGET = 8         # RunServices.pickup_click_attempts


# -- pure logic (unit-tested; no game) -------------------------------------------


def summarise(results: list[dict]) -> list[str]:
    """The report: acquisition's own scorecard, pickit nowhere in it."""
    picked = [r for r in results if r["picked"]]
    lines = [
        f"ACQUIRE  {len(picked)}/{len(results)} lifted "
        f"(pickit not consulted — this is the acquisition seam alone)"
    ]
    for r in results:
        verdict = (
            f"picked in {r['attempts']} attempt(s), {r['latency_s']:.2f}s"
            if r["picked"]
            else f"NOT lifted after {r['attempts']} attempt(s)"
        )
        lines.append(
            f"  unit {r['unit_id']:>7} kind {r['kind']:>4} at {r['position']}"
            f" -> {verdict}"
        )
    if picked:
        mean = sum(r["latency_s"] for r in picked) / len(picked)
        lines.append(f"  mean lift latency (successes): {mean:.2f}s")
    return lines


class _Ctx(EngineContext):
    """A minimal EngineContext carrying a live executor for the actuator."""


# -- live plumbing ---------------------------------------------------------------


def _origin(run: DrillRun) -> tuple[int, int]:
    unit = player_unit(run.session)
    position = (
        unit_position(run.session, unit, offsets.UNIT_TYPE_PLAYER)
        if unit is not None
        else None
    )
    if position is None:
        raise RuntimeError("player position unreadable — not in a game?")
    return position


def _floor(run: DrillRun) -> dict[int, object]:
    origin = _origin(run)
    found: dict[int, object] = {}
    for unit in iter_units_of_type(run.session, offsets.UNIT_TYPE_ITEM):
        gi = _read_ground_item(run.session, unit)
        if gi is None:
            continue
        if (
            abs(gi.position[0] - origin[0]) <= NEAR_SUBTILES
            and abs(gi.position[1] - origin[1]) <= NEAR_SUBTILES
        ):
            found[gi.unit_id] = gi
    return found


def _await_go(run: DrillRun, timeout_s: float = 600.0) -> bool:
    deadline = run.clock() + timeout_s
    while run.clock() < deadline:
        run.check_cancel()
        if run.heard(GO_WORDS):
            return True
        if run.heard(DONE_WORDS):
            return False
        run.sleep(0.2)
    return False


def _acquire_one(
    run: DrillRun, gated: GatedInput, actuator, ctx, gid: int, item
) -> dict:
    """Drive the actuator at one item to a resolution. Detection-free:
    we know only the gid and position, never whether the pickit wants it.

    No walking — the operator drops within reach (the instructions say
    so), and `GatedInput` has no walk primitive; reach-and-route is
    `collect`'s job in the real run, deliberately not reproduced here so
    the drill measures the actuation mechanism alone.
    """
    started = time.monotonic()
    position = item.position

    def _resolved(attempts_used: int) -> dict:
        return {
            "unit_id": gid, "kind": item.kind, "position": position,
            "picked": True, "attempts": attempts_used,
            "latency_s": time.monotonic() - started,
        }

    origin = _origin(run)
    if max(abs(position[0] - origin[0]), abs(position[1] - origin[1])) > REACH_SUBTILES:
        print(f"    unit {gid} is out of reach ({position} vs {origin}) — "
              "drop nearer; not attempted", flush=True)
        return {
            "unit_id": gid, "kind": item.kind, "position": position,
            "picked": False, "attempts": 0, "latency_s": 0.0,
        }

    for attempt in range(CLICK_BUDGET):
        run.check_cancel()
        if gid not in _floor(run):
            return _resolved(attempt)
        try:
            actuator.actuate(ctx, item, attempt)
        except InputRefused as exc:
            print(f"    attempt {attempt}: REFUSED — {exc}", flush=True)
            run.sleep(CLICK_PACE_S)
            continue
        # Tight confirm poll — the thing P2 will make the default.
        deadline = time.monotonic() + CONFIRM_WINDOW_S
        while time.monotonic() < deadline:
            if gid not in _floor(run):
                return _resolved(attempt + 1)
            run.sleep(0.05)
        print(f"    attempt {attempt}: no pickup", flush=True)
    return {
        "unit_id": gid, "kind": item.kind, "position": position,
        "picked": False, "attempts": CLICK_BUDGET,
        "latency_s": time.monotonic() - started,
    }


def make_drill() -> tuple[Drill, object]:
    drill = Drill(
        test_id="T78",
        title="acquisition seam — lift junk with no pickit on the path",
        kind="hybrid",
        sends_input=True,
        instructions=(
            "Stand somewhere safe (town is fine) and drop a handful of",
            "items — ANYTHING, junk included; the pickit is NOT consulted.",
            "Then type GO and hands off. I drive the configured actuator",
            "at each item by id and position alone and report which lifted",
            "and how long each took. Type 'done' to finish early.",
            "ENDS ON ITS OWN. Abort: 'abort', drill-cancel, ESC, mouse.",
        ),
    )

    def body(run: DrillRun) -> str:
        gated = GatedInput(run.session)
        actuator = ClickActuator()   # the run's default mechanism
        ctx = _Ctx(executor=_LiveExecutor(gated))

        before = set(_floor(run))
        run.say("Drop the items now, then type GO.")
        if not _await_go(run):
            raise RuntimeError("no GO — nothing measured")

        fresh = {uid: gi for uid, gi in _floor(run).items() if uid not in before}
        print(f"\n--- {len(fresh)} item(s) to acquire ---", flush=True)
        if not fresh:
            raise RuntimeError(
                f"GO heard but no new items (player {_origin(run)}, "
                f"radius {NEAR_SUBTILES})"
            )

        results = []
        for gid, gi in list(fresh.items()):
            print(f"  acquiring unit {gid} kind {gi.kind} at {gi.position}",
                  flush=True)
            results.append(_acquire_one(run, gated, actuator, ctx, gid, gi))

        for line in summarise(results):
            print(line, flush=True)

        picked = sum(1 for r in results if r["picked"])
        return (
            f"{picked}/{len(results)} lifted with no pickit on the path "
            f"(the seam is real); mechanism {type(actuator).__name__}"
        )

    return drill, body


class _LiveExecutor:
    """Wraps GatedInput so the actuator's `ctx.executor.execute(action)`
    reaches the game. Only the action types the ClickActuator emits are
    handled; anything else is a loud error, not a silent no-op."""

    def __init__(self, gated: GatedInput):
        self._gated = gated

    def execute(self, action):
        from pd2bot.behavior.actions import PickUpItem

        if isinstance(action, PickUpItem):
            # Mirror the real executor's aim: project + sprite offset.
            from pd2bot.behavior.execute import _PICKUP_OFFSETS

            dx, dy = _PICKUP_OFFSETS[action.attempt % len(_PICKUP_OFFSETS)]
            base = self._gated.project_world(*action.position)
            self._gated.click_screen(base[0] + dx, base[1] + dy)
            return
        raise RuntimeError(f"T78 executor cannot handle {type(action).__name__}")


if __name__ == "__main__":
    status = run_drill(*make_drill(), run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
