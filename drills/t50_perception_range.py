"""T50 — how far can the bot actually SEE? Calibrate perception range.

**Read-only. Sends nothing — no clicks, no keys, not even chat.**

## Why this exists

The bot's perception radius is `units.PERCEPTION_RADIUS = 80` subtiles, and
every sizing argument in M5 has been built on top of two claims about it
that were never measured:

1. *"80 subtiles is over three screens"* — used to justify the clearance
   verifying a radius-50 circle from a standstill, and derived from R147's
   *"a screen is ~24 subtiles"*, which is itself unsourced. Worse, it is
   ambiguous: 24 subtiles of screen WIDTH and 24 subtiles of screen
   HALF-extent differ by a factor of two, and the patrol's whole sizing
   table (`docs/plans/2026-08-01-patrol-clearance/notes.md`) reads as if it
   means half-extent while the words say width.

2. *"raising the radius would let the sweep see the whole circle"* — which
   assumes OUR filter is the binding constraint. It may not be. `scan_units`
   walks the client's unit hash table and drops everything outside `radius`,
   but the client only populates that table with units in rooms it has
   loaded. If the client's own horizon is nearer than 80, raising our number
   buys nothing at all and the honest fix is to walk further.

Both claims are checkable without sending a single input, which is what
this drill does.

## What it measures

**Part A — the screen, by arithmetic.** The live client rect plus the
live-calibrated projection constants (`screen.py`: 20 px per subtile in x,
10 in y, measured over 12 walks in T-M3) fully determine which world
offsets are on screen. A point at world offset (dx, dy) lands at pixel
offset (20*(dx-dy), 10*(dx+dy)), so the visible set is

    |dx - dy| <= half_width / 20      and      |dx + dy| <= half_height / 10

which is a diamond in world space, NOT a circle — so "how many subtiles is
a screen" has a different answer per direction, and reporting one number
was always going to mislead. This prints the extent along each of the eight
compass directions the patrol ring uses.

**Part B — the unit horizon, by observation.** Scan at a ladder of radii
and watch where the counts stop growing. A plateau well below the largest
radius means the CLIENT is the limit and `PERCEPTION_RADIUS` is not; counts
still climbing at the top means our filter is genuinely cutting off units
the client was willing to tell us about.

Reported per radius: unit counts by category, the furthest thing seen, and
the wall-clock cost of the scan (the R23 objection to a bigger radius was
cost, and cost is measurable).

**Part C — the far field.** At an effectively unlimited radius, a distance
histogram of everything the hash table holds. This is what R23 is about:
the table contains the stash and units from other levels, so distant rows
here are expected to be junk. If they are NOT junk — if there is a
continuous population out to 200 subtiles — then the horizon is far larger
than assumed and the only thing hiding it is our own constant.

## How to read the result

* Part B plateaus below 80  -> the client is the bound. Raising
  `PERCEPTION_RADIUS` is pointless; covering ground needs a patrol.
* Part B still climbing at 320 -> our filter is the bound. Raising it is a
  real option, priced by the timing column.
* Part C far rows are all one area/level or at absurd distances -> R23's
  reasoning holds and the radius must stay a radius.

## Running it

Stand somewhere with monsters and items around — Cold Plains after the
waypoint is exactly right, ideally without having killed everything first.
Town works for Parts A and C but tells you little about B: the Rogue
Encampment population is sparse and static.

    python drills/t50_perception_range.py
"""

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot import screen  # noqa: E402
from pd2bot.drill import Drill, DrillRun, run_drill  # noqa: E402
from pd2bot.perception.memory import GameSession  # noqa: E402
from pd2bot.perception.snapshot import Perception  # noqa: E402
from pd2bot.perception.units import PERCEPTION_RADIUS, scan_units  # noqa: E402
from pd2bot.window import GameWindow  # noqa: E402

