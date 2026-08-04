"""T17 — identify town NPCs by standing next to them.

Why this drill exists: R52 asked the user to walk to Akara and recorded the
kind that entered perception range on the way as "Akara, verified live".
That is not what the observation showed — anyone standing near Akara gives
the same signature — and T12 then walked the bot confidently to kind 148
expecting the healer, reaching Kashya instead and looping politely at her
(R66). Proximity removes the ambiguity: whoever you are *standing on top
of* is the NPC you named.

For each NPC the user stands beside it and holds still; the bot reads the
nearest ally and records kind + position. Two products, both needed:

    kind  -> the true identity mapping for offsets.NPC_KINDS
    position -> the approach target for TownConfig.npc_positions

The mercenary is excluded by construction (it follows you, so it is always
nearest), and every candidate is printed with its distance so a summon
standing between you and the NPC is visible rather than silently adopted.

Run from the repo root:
    & "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.t17_npc_identify
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import offsets  # noqa: E402
from pd2bot.drill import Drill, DrillAborted, DrillRun, run_drill  # noqa: E402
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.snapshot import Perception  # noqa: E402

# The two M5 needs plus the neighbours most likely to be confused with them;
# naming more costs the user only a few seconds each and settles the table.
TARGETS = ("AKARA (the healer)", "KASHYA (merc resurrector)", "CHARSI", "GHEED")

STILL_SAMPLES = 20  # 2 s of the player not moving
STILL_SUBTILES = 1
NEAR_ENOUGH = 12  # subtiles: "standing beside" for reporting purposes


def nearest_allies(perception, limit: int = 4):
    """Allies sorted by distance from the player, mercenary excluded."""
    snap = perception.snapshot()
    if snap.player is None:
        return []
    px, py = snap.player.position
    scored = [
        (max(abs(a.position[0] - px), abs(a.position[1] - py)), a)
        for a in snap.allies
        if a.merc_kind is None  # the merc follows: never the answer
    ]
    scored.sort(key=lambda pair: pair[0])
    return scored[:limit]


def wait_until_still(run: DrillRun, perception, timeout_s: float = 120.0):
    """Return the player position once it has stopped changing."""
    history: list[tuple[int, int]] = []
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        snap = perception.snapshot()
        if snap.player is not None:
            history.append(snap.player.position)
            if len(history) > STILL_SAMPLES:
                history.pop(0)
            if len(history) == STILL_SAMPLES and all(
                max(abs(p[0] - history[0][0]), abs(p[1] - history[0][1]))
                <= STILL_SUBTILES
                for p in history
            ):
                return history[-1]
        time.sleep(0.1)
    return None


T17 = Drill(
    test_id="T17",
    title="Identify town NPCs by proximity",
    kind="human calibration",
    instructions=(
        "I will name one NPC at a time. Walk right up to them - close enough "
        "to touch - and stand still for ~2s.",
        "I read whoever is nearest and record their kind id and position.",
        "Nothing is clicked; you drive throughout.",
    ),
)


def t17_body(run: DrillRun) -> str:
    perception = Perception(run.session)
    found = {}

    for name in TARGETS:
        run.say(f"Walk up to {name} and stand still beside them (~2s).")
        # A fresh stillness each time: the previous target's stand counts
        # for nothing, or the same reading would be adopted twice.
        time.sleep(3.0)
        position = wait_until_still(run, perception)
        if position is None:
            print(f"{name}: never stood still; skipped", flush=True)
            continue
        candidates = nearest_allies(perception)
        if not candidates:
            print(f"{name}: no allies in range at {position}", flush=True)
            continue

        distance, ally = candidates[0]
        found[name] = (ally.kind, ally.position, distance)
        listing = ", ".join(
            f"kind {a.kind} @{a.position} d={d}" for d, a in candidates
        )
        print(f"{name}: standing at {position}", flush=True)
        print(f"    nearest -> kind {ally.kind} at {ally.position} (d={distance})", flush=True)
        print(f"    all candidates: {listing}", flush=True)
        if distance > NEAR_ENOUGH:
            print(
                f"    !! {distance} subtiles away — stand closer or this "
                "identification is not trustworthy",
                flush=True,
            )
        run.say(f"Got {name}: kind {ally.kind}.", patience_s=15)

    if not found:
        raise DrillAborted("no NPCs identified")

    print("\n== identification ==", flush=True)
    for name, (kind, position, distance) in found.items():
        current = offsets.NPC_KINDS.get(kind, "(unnamed in offsets)")
        agrees = "" if current == "(unnamed in offsets)" else f" [table says: {current}]"
        print(f"{name:28} kind {kind:<5} at {position}  d={distance}{agrees}")

    print("\n== suggested config ==", flush=True)
    for name, (kind, position, _) in found.items():
        print(f"  {name.split()[0].lower()}: kind {kind}, approach {position}")

    return "; ".join(
        f"{name.split()[0]}={kind}@{position}"
        for name, (kind, position, _) in found.items()
    )


if __name__ == "__main__":
    raise SystemExit(0 if run_drill(T17, t17_body, session=GameSession()) == "PASS" else 1)
