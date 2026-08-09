"""The follow loop as a state machine, against a scripted world.

No game, no clock: virtual time advances only inside `sleep`, and the fake
world moves the player toward the last clicked destination at a fixed
speed. What is under test is the escalation ladder — arrive, re-click,
re-plan, give up — and the UI-refusal waiting.
"""

import pytest

from pd2bot.input.gated import InputRefused
from pd2bot.navigate import (
    AVOID_RADIUS,
    MAX_FAILURES,
    NavigationError,
    Navigator,
    WalkResult,
    pick_reachable_target,
)
from pd2bot.safety import SafetyInterrupt, Verdict


class OpenGrid:
    def is_walkable(self, x: int, y: int) -> bool:
        return True

    def is_known(self, x: int, y: int) -> bool:
        return True


class World:
    """Player kinematics: walks toward the last click at `speed` subtiles/s.

    `wall_x` simulates an obstacle the grid does not know about: movement
    clamps there, exactly like the game refusing to path further.
    """

    def __init__(self, start=(0, 0), speed=20.0, wall_x=None) -> None:
        self.x, self.y = float(start[0]), float(start[1])
        self.speed = speed
        self.wall_x = wall_x
        self.destination = None

    def step(self, dt: float) -> None:
        if self.destination is None:
            return
        dx = self.destination[0] - self.x
        dy = self.destination[1] - self.y
        distance = (dx * dx + dy * dy) ** 0.5
        if distance < 1e-9:
            return
        travel = min(self.speed * dt, distance)
        self.x += travel * dx / distance
        self.y += travel * dy / distance
        if self.wall_x is not None and self.x > self.wall_x:
            self.x = float(self.wall_x)

    def position(self):
        return (round(self.x), round(self.y))


class Sim:
    def __init__(self, world: World) -> None:
        self.world = world
        self.now = 0.0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.world.step(seconds)


class FakeInput:
    def __init__(self, world: World, refuse_first: int = 0) -> None:
        self.world = world
        self.refuse_first = refuse_first
        self.clicks = []

    def click_world(self, x: int, y: int):
        if self.refuse_first > 0:
            self.refuse_first -= 1
            raise InputRefused("a blocking panel is open (esc_menu)")
        self.clicks.append((x, y))
        self.world.destination = (x, y)
        return (0, 0)


class DyingMonitor:
    """A monitor stand-in whose character crosses the chicken line at a
    known moment of virtual time — the shape of the 2026-08-07 death,
    where HP fell to zero entirely inside one blocking walk."""

    def __init__(self, sim: "Sim", crosses_at: float) -> None:
        self.sim = sim
        self.crosses_at = crosses_at
        self.polls = 0

    def poll(self) -> None:
        self.polls += 1
        if self.sim.now >= self.crosses_at:
            raise SafetyInterrupt(
                Verdict("life", "life 300/1000 (30%) <= 35% threshold",
                        hp=300, max_hp=1000, pct=30.0)
            )


def navigator(
    world, sim, fake_input, grid_provider=None, avoid=None, audit=None,
    safety_poll=None, walk_budget_s=None,
):
    # `walk_budget_s=None` (no cap) is the default HERE, not in
    # production: most of these tests predate the cap and exercise the
    # give-up ladder within a single call, which is still exactly what
    # `walk_to` does once its budget is removed. The cap has its own
    # tests below.
    return Navigator(
        position_reader=world.position,
        gated_input=fake_input,
        grid_provider=grid_provider or (lambda: OpenGrid()),
        clock=sim.clock,
        sleep=sim.sleep,
        avoid_provider=avoid,
        audit=audit,
        safety_poll=safety_poll,
        walk_budget_s=walk_budget_s,
    )


def test_walks_to_target():
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    result = navigator(world, sim, fake).walk_to((20, 0))
    assert abs(result.arrived_at[0] - 20) <= 3
    assert result.clicks >= 2  # at least two waypoints on a 20-cell run
    assert result.replans == 0
    assert result.duration_seconds > 0


def test_travel_clicks_avoid_interactive_units():
    """R68/R111, fixed at the level the notes prescribed: a travel click
    near an NPC or object INTERACTS instead of moving, and the panel it
    opens kills the walk. So clicks aimed near a known hazard are nudged
    away before being sent — Akara's approach can pass the town waypoint
    without ever clicking it."""
    from pd2bot.navigate import AVOID_RADIUS

    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    hazard = (10, 0)  # squarely on the route to (20, 0)
    result = navigator(world, sim, fake, avoid=lambda: (hazard,)).walk_to((20, 0))
    assert abs(result.arrived_at[0] - 20) <= 3  # still arrives
    for click in fake.clicks:
        span = max(abs(click[0] - hazard[0]), abs(click[1] - hazard[1]))
        assert span >= AVOID_RADIUS, f"click {click} landed on the hazard"
    assert any("nudged" in line for line in result.log)