T50 = Drill(
    test_id="T50",
    title="perception range — how far can the bot actually see?",
    kind="perception",
    sends_input=False,
    instructions=(
        "Go somewhere with monsters, then STAND STILL for 5 seconds.",
        "It will not measure until a monster is genuinely on screen AND you",
        "  have stopped moving — the town run proved a static scan of an",
        "  empty area cannot tell a horizon from a small room.",
        "The bot only READS memory: no clicks, no keys, nothing moves.",
        "Cancel any time: powershell -File tools\\drill-cancel.ps1",
    ),
)

# The ladder. 80 is today's value; the rest bracket it far enough on both
# sides that a plateau is unmistakable rather than a matter of judgement.
RADII = (12, 24, 48, 80, 120, 160, 240, 320)
# Big enough that `near()` accepts everything the hash table holds without
# needing a separate unfiltered code path — the point is to exercise the
# SAME function, so Part C cannot disagree with Part B for a silly reason.
UNLIMITED = 1_000_000
# Repeats per radius, so the timing column is not one sample of a number
# that competes with a game loop for the same memory.
SAMPLES = 3
# The eight directions the patrol ring uses, as unit vectors in world space.
COMPASS = (
    ("E  (+x)", 1, 0),
    ("SE", 1, 1),
    ("S  (+y)", 0, 1),
    ("SW", -1, 1),
    ("W  (-x)", -1, 0),
    ("NW", -1, -1),
    ("N  (-y)", 0, -1),
    ("NE", 1, -1),
)


