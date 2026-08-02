"""T54 — potions acceptance: merc first aid live, mixed-belt preamble,
and the run narrative (R182, the potions-and-narrative-log cycle).

**This test SENDS INPUT** in both stages. Two stages, one gate each:

## Stage 1 — merc first aid (you set the scene, then hands off)

You get the character OUT of town with the merc alive and hurt below
50%, and at least one healing potion somewhere in the belt (a "wrong"
column is welcome — the type search is part of what is under test).
The drill then runs the shipped reflex ladder WITHOUT offense or run
steps: it may drink for the player, recast armor, and — the point —
Alt+<column key> a healing potion to the merc, paced at 3 s. Passes
when at least one chord was sent and the merc reads back above 50%.
Ends on its own after 3 minutes otherwise. The chicken monitor runs at
50% and a death latches: this stage fails rather than sending on.

## Stage 2 — mixed belt + full patrol game (T53's run, R178's belt)

You mix the belt: mana potion(s) squatting in a healing column. For the
full R178 reproduction, ALSO keep healing scarce (~2 reachable) so the
refill genuinely comes up short — expect "belt short ... continuing",
never a halt. With plenty of healing, the refill simply works around
the squatter; both outcomes prove the contract. Type OK and THE BOT
PLAYS one full patrol game exactly like T53 (it may leave your game and
create its own). Passes when the cycle completes with no belt halt; the
drill then names the run's narrative log file (logs/run-*.log) — the
cycle's third deliverable, checked for existence and coarseness.

## How it ends

Stage 1: on its own (merc recovered, or 3 minutes). Stage 2: after one
game (several minutes). Stopping early ALWAYS works: type **abort** in
chat, run `tools\\drill-cancel.ps1`, or take the mouse / press ESC —
the foreground guard stops every send instantly.
"""

import sys
import time
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot.behavior.actions import GiveMercPotion  # noqa: E402
from pd2bot.behavior.execute import CastInFlight, GameActionExecutor  # noqa: E402
from pd2bot.behavior.reflex import ReflexLadder, read_armor_ratio  # noqa: E402
from pd2bot.drill import (  # noqa: E402
    ABORT_WORDS,
    CANCEL_FILE,
    Drill,
    DrillAborted,
    DrillRun,
    run_drill,
)
from pd2bot.input import InputRefused  # noqa: E402
from pd2bot.items import read_carried_items  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.safety import SafetyConfig, SafetyMonitor  # noqa: E402
from pd2bot.skills import SkillSwitchFailed  # noqa: E402
from pd2bot.wiring import BotPaths, build_bot, describe  # noqa: E402

STAGE1_LIVE_S = 180.0  # the merc-aid watch window once preconditions hold
SETUP_PATIENCE_S = 600.0  # how long each stage waits for the user's setup

T54 = Drill(
    test_id="T54",
    title="potions acceptance — merc first aid, mixed-belt refill, run narrative",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "TWO STAGES. Stage 1: get OUT of town, merc alive and below 50%,",
        "a healing potion in the belt (wrong column welcome). Then hands",
        "off: the ladder should Alt+key a potion to the merc. Ends when",
        "the merc passes 50%, or after 3 minutes.",
        "Stage 2: mix the belt (mana in a healing column; scarce healing",
        "reproduces R178 exactly), type OK again - THE BOT THEN PLAYS one",
        "full patrol game like T53 and must NOT halt on the belt.",
        "Stop any time: 'abort' in chat, tools\\drill-cancel.ps1, or take",
        "the mouse / press ESC - your hands always win.",
    ),
)