def test_no_avoid_provider_changes_nothing():
    """Environments with nothing interactive (tests, open field) pass None
    and get the untouched click stream."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    result = navigator(world, sim, fake, avoid=None).walk_to((20, 0))
    assert abs(result.arrived_at[0] - 20) <= 3
    assert not any("nudged" in line for line in result.log)


def test_a_hazard_off_the_route_is_ignored():
    """Only clicks AIMED near a hazard are adjusted — avoidance must not
    warp a walk that was never going to touch anything."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    result = navigator(world, sim, fake, avoid=lambda: ((10, 40),)).walk_to((20, 0))
    assert abs(result.arrived_at[0] - 20) <= 3
    assert not any("nudged" in line for line in result.log)


def test_already_there():
    world = World(start=(5, 5))
    sim = Sim(world)
    result = navigator(world, sim, FakeInput(world)).walk_to((5, 5))
    assert result.arrived_at == (5, 5)
    assert result.clicks == 0


def test_invisible_wall_gives_up_with_typed_error():
    world = World(wall_x=5)  # grid says open; reality stops at x=5
    sim = Sim(world)
    fake = FakeInput(world)
    with pytest.raises(NavigationError, match="gave up"):
        navigator(world, sim, fake).walk_to((30, 0))
    # It tried: re-clicks happened before each re-plan, then it stopped.
    assert len(fake.clicks) >= MAX_FAILURES


def test_a_stuck_walk_steps_aside_before_replanning():
    """R163, the user watching it catch on a wall.

    A re-plan from the same position over the same grid returns the same
    path and clicks the same cell, so a character caught on geometry
    re-derives its way into the identical corner until the budget runs
    out — live, five cycles at (5226, 5658) seven subtiles from its
    target, and the run ended there.

    *Finding another open space or clicking beyond the obstacle often
    solves the problem, provided that the ultimate destination objective
    isn't lost.* So the sidestep must be sideways, and the destination
    must survive it.
    """
    world = World(wall_x=5)
    sim = Sim(world)
    fake = FakeInput(world)
    with pytest.raises(NavigationError):
        navigator(world, sim, fake).walk_to((30, 0))
    # It did not spend every cycle clicking the same unreachable place.
    assert len({click for click in fake.clicks}) > 1, fake.clicks
    sideways = [click for click in fake.clicks if click[1] != 0]
    assert sideways, f"never tried another line: {fake.clicks}"


def test_shaking_loose_keeps_the_destination():
    # The sidestep changes where we plan FROM, never where we are going.
    world = World(wall_x=5)
    sim = Sim(world)
    fake = FakeInput(world)
    with pytest.raises(NavigationError, match=r"target \(30, 0\)"):
        navigator(world, sim, fake).walk_to((30, 0))


def test_obstacle_clearing_leads_to_replan_then_success():
    world = World(wall_x=5)
    sim = Sim(world)
    fake = FakeInput(world)
    plans = 0

    def grid_provider():
        nonlocal plans
        plans += 1
        if plans >= 2:  # by the second plan, the "door" has opened
            world.wall_x = None
        return OpenGrid()

    result = navigator(world, sim, fake, grid_provider).walk_to((20, 0))
    assert result.replans >= 1
    assert abs(result.arrived_at[0] - 20) <= 3
    assert any("stuck" in line for line in result.log)


def test_waits_out_a_brief_panel():
    world = World()
    sim = Sim(world)
    fake = FakeInput(world, refuse_first=3)  # ~0.3 virtual seconds of ESC menu
    result = navigator(world, sim, fake).walk_to((10, 0))
    assert abs(result.arrived_at[0] - 10) <= 3


# -- safety: a blocking walk may not starve the monitor -----------------------
#
# 2026-08-07: the engine blocked inside one `walk_to` for 24 s while a
# 29-hostile pack killed the character. The monitor only ran between
# ticks, so it never looked. These tests pin both halves of the fix —
# the walk interrupts itself, and it comes back on a clock either way.


def test_a_blocked_walk_reaches_the_full_giveup_ladder():
    """The shape of the death, and the reason the next test is a real test.

    With no safety poll and no cap — the pre-fix navigator exactly — a
    walk that cannot progress spends the entire ladder before saying so.
    The assertion is on the CLOCK: this is the window in which nothing
    was watching the character's HP.
    """
    world = World(wall_x=5)
    sim = Sim(world)
    with pytest.raises(NavigationError, match="gave up"):
        navigator(world, sim, FakeInput(world)).walk_to((60, 0))
    assert sim.now > 10.0, "expected a long blind window; got a short one"


