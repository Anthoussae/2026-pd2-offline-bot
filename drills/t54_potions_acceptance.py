"""T54 — potions acceptance: merc feed by ear, mixed-belt preamble,
and the run narrative (R182, the potions-and-narrative-log cycle).

**This test SENDS INPUT** in both stages. Two stages, one gate each.

Run 1's stage 1 (aborted, user redesign): it required the merc injured
below 50%, and reliably lowering merc hp proved impractical to stage.
The rung's own trigger (<50%, paced, never in town) stays as shipped
and sim-tested — the user trusts it. What needs LIVE proof is the
DELIVERY: the Alt+key chord reaching the game as a merc feed rather
than a player drink. The instrument for that is the user's ears.

## Stage 1 — the feed, confirmed by ear (merc at any hp)

Merc alive, sound on, a healing potion somewhere in the belt (the user
has shuffled the columns — the type search picks the column, which is
part of what is under test). The drill sends ONE Alt+chord through the
executor, reports which key and the column's before/after count, and
asks in chat: did she say "thank you"? **YES** = the feed landed
(pass); **NO** = up to 2 more attempts, then FAILED. A NO with the
column count dropping is the telling failure: the key landed but the
Alt did not, i.e. the player drank it — exactly the race the settled
chord exists to prevent.

## Stage 2 — mixed belt + full patrol game (T53's run, R178's belt)

The belt is already shuffled (mana squatting where the layout says
healing). Adjust it if you like — scarce healing (~2 reachable)
reproduces R178 exactly; plenty just proves the refill works around the
squatter; both prove "a mixed belt cannot halt a run". Type OK and THE
BOT PLAYS one full patrol game exactly like T53 (it may leave your game
and create its own). Passes when the cycle completes with no belt halt;
the drill then names the run's narrative log file (logs/run-*.log) —
the cycle's third deliverable, checked for existence and coarseness.

## How it ends

Stage 1: after your YES (or 3 NOs / 2 minutes without an answer).
Stage 2: after one game (several minutes). Stopping early ALWAYS works:
type **abort** in chat, run `tools\\drill-cancel.ps1`, or take the
mouse / press ESC — the foreground guard stops every send instantly.
"""

import sys
import time
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot import offsets  # noqa: E402
from pd2bot.behavior.actions import GiveMercPotion  # noqa: E402
from pd2bot.behavior.execute import CastInFlight, GameActionExecutor  # noqa: E402
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
from pd2bot.skills import SkillSwitchFailed  # noqa: E402
from pd2bot.wiring import BotPaths, build_bot, describe  # noqa: E402

SETUP_PATIENCE_S = 600.0  # how long each stage waits for the user's setup
FEED_ATTEMPTS = 3  # chords offered before stage 1 calls itself FAILED
ANSWER_PATIENCE_S = 120.0  # how long each YES/NO question waits
# Test-scoped answer vocabulary (the T52 END/DONE pattern): exact tokens,
# consulted only while this test is asking, never parsing.
YES_WORDS = frozenset({"yes", "y"})
NO_WORDS = frozenset({"no", "n"})

T54 = Drill(
    test_id="T54",
    title="potions acceptance — merc feed by ear, mixed-belt refill, run narrative",
    kind="hybrid",
    sends_input=True,
    instructions=(
        "TWO STAGES. Stage 1: merc alive, SOUND ON, healing somewhere in",
        "the belt (shuffled is perfect). The drill sends ONE Alt+chord and",
        "asks: did she say thank you? Answer YES or NO in chat (up to 3",
        "tries). Any merc hp is fine - your ears are the instrument.",
        "Stage 2: belt stays mixed (mana in a healing column; scarce",
        "healing reproduces R178 exactly), type OK again - THE BOT THEN",
        "PLAYS one full patrol game like T53 and must NOT halt on the belt.",
        "Stop any time: 'abort' in chat, tools\\drill-cancel.ps1, or take",
        "the mouse / press ESC - your hands always win.",
    ),
)