def _chebyshev(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


# -- arming -------------------------------------------------------------------

# The user's condition, and it is the right one: the town run measured
# nothing about the horizon because the whole town population sat inside 57
# subtiles, so the plateau could equally have meant "the area is this small".
# The field run must not be allowed to conclude before it is actually
# looking at a field.
STILL_S = 5.0  # how long the player must not move before measuring
STILL_EPSILON = 1  # subtiles of drift that still count as standing still
ARM_TIMEOUT_S = 600.0
ARM_POLL_S = 0.5


def _on_screen(session, position: tuple[int, int], origin: tuple[int, int]) -> bool:
    """Is this world position actually DRAWN right now?

    Uses the same projection Part A measures with, rather than a distance
    threshold, because the visible region is a diamond: a monster 30
    subtiles due east is on screen and one 30 subtiles south-east is not.
    "On screen" is the user's condition, so it is worth answering exactly.
    """
    try:
        rect = GameWindow(session.process_id).client_rect()
    except Exception:  # noqa: BLE001 - fall back to the honest approximation
        return _chebyshev(position, origin) <= 19
    projection = screen.Projection(player_world=origin, screen_center=rect.center)
    return rect.contains(*projection.world_to_screen(*position))


def wait_until_armed(run: DrillRun) -> str:
    """Hold until there is a monster on screen and the player has stood still.

    Both halves matter and for different reasons. The monster is what makes
    the measurement mean anything. The stillness is what makes it a
    measurement at all: the scan ladder takes several seconds, and a player
    walking through it would change the answer between the first radius and
    the last, which would look exactly like a horizon.
    """
    session = run.session
    deadline = time.monotonic() + ARM_TIMEOUT_S
    still_since: float | None = None
    last_position: tuple[int, int] | None = None
    last_report = 0.0
    said_armed = False

    while time.monotonic() < deadline:
        run.check_cancel()
        time.sleep(ARM_POLL_S)
        snap = Perception(session).snapshot()
        if snap.player is None:
            continue
        here = snap.player.position
        on_screen = [
            m for m in snap.live_monsters if _on_screen(session, m.position, here)
        ]

        moved = (
            last_position is None
            or _chebyshev(here, last_position) > STILL_EPSILON
        )
        if moved:
            still_since = None
            last_position = here
        elif still_since is None:
            still_since = time.monotonic()

        held = 0.0 if still_since is None else time.monotonic() - still_since
        if on_screen and held >= STILL_S:
            print(
                f"  ARMED at {here}: {len(on_screen)} monster(s) on screen, "
                f"still for {held:.1f}s.\n"
            )
            run.say(f"Armed — {len(on_screen)} monster(s) on screen. Hold still.")
            return f"{len(on_screen)} monster(s) on screen at {here}"

        now = time.monotonic()
        if now - last_report >= 10.0:
            last_report = now
            need = []
            if not on_screen:
                need.append("a monster on screen")
            if held < STILL_S:
                need.append(f"{STILL_S - held:.0f}s more standing still")
            print(
                f"  waiting at {here}: need {' and '.join(need)} "
                f"({len(snap.live_monsters)} live monster(s) in perception)",
                flush=True,
            )
            if not said_armed:
                run.say(f"Waiting for {' and '.join(need)}.")
                said_armed = True

    raise RuntimeError(
        f"never armed: no monster came on screen with the player standing "
        f"still for {STILL_S}s within {ARM_TIMEOUT_S:.0f}s"
    )


def screen_extent(session) -> tuple[int, int] | None:
    """Part A — how much world the window shows, per direction.

    Pure arithmetic over the live client rect: nothing is read from the
    game world, so this half of the drill is valid even standing in town.
    Returns (nearest edge, furthest edge) in subtiles.
    """
    print("== Part A — the screen, by arithmetic ==\n")
    try:
        rect = GameWindow(session.process_id).client_rect()
    except Exception as exc:  # noqa: BLE001 - reported, not fatal
        print(f"  could not read the client rect ({exc}); skipping Part A\n")
        return None

    hud = screen.hud_height(rect)
    print(f"  client area      {rect.width} x {rect.height} px")
    print(f"  HUD strip        {hud} px at the bottom (swallows world clicks)")
    print(
        f"  projection       {screen.PX_PER_SUBTILE_X} px/subtile in x, "
        f"{screen.PX_PER_SUBTILE_Y} in y (live-calibrated, M3)"
    )

    # Walk outward one subtile at a time along each direction until the
    # projected point leaves the area. Stepping rather than solving the
    # inequality on purpose: `clickable` already encodes the edge margin and
    # the HUD, and re-deriving that here is how the two drift apart.
    #
    # Two extents, because they answer different questions and the bot cares
    # about the second: DRAWN is what a human watching sees, CLICKABLE is
    # where a travel click can actually be aimed (the HUD strip eats the
    # bottom of the window, so the two differ, and asymmetrically).
    projection = screen.Projection(player_world=(0, 0), screen_center=rect.center)

    def extent(ux: int, uy: int, *, clickable_only: bool) -> int:
        distance = 0
        while distance < 400:
            nxt = distance + 1
            sx, sy = projection.world_to_screen(ux * nxt, uy * nxt)
            inside = (
                screen.clickable(rect, sx, sy)
                if clickable_only
                else rect.contains(sx, sy)
            )
            if not inside:
                return distance
            distance = nxt
        return distance

    print("\n  half-extent from the player, by direction (subtiles):")
    print(f"    {'direction':10} {'drawn':>7} {'clickable':>10}")
    drawn, clicky = [], []
    for label, ux, uy in COMPASS:
        d = extent(ux, uy, clickable_only=False)
        c = extent(ux, uy, clickable_only=True)
        drawn.append(d)
        clicky.append(c)
        print(f"    {label:10} {d:>7} {c:>10}")

    smallest, largest = min(drawn), max(drawn)
    print(
        f"\n  The visible region is a DIAMOND in world space, not a circle, so "
        "there is no\n  single 'subtiles per screen' number: it is "
        f"{smallest} to {largest} from the player to the\n  edge depending on "
        f"direction — i.e. {2 * smallest} to {2 * largest} subtiles across."
    )
    print(
        f"  Perception ({PERCEPTION_RADIUS}) is {PERCEPTION_RADIUS / largest:.1f}x "
        f"the furthest screen edge and {PERCEPTION_RADIUS / smallest:.1f}x the "
        "nearest."
    )
    print(
        "\n  This is geometry only. It says what a human watching would see; "
        "it is NOT\n  evidence about what the client keeps in memory — that is "
        "Part B.\n"
    )
    return smallest, largest


def unit_horizon(session) -> dict:
    """Part B — where do the counts stop growing?"""
    print("== Part B — the unit horizon, by observation ==\n")
    rows = []
    for radius in (*RADII, UNLIMITED):
        best = None
        elapsed = []
        for _ in range(SAMPLES):
            started = time.perf_counter()
            scan = scan_units(session, radius=radius)
            elapsed.append((time.perf_counter() - started) * 1000)
            # Keep the FULLEST sample, not the last: the game mutates these
            # structures while we read them, so a torn scan reports fewer
            # units than are really there and averaging counts would bake
            # that in. The maximum is the honest estimate of "at least this
            # many were visible".
            total = (
                len(scan.monsters) + len(scan.allies) + len(scan.corpses)
                + len(scan.ground_items) + len(scan.objects)
            )
            if best is None or total > best[0]:
                best = (total, scan)
        total, scan = best
        rows.append((radius, total, scan, min(elapsed)))

    label_for = lambda r: "unlimited" if r == UNLIMITED else str(r)  # noqa: E731
    print(
        f"  {'radius':>10}  {'mon':>4} {'ally':>4} {'corpse':>6} {'item':>5} "
        f"{'obj':>4}  {'total':>5}  {'furthest':>8}  {'scan ms':>7}"
    )
    for radius, total, scan, millis in rows:
        everything = [
            *scan.monsters, *scan.allies, *scan.corpses,
            *scan.ground_items, *scan.objects,
        ]
        origin = _origin(session)
        furthest = (
            max(_chebyshev(u.position, origin) for u in everything)
            if everything and origin is not None
            else 0
        )
        marker = "  <== PERCEPTION_RADIUS" if radius == PERCEPTION_RADIUS else ""
        print(
            f"  {label_for(radius):>10}  {len(scan.monsters):>4} "
            f"{len(scan.allies):>4} {len(scan.corpses):>6} "
            f"{len(scan.ground_items):>5} {len(scan.objects):>4}  "
            f"{total:>5}  {furthest:>8}  {millis:>7.1f}{marker}"
        )

    # The verdict, stated rather than left to the reader — the whole point
    # of the drill is to stop guessing at this.
    finite = [r for r in rows if r[0] != UNLIMITED]
    unlimited_total = rows[-1][1]
    at_80 = next((r[1] for r in finite if r[0] == PERCEPTION_RADIUS), 0)
    plateau = None
    for radius, total, _scan, _ms in finite:
        if total >= unlimited_total:
            plateau = radius
            break
    print()
    if unlimited_total == at_80:
        print(
            f"  VERDICT: raising the radius gains NOTHING here — an unlimited\n"
            f"  scan finds the same {at_80} units as {PERCEPTION_RADIUS} does. "
            "The bound is the\n  client's own horizon (or the area is simply "
            "this empty). Covering\n  more ground needs the character to MOVE, "
            "not a bigger constant."
        )
    else:
        gained = unlimited_total - at_80
        print(
            f"  VERDICT: our filter IS cutting units off — an unlimited scan\n"
            f"  finds {unlimited_total} units against {at_80} at "
            f"{PERCEPTION_RADIUS}, so {gained} more exist in the\n"
            "  hash table. Part C says whether they are real neighbours or "
            "R23's junk."
        )
        if plateau is not None:
            print(f"  Counts plateau at radius {plateau}.")
    return {"rows": rows, "unlimited_total": unlimited_total, "at_80": at_80}


def _origin(session):
    try:
        snap = Perception(session).snapshot()
    except Exception:  # noqa: BLE001
        return None
    return snap.player.position if snap.player is not None else None


def far_field(session) -> None:
    """Part C — what is out there, at no radius limit at all."""
    print("\n== Part C — the far field (no radius limit) ==\n")
    origin = _origin(session)
    if origin is None:
        print("  no player position; skipping\n")
        return
    scan = scan_units(session, radius=UNLIMITED)
    rows = []
    for monster in scan.monsters:
        rows.append(("monster", monster.kind, monster.position))
    for ally in scan.allies:
        rows.append(("ally", ally.kind, ally.position))
    for corpse in scan.corpses:
        rows.append(("corpse", corpse.kind, corpse.position))
    for item in scan.ground_items:
        rows.append(("item", item.kind, item.position))
    for obj in scan.objects:
        rows.append(("object", obj.kind, obj.position))

    buckets = Counter()
    for _kind_of, _kind, position in rows:
        distance = _chebyshev(position, origin)
        for edge in (12, 24, 48, 80, 120, 160, 240, 320, 1000, 10_000):
            if distance <= edge:
                buckets[edge] += 1
                break
        else:
            buckets[-1] += 1

    print(f"  player at {origin}; {len(rows)} units in the hash table\n")
    print("  distance histogram (cumulative bands):")
    for edge in (12, 24, 48, 80, 120, 160, 240, 320, 1000, 10_000):
        if buckets[edge]:
            print(f"    <= {edge:>6}   {buckets[edge]:>4}")
    if buckets[-1]:
        print(f"    beyond    {buckets[-1]:>4}   (other levels / the stash — R23)")

    beyond = sorted(
        (
            (_chebyshev(p, origin), k, kind, p)
            for k, kind, p in rows
            if _chebyshev(p, origin) > PERCEPTION_RADIUS
        ),
    )
    print(
        f"\n  the {min(len(beyond), 20)} nearest units OUTSIDE "
        f"{PERCEPTION_RADIUS} (what raising it would buy):"
    )
    if not beyond:
        print("    none — nothing at all lies between the radius and infinity.")
    for distance, kind_of, kind, position in beyond[:20]:
        print(f"    d={distance:>6}  {kind_of:8} kind {kind:>5} at {position}")


def t50_body(run: DrillRun) -> str:
    session = run.session
    snap = Perception(session).snapshot()
    if snap.player is None:
        raise RuntimeError("not in a game — enter one first")
    area = snap.area.level_no if snap.area else "?"
    print(
        f"T50 perception range — player at {snap.player.position}, "
        f"area {area}, in_town={snap.in_town}\n"
    )
    # Arm before measuring. Part B in town measured nothing about the
    # horizon — the entire town population sat within 57 subtiles, so the
    # plateau was equally consistent with "the area is that small". The
    # user's condition fixes that at the source: do not conclude until
    # there is genuinely a field to look at.
    print("  waiting to arm: need a monster on screen, and you standing still.\n")
    run.say("Walk to somewhere with monsters, then stand still for 5 seconds.")
    armed = wait_until_armed(run)

    snap = Perception(session).snapshot()
    area = snap.area.level_no if snap.area else "?"
    print(f"  measuring in area {area}, in_town={snap.in_town}\n")

    edges = screen_extent(session)
    if edges is not None:
        near, far = edges
        run.say(f"Screen is {2 * near}-{2 * far} subtiles across ({near}-{far} to the edge).")

    horizon = unit_horizon(session)
    at_80, unlimited = horizon["at_80"], horizon["unlimited_total"]
    if unlimited == at_80:
        run.say(
            f"Radius 80 sees {at_80} units; UNLIMITED sees the same {unlimited}. "
            "Our filter is not the limit."
        )
    else:
        run.say(
            f"Radius 80 sees {at_80} units, unlimited sees {unlimited} — "
            f"{unlimited - at_80} are being cut off by our own number."
        )

    far_field(session)
    print("\nT50 complete. Nothing was sent to the game.")
    return (
        f"armed with {armed}; "
        + (f"screen {edges[0]}-{edges[1]} subtiles to the edge; " if edges else "")
        + f"units at radius 80: {at_80}, unlimited: {unlimited}"
        + ("  (our filter is NOT the bound)" if unlimited == at_80 else "")
    )


if __name__ == "__main__":
    status = run_drill(T50, t50_body, run=DrillRun(GameSession()))
    raise SystemExit(0 if status == "PASS" else 1)