def test_a_blocked_walk_is_interrupted_when_vitals_cross():
    """The fix: the same hopeless walk, now with something watching."""
    world = World(wall_x=5)
    sim = Sim(world)
    monitor = DyingMonitor(sim, crosses_at=1.0)
    nav = navigator(world, sim, FakeInput(world), safety_poll=monitor.poll)
    with pytest.raises(SafetyInterrupt) as raised:
        nav.walk_to((60, 0))
    assert raised.value.verdict.kind == "life"
    # Interrupted promptly after the crossing, not at the end of the ladder.
    assert sim.now < 1.5, f"took {sim.now:.1f}s to notice"


def test_the_interrupt_survives_the_navigators_broad_guards():
    """`navigate.py` wraps its click audit and its unstick grid read in
    `except Exception` — each correct about its own concern, each able to
    swallow a chicken. Two properties are pinned here at once: an
    ordinary exception from the audit IS absorbed (the guard works), and
    a SafetyInterrupt raised from the poll is NOT (it is a
    BaseException, and the poll is called outside those guards)."""
    world = World(wall_x=5)
    sim = Sim(world)

    def exploding_audit(point, goal, nudges):
        raise RuntimeError("the audit is broken")

    monitor = DyingMonitor(sim, crosses_at=0.5)
    nav = navigator(
        world, sim, FakeInput(world),
        audit=exploding_audit, safety_poll=monitor.poll,
    )
    with pytest.raises(SafetyInterrupt):
        nav.walk_to((60, 0))


