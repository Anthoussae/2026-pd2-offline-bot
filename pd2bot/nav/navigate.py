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

    python -m pd2bot.nav.navigate --to X Y     walk to a world subtile
    python -m pd2bot.nav.navigate --demo       out-and-back acceptance walk
    python -m pd2bot.nav.navigate --survey     record rooms while YOU walk (no clicks)

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

from pd2bot.input.gated import GatedInput, InputRefused
from pd2bot.nav.pathing import Grid, Point, astar, nearest_walkable, simplify

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
# How close to the walk's GOAL a hazard must be to stop counting as a
# hazard. Small on purpose, and MEASURED (2026-08-01, the click audit on
# the first patrol run).
#
# The exemption exists for one case: `collect` walks to an item's exact
# position to get in range, so the item it is walking to must not be
# dodged. That case has distance ZERO. Testing it against `AVOID_RADIUS`
# instead exempted everything within 3 subtiles of any destination — and
# the audit priced it: of 39 goal-exempt clicks in one run, only 8 had the
# item AS the goal. The other 31 were unrelated items that happened to lie
# 1-3 subtiles from a patrol leg or a dash endpoint, and 21 of those landed
# inside the avoid radius, i.e. would have been nudged away but for the
# exemption. Five clicks landed exactly ON an item.
#
# That is the whole junk-in-the-inventory mechanism: two runs sent ZERO
# deliberate pickups for anything but potions, so every other item arrived
# via a travel click, and this is how the travel clicks got there.
#
# 1 rather than 0 only to absorb a subtile of jitter between the snapshot
# the step aimed from and the one the hazard read used.
GOAL_EXEMPT_RADIUS = 1
# How many times a click may be pushed before we settle for the roomiest
# spot found. Bounded because a ring of hazards has no clear point at
# all, and an unbounded search there would spin instead of walking.
MAX_NUDGES = 8
# --- the sprite box (T83, 2026-08-08) ----------------------------------------
#
# `AVOID_RADIUS` is a world-space Chebyshev radius, and the client's hit
# test is against a SPRITE, in screen space. Those are not the same shape,
# and the difference is not academic — it is the whole NPC misclick.
#
# T83 recorded three travel clicks, all already nudged, all at world gap 6
# from an ally, i.e. beyond the radius:
#
#   (5869, 5733)  merc  at (5863, 5733)  120 px right /  60 px below  ok
#   (5872, 5733)  Kashya at (5878, 5733) 120 px left  /  60 px above  ok
#   (5872, 5727)  Kashya at (5878, 5733)   0 px       / 120 px ABOVE  DIALOG
#
# Same world distance, opposite outcomes, decided entirely by direction on
# screen. `screen.py`'s measured projection is why: screen-x moves 20 px per
# (dx - dy) and screen-y 10 px per (dx + dy), so a world delta of (-6, -6)
# is 0 px sideways and 120 px straight up — her body — while (-6, +6), the
# same Chebyshev 6, is 240 px away across the floor.
#
# Bounds the measurement gives: the sprite is >= 120 px tall above the feet
# (the hit) and < 120 px in half-width (both misses were 120 px sideways).
# These carry a margin above, where the danger is measured, and none out to
# the side, where safety is measured — 80 stays inside both misses rather
# than sitting on them.
#
# Display geometry, like the constants they are built on: re-measure after
# any resolution, window-size or renderer change (the drill re-runs in ~40 s
# and prints both spaces).
SPRITE_HALF_WIDTH_PX = 80
SPRITE_ABOVE_FEET_PX = 150
SPRITE_BELOW_FEET_PX = 40
SPRITE_MARGIN_PX = 20  # how far past the wall an escaping click lands
# How near a ground item a travel click has to land before the audit
# records it. Three times AVOID_RADIUS on purpose: the question the audit
# exists to answer is whether 4 is big enough, and a log that only recorded
# clicks INSIDE 4 could never show that 5, 6 or 7 were where the damage was
# being done. Recording the near misses is the measurement.
CLICK_AUDIT_RADIUS = 12
MAX_FAILURES = 5  # consecutive no-progress plan cycles before giving up
# How long ONE `walk_to` call may block before returning to its caller,
# whatever it has or has not achieved.
#
# The per-waypoint cap (WAYPOINT_TIMEOUT) and the plan-cycle budget
# (MAX_FAILURES) already existed; nothing capped the CALL, so they
# multiplied. On 2026-08-07 that reached 24 seconds with the character
# stuck 3 subtiles from the Cellar 4 exit inside a 29-hostile pack, and
# the run died: the safety monitor only runs between ticks, so a blocked
# engine cannot chicken (docs/reviews/2026-08-07-chicken-starvation-death).
#
# This number is NOT what bounds chicken latency — `safety_poll` is, and
# it interrupts within its own interval. What the cap buys is the tick
# loop itself: the reflex ladder (potions, bone armor), the abort
# channel, and the never-idle checks all live between ticks too, and in
# a pack those seconds are the ones that matter. 2 s because a leg worth
# having makes visible progress inside it, and returning short is
# already the normal outcome here — every caller re-checks distance.
#
# DO NOT lower this below the time the walk's graceful endgames need.
# R262 tried 1.0 and run 8 died 15 s into town: approaching Akara, the
# clicks were (correctly) nudged off the NPC sprites, and the walk's
# honest exits for that state — "arrived at the nudged click" and
# "stopping short: a hazard sits beside the goal" — both live at the
# END of a call. At 1.0 s the budget expired before either could fire,
# every capped return was booked as a no-progress stall, and five
# bookings ended the run with a NavigationError six subtiles from the
# healer. Reverted the same night, measured, not reasoned.
WALK_BUDGET_SECONDS = 2.0
PROGRESS_RESET = 3.0  # subtiles closer to the goal that make a cycle "progress"
# Shake loose before re-planning from a spot that did not work.
#
# A re-plan from the SAME position over the SAME grid returns the same
# path and clicks the same cell, so a character caught on geometry
# re-derives its way into the identical corner until the budget runs out.
# Live, 2026-08-01: five cycles at (5226, 5658) trying to reach
# (5219, 5658) — seven subtiles — and the run ended there.
#
# The user's remedy, and it is the same principle that fixed the object
# click and the patrol point the same day: *finding another open space or
# clicking beyond the obstacle often solves the problem, provided that the
# ultimate destination objective isn't lost.* So: step aside, then
# re-plan. The destination never changes; only where we plan FROM.
#
# Sideways first and never straight back toward the goal — the goal
# direction is the one already proven not to work.
SHAKE_DISTANCE = 6
SHAKE_ANGLES = (90, -90, 135, -135, 45, -45, 180)
# Two walk targets this close are THE SAME ATTEMPT for the cross-call
# stall ladder (R261). The ladder used to key on the exact goal, and
# combat targets jitter a subtile per tick as the monster shifts — so
# a body-blocked dash "changed goals" every tick, the counter reset
# every tick, and the identical doomed 2 s click repeated for 13 s
# with no escalation ever firing (battery run 4, t+114.7; run 5 paid
# 85 s across 41 such walks). 4 subtiles: bigger than target jitter,
# far smaller than a genuine retarget.
STALL_GOAL_BUCKET = 4


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
    # True when the walk returned on its wall-clock budget rather than by
    # arriving or giving up. Not a failure: `arrived_at` is still the
    # truth, and the caller is expected to re-check distance and call
    # again if it still wants the target.
    capped: bool = False
    log: list[str] = field(default_factory=list)


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _screen_offset(origin: Point, point: Point) -> tuple[float, float]:
    """Where `point` is DRAWN relative to `origin`, in window pixels.

    `screen.py`'s projection, minus the camera — which cancels out of a
    difference, so this needs no window and no live client. Imported
    rather than re-typed: they are display-geometry constants that a
    resolution change invalidates, and a second copy would drift out of
    step with the calibration that sets them.

    Screen y grows DOWNWARD, so a negative `sy` means drawn ABOVE.
    """
    from pd2bot.input.screen import PX_PER_SUBTILE_X, PX_PER_SUBTILE_Y

    dx, dy = point[0] - origin[0], point[1] - origin[1]
    return ((dx - dy) * PX_PER_SUBTILE_X, (dx + dy) * PX_PER_SUBTILE_Y)


