"""Walking the character along a planned path, and noticing when reality
disagrees.

The loop per waypoint is simple on purpose (mined from kolbot's Pather and
trimmed to M3 scope): click the waypoint through the gate, watch the
player's position, and escalate when it stops changing — first re-click,
then re-plan from where we actually are, then give up loudly with a typed
error. M4's game-cycle logic consumes that error; M3 does not try to fight
monsters, open doors, or dismiss panels (if a panel blocks input, something
outside the bot's M3 world happened — we wait briefly, then report).

All timing is injectable so the whole state machine is testable with a
scripted fake; no unit test here touches the game or the clock.

    python -m pd2bot.navigate --to X Y     walk to a world subtile
    python -m pd2bot.navigate --demo       out-and-back acceptance walk
    python -m pd2bot.navigate --survey     record rooms while YOU walk (no clicks)

Map knowledge comes from two layers: the live room grids around the player
(ground truth, always) over the explored-map atlas (`mapstore.py`) — every
walk, surveyed or bot-driven, grows the atlas, and single-player maps never
change, so the atlas never goes stale.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot.input import GatedInput, InputRefused
from pd2bot.pathing import Grid, Point, astar, nearest_walkable, simplify

# Move speed varies a lot in play (run vs walk, boots, chill, Holy Freeze),
# so none of these thresholds may assume a pace. Stuck detection is
# *cumulative zero-movement* — `last_position` only advances after a full
# subtile of drift, so slow-but-steady still reads as moving — and the
# give-up counter resets whenever a plan cycle gets meaningfully closer to
# the goal, so "slow" can never add up to "failed"; only "no progress" can.
ARRIVAL_RADIUS = 3  # subtiles: close enough to call a waypoint done
STUCK_SECONDS = 1.5  # zero cumulative movement for this long = stuck
STUCK_EPSILON = 1  # the drift (in subtiles) that counts as movement
POLL_SECONDS = 0.1
UI_WAIT_TIMEOUT = 10.0  # how long we tolerate a blocking panel before failing
WAYPOINT_TIMEOUT = 20.0  # hard per-waypoint cap, whatever else happens
# A travel click landing near an interactive unit INTERACTS instead of
# moving: an NPC opens their dialog, the town waypoint opens its menu (R68,
# and live again in T27/R111 — Akara's approach passes the waypoint at the
# same y, so every retry re-clicked it). Clicks aimed within this many
# subtiles of a known interactive thing are nudged away before being sent.
AVOID_RADIUS = 4
AVOID_MARGIN = 2  # how far beyond the radius the nudged click lands
# How many times a click may be pushed before we settle for the roomiest
# spot found. Bounded because a ring of hazards has no clear point at
# all, and an unbounded search there would spin instead of walking.
MAX_NUDGES = 8
MAX_FAILURES = 5  # consecutive no-progress plan cycles before giving up
PROGRESS_RESET = 3.0  # subtiles closer to the goal that make a cycle "progress"


class NavigationError(RuntimeError):
    """Walking failed in a way retrying won't fix; details in the message."""


