"""T48 — how long a cast takes, and when the client accepts input again.

The bot sends input: it casts bone armor on itself in town and presses one
hotkey per trial. No monsters, no walking, no panels.

Two open questions, one mechanism, so one drill.

**The guessed settle** (review 002). `GameActionExecutor` sleeps a fixed
`cast_settle_s` (0.4 s) inside the engine tick after every cast, so every
cast is 0.4 s in which no survival rung can fire. The number was never
measured — it was chosen as "shorter than two ticks". Phase A measures
what a cast actually costs by sampling the player's own unit MODE, which
is the game's answer rather than ours, and works for every cast rather
than only the ones with a readable effect.

**The unexplained `SkillSwitchFailed`.** It recurred in three separate
stage-B runs on three different skill pairs (95<-83, 68<-83, 68<-95), and
T47 has now ruled out both standing theories: all six hotkeys select
exactly what `config/necro.toml` says, and the presses land. What every
one of those failures has in common is the thing T47 does not do —
**each was a switch attempted immediately after a cast**. If the client
drops input while a cast animation plays, then three presses inside
`ensure_right_skill`'s 1.8 s of patience can all be eaten, the slot keeps
reading whatever was selected last, and that is exactly the reported
symptom. It is also the user's own observation from manual play,
generalised: they saw a following command interrupt the bone-armor cast.

Phase B tests it directly. Cast, wait a measured delay, press ONE hotkey,
and see whether it registers. Sweeping the delay finds the point at which
input starts being accepted — which is the number the settle should be,
and the reason it exists.

Read as: if presses at delay 0.0 are dropped and presses after some delay
land, the theory holds and the threshold is the answer. If presses land
at every delay including 0.0, the theory is dead and `SkillSwitchFailed`
is something else — worth knowing just as much, and cheaper than another
supervised run.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t48_cast_animation
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.behavior.combat import load_class_config  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.input import GatedInput  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.player import read_active_skills, read_player  # noqa: E402
from pd2bot.skills import SkillSwitchFailed, ensure_right_skill  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

SAMPLE_S = 0.02  # 50 Hz against a 25 fps sim: two samples per frame
CAST_CAP_S = 3.0  # longest a cast animation could conceivably run
PRESS_CAP_S = 2.0  # how long to wait for a single press to register
BETWEEN_S = 1.5  # settle between trials, so each starts from rest
# The delays swept in phase B. 0.0 is the bot's current behaviour minus
# the settle; the last is comfortably past any 25 fps animation.
DELAYS = (0.0, 0.1, 0.2, 0.3, 0.5, 0.8)
MIN_MANA = 120  # enough for the whole sweep with margin; below that, stop

T48 = Drill(
    test_id="T48",
    title="cast animation length, and when input is accepted again",
    kind="bot control",
    sends_input=True,
    instructions=(
        "Stand in town, safe, with no panels open — then hands off.",
        "The bot casts BONE ARMOR on itself several times and presses one",
        "  hotkey after each, timing when the press registers. Nothing is",
        "  cast at anything, and nothing moves.",
        "Cancel any time: powershell -File tools\\drill-cancel.ps1",
    ),
)


def _mode(run: DrillRun) -> int | None:
    player = read_player(run.session)
    return None if player is None else player.mode


def _right_skill(run: DrillRun) -> int | None:
    skills = read_active_skills(run.session)
    return None if skills is None else skills.right_id


def _cast_self(run: DrillRun, gated: GatedInput) -> float:
    """Right-click our own feet. Returns the moment the click was sent."""
    player = read_player(run.session)
    if player is None:
        raise DrillAborted("player unreadable mid-drill")
    sent = time.monotonic()
    gated.click_world(*player.position, button="right")
    return sent


def _sample_modes(run: DrillRun, since: float, idle: int | None) -> list[tuple[float, int | None]]:
    """Sample the player's mode until it comes back to `idle`, or the cap.

    Returns every CHANGE with its offset from `since`, so the transcript
    shows the shape of the animation rather than a single number.
    """
    changes: list[tuple[float, int | None]] = []
    last = idle
    deadline = since + CAST_CAP_S
    while time.monotonic() < deadline:
        run.check_cancel()
        now_mode = _mode(run)
        if now_mode != last:
            changes.append((time.monotonic() - since, now_mode))
            last = now_mode
            if now_mode == idle and changes:
                break
        time.sleep(SAMPLE_S)
    return changes


def t48_body(run: DrillRun) -> str:
    if run.player_is_dead():
        raise DrillAborted("the character is dead — this drill sends nothing")
    player = read_player(run.session)
    if player is None:
        raise DrillAborted("not in a game")
    if player.mana < MIN_MANA:
        raise DrillAborted(
            f"mana {player.mana} is below {MIN_MANA} — the sweep casts nine "
            "times and a half-finished sweep answers nothing"
        )

    config = load_class_config(REPO / "config" / "necro.toml")
    armor = config.skills["bone_armor"]
    other = config.skills["desecrate"]  # the press under test; never cast
    gated = GatedInput(run.session, ui_array=run.ui_array)
    lines: list[str] = []

    # -- A: what does a cast actually cost? --------------------------------
    idle_mode = _mode(run)
    lines.append(f"idle mode reads {idle_mode}")
    print(f"  {lines[-1]}", flush=True)
    durations: list[float] = []
    for trial in range(3):
        run.check_cancel()
        ensure_right_skill(run.session, gated, armor, hotkeys=config.hotkeys)
        sent = _cast_self(run, gated)
        changes = _sample_modes(run, sent, idle_mode)
        back = next(
            (at for at, mode in reversed(changes) if mode == idle_mode), None
        )
        if back is not None:
            durations.append(back)
        shape = ", ".join(f"{at * 1000:.0f}ms->{mode}" for at, mode in changes)
        lines.append(
            f"A{trial + 1} cast: "
            + (shape or "NO MODE CHANGE SEEN")
            + (f"  (back to idle after {back * 1000:.0f}ms)" if back else "")
        )
        print(f"  {lines[-1]}", flush=True)
        run.sleep(BETWEEN_S)

    # -- B: when does a hotkey press start landing again? ------------------
    for delay in DELAYS:
        run.check_cancel()
        # Get back onto bone armor patiently, BEFORE the timed part — a
        # failure here would be the very effect under test contaminating
        # its own setup.
        run.sleep(BETWEEN_S)
        try:
            ensure_right_skill(run.session, gated, armor, hotkeys=config.hotkeys)
        except SkillSwitchFailed as exc:
            lines.append(f"B{delay:.1f}s: SETUP FAILED — {exc}")
            print(f"  {lines[-1]}", flush=True)
            continue

        sent = _cast_self(run, gated)
        if delay:
            time.sleep(delay)
        pressed = time.monotonic()
        gated.press_key(config.hotkeys[other])  # ONE press, no retry
        landed = None
        deadline = pressed + PRESS_CAP_S
        while time.monotonic() < deadline:
            run.check_cancel()
            if _right_skill(run) == other:
                landed = time.monotonic() - pressed
                break
            time.sleep(SAMPLE_S)
        lines.append(
            f"B delay {delay:.1f}s (press at {(pressed - sent) * 1000:.0f}ms "
            f"after the cast): "
            + (
                f"LANDED after {landed * 1000:.0f}ms"
                if landed is not None
                else f"DROPPED — slot still reads {_right_skill(run)}"
            )
        )
        print(f"  {lines[-1]}", flush=True)

    # -- the verdict -------------------------------------------------------
    dropped = [line for line in lines if "DROPPED" in line]
    animation = (
        f"{min(durations) * 1000:.0f}-{max(durations) * 1000:.0f}ms"
        if durations
        else "unmeasured (no mode change seen)"
    )
    if not dropped:
        verdict = (
            f"every press landed at every delay — the cast does NOT eat "
            f"following input, so SkillSwitchFailed is something else. "
            f"Cast animation: {animation}"
        )
    elif len(dropped) == len(DELAYS):
        verdict = (
            "every press was dropped, at every delay — that is not about "
            "casting; suspect the press path itself, and note T47 pressed "
            f"the same keys successfully minutes ago. Cast animation: {animation}"
        )
    else:
        verdict = (
            f"{len(dropped)} of {len(DELAYS)} delays dropped the press — the "
            "cast DOES eat following input, which is what SkillSwitchFailed "
            f"has been. Cast animation: {animation}; the settle needs to "
            "cover the drop threshold above"
        )
    lines.append(f"verdict: {verdict}")
    print(f"\n  {lines[-1]}", flush=True)
    run.make_chat_possible(may_send_input=True)
    run.say("T48 done — see the terminal.")
    return "; ".join(lines)


if __name__ == "__main__":
    status = run_drill(T48, t48_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