def _stage1_merc_feed(run: DrillRun, bot) -> str:
    """One Alt+chord through the executor; the user's ears judge it.

    The rung's <50% trigger stays as shipped and sim-tested (the user's
    call, run 1 redesign): what live must prove is the DELIVERY — the
    settled chord arriving as a merc feed, not a player drink. The merc's
    "thank you" voice line is the one observation that separates those
    two, and only a human can hear it.
    """
    session = bot.session
    cfg = bot.class_config.reflex
    executor = GameActionExecutor(
        session=session,
        gated=bot.gated,
        walk_to=bot.navigator.walk_to,
        hotkeys=bot.class_config.hotkeys,
    )

    def carried():
        return read_carried_items(session, with_sockets=False)

    def heal_column() -> int | None:
        """The rung's own search order: configured healing columns first,
        then the rest — the type search under test, on a shuffled belt."""
        items = carried().belt
        others = tuple(
            c for c in range(offsets.BELT_COLUMNS) if c not in cfg.heal_columns
        )
        for column in (*cfg.heal_columns, *others):
            if any(
                i.belt_column == column and i.is_healing_potion for i in items
            ):
                return column
        return None

    def ready() -> bool:
        return (
            bot.perception.snapshot().merc is not None
            and heal_column() is not None
        )

    if not run.announce_until(
        "Stage 1 setup: merc alive nearby, a healing potion in the belt, "
        "sound ON. Waiting...",
        ready,
        repeat_every_s=45.0,
        timeout_s=SETUP_PATIENCE_S,
    ):
        raise RuntimeError(
            "stage 1 preconditions never held (merc alive + healing in belt)"
        )

    attempts = []
    for attempt in range(1, FEED_ATTEMPTS + 1):
        run.check_cancel()
        if run.player_is_dead():
            raise RuntimeError("player reads dead — sending nothing")
        column = heal_column()
        if column is None:
            raise RuntimeError("no healing potion left in the belt")
        before = sum(
            1 for i in carried().belt if i.belt_column == column
        )
        try:
            executor.execute(GiveMercPotion(column))
        except (InputRefused, SkillSwitchFailed, CastInFlight) as exc:
            run.say(f"send refused ({type(exc).__name__}) — retrying shortly.")
            time.sleep(2.0)
            continue
        time.sleep(1.0)  # let the belt read settle before counting
        after = sum(1 for i in carried().belt if i.belt_column == column)
        attempts.append(f"Alt+key {column + 1} ({before}->{after})")
        run.say(
            f"Chord {attempt}: Alt+key {column + 1}, column count "
            f"{before}->{after}. Did she say thank you? YES or NO."
        )
        answer = None
        deadline = time.monotonic() + ANSWER_PATIENCE_S
        while time.monotonic() < deadline:
            run.check_cancel()
            if run.heard(YES_WORDS):
                answer = True
                break
            if run.heard(NO_WORDS):
                answer = False
                break
            time.sleep(0.2)
        if answer is None:
            raise RuntimeError(
                f"no YES/NO within {ANSWER_PATIENCE_S:.0f}s of chord {attempt}"
            )
        if answer:
            result = (
                f"stage 1: thank-you confirmed on chord {attempt} "
                f"({'; '.join(attempts)})"
            )
            print(result, flush=True)
            return result
        run.say("Noted. Trying again." if attempt < FEED_ATTEMPTS else "Noted.")
    raise RuntimeError(
        f"{len(attempts)} chord(s) sent ({'; '.join(attempts)}), none "
        "earned a thank-you — a falling column count with NO means the "
        "player drank it (the Alt did not land)"
    )


def _stage2_mixed_belt_run(run: DrillRun, stop_requested, aborted) -> str:
    """T53's full patrol game, launched onto a deliberately mixed belt."""
    run.say("STAGE 2: keep the belt mixed (mana in a healing column). Scarce")
    run.say("healing (~2 reachable) reproduces R178 exactly; plenty is fine")
    run.say("too. Type OK when ready — the bot then takes over.")
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
    stage1 = _stage1_merc_feed(run, bot)
    run.say("Stage 1 done: " + stage1)
    stage2 = _stage2_mixed_belt_run(run, stop_requested, aborted)
    return f"{stage1} | {stage2}"


if __name__ == "__main__":
    status = run_drill(T54, t54_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