@dataclass
class WalkResult:
    """What actually happened, for logs and acceptance records."""

    target: Point
    arrived_at: Point
    duration_seconds: float
    waypoints: int
    clicks: int = 0
    reclicks: int = 0
    replans: int = 0
    log: list[str] = field(default_factory=list)


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Navigator:
    """Plans over a grid and follows the plan with gated clicks.

    `grid_provider` returns the freshest grid on every call — re-planning
    must see what perception sees *now*, not what it saw at start. In M3
    that is the live stitched collision over the explored-map atlas (see
    the CLI at the bottom).
    """

    def __init__(
        self,
        position_reader: Callable[[], Point | None],
        gated_input: GatedInput,
        grid_provider: Callable[[], Grid],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        avoid_provider: Callable[[], tuple[Point, ...]] | None = None,
    ) -> None:
        self._position = position_reader
        self._input = gated_input
        self._grid_provider = grid_provider
        self._clock = clock
        self._sleep = sleep
        # Where the clickable hazards are RIGHT NOW (NPCs pace), or None for
        # environments with nothing interactive to hit (tests, open field).
        self._avoid = avoid_provider
        # The destination of the walk in flight, so `_safe_click_point`
        # can tell a hazard we are deliberately approaching from one we
        # merely happen to pass. Set per walk_to, cleared after.
        self._goal: Point | None = None

    # -- pieces ---------------------------------------------------------------

    @property
    def window(self):
        """The game window, for callers that need to focus it first."""
        return self._input.window

    def grid(self) -> Grid:
        """The current map knowledge, freshly assembled."""
        return self._grid_provider()

    def position(self) -> Point:
        """Where the player is, or `NavigationError` if we cannot tell."""
        position = self._position()
        if position is None:
            raise NavigationError("player position unreadable — left the game?")
        return position

    def _click(self, waypoint: Point, result: WalkResult) -> None:
        """One gated click, waiting out a briefly-blocking UI panel."""
        deadline = self._clock() + UI_WAIT_TIMEOUT
        while True:
            try:
                self._input.click_world(*waypoint)
                result.clicks += 1
                return
            except InputRefused as refused:
                if self._clock() >= deadline:
                    raise NavigationError(
                        f"input stayed refused for {UI_WAIT_TIMEOUT}s: {refused}"
                    ) from refused
                self._sleep(POLL_SECONDS)

    def _safe_click_point(self, waypoint: Point, result: WalkResult) -> Point:
        """Nudge a travel click off anything interactive near it.

        The click's only job is to make the character walk that way; landing
        a few subtiles off costs nothing (the loop re-plans freely), while
        landing ON a unit costs the whole walk — the dialog or menu it opens
        blocks all further input (R68/R111). So the trade is always worth it.
        The character's own arrival is unaffected: this adjusts clicks, and
        arrival is judged by position.
        """
        if self._avoid is None:
            return waypoint
        hazards = self._avoid()
        # A hazard AT THE DESTINATION is not a hazard — it is the
        # destination. Ground items became travel-click hazards so that a
        # stray click would not scoop the junk the cleanse had just dropped,
        # and that immediately broke the opposite case: `collect` walks to an
        # item's exact position to get in range, every travel click was
        # nudged off the very thing it was walking to, and the bot could
        # never reach anything it wanted. Stage B run 6 died on it, stuck
        # 12 subtiles from a target with a hazard sitting on it.
        #
        # Deliberate approach is distinguishable from an accidental pass:
        # the goal is what the caller ASKED for. Anything else nearby is
        # still avoided.
        if self._goal is not None:
            hazards = tuple(
                h for h in hazards
                if max(abs(h[0] - self._goal[0]), abs(h[1] - self._goal[1]))
                >= AVOID_RADIUS
            )
        if not hazards:
            return waypoint

        def clearance(point: Point) -> int:
            """Distance to the nearest hazard; bigger is safer."""
            return min(
                (max(abs(point[0] - ax), abs(point[1] - ay)) for ax, ay in hazards),
                default=AVOID_RADIUS,
            )

        # Nudge, then LOOK AGAIN. The old version applied every hazard in one
        # pass and never re-checked, so each push could land the click inside
        # the next hazard and the last one silently won. In Cold Plains that
        # walked the click in a circle — (5218,5664) -> (5217,5667) ->
        # (5220,5670) -> (5216,5674) — and back onto the character, who then
        # never moved and failed the walk as "stuck".
        best = waypoint
        current = waypoint
        for _ in range(MAX_NUDGES):
            offender = next(
                (
                    (ax, ay)
                    for ax, ay in hazards
                    if max(abs(current[0] - ax), abs(current[1] - ay)) < AVOID_RADIUS
                ),
                None,
            )
            if offender is None:
                return current  # clear of everything
            if clearance(current) > clearance(best):
                best = current
            ax, ay = offender
            dx, dy = current[0] - ax, current[1] - ay
            span = max(abs(dx), abs(dy))
            if span == 0:
                dx, dy, span = 1, 1, 1  # dead centre: any direction will do
            push = AVOID_RADIUS + AVOID_MARGIN
            current = (round(ax + dx / span * push), round(ay + dy / span * push))
            result.log.append(
                f"click nudged off interactive unit at ({ax}, {ay}): "
                f"{waypoint} -> {current}"
            )
        # Boxed in. Send the roomiest candidate rather than giving up: one
        # click that might interact is recoverable (the loop re-plans, panels
        # get closed), whereas refusing to click is a walk that cannot finish.
        best = max((best, current), key=clearance)
        result.log.append(f"no clear click near {waypoint}; using {best}")
        return best

    def _walk_one_waypoint(self, waypoint: Point, result: WalkResult) -> bool:
        """Walk until inside the arrival radius. True on arrival, False when
        stuck (caller decides whether to re-plan)."""
        self._click(self._safe_click_point(waypoint, result), result)
        waypoint_deadline = self._clock() + WAYPOINT_TIMEOUT
        last_position = self.position()
        last_moved = self._clock()
        reclicked = False

        while True:
            self._sleep(POLL_SECONDS)
            position = self.position()
            now = self._clock()

            if _distance(position, waypoint) <= ARRIVAL_RADIUS:
                return True
            if _distance(position, last_position) >= STUCK_EPSILON:
                last_position, last_moved = position, now
                continue
            if now - last_moved >= STUCK_SECONDS or now >= waypoint_deadline:
                if not reclicked and now < waypoint_deadline:
                    # First escalation: the click may simply not have taken.
                    reclicked = True
                    result.reclicks += 1
                    result.log.append(f"re-click at {position} toward {waypoint}")
                    self._click(self._safe_click_point(waypoint, result), result)
                    last_moved = self._clock()
                    continue
                result.log.append(f"stuck at {position} toward {waypoint}")
                return False

    # -- the public act ---------------------------------------------------------

    def walk_to(self, target: Point) -> WalkResult:
        self._goal = target
        try:
            return self._walk_to(target)
        finally:
            self._goal = None

    def _walk_to(self, target: Point) -> WalkResult:
        started = self._clock()
        result = WalkResult(
            target=target, arrived_at=(0, 0), duration_seconds=0.0, waypoints=0
        )

        failures = 0
        best_remaining: float | None = None
        while True:
            grid = self._grid_provider()
            start = self.position()
            goal = nearest_walkable(grid, *target)
            if goal is None:
                # "No walkable cell" has two very different causes, and the
                # caller needs to know which: solid wall, or terra incognita.
                known = grid.is_known(*target)
                raise NavigationError(
                    f"no walkable cell near {target}: "
                    + (
                        "the area is known but solidly blocked there"
                        if known
                        else "that ground has never been seen — survey it first "
                        "(unknown ground is treated as blocked on purpose)"
                    )
                )
            path = astar(grid, start, goal)
            if path is None:
                raise NavigationError(f"no path from {start} to {goal}")
            waypoints = simplify(grid, path)
            result.waypoints = len(waypoints)
            result.log.append(f"planned {len(path)} cells -> {len(waypoints)} waypoints")

            arrived = True
            # waypoints[0] is where we stand; there is nothing to click there.
            for waypoint in waypoints[1:]:
                if not self._walk_one_waypoint(waypoint, result):
                    arrived = False
                    break

            position = self.position()
            if arrived and _distance(position, goal) <= ARRIVAL_RADIUS:
                result.arrived_at = position
                result.duration_seconds = self._clock() - started
                return result

            # A cycle that got meaningfully closer is progress, however slow
            # (chill, Holy Freeze, walking): reset the counter. Only cycles
            # that gain nothing count toward giving up.
            remaining = _distance(position, goal)
            if best_remaining is None or best_remaining - remaining >= PROGRESS_RESET:
                if best_remaining is not None:
                    failures = 0
                best_remaining = remaining

            failures += 1
            if failures >= MAX_FAILURES:
                raise NavigationError(
                    f"gave up after {failures} plan cycles without progress; "
                    f"last position {position}, target {goal}; "
                    f"log: {'; '.join(result.log[-5:])}"
                )
            result.replans += 1
            result.log.append(f"re-planning from {position} ({failures} no-progress cycles)")