def _stage1_merc_aid(run: DrillRun, bot) -> str:
    """The reflex ladder live, no offense: the merc rung must feed."""
    session = bot.session
    cfg = bot.class_config.reflex
    threshold = cfg.merc_heal_below_pct

    ladder = ReflexLadder(
        cfg,
        carried=lambda: read_carried_items(session, with_sockets=False),
        armor_ratio=lambda: read_armor_ratio(session),
        is_walkable=bot.is_walkable,
        combat_upkeep=None,  # no offense in this stage, by design
    )
    executor = GameActionExecutor(
        session=session,
        gated=bot.gated,
        walk_to=bot.navigator.walk_to,
        hotkeys=bot.class_config.hotkeys,
    )
    monitor = SafetyMonitor(session, SafetyConfig(life_chicken_pct=50.0))

    def merc_pct() -> float | None:
        merc = bot.perception.snapshot().merc
        if merc is None or merc.max_hp <= 0:
            return None
        return 100.0 * merc.hp / merc.max_hp

    def ready() -> bool:
        snap = bot.perception.snapshot()
        merc = snap.merc
        if snap.in_town or merc is None or merc.max_hp <= 0:
            return False
        if 100.0 * merc.hp / merc.max_hp >= threshold:
            return False
        carried = read_carried_items(session, with_sockets=False)
        return any(i.is_healing_potion for i in carried.belt)

    if not run.announce_until(
        f"Stage 1 setup: out of town, merc below {threshold:.0f}%, healing "
        "in the belt. Waiting...",
        ready,
        repeat_every_s=45.0,
        timeout_s=SETUP_PATIENCE_S,
    ):
        raise RuntimeError(
            "stage 1 preconditions never held (out of town + merc under "
            f"{threshold:.0f}% + healing in belt)"
        )
    run.say("Stage 1 LIVE — hands off; the ladder is watching the merc.")

    chords = 0
    other_rungs: dict[str, int] = {}
    last_pct = merc_pct()
    deadline = time.monotonic() + STAGE1_LIVE_S
    while time.monotonic() < deadline:
        run.check_cancel()
        monitor.tick()  # chicken/death end the stage rather than send on
        decision = ladder.evaluate(bot.perception.snapshot())
        if decision is not None:
            try:
                executor.execute(decision.action)
            except (InputRefused, SkillSwitchFailed, CastInFlight):
                decision.commit_attempted()  # pacing survives a refusal
                time.sleep(0.2)
                continue
            decision.commit_attempted()
            decision.commit_sent()
            if isinstance(decision.action, GiveMercPotion):
                chords += 1
                print(
                    f"  merc feed #{chords}: {decision.reason} -> "
                    f"Alt+key {decision.action.column + 1}",
                    flush=True,
                )
            else:
                other_rungs[decision.rung] = other_rungs.get(decision.rung, 0) + 1
        last_pct = merc_pct()
        if chords and last_pct is not None and last_pct >= threshold:
            break
        time.sleep(0.2)

    extras = (
        "; other rungs: "
        + ", ".join(f"{r} x{n}" for r, n in sorted(other_rungs.items()))
        if other_rungs
        else ""
    )
    if not chords:
        raise RuntimeError(
            f"the merc rung never fired in {STAGE1_LIVE_S:.0f}s "
            f"(merc last read {last_pct if last_pct is not None else 'gone'}%)"
            + extras
        )
    if last_pct is None or last_pct < threshold:
        raise RuntimeError(
            f"{chords} chord(s) sent but the merc never recovered past "
            f"{threshold:.0f}% (last {last_pct})" + extras
        )
    result = f"stage 1: {chords} Alt-chord(s), merc back to {last_pct:.0f}%{extras}"
    print(result, flush=True)
    return result


def _stage2_mixed_belt_run(run: DrillRun, stop_requested, aborted) -> str:
    """T53's full patrol game, launched onto a deliberately mixed belt."""
    run.say("STAGE 2: mix the belt now — mana potion(s) in a healing column.")
    run.say("Scarce healing (~2 reachable) reproduces R178 exactly; plenty")
    run.say("is fine too. Type OK when ready — the bot then takes over.")
    if not run.await_ok(timeout_s=SETUP_PATIENCE_S):
        raise RuntimeError("stage 2 never got its OK")

    bot = build_bot(
        paths=replace(BotPaths(), run=REPO / "runs" / "cold-plains-patrol.toml"),
        chicken_life_pct=50.0,  # the P6 stage-B setting
        should_stop=stop_requested,
    )
    for line in describe(bot):
        print(line, flush=True)

    started = time.monotonic()
    report = bot.cycle().run_games(bot.runner(), max_games=1)
    duration = time.monotonic() - started

    game_lines = []
    for index, engine in enumerate(bot.engines(), start=1):
        summary = engine.report.summary()
        print(f"\n--- game {index}: {summary} ---")
        for line in engine.report.log:
            print(f"  {line}")
        game_lines.append(summary)

    if aborted[0]:
        raise DrillAborted("stopped by request mid-run")
    cycle_summary = report.summary() if hasattr(report, "summary") else str(report)
    if getattr(report, "completed", None) == 0:
        raise RuntimeError(f"no clean cycle: {cycle_summary}")

    # The narrative log (P3): the run must have left a readable story.
    logs = sorted(
        (REPO / "logs").glob("run-*.log"),
        key=lambda p: p.stat().st_mtime,
    )
    if not logs:
        raise RuntimeError("no narrative log was written under logs/")
    narrative = logs[-1]
    lines = narrative.read_text(encoding="utf-8").splitlines()
    belt_lines = [ln for ln in lines if "belt" in ln]
    print(f"\nnarrative: {narrative.name}, {len(lines)} line(s)")
    for ln in belt_lines:
        print(f"  {ln}")

    return (
        f"stage 2: {duration:.0f}s; {cycle_summary}; "
        + "; ".join(f"game {i + 1}: {s}" for i, s in enumerate(game_lines))
        + f"; narrative {narrative.name} ({len(lines)} lines"
        + (f", belt: {belt_lines[-1].split('  ', 1)[-1].strip()}" if belt_lines else "")
        + ")"
    )


def t54_body(run: DrillRun) -> str:
    aborted = [False]

    def stop_requested() -> bool:
        if aborted[0]:
            return True
        try:
            if CANCEL_FILE.exists():
                aborted[0] = True
                return True
        except OSError:
            pass
        if run.heard(ABORT_WORDS):
            aborted[0] = True
            return True
        return False

    # One bot assembly serves stage 1 (its perception/input/config) and is
    # rebuilt for stage 2 (fresh per-run state, same shape as T53).
    bot = build_bot(
        paths=replace(BotPaths(), run=REPO / "runs" / "cold-plains-patrol.toml"),
        chicken_life_pct=50.0,
        should_stop=stop_requested,
    )
    stage1 = _stage1_merc_aid(run, bot)
    run.say("Stage 1 done: " + stage1)
    stage2 = _stage2_mixed_belt_run(run, stop_requested, aborted)
    return f"{stage1} | {stage2}"


if __name__ == "__main__":
    status = run_drill(T54, t54_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