def test_the_interrupt_escapes_the_ui_wait_loop():
    """A walk can also block waiting out a panel — up to 10 s of it."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world, refuse_first=1000)  # a panel that never closes
    monitor = DyingMonitor(sim, crosses_at=0.3)
    nav = navigator(world, sim, fake, safety_poll=monitor.poll)
    with pytest.raises(SafetyInterrupt):
        nav.walk_to((20, 0))
    assert sim.now < 1.0


def test_a_stuck_walk_returns_on_its_budget_with_nothing_watching():
    """The second, independent half: even with no monitor at all, one
    `walk_to` call gives the tick loop back on a wall clock — which is
    what the reflex ladder and the abort channel need."""
    world = World(wall_x=5)
    sim = Sim(world)
    nav = navigator(world, sim, FakeInput(world), walk_budget_s=2.0)
    result = nav.walk_to((60, 0))
    assert result.capped is True
    assert sim.now < 4.0, f"budget overshot: {sim.now:.1f}s"
    assert result.arrived_at == world.position()  # honest about where it got


def test_the_real_monitor_interrupts_a_real_walk_within_its_interval():
    """The end-to-end latency, MEASURED rather than derived — the number
    the P2 review gate reports and the one the 2026-08-07 death makes
    worth knowing. Everything here is real except the world: a real
    SafetyMonitor, its real rate limiter, the real walk loop.
    """
    from pd2bot.perception.player import Player
    from pd2bot.perception.world import Area
    from pd2bot.safety import SafetyConfig, SafetyMonitor

    world = World(wall_x=5)
    sim = Sim(world)
    vitals = {"hp": 1000}

    def read_player(_session):
        return Player(
            name="MaqiuDoubing", level=90, act=1, position=world.position(),
            mode=1, hp=vitals["hp"], max_hp=1000, mana=400, max_mana=500,
            stamina=300, max_stamina=300, experience=0, gold=0, gold_stash=0,
            strength=100, dexterity=100, vitality=300, energy=100,
        )

    monitor = SafetyMonitor(
        session=None,
        config=SafetyConfig(life_chicken_pct=35.0),
        read_player_fn=read_player,
        read_area_fn=lambda s: Area(level_no=3, position=(0, 0), size=(100, 100)),
        alert=lambda: None,
        clock=sim.clock,
    )

    crossed_at = {"t": None}

    def falling_health() -> None:
        # The pack does its work while the walk is blocked — the shape of
        # the death exactly: HP reaching the line with no tick in sight.
        if sim.now >= 1.0 and crossed_at["t"] is None:
            vitals["hp"] = 300  # 30% — below the 35% line
            crossed_at["t"] = sim.now
        monitor.poll()

    nav = navigator(world, sim, FakeInput(world), safety_poll=falling_health)
    with pytest.raises(SafetyInterrupt) as raised:
        nav.walk_to((60, 0))

    assert raised.value.verdict.kind == "life"
    latency = sim.now - crossed_at["t"]
    # The bound: one poll interval (the monitor's rate limit) plus one
    # walk-loop poll. Anything larger means a blocking site was missed.
    assert latency <= SafetyConfig().poll_interval_s + 0.1 + 1e-9, (
        f"took {latency:.2f}s to notice"
    )


def test_the_budget_also_bounds_a_walk_stuck_behind_a_panel():
    """`_click` waits out a blocking panel for up to UI_WAIT_TIMEOUT —
    five times the cap. An operator pressing ESC opens exactly such a
    panel, and the engine cannot notice they took the controls while the
    walk is in there.

    It must come back QUICKLY *and* LOUDLY. The first cut returned a
    quiet capped result, which cost the NPC-misclick recovery — see
    `test_a_refused_click_raises_even_when_the_budget_expires_first`.
    """
    world = World()
    sim = Sim(world)
    fake = FakeInput(world, refuse_first=1000)  # a panel that never closes
    with pytest.raises(NavigationError, match="refused"):
        navigator(world, sim, fake, walk_budget_s=2.0).walk_to((20, 0))
    assert sim.now < 4.0, f"held for {sim.now:.1f}s behind the panel"


def test_a_normal_walk_is_never_capped():
    world = World()
    sim = Sim(world)
    result = navigator(world, sim, FakeInput(world), walk_budget_s=2.0).walk_to((20, 0))
    assert result.capped is False
    assert abs(result.arrived_at[0] - 20) <= 3


def test_the_giveup_ladder_survives_the_cap_across_calls():
    """The cap must not turn "this cannot be walked" into silence.

    Without carried state a capped call never raises, so a caller that
    relies on `NavigationError` — traverse, and it was traverse that
    died — would retry a hopeless target for ever. The ladder therefore
    counts across calls instead of within one.
    """
    world = World(wall_x=5)
    sim = Sim(world)
    nav = navigator(world, sim, FakeInput(world), walk_budget_s=2.0)
    with pytest.raises(NavigationError, match="gave up"):
        for _ in range(MAX_FAILURES + 2):
            assert nav.walk_to((60, 0)).capped


def test_progress_resets_the_carried_ladder():
    """A walk that is merely slow must never add up to a walk that failed
    — the rule the original in-call ladder already had."""
    world = World(wall_x=5)
    sim = Sim(world)
    nav = navigator(world, sim, FakeInput(world), walk_budget_s=2.0)
    for _ in range(MAX_FAILURES + 2):
        nav.walk_to((60, 0))
        world.wall_x += 10  # the obstacle keeps yielding: real progress
    # No give-up: every attempt got meaningfully closer.


def test_a_new_destination_forgets_the_old_ladder():
    world = World(wall_x=5)
    sim = Sim(world)
    nav = navigator(world, sim, FakeInput(world), walk_budget_s=2.0)
    for _ in range(MAX_FAILURES):  # one short of giving up
        nav.walk_to((60, 0))
    world.wall_x = None
    result = nav.walk_to((20, 0))  # a different target, a clean slate
    assert abs(result.arrived_at[0] - 20) <= 3


def test_target_picker_finds_reachable_ground():
    """The demo must aim somewhere real: known, walkable, and reachable."""
    target, radius = pick_reachable_target(OpenGrid(), (0, 0), distance=60)
    assert target is not None
    assert radius == 60
    assert 55 <= max(abs(target[0]), abs(target[1])) <= 61


def test_target_picker_refuses_unknown_ground():
    """Standing in unsurveyed territory yields no target at all, rather
    than one the navigator would fail on later — the original demo bug."""

    class NothingKnown:
        def is_walkable(self, x, y):
            return False

        def is_known(self, x, y):
            return False

    target, _ = pick_reachable_target(NothingKnown(), (0, 0), distance=60)
    assert target is None


def test_target_picker_settles_for_a_nearer_spot():
    """When 60 subtiles is unavailable but 30 is, take the 30."""

    class SmallIsland:
        def is_walkable(self, x, y):
            return abs(x) <= 35 and abs(y) <= 35

        def is_known(self, x, y):
            return self.is_walkable(x, y)

    island = SmallIsland()
    target, radius = pick_reachable_target(island, (0, 0), distance=60)
    assert target is not None
    assert island.is_walkable(*target)  # it stayed on solid ground...
    assert radius < 60  # ...by giving up on the full distance
    # The sweep radius is a compass distance, so a diagonal hit lands nearer
    # than the radius suggests; what matters is that the cell is real.
    assert max(abs(target[0]), abs(target[1])) <= 35


def test_permanent_panel_fails_loudly():
    world = World()
    sim = Sim(world)
    fake = FakeInput(world, refuse_first=10_000)
    with pytest.raises(NavigationError, match="refused"):
        navigator(world, sim, fake).walk_to((10, 0))


def test_slow_character_still_arrives():
    """Chilled/walking pace (1 subtile/s) is slow, not stuck: cumulative
    drift keeps registering as movement and the walk just takes longer."""
    world = World(speed=1.0)
    sim = Sim(world)
    result = navigator(world, sim, FakeInput(world)).walk_to((20, 0))
    assert abs(result.arrived_at[0] - 20) <= 3
    assert result.replans == 0  # never even looked stuck


def test_crawling_character_replans_but_never_gives_up():
    """Extreme slow (0.4 subtiles/s — heavy chill) DOES trip the stuck
    ladder repeatedly, but every cycle inches closer, and progress resets
    the give-up counter — slow can never add up to failed."""
    world = World(speed=0.4)
    sim = Sim(world)
    result = navigator(world, sim, FakeInput(world)).walk_to((20, 0))
    assert abs(result.arrived_at[0] - 20) <= 3
    assert result.replans >= 1  # the ladder fired...
    assert any("stuck" in line for line in result.log)  # ...was logged...
    # ...and the counter kept resetting instead of exhausting MAX_FAILURES.


def test_a_cluster_of_hazards_still_yields_a_clear_click():
    """Stage B run 3, as a test.

    The old nudge applied every hazard in one pass without re-checking, so
    each push could land the click inside the next hazard and the last one
    won. Against a Cold Plains scenery cluster it walked the click in a
    circle and back onto the character, who then never moved and failed the
    walk as "stuck". Nudging must CONVERGE, not just happen.
    """
    from pd2bot.navigate import AVOID_RADIUS

    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    # Five hazards packed around the route, the shape that broke it.
    cluster = ((10, 0), (12, 2), (8, 3), (13, -2), (9, -3))
    result = navigator(world, sim, fake, avoid=lambda: cluster).walk_to((20, 0))
    assert abs(result.arrived_at[0] - 20) <= 3, "the walk must still finish"
    for click in fake.clicks:
        for hazard in cluster:
            span = max(abs(click[0] - hazard[0]), abs(click[1] - hazard[1]))
            assert span >= AVOID_RADIUS, f"click {click} landed on {hazard}"


def test_being_boxed_in_still_produces_a_click():
    """A ring with no clear point inside it must not stop the walk.

    One click that might interact is recoverable — the loop re-plans and
    panels get closed. A walk that refuses to click is not: that is the
    failure that ended stage B's third attempt, and it is worse.
    """
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    ring = tuple(
        (10 + dx, dy) for dx in (-2, 0, 2) for dy in (-2, 0, 2)
    )
    result = navigator(world, sim, fake, avoid=lambda: ring).walk_to((20, 0))
    assert fake.clicks, "boxed in is not a reason to send nothing"
    assert abs(result.arrived_at[0] - 20) <= 3


# -- which units count as hazards at all (stage B run 3) --------------------------


def _hazards_for(monkeypatch, *, objects, allies, in_town, ground_items=None):
    """Run `live_navigator`'s hazard provider over a scripted snapshot."""
    from types import SimpleNamespace

    from pd2bot.navigate import live_navigator

    snap = SimpleNamespace(
        objects=objects, allies=allies, in_town=in_town,
        ground_items=ground_items or [],
    )
    monkeypatch.setattr(
        "pd2bot.perception.snapshot.Perception",
        lambda session: SimpleNamespace(snapshot=lambda: snap),
    )
    monkeypatch.setattr("pd2bot.navigate.GatedInput", lambda session: object())
    navigator = live_navigator(object(), store=None, difficulty=2)
    return set(navigator._avoid())