# --- CLI: the acceptance-walk tool -------------------------------------------


def pick_reachable_target(
    grid: Grid, start: Point, distance: int = 60, minimum: int = 25
) -> tuple[Point | None, int]:
    """Find somewhere genuinely walkable about `distance` subtiles away.

    A fixed offset is no good for a demo: it lands in unseen ground or
    inside a wall as often as not, and fails before the navigator gets to
    show anything. This sweeps 16 directions, preferring the furthest
    distance that yields a cell which is known, walkable, and actually
    reachable (A* agrees) — so a failure afterwards is a real one.
    """
    for radius in range(distance, minimum - 1, -5):
        for index in range(16):
            angle = 2 * math.pi * index / 16
            candidate = (
                start[0] + round(math.cos(angle) * radius),
                start[1] + round(math.sin(angle) * radius),
            )
            if not (grid.is_known(*candidate) and grid.is_walkable(*candidate)):
                continue
            if astar(grid, start, candidate) is not None:
                return candidate, radius
    return None, 0


def _record_visible_rooms(session, store, difficulty: int, stats: dict | None = None) -> int:
    """Merge whatever rooms are loaded right now into the atlas."""
    from pd2bot.collision import read_local_collision
    from pd2bot.world import read_area, read_map_seed

    area = read_area(session)
    seed = read_map_seed(session)
    if area is None or seed is None:
        return 0
    local = read_local_collision(session)
    per_area = None if stats is None else stats.setdefault(
        (seed, area.level_no), {"added": 0, "updated": 0}
    )
    return store.open(seed, difficulty, area.level_no).record(local, per_area)


