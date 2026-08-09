"""T80 + T81 — both safety layers against the real client, UNATTENDED.

This is the canary for `docs/archive/plans/2026-08-07-safety-starvation/`, run
without a human in the loop: it takes the game window itself, creates
its own game from wherever the client happens to be, runs five rounds,
puts everything back, and leaves the game.

**Why it is safe to run unattended, stated precisely.** Every round
happens in TOWN, and the only chicken condition armed is MANA — the
live-test path `pd2bot/safety.py` was built with, whose whole point is
that "the code path is identical to life chicken, so testing one tests
both". Life chicken is set to 0 in round 2, so nothing can fire on HP.
Nothing walks into a monster, nothing fights, and the character cannot
be hurt by anything here. The one destructive-looking act — the watchdog
pressing ESC — merely PAUSES an offline single-player game, and round 3
un-pauses it.

The rounds, and what each would catch:

1. **the cap** — one `walk_to` must hand control back on its wall clock
   instead of walking the whole way. This is the thing that did not
   exist on 2026-08-07, when one walk held the tick loop for 24 s.
2. **the interrupt** — a real `SafetyMonitor`, armed part way through a
   walk that is provably in flight, must raise from INSIDE it.
3. **the watchdog fires** — a genuinely separate process, with no bot
   running at all, must press ESC and pause the game.
4. **the latch disarms world input** — with the pause cleared and the
   game live again, `GatedInput` must still refuse, and `MenuInput` must
   not (that asymmetry is what lets the bot finish its own clean exit).
5. **the dead-man switch** — with the watchdog stopped and its heartbeat
   stale, a run that requires it must refuse to take a step.

Teardown runs in a `finally` and is not optional: un-pause, kill the
watchdog, clear the latch, leave the game. A canary that leaves a latch
behind would disarm the operator's next launch.

    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.safety_canary
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from drills.t80_safety_interrupt import (  # noqa: E402
    ARM_AFTER_S,
    CAP_SLACK_S,
    PROMPT_S,
)
from pd2bot import offsets, watchdog  # noqa: E402
from pd2bot.behavior.engine import (  # noqa: E402
    BehaviorEngine,
    EngineConfig,
    WatchdogDown,
)
from pd2bot.cycle import GameCycle  # noqa: E402
from pd2bot.input import GatedInput, InputRefused  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import (  # noqa: E402
    WALK_BUDGET_SECONDS,
    live_navigator,
    pick_reachable_target,
)
from pd2bot.perception import uistate, world  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.safety import (  # noqa: E402
    SafetyConfig,
    SafetyInterrupt,
    SafetyMonitor,
)

WATCHDOG_FIRE_TIMEOUT_S = 20.0
UNPAUSE_TIMEOUT_S = 10.0


class Round:
    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = False
        self.detail = ""

    def passed(self, detail: str) -> None:
        self.ok, self.detail = True, detail

    def failed(self, detail: str) -> None:
        self.ok, self.detail = False, detail

    def __str__(self) -> str:
        return f"  [{'PASS' if self.ok else 'FAIL'}] {self.name}: {self.detail}"


def _position(session) -> tuple[int, int]:
    player = read_player(session)
    if player is None:
        raise RuntimeError("player unreadable — not in a game?")
    return player.position


def _esc_menu_open(session, ui_array: int) -> bool:
    return uistate.is_in_game(session) and uistate.read_ui_state(
        session, ui_array
    ).is_open(offsets.UI_ESCMENU_MAIN)


def _stop_watchdog(process: subprocess.Popen) -> None:
    """Kill the watchdog and VERIFY it died — the whole tree, not the pid.

    `Popen.pid` is not the watchdog's pid here. The venv's `python.exe`
    re-execs, so the pid we hold is a launcher shim: measured on this
    machine, `Popen.pid` 5192 against the child's own `os.getpid()`
    18768, and the canary's own run showed a latch written by pid 25084
    from a process spawned as 21200. `terminate()` on the shim therefore
    may leave the real watchdog running — and an orphaned watchdog is one
    that can press ESC into a later, unrelated game.

    So: terminate, then taskkill the tree, then confirm the heartbeat has
    actually gone stale. Verification over assumption, which is the rule
    the watchdog itself follows about its own ESC.
    """
    try:
        process.terminate()
        process.wait(timeout=3)
    except Exception:  # noqa: BLE001
        pass
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True,
        check=False,
    )
    deadline = time.monotonic() + watchdog.HEARTBEAT_STALE_AFTER_S + 3
    while time.monotonic() < deadline:
        if not watchdog.watchdog_is_alive():
            return
        time.sleep(0.3)
    print("    WARNING: the watchdog heartbeat is still fresh after a kill")


def _crashed(name: str, exc: BaseException) -> Round:
    entry = Round(name)
    entry.failed(f"raised {type(exc).__name__}: {exc}")
    return entry


def _guarded(name: str, fn, *args) -> Round:
    """Run one round; a crash becomes a FAIL, never a lost report.

    An unattended canary that dies half way through is worse than one
    that fails: the summary is the whole deliverable, and the first run
    of this script threw away four rounds' results because the fifth
    raised.
    """
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001
        print(f"    round crashed: {type(exc).__name__}: {exc}")
        return _crashed(name, exc)


# -- the rounds ----------------------------------------------------------------


def round_cap(session, store) -> Round:
    result_round = Round("1. the wall-clock cap")
    nav = live_navigator(session, store)
    start = _position(session)
    target, radius = pick_reachable_target(nav.grid(), start, distance=60)
    if target is None:
        result_round.failed(f"no reachable target near {start} — no open ground?")
        return result_round
    print(f"    walking {start} -> {target} ({radius} subtiles), nothing watching")
    began = time.monotonic()
    walk = nav.walk_to(target)
    held = time.monotonic() - began
    print(
        f"    returned after {held:.2f}s, capped={walk.capped}, "
        f"at {walk.arrived_at}, {walk.clicks} click(s)"
    )
    if held > WALK_BUDGET_SECONDS + CAP_SLACK_S:
        result_round.failed(
            f"held the caller {held:.2f}s against a {WALK_BUDGET_SECONDS:.1f}s budget"
        )
    else:
        result_round.passed(
            f"returned in {held:.2f}s (budget {WALK_BUDGET_SECONDS:.1f}s), "
            f"capped={walk.capped}"
        )
    return result_round


def round_interrupt(session, store) -> Round:
    result_round = Round("2. the in-process interrupt")
    monitor = SafetyMonitor(
        session,
        SafetyConfig(
            life_chicken_pct=0.0,  # explicitly disarmed: nothing fires on HP
            # 100, not 99. The first run of this canary used 99 and the
            # round silently proved nothing: the character stood at
            # 356/356 mana, and `pct <= threshold` is false at exactly
            # 100%. A threshold a full character can never cross is a
            # test that cannot fail — which is the shape this repo keeps
            # paying for. At 100 the condition is true whenever it is
            # asked, so ARMING is the crossing, which is what the round
            # times.
            mana_chicken_pct=100.0,
            chicken_in_town=True,
        ),
    )
    armed_at: list[float] = []
    moved: list[int] = [0]
    began = [0.0]
    walk_start = _position(session)

    def poll() -> None:
        if time.monotonic() - began[0] < ARM_AFTER_S:
            return
        if not armed_at:
            armed_at.append(time.monotonic())
            here = _position(session)
            moved[0] = max(
                abs(here[0] - walk_start[0]), abs(here[1] - walk_start[1])
            )
            print(
                f"    armed at +{armed_at[0] - began[0]:.2f}s, "
                f"moved {moved[0]} subtile(s) so far"
            )
        monitor.poll()

    nav = live_navigator(session, store, safety_poll=poll)
    target, radius = pick_reachable_target(nav.grid(), walk_start, distance=60)
    if target is None:
        result_round.failed("no reachable target for the second walk")
        return result_round
    print(f"    walking {walk_start} -> {target} ({radius}), monitor arms at +{ARM_AFTER_S}s")

    began[0] = time.monotonic()
    latency = None
    try:
        nav.walk_to(target)
        print("    the walk RETURNED — no interrupt")
    except SafetyInterrupt as interrupt:
        latency = time.monotonic() - armed_at[0] if armed_at else 0.0
        print(f"    SafetyInterrupt {latency:.2f}s after arming: {interrupt}")

    if latency is None:
        result_round.failed("no SafetyInterrupt was raised from inside the walk")
    elif moved[0] < 1:
        # The T72 lesson: a walk that never started would pass by raising
        # instantly, and this round would be testing nothing at all.
        result_round.failed(
            f"the character moved {moved[0]} subtiles before arming — "
            "the walk was not in flight, so nothing was proven"
        )
    elif latency > PROMPT_S:
        result_round.failed(f"the interrupt took {latency:.2f}s to arrive")
    else:
        result_round.passed(
            f"raised {latency:.2f}s after arming, from a walk that had "
            f"already moved {moved[0]} subtiles"
        )
    return result_round


def round_watchdog_fires(session, ui_array) -> tuple[Round, subprocess.Popen | None]:
    result_round = Round("3. the watchdog fires (separate process)")
    watchdog.clear_latch()
    process = subprocess.Popen(
        # --mana 100 for the same reason round 2 uses 100: at full mana a
        # 99% threshold is never crossed, and the round would time out
        # while appearing to test something.
        [sys.executable, "-m", "pd2bot.watchdog", "--mana", "100", "--in-town"],
        cwd=str(REPO),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(f"    watchdog started as pid {process.pid} — no bot is running")
    deadline = time.monotonic() + WATCHDOG_FIRE_TIMEOUT_S
    while time.monotonic() < deadline:
        if _esc_menu_open(session, ui_array):
            latch = watchdog.active_latch()
            if latch is None:
                result_round.failed("the game paused but no latch was written")
            else:
                result_round.passed(
                    f"game paused, latch reason={latch.get('reason')} "
                    f"pct={latch.get('pct')} from pid {latch.get('pid')}"
                )
            return result_round, process
        if process.poll() is not None:
            result_round.failed(
                f"the watchdog exited early ({process.returncode}): "
                f"{(process.stdout.read() if process.stdout else '')[:400]}"
            )
            return result_round, None
        time.sleep(0.2)
    result_round.failed(
        f"the ESC menu never opened within {WATCHDOG_FIRE_TIMEOUT_S:.0f}s"
    )
    return result_round, process


def round_latch_disarms(session, menu, ui_array) -> Round:
    """With the pause cleared and the game live again, the latch alone
    must still stop world input — and must NOT stop the menu path."""
    result_round = Round("4. the latch disarms world input, not the exit")
    deadline = time.monotonic() + UNPAUSE_TIMEOUT_S
    while _esc_menu_open(session, ui_array) and time.monotonic() < deadline:
        menu.window.bring_to_foreground()
        menu.press_escape()
        time.sleep(0.4)
    if _esc_menu_open(session, ui_array):
        result_round.failed("could not un-pause the game to test the latch alone")
        return result_round

    latch = watchdog.active_latch()
    if latch is None:
        result_round.failed("the latch vanished before it could be tested")
        return result_round

    gated = GatedInput(session, ui_array=ui_array)
    try:
        gated.check()
        result_round.failed("GatedInput allowed world input with a fresh latch")
        return result_round
    except InputRefused as refused:
        if "watchdog" not in str(refused):
            result_round.failed(f"refused, but not for the latch: {refused}")
            return result_round
        print(f"    GatedInput refused: {refused}")

    # MenuInput's guard is the COMPLEMENT of GatedInput's, so in a game
    # with no ESC menu open it legitimately refuses — and that refusal is
    # not the thing under test. What must never happen is a refusal
    # because of the LATCH.
    #
    # Written first as `menu_ok = True` in both branches, which could not
    # fail: the exact "a test that can pass without doing the thing it
    # tests" shape this plan's own phase files warn about, caught on a
    # re-read of a PASSING run. The reason it matters here specifically:
    # this assertion is the only thing standing between a watchdog pause
    # and a bot that cannot complete its own Save-and-Exit.
    menu_refusal = None
    try:
        menu.check()
    except InputRefused as refused:
        menu_refusal = str(refused)
    menu_ok = menu_refusal is None or "watchdog" not in menu_refusal
    print(f"    MenuInput: {menu_refusal or 'allowed'}")

    watchdog.clear_latch()
    gated_after = GatedInput(session, ui_array=ui_array)
    try:
        gated_after.check()
        cleared = True
    except InputRefused as refused:
        cleared = "watchdog" not in str(refused)

    if not cleared:
        result_round.failed("clearing the latch did not re-arm world input")
    elif not menu_ok:
        result_round.failed("MenuInput was blocked by the latch — the exit is not safe")
    else:
        result_round.passed(
            "world input refused while latched, allowed once cleared; "
            "the menu path was never blocked by it"
        )
    return result_round


def round_dead_man(session) -> Round:
    result_round = Round("5. the dead-man switch")
    waited = 0.0
    while watchdog.watchdog_is_alive() and waited < watchdog.HEARTBEAT_STALE_AFTER_S + 3:
        time.sleep(0.5)
        waited += 0.5
    if watchdog.watchdog_is_alive():
        result_round.failed(
            f"the heartbeat was still fresh {waited:.1f}s after the watchdog was killed"
        )
        return result_round
    print(f"    heartbeat went stale after {waited:.1f}s")

    class OneStep:
        name = "canary"

        def step(self, snap, ctx):  # pragma: no cover - the failure we pin
            raise AssertionError("the engine took a step without a watchdog")

    # A REAL snapshot of the live game, not a stub. The first run of this
    # canary passed `lambda: None` and crashed inside the engine before
    # reaching the check it came to make — the engine reads the snapshot
    # before consulting the dead-man switch, so a fake that is not a
    # snapshot tests the fake.
    engine = BehaviorEngine(
        snapshot=Perception(session).snapshot,
        monitor=type("M", (), {"tick": lambda self: None})(),
        states=[OneStep()],
        executor=type("E", (), {"execute": lambda self, a: None})(),
        config=EngineConfig(require_watchdog=True),
        watchdog_alive=watchdog.watchdog_is_alive,
    )
    try:
        engine.tick()
        result_round.failed("the engine ticked with no watchdog alive")
    except WatchdogDown as down:
        result_round.passed(f"the engine refused to run: {down}")
    except AssertionError as boom:
        result_round.failed(str(boom))
    return result_round


# -- the run -------------------------------------------------------------------


def main() -> int:
    print("=" * 70)
    print("  SAFETY CANARY (T80 + T81) — unattended, town only, mana only")
    print("=" * 70, flush=True)

    session = GameSession()
    menu = MenuInput(session)
    ui_array = menu.ui_array
    cycle = GameCycle(session, menu)

    if not menu.window.bring_to_foreground():
        print("could not focus the game window — refusing to send anything")
        return 1
    print("game window focused", flush=True)

    watchdog.clear_latch()  # a stale latch would disarm round 1 before it began
    rounds: list[Round] = []
    dog: subprocess.Popen | None = None
    created = False
    try:
        print("creating a game...", flush=True)
        cycle.create_game()
        created = True
        area = world.read_area(session)
        player = read_player(session)
        print(
            f"in game: {player.name if player else '?'} in area "
            f"{area.level_no if area else '?'}, "
            f"{player.hp}/{player.max_hp} life, {player.mana}/{player.max_mana} mana"
            if player
            else "in game",
            flush=True,
        )
        if area is None or area.level_no not in offsets.TOWN_AREAS:
            print("NOT IN TOWN — refusing to run the walking rounds")
            return 1

        store = MapStore()
        rounds.append(_guarded("1. the wall-clock cap", round_cap, session, store))
        rounds.append(
            _guarded("2. the in-process interrupt", round_interrupt, session, store)
        )
        try:
            fired, dog = round_watchdog_fires(session, ui_array)
        except Exception as exc:  # noqa: BLE001
            fired, dog = _crashed("3. the watchdog fires (separate process)", exc), None
        rounds.append(fired)
        rounds.append(
            _guarded(
                "4. the latch disarms world input, not the exit",
                round_latch_disarms, session, menu, ui_array,
            )
        )
        if dog is not None:
            _stop_watchdog(dog)
            dog = None
        rounds.append(_guarded("5. the dead-man switch", round_dead_man, session))
    finally:
        if dog is not None:
            _stop_watchdog(dog)
        watchdog.clear_latch()
        try:
            if _esc_menu_open(session, ui_array):
                menu.window.bring_to_foreground()
                menu.press_escape()
                time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001
            print(f"teardown: could not un-pause ({exc})")
        if created:
            try:
                print("leaving the game...", flush=True)
                cycle.leave_game()
                print("left cleanly")
            except Exception as exc:  # noqa: BLE001
                print(f"teardown: leave_game failed ({exc}) — a human should look")

    print("\n" + "=" * 70)
    for entry in rounds:
        print(entry)
    failed = [r for r in rounds if not r.ok]
    print("=" * 70)
    if failed or len(rounds) < 5:
        print(f"  RESULT: FAIL ({len(failed)} of {len(rounds)} rounds)")
        return 1
    print(f"  RESULT: PASS ({len(rounds)}/5 rounds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