def _obj(kind, position):
    from types import SimpleNamespace

    return SimpleNamespace(kind=kind, position=position)


def _ally(position, *, is_alive=True, is_corpse=False):
    from types import SimpleNamespace

    return SimpleNamespace(
        position=position, is_alive=is_alive, is_corpse=is_corpse
    )


def test_decorative_scenery_is_not_a_hazard(monkeypatch):
    """The Cold Plains cluster: 15 objects of kinds 160/161/162 packed into
    ~12 subtiles, none of them clickable, which between them made the area
    unnavigable. Avoiding what cannot punish a click costs mobility for
    nothing — the same reasoning that already excludes monsters."""
    hazards = _hazards_for(
        monkeypatch,
        objects=[_obj(160, (10, 10)), _obj(161, (11, 11)), _obj(162, (12, 12))],
        allies=[],
        in_town=False,
    )
    assert hazards == set()


def test_the_waypoint_is_still_a_hazard(monkeypatch):
    from pd2bot.offsets import OBJ_WAYPOINT_A1

    """The narrowing must not lose the case it was built for: the character
    arrives standing ON the waypoint, and clicking it opens the menu."""
    hazards = _hazards_for(
        monkeypatch,
        objects=[_obj(OBJ_WAYPOINT_A1, (10, 10)), _obj(160, (11, 11))],
        allies=[],
        in_town=False,
    )
    assert hazards == {(10, 10)}


