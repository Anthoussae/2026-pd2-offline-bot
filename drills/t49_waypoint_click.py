"""T49 — why does clicking the town waypoint not open its panel?

The bot sends input: it walks near the waypoint and left-clicks it, once
per attempt, reporting the state at every stage. Nothing else.

Two runs on 2026-08-01 died identically in `open_object_panel`:

    waypoint never opened its panel after 3 attempts
    — last click at (5884, 5709), player at (5886, 5711)

Distance 2, against a `min_interact_range` of 4. The obvious reading was
that the standoff was not being achieved, so `_walk_near` was taught to
VERIFY its step-back rather than assume it — and the second run failed
byte for byte identically, which killed that explanation.

Then the user, watching: *the bot appeared to reach the waypoint and
hover the mouse over it, but never left-clicked (as far as I could
tell).* That splits three possibilities the logs cannot:

  A  the standoff is never achieved, so the click lands on the tile the
     character is standing on and does nothing (D2 ignores it);
  B  the standoff IS achieved and the click is sent, but the panel does
     not open — a projection or a timing problem;
  C  the click is never sent at all. `GatedInput.click_screen` moves the
     cursor, sleeps a frame, and then RE-CHECKS the guard before pressing
     the button — so a guard that fails in that window leaves the mouse
     hovering over the target having sent nothing, which is exactly what
     was described.

So this measures each stage separately instead of reasoning about them:
where the character is before and after the approach, what the click
projects to, whether the guard passes at the moment of the click, and
whether the panel opened. It does NOT travel anywhere — it only tries to
open the panel, and closes it again.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t49_waypoint_click
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput, InputRefused  # noqa: E402
from pd2bot.mapstore import MapStore  # noqa: E402
from pd2bot.menuinput import MenuInput  # noqa: E402
from pd2bot.navigate import live_navigator  # noqa: E402
from pd2bot.panelinput import PanelInput  # noqa: E402
from pd2bot.perception import uistate  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_player  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.town import TownConfig, TownLayer  # noqa: E402

ATTEMPTS = 3
PANEL_WAIT_S = 6.0

T49 = Drill(
    test_id="T49",
    title="why the town waypoint does not open when clicked",
    kind="bot control",
    sends_input=True,
    instructions=(
        "Stand in town, safe, with no panels open — then hands off.",
        "The bot walks near the waypoint and left-clicks it, up to three",
        "  times, reporting what it sees at each stage. It does NOT",
        "  travel anywhere.",
        "Watch the MOUSE: the question is whether a click is sent at all.",
        "Cancel any time: powershell -File tools\\drill-cancel.ps1",
    ),
)


def _chebyshev(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _build_town(run: DrillRun) -> TownLayer:
    session = run.session
    navigator = live_navigator(session, MapStore(), offsets.DIFFICULTY_HELL)
    return TownLayer(
        session=session,
        gated=GatedInput(session, ui_array=run.ui_array),
        panel=PanelInput(session, ui_array=run.ui_array),
        menu=MenuInput(session, ui_array=run.ui_array),
        walk_to=navigator.walk_to,
        snapshot=Perception(session).snapshot,
        config=TownConfig(),
        should_stop=lambda: run.cancelled or run._cancel_file.exists(),
    )


def _waypoint(run: DrillRun):
    for obj in Perception(run.session).snapshot().objects:
        if obj.kind == offsets.OBJ_WAYPOINT_A1:
            return obj.position
    return None


def _panel_open(run: DrillRun) -> bool:
    return uistate.read_ui_state(run.session, run.ui_array).is_open(
        offsets.UI_WPMENU
    )


def t49_body(run: DrillRun) -> str:
    if run.player_is_dead():
        raise DrillAborted("the character is dead — this drill sends nothing")
    area = Perception(run.session).snapshot().area
    if area is None or area.level_no != offsets.AREA_ROGUE_ENCAMPMENT:
        raise DrillAborted("stand in the Rogue Encampment for this drill")

    town = _build_town(run)
    gated = town.gated
    config = town.config
    lines: list[str] = []

    target = _waypoint(run)
    if target is None:
        raise DrillAborted("the waypoint is not in perception range from here")
    player = read_player(run.session)
    lines.append(
        f"waypoint at {target}, player at {player.position}, "
        f"distance {_chebyshev(player.position, target)} "
        f"(want {config.min_interact_range}-{config.interact_range})"
    )
    print(f"  {lines[-1]}", flush=True)

    for attempt in range(1, ATTEMPTS + 1):
        run.check_cancel()
        if _panel_open(run):
            lines.append(f"attempt {attempt}: panel already open before clicking")
            break

        # -- stage 1: the approach ----------------------------------------
        town._walk_near(target, minimum=config.min_interact_range)
        player = read_player(run.session)
        distance = _chebyshev(player.position, target)
        standoff_ok = config.min_interact_range <= distance <= config.interact_range
        lines.append(
            f"attempt {attempt} approach: player {player.position}, "
            f"distance {distance} — standoff "
            f"{'OK' if standoff_ok else 'NOT ACHIEVED'}"
        )
        print(f"  {lines[-1]}", flush=True)

        # -- stage 2: does the guard pass right now? ----------------------
        try:
            gated.check()
            guard = "passes"
        except InputRefused as exc:
            guard = f"REFUSES — {exc}"
        state = uistate.read_ui_state(run.session, run.ui_array)
        lines.append(
            f"attempt {attempt} guard: {guard}; "
            f"panels {', '.join(state.names) or 'none'}"
        )
        print(f"  {lines[-1]}", flush=True)

        # -- stage 3: the click itself ------------------------------------
        try:
            screen = gated.click_world(*target)
            sent = f"sent, projected to {screen}"
        except InputRefused as exc:
            # THE hypothesis: the cursor moves, the guard re-checks, and
            # the press never happens. From outside that is a hover.
            sent = f"REFUSED MID-CLICK — {exc}"
        except Exception as exc:  # noqa: BLE001 - a drill reports, it does not crash
            sent = f"{type(exc).__name__}: {exc}"
        lines.append(f"attempt {attempt} click: {sent}")
        print(f"  {lines[-1]}", flush=True)

        # -- stage 4: did anything happen? --------------------------------
        deadline = time.monotonic() + PANEL_WAIT_S
        opened = False
        while time.monotonic() < deadline:
            run.check_cancel()
            if _panel_open(run):
                opened = True
                break
            time.sleep(0.1)
        player = read_player(run.session)
        lines.append(
            f"attempt {attempt} result: panel "
            f"{'OPENED' if opened else 'did not open'}; "
            f"player now {player.position} "
            f"(distance {_chebyshev(player.position, target)})"
        )
        print(f"  {lines[-1]}", flush=True)
        if opened:
            break

    if _panel_open(run):
        town.close_panels()  # leave the character as we found it
        lines.append("panel closed again")

    print("", flush=True)
    run.make_chat_possible(may_send_input=True)
    run.say("T49 done — see the terminal.")
    return "; ".join(lines)


if __name__ == "__main__":
    status = run_drill(T49, t49_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
