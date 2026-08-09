"""T52 — the manual survey: the user walks, the atlas records.

**Read-only as far as the world is concerned: no clicks, no movement, no
skills.** It talks in chat (the OK gate, coverage updates, the DONE line),
and chat types characters — so it is not literally send-free, and saying
so is cheaper than a reader discovering it. The user drives the character
throughout; the bot only records.

## Why a human walk at all

The automated survey exists (`runs/survey-*.toml`) and works; a human
with map knowledge and a kill button is simply FASTER over a hostile
area, and the user asked for exactly this (R177 follow-on, 2026-08-02).
The atlas cannot tell who did the walking: rooms record identically
either way, transient occupancy (monsters, corpses, items — and the
player) is stripped before saving, and a re-visited room replaces its
stored grid. Nothing about a manual survey can pollute the map.

## How it runs

1. The standard Drill Kit protocol: banner, instructions, then the OK
   gate — the recording starts when the user types **OK** in chat.
2. Once a second, whatever rooms the client has loaded are merged into
   the atlas (`maps/`, keyed by seed+difficulty+area — walking into the
   Den or Blood Moor mid-walk records under THAT area's file, which is
   a bonus rather than a problem).
3. Every ~45 s the drill answers back in chat: rooms recorded and
   frontier points still open for the area the user is standing in.
   "0 frontier open" means that area is done.
4. **The user types END when they believe they are done** (also: DONE).
   Abort words work throughout; `--seconds` is the wall-clock backstop.

## Advice for the walk (also said in chat)

- Movement is the whole job: the client loads rooms ~46-67 subtiles out
  (T51), so passing within ~40 of ground records it. Standing still
  records nothing new.
- Perimeter first, then rough lanes ~60-80 subtiles apart across the
  middle. Two sloppy passes beat one careful one.
- Kill only what bothers you; corpses and monsters are stripped from
  the stored grids either way.
- Walk INTO the pockets: dead ends, fenced yards, and especially the
  eastern pocket past the wall at x~5350 (the R174 dead zone) — ground
  behind walls only records if you stand near it.
"""

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.nav import survey  # noqa: E402
from pd2bot.nav.mapstore import MapStore  # noqa: E402
from pd2bot.nav.navigate import _record_visible_rooms  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.world import read_area, read_map_seed  # noqa: E402

DIFFICULTY = 2  # Hell — the only difficulty this character runs
POLL_S = 1.0
REPORT_EVERY_S = 45.0
SAY_PATIENCE_S = 2.5  # chat is a courtesy; the recording is the point
END_WORDS = frozenset({"end", "end test", "done"})
DEFAULT_SECONDS = 1800.0

T52 = Drill(
    test_id="T52",
    title="manual survey — you walk, the atlas records",
    kind="human calibration",
    sends_input=False,
    instructions=(
        "WALK THE AREA; the bot records the map once a second. You drive.",
        "Perimeter first, then lanes ~60-80 subtiles apart. Enter the pockets.",
        "Coverage is reported in chat every ~45s; 0 frontier = area done.",
        "TYPE 'END' IN CHAT WHEN YOU BELIEVE YOU ARE DONE (or 'done').",
        "Cancel any time: 'abort' in chat, or tools\\drill-cancel.ps1",
    ),
)


def t52_body(run: DrillRun, seconds: float = DEFAULT_SECONDS) -> str:
    session = run.session
    store = MapStore(REPO / "maps")
    started = time.monotonic()
    last_report = 0.0
    # (seed, area) -> rooms held when this walk first saw the area, so
    # the summary can say what THIS walk added rather than restating the
    # whole atlas.
    first_seen: dict[tuple[int, int], int] = {}
    ending = f"the {seconds:.0f}s backstop"

    while time.monotonic() - started < seconds:
        run.check_cancel()
        if run.heard(END_WORDS):
            ending = "the user typed END"
            break
        time.sleep(POLL_S)

        area = read_area(session)
        seed = read_map_seed(session)
        if area is None or seed is None:
            continue  # mid-transition; the walk goes on
        explored = store.open(seed, DIFFICULTY, area.level_no)
        first_seen.setdefault((seed, area.level_no), explored.room_count)
        _record_visible_rooms(session, store, DIFFICULTY)

        now = time.monotonic()
        if now - last_report >= REPORT_EVERY_S:
            last_report = now
            frontier = len(
                survey.frontier_targets(explored, area.bounds_subtiles)
            )
            run.say(
                f"area {area.level_no}: {explored.room_count} rooms, "
                f"{frontier} frontier open"
                + (". Looks done — END when ready." if frontier == 0 else "."),
                patience_s=SAY_PATIENCE_S,
            )

    if not first_seen:
        raise RuntimeError(
            "never saw a readable area — was a game running the whole time?"
        )

    parts = []
    for (seed, area_no), before in sorted(first_seen.items()):
        explored = store.open(seed, DIFFICULTY, area_no)
        # Frontier from the LEVEL bounds only makes sense for the area the
        # player is in (read live); for others report rooms alone.
        area = read_area(session)
        if area is not None and area.level_no == area_no:
            open_now = len(
                survey.frontier_targets(explored, area.bounds_subtiles)
            )
            parts.append(
                f"area {area_no}: {before}->{explored.room_count} rooms, "
                f"{open_now} frontier open"
            )
        else:
            parts.append(f"area {area_no}: {before}->{explored.room_count} rooms")
    summary = "; ".join(parts)
    print(f"\n  {summary}", flush=True)
    run.say(f"T52 DONE — {summary}. Atlas saved; you can stop.", patience_s=10.0)
    return f"stopped on {ending}; {summary}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="T52 — the manual survey")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    args = parser.parse_args()
    status = run_drill(
        T52,
        lambda run: t52_body(run, seconds=args.seconds),
        run=DrillRun(GameSession()),
    )
    raise SystemExit(0 if status == "PASS" else 1)