def test_allies_are_hazards_in_town_only(monkeypatch):
    """In town an ally is an NPC whose dialog blocks all input (R66/R78 —
    T12 opened Kashya's chat with travel clicks and looped). Outside town
    every ally is the merc or a summon, clicking one opens nothing, and a
    working necro is surrounded by seven of them exactly when movement
    matters most."""
    in_town = _hazards_for(
        monkeypatch, objects=[], allies=[_ally((5, 5))], in_town=True
    )
    in_field = _hazards_for(
        monkeypatch, objects=[], allies=[_ally((5, 5))], in_town=False
    )
    assert in_town == {(5, 5)}
    assert in_field == set()


# -- the sprite box (T83, 2026-08-08) ---------------------------------------------
#
# The fixture is the live measurement itself: Kashya at (5878, 5733), the
# merc at (5863, 5733), and the three travel clicks the drill recorded — all
# at world gap 6, all beyond AVOID_RADIUS, and only one of them fatal.

KASHYA = (5878, 5733)
MERC = (5863, 5733)
CLICK_BESIDE_MERC = (5869, 5733)      # 120 px right / 60 px below — harmless
CLICK_BESIDE_KASHYA = (5872, 5733)    # 120 px left  / 60 px above — harmless
CLICK_UP_KASHYAS_SPRITE = (5872, 5727)  # 0 px / 120 px ABOVE — opened npc_menu


def test_the_sprite_box_matches_what_the_game_actually_did():
    """The three measured clicks, classified. This is the whole fix in one
    assertion: identical world distance, opposite outcomes, and the box has
    to agree with the client rather than with Chebyshev."""
    from pd2bot.navigate import _inside_sprite

    assert _inside_sprite(KASHYA, CLICK_UP_KASHYAS_SPRITE), (
        "the click that opened her dialog is not being avoided"
    )
    assert not _inside_sprite(KASHYA, CLICK_BESIDE_KASHYA), (
        "a click 120 px to her side was harmless and must stay allowed"
    )
    assert not _inside_sprite(MERC, CLICK_BESIDE_MERC)


def test_world_distance_alone_cannot_tell_those_clicks_apart():
    """Why the radius could never have worked, stated as a test: the fatal
    click and a harmless one are the SAME Chebyshev distance away."""
    def cheb(a, b):
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

    assert cheb(KASHYA, CLICK_UP_KASHYAS_SPRITE) == 6
    assert cheb(KASHYA, CLICK_BESIDE_KASHYA) == 6
    assert 6 > AVOID_RADIUS  # both were already outside the old rule


def test_an_escape_never_goes_up_screen():
    """Up-screen is behind the unit and is the far wall of a box 150 px tall
    — and it is what the old world-space push chose when it produced the
    click that opened the dialog."""
    from pd2bot.navigate import _screen_offset, _sprite_escapes

    for escape in _sprite_escapes(KASHYA):
        _, sy = _screen_offset(KASHYA, escape)
        assert sy >= 0, f"escape {escape} is drawn above her feet"


def test_every_escape_actually_leaves_the_sprite():
    from pd2bot.navigate import _inside_sprite, _sprite_escapes

    for escape in _sprite_escapes(KASHYA):
        assert not _inside_sprite(KASHYA, escape)


def test_an_escape_also_clears_the_world_radius():
    """A sprite hazard is a world hazard too. An escape that cleared the
    box but sat inside `AVOID_RADIUS` would be rejected by the very next
    check, and the nudge would spin until it ran out of tries."""
    from pd2bot.navigate import _sprite_escapes

    for escape in _sprite_escapes(KASHYA):
        span = max(abs(escape[0] - KASHYA[0]), abs(escape[1] - KASHYA[1]))
        assert span >= AVOID_RADIUS, f"escape {escape} is inside the radius"


def test_a_click_up_a_sprite_is_nudged_out_of_it():
    """End to end through the nudge, with the measured geometry."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    nav = navigator(world, sim, fake, avoid=lambda: (KASHYA,))
    nav._sprites = lambda: (KASHYA,)
    result = WalkResult(target=KASHYA, arrived_at=(0, 0), duration_seconds=0.0,
                        waypoints=0)

    point, nudges = nav._nudged_click_point(CLICK_UP_KASHYAS_SPRITE, result)

    from pd2bot.navigate import _inside_sprite

    assert nudges >= 1
    assert not _inside_sprite(KASHYA, point)


def test_a_click_beside_a_sprite_is_left_alone():
    """The other half of the trade. Over-avoiding costs mobility, and the
    measurement says the sides were never the problem."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    nav = navigator(world, sim, fake, avoid=lambda: ())
    nav._sprites = lambda: (KASHYA,)
    result = WalkResult(target=(0, 0), arrived_at=(0, 0), duration_seconds=0.0,
                        waypoints=0)

    point, nudges = nav._nudged_click_point(CLICK_BESIDE_KASHYA, result)

    assert point == CLICK_BESIDE_KASHYA
    assert nudges == 0


