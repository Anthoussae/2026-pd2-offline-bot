"""The follow loop as a state machine, against a scripted world.

No game, no clock: virtual time advances only inside `sleep`, and the fake
world moves the player toward the last clicked destination at a fixed
speed. What is under test is the escalation ladder — arrive, re-click,
re-plan, give up — and the UI-refusal waiting.
"""

import pytest

from pd2bot.input import InputRefused
from pd2bot.navigate import (
    MAX_FAILURES,
    NavigationError,
    Navigator,
    pick_reachable_target,
)


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


def navigator(world, sim, fake_input, grid_provider=None, avoid=None):
    return Navigator(
        position_reader=world.position,
        gated_input=fake_input,
        grid_provider=grid_provider or (lambda: OpenGrid()),
        clock=sim.clock,
        sleep=sim.sleep,
        avoid_provider=avoid,
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
        "pd2bot.snapshot.Perception",
        lambda session: SimpleNamespace(snapshot=lambda: snap),
    )
    monkeypatch.setattr("pd2bot.navigate.GatedInput", lambda session: object())
    navigator = live_navigator(object(), store=None, difficulty=2)
    return set(navigator._avoid())


def _obj(kind, position):
    from types import SimpleNamespace

    return SimpleNamespace(kind=kind, position=position)


def _ally(position):
    from types import SimpleNamespace

    return SimpleNamespace(position=position, is_alive=True)


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
