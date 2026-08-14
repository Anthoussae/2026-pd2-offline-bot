"""A read-only recorder for HUMAN-played runs (R255).

The run event log is engine-tied: every event in it is emitted by the
bot's own tick loop, so a run the OPERATOR plays leaves no record at
all. This module closes that gap for the human-vs-bot Cold Plains speed
comparison — the operator plays, this watches, and both sides of the
diff end up in the same `logs/runs/` format the existing renderer and
tools already read.

**It cannot act, by construction.** Nothing here imports an input class:
the module opens a `GameSession` (pymem reads), takes `Perception`
snapshots on a timer, and writes a `RunLog`. There is no `GatedInput`,
no `MenuInput`, no `Chat`, no watchdog — a process with no send path
needs no guard against sending. The precedents are the watchdog and the
atlas's passive room recorder: independent processes that observe the
same game the bot plays.

What it records, at `interval_s` (default 4 Hz):

- `observe.sample` — the same fields the engine's `tick` events carry
  (world position, hp/mana, hostile and ground-item counts), so one
  reducer (`pd2bot.runlog.compare`) reads both logs without caring who
  played.
- `observe.area` — area transitions, the phase boundaries of the diff.
- `observe.kill` — a hostile seen alive turns up dead. Deaths are
  detected through the corpse list (a dead monster ROUTES to `corpses`,
  snapshot.py), never through disappearance — a monster that walks out
  of scan range is not a kill.
- `observe.pickup` — a ground item vanishes while the player stands
  within `pickup_radius` of where it lay. The radius is what separates
  a pickup from a room unloading behind the player (the client keeps a
  ~3x3 room neighbourhood; items beyond it vanish from perception).

The recording starts when the operator enters a game and ends when they
leave it — save-and-exit is the natural stop button. Backstops: the
drill-cancel file (`tools\\drill-cancel.ps1`, the standing abort kit)
and a hard duration cap. A torn read mid-transition must not end a
recording, so "left the game" means several CONSECUTIVE out-of-game
reads, not one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pd2bot import offsets

# 4 Hz: comfortably above the engine's ~0.66 ticks/s baseline log, cheap
# (a snapshot costs ~16 ms), and fine enough that a 1 s idle span is
# four identical samples rather than a rounding artifact.
DEFAULT_INTERVAL_S = 0.25
# A human picking an item stands next to it when it leaves the floor
# (the click walks them adjacent first). 8 subtiles is generous for that
# and far inside the ~46-subtile unload horizon (T51) that also makes
# items vanish.
PICKUP_RADIUS = 8
# Consecutive not-in-game snapshots before the recording ends. At 4 Hz
# this is ~0.75 s — longer than any torn read, shorter than a real exit
# could ever be reversed.
EXIT_READS = 3


@dataclass
class RunObserver:
    """The pure diffing core: fed snapshots, emits events, sends nothing.

    Separated from the live loop so every detection rule is unit-testable
    with hand-built snapshots — the same split survey.py uses.
    """

    sink: object  # RunLog-shaped: .area(id, name), .event(kind, **fields)
    pickup_radius: int = PICKUP_RADIUS
    exit_reads: int = EXIT_READS
    _area: int | None = None
    _hostiles: dict = field(default_factory=dict)  # unit_id -> (kind, position)
    _ground: dict = field(default_factory=dict)  # unit_id -> (kind, position)
    _out_of_game: int = 0

    def observe(self, snap) -> bool:
        """Record one snapshot. Returns False when the run is over."""
        if not snap.in_game:
            self._out_of_game += 1
            return self._out_of_game < self.exit_reads
        self._out_of_game = 0
        if snap.player is None or snap.area is None:
            # Mid-load: in a game but the world chain is torn. Nothing to
            # record, and nothing to conclude either.
            return True
        self._note_area(snap)
        self._note_kills(snap)
        self._note_pickups(snap)
        self.sink.event(
            "observe.sample",
            player={"world": list(snap.player.position)},
            hp=snap.player.hp,
            max_hp=snap.player.max_hp,
            mana=snap.player.mana,
            max_mana=snap.player.max_mana,
            hostiles=len(snap.live_monsters),
            ground_items=len(snap.ground_items),
            allies=len(snap.allies),
        )
        return True

    def _note_area(self, snap) -> None:
        level = snap.area.level_no
        if level == self._area:
            return
        name = offsets.AREA_NAMES.get(level, f"area {level}")
        self.sink.area(level, name)
        self.sink.event(
            "observe.area",
            entered=level,
            entered_name=name,
            left=self._area,
        )
        self._area = level
        # Unit ids are per-area state: carrying them across a transition
        # would let an id reused by the new area read as a kill or a
        # pickup that never happened.
        self._hostiles.clear()
        self._ground.clear()

    def _note_kills(self, snap) -> None:
        corpse_ids = {c.unit_id for c in snap.corpses}
        for unit_id, (kind, position) in list(self._hostiles.items()):
            if unit_id in corpse_ids:
                self.sink.event(
                    "observe.kill",
                    unit_id=unit_id,
                    monster_kind=kind,
                    at_position=list(position),
                )
                del self._hostiles[unit_id]
        for monster in snap.live_monsters:
            self._hostiles[monster.unit_id] = (monster.kind, monster.position)
        # A hostile that simply vanished (out of scan range) stays in the
        # book — if the player circles back and kills it, the corpse
        # check above still catches it; if not, it was never a kill.

    def _note_pickups(self, snap) -> None:
        current = {item.unit_id for item in snap.ground_items}
        px, py = snap.player.position
        for unit_id, (kind, (ix, iy)) in list(self._ground.items()):
            if unit_id in current:
                continue
            if max(abs(px - ix), abs(py - iy)) <= self.pickup_radius:
                self.sink.event(
                    "observe.pickup",
                    unit_id=unit_id,
                    item_kind=kind,
                    at_position=[ix, iy],
                )
            del self._ground[unit_id]
        for item in snap.ground_items:
            self._ground[item.unit_id] = (item.kind, item.position)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - live only
    import argparse
    import sys
    from pathlib import Path

    from pd2bot.drill import CANCEL_FILE, clear_cancel
    from pd2bot.perception.memory import (
        GameNotRunning,
        GameSession,
        NeedsAdministrator,
    )
    from pd2bot.perception.player import read_player
    from pd2bot.perception.snapshot import Perception
    from pd2bot.perception.world import read_map_seed
    from pd2bot.runlog import RunLog

    parser = argparse.ArgumentParser(
        description="Record a HUMAN-played run, read-only: no input is ever sent."
    )
    parser.add_argument(
        "--name", default="human-coldplains",
        help="run-directory suffix (default: human-coldplains)",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL_S,
        help="seconds between snapshots (default 0.25)",
    )
    parser.add_argument(
        "--max-minutes", type=float, default=30.0,
        help="hard stop, in case the recording is forgotten (default 30)",
    )
    args = parser.parse_args(argv)

    try:
        session = GameSession()
    except (GameNotRunning, NeedsAdministrator) as exc:
        print(exc, file=sys.stderr)
        return 1
    perception = Perception(session)

    if CANCEL_FILE.exists():
        clear_cancel()
        print("note: cleared a stale drill-cancel file before recording")

    print("read-only recorder: waiting for you to enter a game (Ctrl+C or")
    print("tools\\drill-cancel.ps1 aborts; leaving the game ends it cleanly)")
    while True:
        if CANCEL_FILE.exists():
            print("cancelled before a game was entered; nothing recorded")
            return 0
        try:
            if perception.snapshot().in_game:
                break
        except Exception:  # noqa: BLE001 - keep waiting through torn reads
            pass
        time.sleep(0.5)

    header: dict = {"recorder": "human-observer", "interval_s": args.interval}
    try:
        header["map_seed"] = read_map_seed(session)
        player = read_player(session)
        if player is not None:
            header["character"] = player.name
            header["level"] = player.level
    except Exception:  # noqa: BLE001 - honest absence, never a guess
        header.setdefault("map_seed", None)
    runlog = RunLog(args.name, root=Path("logs") / "runs", header=header)
    observer = RunObserver(runlog)
    print(f"recording -> {runlog.directory}")

    started = time.monotonic()
    ending = "left the game"
    read_failures = 0
    try:
        while True:
            if CANCEL_FILE.exists():
                ending = "cancelled (drill-cancel file)"
                break
            if time.monotonic() - started > args.max_minutes * 60:
                ending = f"duration cap ({args.max_minutes:g} min)"
                break
            try:
                snap = perception.snapshot()
            except Exception as exc:  # noqa: BLE001 - record, never crash
                read_failures += 1
                if read_failures == 1:
                    runlog.event("observe.read_failed", error=str(exc))
                time.sleep(args.interval)
                continue
            read_failures = 0
            if not observer.observe(snap):
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        ending = "Ctrl+C"
    runlog.close(ending=ending)
    print(f"recording ended ({ending}): {runlog.directory}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