def test_sprites_are_not_consulted_when_no_provider_is_wired():
    """Every existing caller — the CLI, the drills, the field — keeps the
    plain world rule until something hands it a sprite provider."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    nav = navigator(world, sim, fake, avoid=lambda: ())
    result = WalkResult(target=(0, 0), arrived_at=(0, 0), duration_seconds=0.0,
                        waypoints=0)

    assert nav._sprites is None
    assert nav._nudged_click_point(CLICK_UP_KASHYAS_SPRITE, result) == (
        CLICK_UP_KASHYAS_SPRITE, 0
    )


def test_the_goal_is_exempt_from_the_sprite_box_too():
    """Walking TO an NPC must stay possible: the thing we are deliberately
    approaching is not something to dodge, whatever shape it is."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    nav = navigator(world, sim, fake, avoid=lambda: ())
    nav._sprites = lambda: (KASHYA,)
    nav._goal = KASHYA
    result = WalkResult(target=KASHYA, arrived_at=(0, 0), duration_seconds=0.0,
                        waypoints=0)

    point, nudges = nav._nudged_click_point(CLICK_UP_KASHYAS_SPRITE, result)

    assert point == CLICK_UP_KASHYAS_SPRITE
    assert nudges == 0


def test_a_town_npc_is_a_hazard_whatever_its_hp_reads(monkeypatch):
    """The hazard rule must not rest on an unmeasured fact.

    A town NPC carries no combat stats (that is how she came to be
    misfiled as scenery on 2026-08-06), and whether her stat list carries
    HP at all is not something this repo has measured. `is_alive` reads a
    missing HP stat as dead, which would drop her from the hazard set and
    reproduce the misclick with everything else looking correct. Corpses
    are excluded upstream — `scan_units` files them in `corpses`, never in
    `allies` — so this rule asks the question it can actually answer.
    """
    hazards = _hazards_for(
        monkeypatch,
        objects=[],
        allies=[_ally((5, 5), is_alive=False, is_corpse=False)],
        in_town=True,
    )
    assert hazards == {(5, 5)}


def test_ground_items_are_hazards(monkeypatch):
    """Clicking a ground item picks it up — the same hazard class as a
    waypoint menu, and the one the user watched loop in stage B run 4: the
    cleanse drops junk at the character's feet, the next travel click lands
    on it, and it comes straight back into the inventory to be cleansed
    again. Deliberate pickups go through the executor's own click, not the
    navigator, so they are unaffected."""
    hazards = _hazards_for(
        monkeypatch,
        objects=[],
        allies=[],
        in_town=False,
        ground_items=[_obj(999, (7, 7))],
    )
    assert hazards == {(7, 7)}


def test_a_hazard_on_the_destination_does_not_block_arrival():
    """Stage B run 6, as a test.

    Ground items became hazards so a stray travel click would not scoop up
    the junk the cleanse had just dropped — and that immediately broke the
    opposite case. `collect` walks to an item's exact position to get in
    range, so every click was nudged off the very thing it was walking to
    and the bot could never reach anything it wanted.

    A hazard at the destination is not a hazard; it is the destination.
    """
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    target = (20, 0)
    result = navigator(world, sim, fake, avoid=lambda: (target,)).walk_to(target)
    assert abs(result.arrived_at[0] - 20) <= 3, "the walk must still arrive"
    assert not any("nudged" in line for line in result.log)