def _inside_sprite(hazard: Point, point: Point) -> bool:
    """Would a click at `point` land on the unit standing at `hazard`?

    The box is tall and narrow because a standing character is: see the
    constants for the three measured clicks that fixed its dimensions.
    """
    sx, sy = _screen_offset(hazard, point)
    return (
        abs(sx) <= SPRITE_HALF_WIDTH_PX
        and -SPRITE_ABOVE_FEET_PX <= sy <= SPRITE_BELOW_FEET_PX
    )


def _sprite_escapes(hazard: Point) -> tuple[Point, ...]:
    """Click points just outside a sprite, nearest wall first.

    Left, right, DOWN-screen — and, last, UP-screen BEYOND the box.
    Up-screen INSIDE the box is what the old world-space push produced
    (the click that opened Kashya's dialog was 120 px straight up her
    sprite), and stays forbidden: the up candidate here clears the box's
    150 px wall plus the margin — above the head, on clear ground. It is
    offered at all because of T88 (2026-08-13): Charsi lay up-screen of
    a bystander NPC, the three old escapes were all lateral or backward,
    and the walk "escaped" sideways without progress five times and gave
    up 18 subtiles short. When the goal lies past the unit, behind them
    IS past them — the goal-aware selection in `_nudged_click_point` is
    what promotes this candidate, and only when the goal earns it.

    Built from whole subtiles rather than by inverting the projection and
    rounding. Two reasons, both found by the tests: rounding lands on the
    box WALL as often as outside it (a half-subtile is 10 px, and the
    wall is inclusive), and an escape must clear `AVOID_RADIUS` as well —
    a sprite hazard is a world hazard too, so a screen-space escape that
    ignored the radius would be rejected by the very next check and the
    nudge would spin.

    The two clean axes: a world step of (k, -k) moves the click PURELY
    sideways on screen (2k * 20 px, no vertical), and (k, k) moves it
    purely down-screen (2k * 10 px). So one integer `k` per axis, big
    enough to clear both rules.
    """
    from pd2bot.input.screen import PX_PER_SUBTILE_X, PX_PER_SUBTILE_Y

    def steps(needed_px: float, px_per_step: int) -> int:
        return max(
            math.ceil(needed_px / (2 * px_per_step)),
            AVOID_RADIUS,  # the world rule still applies to the same unit
        )

    side = steps(SPRITE_HALF_WIDTH_PX + SPRITE_MARGIN_PX, PX_PER_SUBTILE_X)
    down = steps(SPRITE_BELOW_FEET_PX + SPRITE_MARGIN_PX, PX_PER_SUBTILE_Y)
    up = steps(SPRITE_ABOVE_FEET_PX + SPRITE_MARGIN_PX, PX_PER_SUBTILE_Y)
    hx, hy = hazard
    return (
        (hx - side, hy + side),  # left across the floor
        (hx + side, hy - side),  # right across the floor
        (hx + down, hy + down),  # toward the camera, in front of them
        (hx - up, hy - up),      # past them, above the head (T88)
    )


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
        sprite_provider: Callable[[], tuple[Point, ...]] | None = None,
        audit: Callable[[Point, Point | None, int], None] | None = None,
        safety_poll: Callable[[], None] | None = None,
        walk_budget_s: float | None = WALK_BUDGET_SECONDS,
        on_plan: Callable[..., None] | None = None,
    ) -> None:
        self._position = position_reader
        self._input = gated_input
        self._grid_provider = grid_provider
        self._clock = clock
        self._sleep = sleep
        # Called from inside every waiting loop in this class. It raises
        # (SafetyInterrupt) when the character must stop what it is
        # doing right now; it is not asked for an opinion and returns
        # nothing. None = nothing is watching, which is correct for the
        # CLI, the survey tool and the drills — they have no monitor.
        #
        # The contract that matters: this is called from OUTSIDE every
        # `except Exception` guard below, and its exception is a
        # BaseException, so neither this class's unstick guard nor the
        # click audit can swallow a chicken. Both halves are deliberate;
        # keep both if you move a call site.
        self._safety_poll = safety_poll
        self._walk_budget_s = walk_budget_s
        # Where the clickable hazards are RIGHT NOW (NPCs pace), or None for
        # environments with nothing interactive to hit (tests, open field).
        self._avoid = avoid_provider
        # The subset of those hazards that is a STANDING UNIT, whose hit
        # box is a tall sprite rather than a patch of floor (T83). Optional
        # and defaulting to None so every existing caller keeps the plain
        # world-space rule: the box is checked IN ADDITION to
        # `AVOID_RADIUS`, never instead of it, so nothing the radius
        # already caught is given back.
        self._sprites = sprite_provider
        # Called with (final click point, goal, nudges applied) for every
        # travel click actually sent. PURE MEASUREMENT — it changes no
        # decision, and it exists because the user asked to measure before
        # tuning: junk keeps arriving in the inventory with zero deliberate
        # `PickUpItem` sends behind it, so travel clicks are landing on
        # ground items, and nobody knows whether that is AVOID_RADIUS being
        # too tight or the goal exemption below letting them through.
        #
        # `WalkResult.log` could not answer it: production discards the
        # WalkResult entirely (`GameActionExecutor` calls `walk_to` and
        # keeps nothing), so every nudge line this class has ever written
        # has gone nowhere outside the navdemo CLI.
        self._audit = audit
        # Called with keyword fields after every PLAN — the
        # `nearest_walkable` + `astar` + `simplify` block — whatever its
        # outcome. PURE MEASUREMENT, same contract as `audit`: it changes
        # no decision and must never wound the walk it measures. It
        # exists because of 2026-08-13's 47 s stall: two ~21 s A* floods
        # were visible only as tick durations with nothing inside them
        # (`nav.failed` reports the walk's verdict, not the plan's
        # price), and the T92 human-vs-bot comparison had to be invented
        # to even locate them. See docs/architecture/run-log.md,
        # `nav.plan`.
        self._on_plan = on_plan
        # The destination of the walk in flight, so `_safe_click_point`
        # can tell a hazard we are deliberately approaching from one we
        # merely happen to pass. Set per walk_to, cleared after.
        self._goal: Point | None = None
        # When the walk in flight must return by. Set per walk_to.
        self._deadline: float | None = None
        # Give-up state that has to OUTLIVE a single call.
        #
        # The wall-clock cap returns before the no-progress ladder can
        # finish, so without this a hopeless target would be retried for
        # ever: every call capped, no call ever raising. Callers that
        # keep their own per-target budgets (the patrol's `_attempts`,
        # pickup's `collect_stalls`) would still cope, but the ones that
        # rely on `NavigationError` to mean "this cannot be walked" —
        # traverse, and it was traverse that died — would not.
        #
        # So the ladder is unchanged in what it counts; it just counts
        # across calls now. Same give-up, and the tick loop gets to
        # breathe between the rungs.
        self._stall_goal: Point | None = None
        self._stall_count = 0
        self._stall_best: float | None = None

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

    def _note_plan(self, **fields) -> None:
        """Report one plan's cost to whoever is measuring. Never raises."""
        if self._on_plan is None:
            return
        try:
            self._on_plan(**fields)
        except Exception:  # noqa: BLE001 - measurement must never break a walk
            pass

    def _safety(self) -> None:
        """Ask the watcher whether the character must stop right now.

        Raises `SafetyInterrupt` (a BaseException) when it must; returns
        nothing when it need not. Called from every loop in this class
        that waits, because every one of them is time the safety monitor
        would otherwise not be running.
        """
        if self._safety_poll is not None:
            self._safety_poll()

    def _wait(self, seconds: float) -> None:
        """Sleep, but in poll-sized pieces with a safety check between.

        Any flat sleep is a window in which the character can die
        unwatched. This class had one — the shake-loose settle — and
        1.5 s is a long time in a pack.
        """
        remaining = seconds
        while remaining > 0:
            step = min(POLL_SECONDS, remaining)
            self._sleep(step)
            remaining -= step
            self._safety()
            if self._out_of_budget():
                return

    def _click(self, waypoint: Point, result: WalkResult) -> None:
        """One gated click, waiting out a briefly-blocking UI panel."""
        deadline = self._clock() + UI_WAIT_TIMEOUT
        # Kept outside the `except`, which unbinds its own name on exit.
        blocked_by: InputRefused | None = None
        while True:
            try:
                self._input.click_world(*waypoint)
                result.clicks += 1
                return
            except InputRefused as refused:
                blocked_by = refused
                if self._clock() >= deadline:
                    raise NavigationError(
                        f"input stayed refused for {UI_WAIT_TIMEOUT}s: {refused}"
                    ) from refused
                self._sleep(POLL_SECONDS)
            # Outside the `except` on purpose: a safety interrupt raised
            # in here would otherwise be chained onto the InputRefused,
            # which reads as though the refusal caused it.
            self._safety()
            # The budget applies here too, or a blocking panel could hold
            # the tick loop for the full UI_WAIT_TIMEOUT — five times the
            # cap. But it must RAISE rather than return quietly, and the
            # difference is not cosmetic:
            #
            # A travel click that lands on an NPC opens their dialog, and
            # that dialog refuses every click after it. The recovery for
            # that (R66/R68, live in T12 and T27) lives in the town
            # layer's `_walk_guarded`, and it keys on **NavigationError**
            # — it closes the panel, sidesteps, and re-walks. The first
            # cut of this budget check returned quietly instead, so the
            # walk came back merely "capped", no recovery ever ran, the
            # dialog stayed open, and the bot stood at the same subtile
            # until it gave up. Observed live 2026-08-08: stuck at
            # (5877, 5734), 45 subtiles short of Akara, zero movement
            # across four legs.
            #
            # Only reachable after a refusal, so the cause is always
            # attached.
            if self._out_of_budget():
                raise NavigationError(
                    f"input stayed refused until the walk budget expired: "
                    f"{blocked_by}"
                ) from blocked_by

    def _safe_click_point(self, waypoint: Point, result: WalkResult) -> Point:
        """The click we will actually send, plus the audit of where it landed."""
        point, nudges = self._nudged_click_point(waypoint, result)
        if self._audit is not None:
            try:
                self._audit(point, self._goal, nudges)
            except Exception:  # noqa: BLE001 - measurement must never break a walk
                pass
        return point

    def _nudged_click_point(
        self, waypoint: Point, result: WalkResult
    ) -> tuple[Point, int]:
        """Nudge a travel click off anything interactive near it.

        The click's only job is to make the character walk that way; landing
        a few subtiles off costs nothing (the loop re-plans freely), while
        landing ON a unit costs the whole walk — the dialog or menu it opens
        blocks all further input (R68/R111). So the trade is always worth it.
        The character's own arrival is unaffected: this adjusts clicks, and
        arrival is judged by position.
        """
        if self._avoid is None:
            return waypoint, 0
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
        # still avoided — including things merely NEAR the goal, which is
        # the correction the click audit forced (see GOAL_EXEMPT_RADIUS).
        # "The item I am walking to" and "an item lying three subtiles from
        # where I happen to be heading" are different facts, and testing
        # both against AVOID_RADIUS made them the same one.
        if self._goal is not None:
            hazards = tuple(
                h for h in hazards
                if max(abs(h[0] - self._goal[0]), abs(h[1] - self._goal[1]))
                > GOAL_EXEMPT_RADIUS
            )
        # The hazards that are standing UNITS, whose hit box is a sprite.
        # Same goal exemption: the thing we are deliberately walking to is
        # not something to dodge, whatever shape it is.
        sprites = self._sprites() if self._sprites is not None else ()
        if self._goal is not None:
            sprites = tuple(
                h for h in sprites
                if max(abs(h[0] - self._goal[0]), abs(h[1] - self._goal[1]))
                > GOAL_EXEMPT_RADIUS
            )
        if not hazards and not sprites:
            return waypoint, 0

        def clearance(point: Point) -> int:
            """Distance to the nearest hazard; bigger is safer."""
            return min(
                (max(abs(point[0] - ax), abs(point[1] - ay)) for ax, ay in hazards),
                default=AVOID_RADIUS,
            )

        def roominess(point: Point) -> tuple[int, int]:
            """How good a fallback this click is, worst thing first.

            Landing on a sprite outranks every world-space consideration:
            it is the difference between a click that walks and a click
            that opens a dialog and ends the walk.
            """
            return (
                -sum(1 for s in sprites if _inside_sprite(s, point)),
                clearance(point),
            )

        # Nudge, then LOOK AGAIN. The old version applied every hazard in one
        # pass and never re-checked, so each push could land the click inside
        # the next hazard and the last one silently won. In Cold Plains that
        # walked the click in a circle — (5218,5664) -> (5217,5667) ->
        # (5220,5670) -> (5216,5674) — and back onto the character, who then
        # never moved and failed the walk as "stuck".
        best = waypoint
        current = waypoint
        nudges = 0
        for _ in range(MAX_NUDGES):
            # The sprite box is tested FIRST, because only the screen-space
            # escape can resolve it. A world push aimed "away" from a unit
            # is free to choose straight up her sprite — which is not a
            # hypothesis about this code, it is what T83 caught it doing.
            sprite_offender = next(
                (s for s in sprites if _inside_sprite(s, current)), None
            )
            offender = next(
                (
                    (ax, ay)
                    for ax, ay in hazards
                    if max(abs(current[0] - ax), abs(current[1] - ay)) < AVOID_RADIUS
                ),
                None,
            )
            if sprite_offender is None and offender is None:
                return current, nudges  # clear of everything
            if roominess(current) > roominess(best):
                best = current
            if sprite_offender is not None:
                candidates = _sprite_escapes(sprite_offender)
                clear = [
                    c for c in candidates
                    if not any(_inside_sprite(s, c) for s in sprites)
                    and clearance(c) >= AVOID_RADIUS
                ]
                # Closest to where the WALK IS GOING, not to what we meant
                # to click. Least-deviation-from-the-waypoint was the T88
                # loop: the blocked waypoint sits inside the sprite's tall
                # band, so the nearest escape stayed on the WRONG side of
                # the blocker, and five "successful" walks gained nothing.
                # The goal is the one point that is never inside the band
                # (it is exempted above), so keying on it picks the side
                # of the unit that actually advances.
                aim = self._goal if self._goal is not None else waypoint
                current = min(
                    clear or list(candidates),
                    key=lambda c: _distance(c, aim),
                )
                nudges += 1
                result.log.append(
                    f"click stepped out of the sprite at {sprite_offender}: "
                    f"{waypoint} -> {current}"
                )
                continue
            ax, ay = offender
            dx, dy = current[0] - ax, current[1] - ay
            span = max(abs(dx), abs(dy))
            if span == 0:
                dx, dy, span = 1, 1, 1  # dead centre: any direction will do
            push = AVOID_RADIUS + AVOID_MARGIN
            current = (round(ax + dx / span * push), round(ay + dy / span * push))
            nudges += 1
            result.log.append(
                f"click nudged off interactive unit at ({ax}, {ay}): "
                f"{waypoint} -> {current}"
            )
        # Boxed in. Send the roomiest candidate rather than giving up: one
        # click that might interact is recoverable (the loop re-plans, panels
        # get closed), whereas refusing to click is a walk that cannot finish.
        best = max((best, current), key=roominess)
        result.log.append(f"no clear click near {waypoint}; using {best}")
        return best, nudges

    def _blocked_by_avoidance(self, position: Point, goal: Point) -> bool:
        """Is a hazard beside the goal the reason we are stopping short?

        True only when a hazard sits close enough to `goal` that any click
        aimed there would be nudged away, and we are already about as close
        as such a nudge allows. Deliberately narrow: it must not swallow a
        walk that failed for terrain, which still needs its re-plans and
        its eventual `NavigationError`.
        """
        if self._avoid is None:
            return False
        try:
            hazards = self._avoid()
        except Exception:  # noqa: BLE001 - unreadable: not our answer to give
            return False
        beside = [
            h for h in hazards
            if max(abs(h[0] - goal[0]), abs(h[1] - goal[1])) <= AVOID_RADIUS
        ]
        if not beside:
            return False
        return _distance(position, goal) <= AVOID_RADIUS + AVOID_MARGIN + ARRIVAL_RADIUS

    def _walk_one_waypoint(self, waypoint: Point, result: WalkResult) -> bool:
        """Walk until inside the arrival radius. True on arrival, False when
        stuck (caller decides whether to re-plan).

        **Arrival is judged against where we actually CLICKED**, as well as
        against the waypoint we meant. Those are the same point almost
        always, and differ exactly when avoidance nudged the click off
        something — at which point demanding arrival at the original is
        demanding the character reach a spot we deliberately refused to
        send them to. That contradiction is a guaranteed "stuck", and it is
        what the goal exemption was papering over: rather than accept
        landing a few subtiles short of a hazard, the old rule stopped
        avoiding the hazard at all, and travel clicks went back to scooping
        ground items (measured: 31 accidental exemptions in one run).

        Landing short is the correct outcome here. Every caller re-checks
        distance itself — `collect` before clicking, the patrol before
        crediting a point — so a walk that ends 6 subtiles out is reported
        honestly and costs one more leg, whereas a walk that cannot finish
        costs the target.
        """
        clicked = self._safe_click_point(waypoint, result)
        self._click(clicked, result)
        waypoint_deadline = self._clock() + WAYPOINT_TIMEOUT
        last_position = self.position()
        last_moved = self._clock()
        reclicked = False

        while True:
            self._sleep(POLL_SECONDS)
            # First thing after the sleep, before any of the arrival and
            # stuck arithmetic: this is the loop the character spends its
            # walking life in, so this call is what makes the monitor
            # effectively continuous rather than per-tick.
            self._safety()
            position = self.position()
            now = self._clock()
            if self._out_of_budget():
                result.log.append(
                    f"walk budget spent at {position} toward {waypoint}"
                )
                result.capped = True
                return False

            if _distance(position, waypoint) <= ARRIVAL_RADIUS:
                return True
            if (
                clicked != waypoint
                and _distance(position, clicked) <= ARRIVAL_RADIUS
            ):
                result.log.append(
                    f"arrived at {position}, the closest we could safely click "
                    f"to {waypoint} (nudged to {clicked})"
                )
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
                    clicked = self._safe_click_point(waypoint, result)
                    self._click(clicked, result)
                    last_moved = self._clock()
                    continue
                result.log.append(f"stuck at {position} toward {waypoint}")
                return False

    # -- the public act ---------------------------------------------------------

    def walk_to(self, target: Point) -> WalkResult:
        self._goal = target
        if self._stall_goal is None or (
            _distance(target, self._stall_goal) > STALL_GOAL_BUCKET
        ):
            # A genuinely new destination is a fresh attempt, whatever the
            # last one did. A target that merely JITTERED (the monster
            # shifted a subtile) is the same attempt — see
            # STALL_GOAL_BUCKET. The anchor deliberately stays at the
            # family's FIRST target rather than trailing the jitter, so
            # slow drift cannot walk the bucket window along with it.
            self._stall_goal, self._stall_count, self._stall_best = target, 0, None
        self._deadline = (
            None if self._walk_budget_s is None
            else self._clock() + self._walk_budget_s
        )
        try:
            return self._walk_to(target)
        finally:
            self._goal = None
            self._deadline = None

    def _out_of_budget(self) -> bool:
        """Has this walk_to call used up its wall clock?"""
        return self._deadline is not None and self._clock() >= self._deadline

    def _walk_to(self, target: Point) -> WalkResult:
        started = self._clock()
        result = WalkResult(
            target=target, arrived_at=(0, 0), duration_seconds=0.0, waypoints=0
        )

        # The last capped attempt at this same (bucketed) goal gained
        # NOTHING, so repeating its click unchanged is not a retry —
        # this codebase's own rule. Step aside FIRST, before spending
        # this call's budget on the identical doomed click. Whatever is
        # eating the click — a swing animation, unit collision, an
        # interaction — a sidestep changes the approach angle and the
        # next plan routes from the new spot (the R163 remedy, applied
        # one attempt earlier than the give-up path applies it).
        if self._stall_count >= 1:
            self._shake_loose(self.position(), target, result)

        failures = 0
        best_remaining: float | None = None
        while True:
            plan_started = self._clock()
            grid = self._grid_provider()
            start = self.position()
            goal = nearest_walkable(grid, *target)
            if goal is None:
                # "No walkable cell" has two very different causes, and the
                # caller needs to know which: solid wall, or terra incognita.
                known = grid.is_known(*target)
                self._note_plan(
                    source="walk", start=start, goal=None, target=target,
                    duration_s=round(self._clock() - plan_started, 3),
                    outcome="no_walkable_cell",
                )
                raise NavigationError(
                    f"no walkable cell near {target}: "
                    + (
                        "the area is known but solidly blocked there"
                        if known
                        else "that ground has never been seen — survey it first "
                        "(unknown ground is treated as blocked on purpose)"
                    )
                )
            search_stats: dict = {}
            path = astar(grid, start, goal, stats=search_stats)
            if path is None:
                self._note_plan(
                    source="walk", start=start, goal=goal, target=target,
                    duration_s=round(self._clock() - plan_started, 3),
                    outcome="no_path", **search_stats,
                )
                raise NavigationError(f"no path from {start} to {goal}")
            waypoints = simplify(grid, path)
            result.waypoints = len(waypoints)
            self._note_plan(
                source="walk", start=start, goal=goal, target=target,
                duration_s=round(self._clock() - plan_started, 3),
                outcome="path", path_cells=len(path), waypoints=len(waypoints),
                **search_stats,
            )
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
                self._stall_goal, self._stall_count, self._stall_best = None, 0, None
                return result

            # Out of wall clock. Return what we achieved rather than
            # starting another plan cycle — the caller wants its tick
            # loop back, and re-planning from here is what turned five
            # budgets into 24 seconds. Deliberately NOT a NavigationError
            # in itself: nothing has failed yet, we were merely
            # interrupted, and a caller that still wants this target will
            # ask again. The give-up ladder is carried across those calls
            # instead (see `_stall_*`), so "this cannot be walked" is
            # still eventually said — just not by burning a whole tick.
            if result.capped or self._out_of_budget():
                result.capped = True
                result.arrived_at = position
                result.duration_seconds = self._clock() - started
                remaining = _distance(position, goal)
                if self._stall_best is None or self._stall_best - remaining >= (
                    PROGRESS_RESET
                ):
                    self._stall_best = remaining
                    self._stall_count = 0
                else:
                    self._stall_count += 1
                result.log.append(
                    f"returning on the {self._walk_budget_s:.1f}s walk budget "
                    f"at {position}, {remaining:.0f} short of {goal} "
                    f"({self._stall_count} capped attempts without progress)"
                )
                if self._stall_count >= MAX_FAILURES:
                    raise NavigationError(
                        f"gave up after {self._stall_count} capped attempts "
                        f"without progress; last position {position}, "
                        f"target {goal}; log: {'; '.join(result.log[-5:])}"
                    )
                return result

            # Walked every waypoint, still short of the goal, and the reason
            # is that avoidance refused to click there: the goal has a hazard
            # beside it. Re-planning cannot help — the next plan ends at the
            # same cell and the same click gets nudged the same way, which is
            # this codebase's own rule that a retry unable to differ from the
            # attempt it retries is not a retry. So stop, and report where we
            # got: `arrived_at` is the truth, every caller re-checks distance,
            # and one honest short walk beats five identical failures and a
            # dead run.
            if arrived and self._blocked_by_avoidance(position, goal):
                result.log.append(
                    f"stopping {_distance(position, goal):.0f} short of {goal}: "
                    "a hazard sits beside it and the click cannot be aimed "
                    "closer"
                )
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
            # Move BEFORE re-planning, or the next plan is this plan.
            self._shake_loose(position, goal, result)

    def _shake_loose(self, position: Point, goal: Point, result: WalkResult) -> bool:
        """Step aside so the next plan can differ from the one that failed.

        Caught on a wall, the loop re-planned from where it stood, got the
        same path back, and clicked the same cell until it ran out of
        cycles. The destination is not the problem and is left alone — the
        only thing changed is where we plan from.

        Best effort by design: it reports whether it moved, and a failure
        here just means the next re-plan is no worse off than before.
        """
        try:
            grid = self._grid_provider()
        except Exception:  # noqa: BLE001 - unstick must not raise
            return False
        base = math.atan2(goal[1] - position[1], goal[0] - position[0])
        for degrees in SHAKE_ANGLES:
            angle = base + math.radians(degrees)
            spot = (
                round(position[0] + SHAKE_DISTANCE * math.cos(angle)),
                round(position[1] + SHAKE_DISTANCE * math.sin(angle)),
            )
            try:
                if not (grid.is_known(*spot) and grid.is_walkable(*spot)):
                    continue
            except Exception:  # noqa: BLE001 - a torn grid read is not fatal
                continue
            result.log.append(f"shaking loose to {spot}")
            self._click(self._safe_click_point(spot, result), result)
            self._wait(STUCK_SECONDS)
            return True
        result.log.append(f"nowhere to shake loose to from {position}")
        return False


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
    from pd2bot.nav.collision import read_local_collision
    from pd2bot.perception.world import read_area, read_map_seed

    area = read_area(session)
    seed = read_map_seed(session)
    if area is None or seed is None:
        return 0
    local = read_local_collision(session)
    per_area = None if stats is None else stats.setdefault(
        (seed, area.level_no), {"added": 0, "updated": 0}
    )
    return store.open(seed, difficulty, area.level_no).record(local, per_area)