def live_navigator(session, store, difficulty: int = 2) -> Navigator:
    """Wire the navigator to the live game: positions from memory, clicks
    through the gate, and on every (re-)plan the explored-map atlas under
    the live room grids (live is ground truth where loaded). The position
    reader doubles as the recorder: roughly once a second while walking,
    the rooms currently in view are merged into the atlas — so the bot
    surveys as a side effect of going anywhere.

    Public because everything above navigation needs this exact wiring:
    the M3 CLI, M5's town drills, and P4's behaviour engine."""
    from pd2bot import offsets
    from pd2bot.collision import read_local_collision
    from pd2bot.pathing import OverlayGrid
    from pd2bot.units import player_unit, unit_position
    from pd2bot.world import read_area, read_map_seed

    polls_between_records = max(1, round(1.0 / POLL_SECONDS))
    poll_count = 0

    def position() -> Point | None:
        nonlocal poll_count
        poll_count += 1
        if poll_count % polls_between_records == 0:
            _record_visible_rooms(session, store, difficulty)
        unit = player_unit(session)
        if unit is None:
            return None
        return unit_position(session, unit, offsets.UNIT_TYPE_PLAYER)

    def grid() -> Grid:
        live = read_local_collision(session)
        area = read_area(session)
        seed = read_map_seed(session)
        if area is None or seed is None:
            return live
        explored = store.open(seed, difficulty, area.level_no)
        explored.record(live)
        return OverlayGrid(base=explored, overlay=live)

    def clickable_hazards() -> tuple[Point, ...]:
        """Everything a travel click must not land on, where it is NOW.

        Read fresh per click because NPCs pace. Corpses are excluded —
        nothing opens — and monsters are deliberately NOT avoided: outside
        town a click near a monster is at worst an attack, and dodging every
        hostile would make Cold Plains unwalkable.

        Two narrowings, both paid for live in stage B's third attempt:

        **Objects** are filtered to `INTERACTIVE_OBJECT_KINDS`. Avoiding all
        of them treated 15 pieces of decorative Cold Plains scenery as
        hazards and made the area unwalkable. The same reasoning that
        excludes monsters excludes scenery: avoiding what cannot punish a
        click costs mobility for nothing.

        **Allies are avoided in town only.** The hazard this rule was
        written for is a town NPC's dialog (R66/R78 — T12 opened Kashya's
        chat with its travel clicks and looped). Outside town every ally is
        the merc or a summon, and clicking one opens nothing at all — while
        a necro at work is permanently surrounded by seven of them, exactly
        when movement matters most. (An ally NPC standing in the field would
        need this revisited; none exists on the Cold Plains route. Worth a
        look when M6 adds areas.)
        """
        from pd2bot.snapshot import Perception

        try:
            snap = Perception(session).snapshot()
        except Exception:
            return ()  # unreadable mid-load: no avoidance beats no walk
        points = [
            o.position
            for o in snap.objects
            if o.kind in offsets.INTERACTIVE_OBJECT_KINDS
        ]
        # Ground items, because clicking one PICKS IT UP. That is the same
        # hazard class — a travel click doing something other than moving —
        # and it produced a loop the user watched in stage B run 4: the
        # cleanse drops junk at the character's feet, the next travel click
        # lands on it, and the junk comes straight back into the inventory
        # to be cleansed again. Deliberate pickups are unaffected; they go
        # through the executor's own click, not the navigator.
        points += [i.position for i in snap.ground_items]
        if snap.in_town:
            points += [a.position for a in snap.allies if a.is_alive]
        return tuple(points)

    return Navigator(
        position_reader=position,
        gated_input=GatedInput(session),
        grid_provider=grid,
        avoid_provider=clickable_hazards,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from pd2bot.mapstore import DEFAULT_ROOT, MapStore
    from pd2bot.memory import GameNotRunning, GameSession, NeedsAdministrator
    from pd2bot.window import WindowNotFound

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--to", nargs=2, type=int, metavar=("X", "Y"))
    group.add_argument(
        "--demo",
        action="store_true",
        help="acceptance walk: 60 subtiles out, then back to the start",
    )
    group.add_argument(
        "--survey",
        action="store_true",
        help="record rooms into the atlas while you walk; sends no input",
    )
    parser.add_argument("--maps", default=DEFAULT_ROOT, help="atlas directory")
    parser.add_argument("--difficulty", type=int, default=2, help="0/1/2, default hell")
    parser.add_argument(
        "--distance", type=int, default=60, help="demo: how far to walk (subtiles)"
    )
    args = parser.parse_args(argv)

    store = MapStore(args.maps)

    try:
        session = GameSession()
    except (GameNotRunning, NeedsAdministrator) as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.survey:
        import time as clock

        from pd2bot import offsets

        print("surveying — walk around; Ctrl+C to stop. No input is sent.")
        recorded = 0
        stats: dict = {}
        try:
            while True:
                recorded += _record_visible_rooms(session, store, args.difficulty, stats)
                print(f"\r  rooms recorded/updated this session: {recorded}   ", end="")
                clock.sleep(0.5)
        except KeyboardInterrupt:
            print(f"\nsurvey ended; {recorded} room grids recorded/updated\n")
            # Broken down per area, because walking between areas records
            # each of them — which looks like churn if you only see a total.
            for (seed, area_id), counts in sorted(stats.items()):
                added, updated = counts.get("added", 0), counts.get("updated", 0)
                if not (added or updated):
                    continue
                print(f"  seed {seed:08x} area {area_id}: {added} new, {updated} re-recorded")
                bits = counts.get("bits", {})
                if not bits:
                    continue
                # Re-recording means stored terrain changed. Name the bits so
                # a wrongly-persistent flag is identified, not guessed at.
                print("    bits that changed on re-record (cells affected):")
                for bit, count in sorted(bits.items(), key=lambda kv: -kv[1]):
                    name = offsets.COLL_FLAG_NAMES.get(bit, "unknown")
                    transient = " [should have been stripped!]" if (
                        bit & offsets.COLL_TRANSIENT_MASK
                    ) else ""
                    print(f"      0x{bit:04X} {name:<14} {count:>7}{transient}")
            return 0

    try:
        navigator = live_navigator(session, store, args.difficulty)
    except WindowNotFound as exc:
        print(exc, file=sys.stderr)
        return 1

    if not navigator.window.bring_to_foreground():
        print("could not foreground the game window", file=sys.stderr)
        return 1

    def run(target: Point) -> bool:
        print(f"walking to {target} ...")
        try:
            result = navigator.walk_to(target)
        except NavigationError as error:
            print(f"FAILED: {error}", file=sys.stderr)
            return False
        print(
            f"arrived at {result.arrived_at} in {result.duration_seconds:.1f}s — "
            f"{result.waypoints} waypoints, {result.clicks} clicks, "
            f"{result.reclicks} re-clicks, {result.replans} re-plans"
        )
        for line in result.log:
            print(f"  {line}")
        return True

    start = navigator.position()
    if args.to:
        return 0 if run((args.to[0], args.to[1])) else 1

    # Report what the bot actually knows before it tries anything: a demo
    # that fails because it is standing in unsurveyed ground should say so,
    # not look like a navigation bug.
    grid = navigator.grid()
    known_bounds = getattr(grid, "bounds", None)
    print(f"standing at {start}; map knowledge bounds {known_bounds}")

    out, radius = pick_reachable_target(grid, start, args.distance)
    if out is None:
        print(
            f"no reachable target between 25 and {args.distance} subtiles away.\n"
            "Either this ground has not been surveyed, or you are boxed in. "
            "Run `--survey` and walk the area first.",
            file=sys.stderr,
        )
        return 1

    print(f"demo: {start} -> {out} ({radius} subtiles away) -> back")
    ok = run(out) and run(start)
    print("demo:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