def test_an_item_merely_NEAR_the_destination_is_still_avoided():
    """The junk mechanism, measured on the first patrol run and fixed.

    The goal exemption is for the item `collect` is deliberately walking
    to — distance ZERO. Testing it against AVOID_RADIUS exempted anything
    within 3 subtiles of any destination, so a rune lying beside a patrol
    leg's endpoint stopped being avoided and the travel click scooped it.
    Of 39 goal-exempt clicks in one run, 31 were this; 21 landed inside
    the avoid radius and five landed exactly on an item.
    """
    from pd2bot.navigate import AVOID_MARGIN, AVOID_RADIUS

    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    goal = (20, 0)
    hazard = (22, 2)  # 2 from the goal: near it, emphatically not it
    result = navigator(world, sim, fake, avoid=lambda: (hazard,)).walk_to(goal)

    # Not one click near the item — that is the whole point.
    for click in fake.clicks:
        span = max(abs(click[0] - hazard[0]), abs(click[1] - hazard[1]))
        assert span >= AVOID_RADIUS, (
            f"click {click} landed {span} from an item beside the destination"
        )
    # And it STOPS SHORT rather than failing. Demanding arrival at a point
    # we deliberately refused to click is a guaranteed stuck, and turning
    # that into a NavigationError would cost the caller its target — which
    # is how "avoid items properly" would have become "cannot reach
    # anything near an item". Close enough is reported honestly; every
    # caller re-checks distance for itself.
    short = max(
        abs(result.arrived_at[0] - goal[0]), abs(result.arrived_at[1] - goal[1])
    )
    assert short <= AVOID_RADIUS + AVOID_MARGIN + 3, (
        f"stopped {short} short of {goal}, further than avoidance explains"
    )


def test_the_click_audit_sees_every_click_and_never_changes_one():
    """The instrument for the junk question, and it must be inert.

    Junk keeps arriving in the inventory behind ZERO deliberate pickups,
    so travel clicks are scooping ground items — but nobody knows whether
    AVOID_RADIUS is too tight or something bypasses it. The audit reports;
    it must not decide.
    """
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    seen = []
    hazard = (10, 0)
    result = navigator(
        world, sim, fake, avoid=lambda: (hazard,),
        audit=lambda point, goal, nudges: seen.append((point, goal, nudges)),
    ).walk_to((20, 0))

    assert len(seen) == len(fake.clicks), "every sent click must be audited"
    assert all(goal == (20, 0) for _point, goal, _n in seen)
    assert any(nudges > 0 for _p, _g, nudges in seen), "it saw the nudging"

    # And the walk is byte-identical without it.
    world2 = World()
    sim2 = Sim(world2)
    fake2 = FakeInput(world2)
    plain = navigator(world2, sim2, fake2, avoid=lambda: (hazard,)).walk_to((20, 0))
    assert fake2.clicks == fake.clicks
    assert plain.arrived_at == result.arrived_at


def test_a_failing_audit_cannot_break_a_walk():
    """Measurement is never worth a run. A broken probe stays a broken probe."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world)

    def explode(point, goal, nudges):
        raise RuntimeError("the probe is broken")

    result = navigator(world, sim, fake, audit=explode).walk_to((20, 0))
    assert abs(result.arrived_at[0] - 20) <= 3


def test_a_hazard_short_of_the_destination_is_still_avoided():
    """The narrowing must not disarm the mechanism generally: only what sits
    AT the goal is exempt, not everything on the way to it."""
    from pd2bot.navigate import AVOID_RADIUS

    world = World()
    sim = Sim(world)
    fake = FakeInput(world)
    hazard = (10, 0)  # on the route, far from the (20, 0) goal
    result = navigator(world, sim, fake, avoid=lambda: (hazard,)).walk_to((20, 0))
    assert any("nudged" in line for line in result.log)
    for click in fake.clicks:
        span = max(abs(click[0] - hazard[0]), abs(click[1] - hazard[1]))
        assert span >= AVOID_RADIUS


def test_a_refused_click_raises_even_when_the_budget_expires_first():
    """The NPC-misclick recovery keys on NavigationError.

    A travel click that lands on an NPC opens their dialog, and the
    dialog refuses every click after it. `town._walk_guarded` recovers
    from exactly that — close the panel, sidestep, re-walk — but only
    when it sees a `NavigationError`. The first cut of the walk budget
    returned quietly instead, so the walk came back merely "capped", no
    recovery ran, and the bot stood still until it gave up. Live
    2026-08-08: stuck 45 subtiles short of Akara, zero movement.

    A budget that silently swallows "I could not send anything" is worse
    than no budget: the caller cannot tell "did not arrive" from
    "cannot act at all".
    """
    world = World()
    sim = Sim(world)
    fake = FakeInput(world, refuse_first=1000)  # a dialog that never closes
    nav = navigator(world, sim, fake, walk_budget_s=2.0)
    with pytest.raises(NavigationError, match="refused"):
        nav.walk_to((20, 0))


def test_the_refusal_reason_survives_into_the_error():
    """The town layer reads the open panel from the game, but the trail
    has to say WHY for anyone reading the log afterwards."""
    world = World()
    sim = Sim(world)
    fake = FakeInput(world, refuse_first=1000)
    nav = navigator(world, sim, fake, walk_budget_s=2.0)
    with pytest.raises(NavigationError, match="esc_menu"):
        nav.walk_to((20, 0))