def live_navigator(
    session,
    store,
    difficulty: int = 2,
    safety_poll: Callable[[], None] | None = None,
    on_plan: Callable[..., None] | None = None,
) -> Navigator:
    """Wire the navigator to the live game: positions from memory, clicks
    through the gate, and on every (re-)plan the explored-map atlas under
    the live room grids (live is ground truth where loaded). The position
    reader doubles as the recorder: roughly once a second while walking,
    the rooms currently in view are merged into the atlas — so the bot
    surveys as a side effect of going anywhere.

    Public because everything above navigation needs this exact wiring:
    the M3 CLI, M5's town drills, and P4's behaviour engine."""
    from pd2bot import offsets
    from pd2bot.nav.collision import read_local_collision
    from pd2bot.nav.pathing import OverlayGrid
    from pd2bot.perception.units import player_unit, unit_position
    from pd2bot.perception.world import read_area, read_map_seed

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
        from pd2bot.perception.snapshot import Perception

        try:
            snap = Perception(session).snapshot()
        except Exception:
            # Unreadable mid-load: no avoidance beats no walk. The sprite
            # list is cleared with it — keeping the last one would dodge
            # NPCs at positions from a town we may have already left.
            last_sprites[0] = ()
            return ()
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
        last_items[0] = tuple(i.position for i in snap.ground_items)
        if snap.in_town:
            # `not is_corpse` rather than `is_alive`, deliberately. Allies
            # cannot contain corpses at all (the corpse branch of
            # `scan_units` runs first), so the two agree on everything that
            # carries an HP stat — and disagree on anything that does not,
            # where `is_alive` reads hp 0 as dead and drops it. Whether a
            # town NPC's stat list carries HP is not something this repo
            # has measured, and this rule must not depend on an unmeasured
            # fact: the whole hazard set going quiet is precisely the
            # failure of 2026-08-06 (see `units.scan_units`), and it was
            # invisible until two live runs stalled on it.
            points += [a.position for a in snap.allies if not a.is_corpse]
            last_sprites[0] = tuple(
                a.position for a in snap.allies if not a.is_corpse
            )
        else:
            last_sprites[0] = ()
        return tuple(points)

    # The standing units from the most recent hazard read (T83). Kept from
    # that read rather than taken fresh: the two are consulted about the
    # SAME click, and a second snapshot would be a different moment as well
    # as ~19 ms of it. Town only, for the same reason the ally rule is —
    # outside town every ally is the merc or a summon, and clicking one
    # opens nothing.
    last_sprites: list[tuple[Point, ...]] = [()]

    def sprite_hazards() -> tuple[Point, ...]:
        return last_sprites[0]

    # The ground items seen by the most recent hazard read, kept so the
    # audit can measure against them without paying for a second snapshot
    # (~19 ms per click, and it would be a DIFFERENT moment anyway).
    last_items: list[tuple[Point, ...]] = [()]

    def audit_click(point: Point, goal: Point | None, nudges: int) -> None:
        """Record travel clicks that land near a ground item. Measurement only.

        The open question (user, 2026-08-01): two runs put junk in the
        inventory having sent ZERO deliberate `PickUpItem` actions for
        anything but potions, so travel clicks are scooping items. Ground
        items ARE avoided, at `AVOID_RADIUS` 4 — so either that is too
        tight, or something is bypassing it. There is exactly one known
        bypass, and this reports it explicitly: a hazard within
        `AVOID_RADIUS` of the WALK'S GOAL is deliberately not avoided (it
        is usually the thing we are walking to), and every `MoveTo` sets a
        goal — including patrol legs and combat dashes, which are aimed at
        open ground and have no business exempting an item near them.

        Reported rather than fixed, because the user asked to measure
        first and the two causes want different fixes.
        """
        items = last_items[0]
        if not items:
            return
        nearest = min(
            items, key=lambda i: max(abs(point[0] - i[0]), abs(point[1] - i[1]))
        )
        distance = max(abs(point[0] - nearest[0]), abs(point[1] - nearest[1]))
        if distance > CLICK_AUDIT_RADIUS:
            return
        exempt = goal is not None and (
            max(abs(nearest[0] - goal[0]), abs(nearest[1] - goal[1])) < AVOID_RADIUS
        )
        verdict = (
            "GOAL-EXEMPT (not avoided by design)"
            if exempt
            else ("INSIDE avoid radius" if distance < AVOID_RADIUS else "near miss")
        )
        print(
            f"  click audit: click {point} landed {distance} from ground item "
            f"{nearest} — {verdict}; goal {goal}, {nudges} nudge(s)",
            flush=True,
        )

    return Navigator(
        position_reader=position,
        gated_input=GatedInput(session),
        grid_provider=grid,
        avoid_provider=clickable_hazards,
        sprite_provider=sprite_hazards,
        audit=audit_click,
        # None for the CLI, the survey tool and the drills — they have no
        # monitor to consult and must keep working. The behaviour engine
        # passes the real one (see `wiring.build_bot`), and a walk with
        # nothing watching is still capped.
        safety_poll=safety_poll,
        # Plan-cost telemetry (T92): None for the CLI and drills, the run
        # log's emitter in production — same wiring story as safety_poll.
        on_plan=on_plan,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    from pd2bot.input.window import WindowNotFound
    from pd2bot.nav.mapstore import DEFAULT_ROOT, MapStore
    from pd2bot.perception.memory import GameNotRunning, GameSession, NeedsAdministrator

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
