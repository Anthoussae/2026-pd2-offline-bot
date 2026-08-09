"""T46 — what stats 132/133 do when bone armor is DOWN, UP, and HIT.

Read-only: the bot sends nothing but chat. The user does the casting.

Two debts settle here. The first is old — P1 drill B verified the stats are
fixed-point but deferred the falls-when-hit half, and P6's checklist has
been carrying it ever since. The second is new and cost a live run: the
user watched stage B and reported **the bot never cast bone armor at all**.

The mechanism is already visible in the code. `read_armor_ratio` does

    if current is None or not maximum:
        return None

and the ladder reads None as "the stat is unreadable", falling back to
R47's recast-after-being-hit. But a character with NO bone armor up almost
certainly has no 132/133 entries either — so "the armor is down", which is
the strongest possible reason to cast, arrives as the same None that means
"I cannot tell", and in town nothing ever hits us to break the tie. Exactly
the conflation `read_socket_count` was fixed for this morning: a stat list
that read fine and lacks an entry is INFORMATION, not ignorance.

Before flipping it, the flip has to be safe, and that is what this drill
is for. If 132/133 are simply the wrong ids, then "absent means down"
would make rung 8 fire every `armor_retry_s` forever — and since a firing
rung consumes the tick, the bot would recast bone armor for eternity and
never once attack. That is a worse failure than the one being fixed, so
the ids get checked against the live game first.

    A  armor down   are 132/133 absent, or present and zero?
    B  armor up     do they appear, and does max look like a real pool?
    C  after a hit  does current fall while max holds?

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t46_bone_armor_stat
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.units import player_unit, read_stats  # noqa: E402

T46 = Drill(
    test_id="T46",
    title="bone armor stats 132/133: down, up, and after a hit",
    kind="perception",
    sends_input=False,
    instructions=(
        "Stand in town with bone armor NOT active (let it expire, or just",
        "  start fresh — the drill will tell you what it reads).",
        "It will then ask you to cast bone armor, and later to take a hit.",
        "The bot sends nothing but chat throughout.",
        "Cancel any time: powershell -File tools\\drill-cancel.ps1",
    ),
)


def _armor(run: DrillRun) -> tuple[int | None, int | None, int]:
    """(current, maximum, how many stats the list held at all).

    The third value is the one that makes the answer trustworthy: a stat
    list that read fine and lacks 132/133 says the armor is down, while an
    EMPTY list says only that nothing was read. Without it the two look
    identical, which is the whole defect being investigated.
    """
    unit = player_unit(run.session)
    if unit is None:
        raise DrillAborted("not in a game")
    stats = read_stats(run.session, unit)
    return (
        stats.get(offsets.STAT_BONE_ARMOR),
        stats.get(offsets.STAT_BONE_ARMOR_MAX),
        len(stats),
    )


def _describe(label: str, reading: tuple[int | None, int | None, int]) -> str:
    current, maximum, total = reading
    return (
        f"{label}: stat {offsets.STAT_BONE_ARMOR}="
        f"{'ABSENT' if current is None else current}, "
        f"stat {offsets.STAT_BONE_ARMOR_MAX}="
        f"{'ABSENT' if maximum is None else maximum} "
        f"({total} stats read in total)"
    )


def t46_body(run: DrillRun) -> str:
    lines = []

    # -- A: armor down -----------------------------------------------------
    down = _armor(run)
    lines.append(_describe("A down ", down))
    print(f"  {lines[-1]}", flush=True)
    if down[2] == 0:
        raise DrillAborted(
            "the stat list read EMPTY — that is a perception failure, not an "
            "answer about bone armor; nothing below would mean anything"
        )
    if down[0] is not None and down[1]:
        lines.append(
            "  NOTE: the stats are present with armor down — so the ratio "
            "already reads 0.0 and the None path was never the problem"
        )
        print(f"  {lines[-1]}", flush=True)

    # -- B: armor up -------------------------------------------------------
    if not run.announce_until(
        "T46: cast BONE ARMOR now, please. Waiting...",
        lambda: _armor(run)[1] not in (None, 0),
        timeout_s=180.0,
    ):
        raise DrillAborted("bone armor never showed up in the stat list")
    up = _armor(run)
    lines.append(_describe("B up   ", up))
    print(f"  {lines[-1]}", flush=True)

    # -- C: after a hit ----------------------------------------------------
    baseline = up[0] or 0
    run.say(
        "T46: now take a hit with the armor up — a Cold Plains monster is "
        "fine. Waiting up to 4 minutes; cancel if you would rather not."
    )
    fell = run.wait_until(
        lambda: (_armor(run)[0] or 0) < baseline, timeout_s=240.0
    )
    after = _armor(run)
    lines.append(_describe("C hit  ", after) + ("" if fell else "  (NO FALL SEEN)"))
    print(f"  {lines[-1]}", flush=True)

    # -- the verdict the fix depends on ------------------------------------
    absent_when_down = down[0] is None and down[1] is None
    real_pool = bool(up[1])
    verdict = (
        "ABSENT-WHEN-DOWN: 'no 132/133' means the armor is down, so the "
        "ladder may treat it as 0.0 and cast"
        if absent_when_down and real_pool
        else "NOT absent when down — the None path is NOT why it never cast; "
        "investigate before changing the ladder"
    )
    lines.append(f"verdict: {verdict}")
    print(f"\n  {lines[-1]}", flush=True)
    run.make_chat_possible(may_send_input=False)
    run.say("T46 done — see the terminal.")
    return "; ".join(lines)


if __name__ == "__main__":
    status = run_drill(T46, t46_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
