"""Production assembly: the one place the real bot is put together.

Every layer below this is written to be injected into, and until now only
the sim and the drills ever did the injecting. That is exactly why the P5b
review's findings clustered where they did: the code is correct when
assembled correctly, and nothing had yet been responsible for assembling it
correctly. This module is that responsibility.

**Session-scoped vs per-game.** The split is not a style choice, and getting
it backwards breaks things in both directions:

- The `SafetyMonitor` is built ONCE per session because the death latch is
  instance state. A fresh monitor per game would clear it, and its own
  comment says why that must never happen — "a re-created game must not
  resurrect the bot's confidence".
- The `TownLayer` is built once too, so the cleanse's protected baseline is
  genuinely session-wide rather than re-captured each game (which would
  re-protect whatever the bot picked up last game, forever).
- Everything with per-run bookkeeping is built FRESH per game: the combat
  module (`_last_strike` grows one entry per monster ever struck), the
  ladder's cooldowns, the executor's trace, and `RunServices`' pickup
  memory. Review 005 flagged all four as unbounded across a session; a
  per-game lifetime is what bounds them.

The item vocabulary, the pickit and the class config are read once at
startup and shared: they are immutable data, and re-reading them per game
would let a mid-session edit take effect halfway through, which is a
debugging experience nobody wants.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from pd2bot import mapframe, offsets, survey
from pd2bot.behavior.combat import ClassConfig, load_class_config
from pd2bot.behavior.engine import BehaviorEngine, EngineConfig
from pd2bot.behavior.execute import GameActionExecutor
from pd2bot.behavior.necro import NecroCombat
from pd2bot.behavior.reflex import ReflexLadder, read_armor_ratio
from pd2bot.behavior.run import build_states, default_registry, load_run
from pd2bot.behavior.runner import BehaviorRunner
from pd2bot.behavior.steps import RunServices, build_registry
from pd2bot.chat import Chat
from pd2bot.cycle import GameCycle
from pd2bot.exits import ExitMemory, read_level_exits
from pd2bot.input import GatedInput
from pd2bot.items import read_carried_items
from pd2bot.mapstore import MapStore
from pd2bot.memory import GameSession
from pd2bot.menuinput import MenuInput
from pd2bot.narrate import Narrator
from pd2bot.navigate import live_navigator
from pd2bot.panelinput import PanelInput
from pd2bot.pathing import astar, nearest_walkable, simplify
from pd2bot.pickit import Pickit, cleanse_keep, load_item_table, load_pickit
from pd2bot.player import read_player
from pd2bot.runlog import RunLog
from pd2bot.safety import SafetyConfig, SafetyMonitor
from pd2bot.snapshot import Perception
from pd2bot.town import PreambleReport, TownConfig, TownLayer
from pd2bot.uistate import find_ui_array
from pd2bot.waypoint import WaypointTravel
from pd2bot.world import read_area, read_map_seed

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config"
RUNS = REPO / "runs"

# A belt column holds 4 potions; capacity is columns x rows. One source:
# the same constant the town layer's capacity accounting reads (P1, R179).
BELT_ROWS = offsets.BELT_ROWS


class WiringError(RuntimeError):
    """The bot cannot be assembled safely; the message says what is missing."""


# -- the pieces the checklist names ----------------------------------------------


def belt_capacity(class_config: ClassConfig) -> dict[str, int]:
    """Belt capacity per potion type, DERIVED from the class config.

    The pickit's potion rules ask "is the belt full of this type yet?" and
    the answer depends on the R53 layout — healing owns two columns, so its
    capacity is double. `pickit.DEFAULT_BELT_CAPACITY` hardcodes the necro's
    answer so a bare `Pickit` behaves; this is the authority, and deriving
    it means a layout change cannot leave the two disagreeing.
    """
    return {
        potion_type: BELT_ROWS
        * sum(1 for column in class_config.belt.columns if column == potion_type)
        for potion_type in ("healing", "mana", "rejuv")
    }


def town_config_for(class_config: ClassConfig, base: TownConfig | None = None) -> TownConfig:
    """A `TownConfig` whose belt minimums come from the class config.

    Both types carry min_healing/min_mana/min_rejuv, which is one number in
    two files — the shape review 004 flagged for the potion reserve. The
    wiring cannot merge the types, but it can make sure only ONE of them is
    ever the source, and the class config is the one the user tunes.
    """
    base = base if base is not None else TownConfig()
    return replace(
        base,
        min_healing=class_config.belt.min_healing,
        min_mana=class_config.belt.min_mana,
        min_rejuv=class_config.belt.min_rejuv,
    )


def route_service(
    navigator,
) -> Callable[[tuple[int, int]], list[tuple[int, int]] | None]:
    """`route_to(target)` for RunServices (R181): the same A* the
    navigator walks with, exposed READ-ONLY so steps can ask "is there a
    route, and which way?" before spending legs at a fence.

    Returns the simplified waypoint list, or None when the map says no
    path exists — the steps' instant write-off signal. Cached per
    (origin bucket, target): a route survives the few legs walked inside
    one 8-subtile bucket, because re-planning every tick is the tick-rate
    waste this repo keeps refusing; the atlas only grows, so a briefly
    stale route is at worst conservative. An unreadable position answers
    "walk straight" (`[target]`) rather than None — a torn read must not
    write a target off.
    """
    cache: dict = {"key": None, "route": None}

    def route_to(target: tuple[int, int]) -> list[tuple[int, int]] | None:
        try:
            start = navigator.position()
        except Exception:
            return [target]
        key = ((start[0] // 8, start[1] // 8), target)
        if cache["key"] == key:
            return cache["route"]
        # The grid is assembled only on a cache MISS: stitching live
        # collision over the atlas is the expensive half of a plan.
        try:
            grid = navigator.grid()
        except Exception:
            return [target]
        route: list[tuple[int, int]] | None = None
        goal = nearest_walkable(grid, *target)
        if goal is not None:
            path = astar(grid, start, goal)
            if path is not None:
                route = simplify(grid, path)
        if route is not None:
            # None is deliberately NOT cached (T55 run 1): a torn live
            # collision read walled the origin in for ~a second and five
            # ring points the clearance had just WALKED got "no route" —
            # the offline atlas paths all of them in <70 ms. A cached
            # None would hand the callers' confirmation retry the same
            # wrong answer for free; recomputing it re-reads the grid,
            # which is exactly the point.
            cache["key"] = key
            cache["route"] = route
        return route

    return route_to


def walkability(navigator) -> Callable[[tuple[int, int]], bool]:
    """The `is_walkable(point)` predicate the ladder and combat module take.

    Both use it the same way: to check that somewhere they are about to
    retreat or warp to is real ground. So it asks the navigator for a FRESH
    grid each call — the atlas grows as rooms load, and a cached grid would
    keep saying "unknown" about ground the character can now see.

    `is_known` is checked first because unknown is not walkable and the two
    are different questions (`collision.py`): a cell we have never read must
    read False here, or blood warp would be aimed into ground nobody has
    ever seen — burning the cast, the mana and 12% of max hp for a teleport
    the game refuses.

    An unreadable grid answers False rather than raising. These are callers
    with a fallback — "this escape is not available" is a decision the
    ladder already knows how to make — and mid-load is exactly when both a
    read fails and an escape is most likely to be wanted.
    """

    def is_walkable(point: tuple[int, int]) -> bool:
        try:
            grid = navigator.grid()
            return grid.is_known(*point) and grid.is_walkable(*point)
        except Exception:
            return False

    return is_walkable


class SessionBaseline:
    """Unit ids the character was already carrying when the bot started.

    The cleanse exists to clean up the bot's OWN accidents, so anything that
    predates it is protected (R128). `TownLayer` will capture this itself if
    nobody supplies it, but that implicit version is "a floor, not the goal"
    (review 001): it is captured per TownLayer, so a wiring that built one
    per game would re-baseline every game and protect last game's junk
    forever. Supplying it explicitly says the intent out loud and survives
    someone later moving construction into the per-game factory.

    Capture is LAZY and gated on being in a game. Out of a game the
    inventory reads empty, and an empty baseline does not mean "protect
    nothing" — it means "we did not look". Handing that to the cleanse is
    precisely the silent worst case issue 001 was written about, so it
    raises instead.
    """

    def __init__(
        self,
        session: GameSession,
        *,
        carried: Callable[[GameSession], object] = read_carried_items,
        read_player_fn: Callable[[GameSession], object] = read_player,
    ) -> None:
        self._session = session
        self._carried = carried
        self._read_player = read_player_fn
        self._ids: set[int] | None = None

    @property
    def captured(self) -> bool:
        return self._ids is not None

    def __call__(self) -> set[int]:
        if self._ids is None:
            if self._read_player(self._session) is None:
                raise WiringError(
                    "refusing to take the cleanse baseline outside a game: "
                    "the inventory reads empty there, and an empty baseline "
                    "protects nothing rather than everything"
                )
            self._ids = {
                item.unit_id
                for item in self._carried(self._session).main_inventory
            }
        return self._ids


# -- the session ------------------------------------------------------------------


@dataclass(frozen=True)
class BotPaths:
    """Where the data files live. Overridable so drills can point elsewhere."""

    class_config: Path = CONFIG / "necro.toml"
    pickit: Path = CONFIG / "pickit.toml"
    item_table: Path = CONFIG / "item_ids.toml"
    run: Path = RUNS / "cold-plains.toml"


@dataclass
class LiveBot:
    """Everything session-scoped, assembled once and reused across games."""

    session: GameSession
    class_config: ClassConfig
    pickit: Pickit
    town: TownLayer
    waypoint: WaypointTravel
    monitor: SafetyMonitor
    navigator: object
    is_walkable: Callable[[tuple[int, int]], bool]
    perception: Perception
    gated: GatedInput
    baseline: SessionBaseline
    paths: BotPaths
    # The atlas store and the difficulty it is keyed under — the survey
    # service reads both; the navigator holds the same store instance.
    store: MapStore = field(default_factory=MapStore)
    difficulty: int = offsets.DIFFICULTY_HELL
    engine_config: EngineConfig = field(default_factory=EngineConfig)
    clock: Callable[[], float] = time.monotonic
    should_stop: Callable[[], bool] | None = None
    # `--radius`, applied to every clear_radius step at engine-build time.
    # None means "whatever the run file says".
    radius_override: int | None = None
    # The narrative channel's indirection (R179). The town layer is
    # SESSION-scoped and the Narrator is PER-RUN (one file per run), so the
    # town holds a closure that reads this holder, and each engine build
    # points it at the fresh run's narrator. build_bot wires the closure;
    # engine_factory swaps the target.
    narrate_ref: dict = field(default_factory=lambda: {"fn": None})
    _engines: list[BehaviorEngine] = field(default_factory=list)
    # Every run log opened this session, newest last — so a drill can name
    # the file it just produced instead of the operator hunting for it.
    _runlogs: list[object] = field(default_factory=list)

    @property
    def cleanse_enabled(self) -> bool:
        """False while the pickit vocabulary still has unresolved names —
        the whitelist cannot recognise what it must protect, so dropping is
        disabled outright rather than run with a hole in it."""
        return cleanse_keep(self.pickit) is not None

    def pickit_item_name(self, kind: int) -> str | None:
        """kind -> the verified item name, or None (never a guess).

        Routed through the pickit's own `ItemTable`, which is anchored to
        D2 item CODES rather than to numbers (R144). A second naming path
        is precisely how a Wire Fleece came to be picked up as a Kraken
        Shell, so the log gets the same table or nothing.
        """
        table = getattr(self.pickit, "item_table", None)
        if table is None:
            return None
        try:
            return table.name_for(kind)
        except Exception:  # noqa: BLE001
            return None

    def run_header(self, session: GameSession) -> dict:
        """What the run.json header records: enough to tell two runs apart
        and to know what the bot believed when it started."""
        header: dict = {
            "run_file": str(self.paths.run),
            "class_config": str(self.paths.class_config),
            "chicken_life_pct": self.class_config.chicken_life_pct,
            "tick_interval_s": self.engine_config.tick_interval_s,
            "idle_bail_s": self.engine_config.idle_bail_s,
            "wait_bail_s": self.engine_config.wait_bail_s,
        }
        # Best effort, and labelled when it fails: a header that guessed
        # the seed would make two different maps look like one.
        try:
            header["map_seed"] = read_map_seed(session)
        except Exception:  # noqa: BLE001
            header["map_seed"] = None
            header["map_seed_unread"] = True
        try:
            player = read_player(session)
            if player is not None:
                header["character"] = player.name
                header["level"] = player.level
        except Exception:  # noqa: BLE001
            header["character"] = None
        return header

    def engine_factory(self, session: GameSession) -> BehaviorEngine:
        """Build one game's engine. Everything stateful is fresh here."""
        # One narrative file per run (R179). Constructing the Narrator
        # writes nothing — the file appears on the first narrated line —
        # so the throwaway engine `describe` builds for pre-flight leaves
        # no empty log behind.
        narrator = Narrator(REPO / "logs", clock=self.clock)
        self.narrate_ref["fn"] = narrator.narrate
        # The run event log (R220 Q11: MANDATORY, never opt-in). Opened
        # per run alongside the narrative, which keeps its own job: the
        # narrative is the story a human skims, this is the record a tool
        # queries. Optional instrumentation means the one run you most
        # need to explain is the one where somebody forgot the flag —
        # which is not hypothetical, it is T71.
        runlog = RunLog(
            self.paths.run.stem,
            root=REPO / "logs" / "runs",
            clock=self.clock,
            header=self.run_header(session),
        )
        self._runlogs.append(runlog)
        # The monitor is SESSION-scoped (the death latch lives in it), so
        # it cannot be constructed per run — repoint its log instead, the
        # same treatment `narrate_ref` gets for the town layer.
        self.monitor.runlog = runlog
        # The town layer is session-scoped too (its cleanse baseline must
        # be), so it takes the same treatment. The waypoint layer reads
        # the log through it rather than holding a second reference —
        # one holder, one place to repoint.
        self.town.runlog = runlog
        # The area frame the log's coordinates are relative to. Read per
        # call rather than cached: the area changes under the bot, and a
        # stale frame would silently shift every local coordinate.
        def frame():
            try:
                return mapframe.MapFrame.from_area(read_area(session))
            except Exception:  # noqa: BLE001 - honest fallback, never a guess
                return mapframe.MapFrame.unknown()

        combat = NecroCombat(
            config=self.class_config.combat,
            is_walkable=self.is_walkable,
            clock=self.clock,
            # The named presets (M6 P3): run steps select per step, the
            # module swaps configs, bookkeeping survives the swap.
            postures=self.class_config.postures,
        )
        # Futile-strike write-offs reach the run log (T72/T74). Recorded
        # rather than acted on across runs, deliberately: the "immune"
        # signature belongs to THIS spawn (Hell rolls immunities per
        # pack), so generalising it to the monster's kind would teach the
        # bot to skip killable monsters. Only the "no-contact" signature
        # is a candidate for a durable per-kind rule, and promoting one
        # is a human decision — the item_ids.learned.toml precedent.
        def note_write_off(**fields):
            runlog.event("combat.write_off", **fields)

        combat.note_write_off = note_write_off
        ladder = ReflexLadder(
            self.class_config.reflex,
            # with_sockets=False: this runs EVERY TICK and only ever reads
            # the belt, so it must not pay for a stat read per inventory
            # item. The cleanse is the only consumer that needs sockets and
            # it goes through the town layer, which takes the default (R132).
            carried=lambda: read_carried_items(session, with_sockets=False),
            armor_ratio=lambda: read_armor_ratio(session),
            is_walkable=self.is_walkable,
            combat_upkeep=lambda snap: combat.upkeep(snap),
            clock=self.clock,
        )
        executor = GameActionExecutor(
            session=session,
            gated=self.gated,
            walk_to=self.navigator.walk_to,
            hotkeys=self.class_config.hotkeys,
            clock=self.clock,
            # Right-skill parking (M6 P3, user note 1): after a cast
            # burst, switch back to the armor skill so Revive never stays
            # the active right skill (selectable corpses interfere with
            # pathing and pickup).
            park_skill_id=self.class_config.reflex.armor_skill_id,
            park_grace_s=self.class_config.combat.park_grace_s,
            # Instrumentation (the run-event-log plan, P3): every action
            # that reaches the game becomes an event with all three
            # coordinate frames. The name tables are the EXISTING
            # code-anchored ones — never a second guessing path (R144).
            runlog=runlog,
            frame=frame,
            skill_names={
                skill_id: name
                for name, skill_id in self.class_config.skills.items()
            },
            item_names=self.pickit_item_name,
        )
        def field_cleanse() -> int:
            """The town cleanse, run in the field — and its report SURFACED.

            The report used to be constructed here and thrown away with the
            call (`lambda: self.town.cleanse_inventory(PreambleReport())`),
            which meant the field cleanse was silent even about dropping
            things. That is half of why the user could not tell a run where
            junk reached the stash from one where the cleanse found nothing
            to drop: in town the lines reach the preamble report, and out
            here they reached nobody at all.
            """
            report = PreambleReport()
            dropped = self.town.cleanse_inventory(report)
            for line in report.log:
                print(f"  field {line}", flush=True)
            return dropped

        # The survey service (R175/R176): frontier targets and coverage over
        # the shared atlas, behind closures so the step never learns what a
        # MapStore is. The target list is cached per (seed, area,
        # content REVISION — not room count, which a re-recorded room with
        # changed terrain leaves unchanged; session-review issue 003):
        # frontier extraction walks every stored room edge, and
        # recomputing that on a tick where nothing new was recorded
        # would be pure heat.
        survey_cache: dict = {"key": None, "targets": []}

        def _survey_area():
            area = read_area(session)
            seed = read_map_seed(session)
            if area is None or seed is None:
                return None, None
            return area, self.store.open(seed, self.difficulty, area.level_no)

        def survey_targets() -> list[tuple[int, int]]:
            area, explored = _survey_area()
            if area is None:
                return []  # mid-transition: nothing to walk toward yet
            key = (explored.seed, explored.area_id, explored.revision)
            if survey_cache["key"] != key:
                survey_cache["key"] = key
                survey_cache["targets"] = survey.frontier_targets(
                    explored, area.bounds_subtiles
                )
            return list(survey_cache["targets"])

        def survey_coverage() -> str:
            area, explored = _survey_area()
            if area is None:
                return "area unreadable"
            return survey.coverage(explored, area.bounds_subtiles)

        # The kill-switch correlation (R189): field-side, the bot's ONE
        # ESC sender is this closure; stamping it lets the engine tell
        # the bot's own escape from the operator's.
        escape_stamp: dict = {"at": None}

        def clear_panels_tracked() -> None:
            escape_stamp["at"] = self.clock()
            self.town.close_panels()

        # The traverse services (M6 P2): the live exit reader, and the
        # exit memory keyed by (seed, difficulty, area, dest) — the seed
        # read live per call so the closures never go stale across games.
        exit_memory = ExitMemory(self.store.root / "exits.json")

        def exit_recall(area: int, dest: int) -> tuple[int, int] | None:
            seed = read_map_seed(session)
            if seed is None:
                return None
            return exit_memory.recall(seed, self.difficulty, area, dest)

        def exit_remember(
            area: int, dest: int, position: tuple[int, int]
        ) -> None:
            seed = read_map_seed(session)
            if seed is not None:
                exit_memory.remember(
                    seed, self.difficulty, area, dest, position
                )

        services = RunServices(
            run_preamble=self.town.run_preamble,
            travel_to=self.waypoint.take,
            combat=combat,
            postures=frozenset(self.class_config.postures),
            level_exits=lambda: read_level_exits(session),
            exit_recall=exit_recall,
            exit_remember=exit_remember,
            pickit=self.pickit,
            carried=lambda: read_carried_items(session, with_sockets=False),
            clock=self.clock,
            survey_targets=survey_targets,
            survey_coverage=survey_coverage,
            # The field cleanse: the same procedure the town preamble runs,
            # behind a closure so the step never learns what a TownLayer is.
            # None while the vocabulary is incomplete, and the step already
            # treats None as "unavailable" rather than as "nothing to do".
            cleanse=(field_cleanse if self.cleanse_enabled else None),
            # The same retried ESC the town layer has used since R85, made
            # available in the field — where a panel is worse, because
            # nothing out there opens one deliberately and every send is
            # refused until it closes.
            clear_panels=clear_panels_tracked,
            narrate=narrator.narrate,
            route_to=route_service(self.navigator),
            runlog=runlog,
            frame=frame,
        )
        registry = build_registry(services)
        run = load_run(self.paths.run, registry)
        if self.radius_override is not None:
            run = run.with_radius(self.radius_override)
        return BehaviorEngine(
            snapshot=self.perception.snapshot,
            monitor=self.monitor,  # SESSION-scoped: the death latch is in it
            states=build_states(run, registry),
            executor=executor,
            ladder=ladder,
            combat=combat,
            config=self.engine_config,
            clock=self.clock,
            narrate=narrator.narrate,
            # The outside stop order (drill abort, operator request):
            # polled at the top of every tick, so a chat abort takes
            # effect within one tick wherever the run is — the town
            # layer's waits were previously the ONLY place this was
            # consulted (T54 run 3).
            should_stop=self.should_stop,
            # The Enter/ESC kill switch (R189): the operator's own keys
            # stop the run, correlated against the stamp above.
            bot_escape_at=lambda: escape_stamp["at"],
            runlog=runlog,
            frame=frame,
        )

    def engines(self) -> list[BehaviorEngine]:
        """Every engine built this session, newest last.

        Kept because the run's whole value at stage B is its DECISION TRACE
        — the phase file asks for it explicitly, to compare against the sim
        — and until now a completed run printed one line of cycle summary
        and threw the rest away. Run 4 finished the first end-to-end Cold
        Plains clear and left no record of what it decided.
        """
        return self._engines

    def runner(self) -> BehaviorRunner:
        def factory(session: GameSession) -> BehaviorEngine:
            engine = self.engine_factory(session)
            self._engines.append(engine)
            return engine

        # The operator watches the GAME, not the console (R164). A run that
        # simply stops leaves them guessing whether it is thinking, stuck,
        # or done — the same reason drills have announced themselves in
        # chat since R95.
        return BehaviorRunner(factory, announce=Chat(self.session).say)

    def cycle(self) -> GameCycle:
        return GameCycle(self.session, MenuInput(self.session))


def build_bot(
    session: GameSession | None = None,
    *,
    paths: BotPaths | None = None,
    difficulty: int = offsets.DIFFICULTY_HELL,
    engine_config: EngineConfig | None = None,
    town_config: TownConfig | None = None,
    chicken_life_pct: float | None = None,
    should_stop: Callable[[], bool] | None = None,
    radius_override: int | None = None,
) -> LiveBot:
    """Assemble the real bot against a live client.

    `chicken_life_pct` overrides the class config's number, which is what
    P6's staged ladder needs: stage B runs at 50% and only comes down to the
    R49 default as stages pass. Nothing else in the safety stack is
    overridable from here on purpose.
    """
    paths = paths if paths is not None else BotPaths()
    session = session if session is not None else GameSession()
    ui_array = find_ui_array(session)

    class_config = load_class_config(paths.class_config)
    pickit = load_pickit(
        paths.pickit,
        item_table=load_item_table(paths.item_table),
        belt_capacity=belt_capacity(class_config),
    )

    gated = GatedInput(session, ui_array=ui_array)
    # The store is kept on the bot (not just inside the navigator's
    # closures) because the survey service reads coverage from it — one
    # store, or the survey would report on an atlas nobody is writing to.
    store = MapStore()
    navigator = live_navigator(session, store, difficulty)
    perception = Perception(session)
    baseline = SessionBaseline(session)

    # The narrative dispatch (R179): the town layer outlives any one run,
    # so it narrates through this holder and each engine build repoints it
    # at the fresh run's Narrator (see LiveBot.narrate_ref).
    narrate_ref: dict = {"fn": None}

    def town_narrate(text: str) -> None:
        fn = narrate_ref["fn"]
        if fn is not None:
            fn(text)

    town = TownLayer(
        session=session,
        gated=gated,
        panel=PanelInput(session, ui_array=ui_array),
        menu=MenuInput(session, ui_array=ui_array),
        walk_to=navigator.walk_to,
        snapshot=perception.snapshot,
        config=town_config_for(class_config, town_config),
        # Both readers, named here rather than defaulted, because the split
        # is the whole point (review 003): every verification loop in the
        # layer polls the cheap one at 10 Hz, and only the cleanse's
        # socket-conditioned whitelist pays for the stat reads. Wired
        # together so neither can be silently the other.
        carried=lambda s: read_carried_items(s, with_sockets=False),
        carried_with_sockets=read_carried_items,
        # The two halves of the cleanse, wired together or not at all.
        # `cleanse_keep` returns None while any keeper is unrecognised, and
        # a None whitelist disables dropping entirely — so a half-resolved
        # vocabulary switches the feature off rather than running it blind.
        keep_item=cleanse_keep(pickit),
        protected_ids=baseline,
        should_stop=should_stop,
        narrate=town_narrate,
    )
    monitor = SafetyMonitor(
        session,
        SafetyConfig(
            life_chicken_pct=(
                class_config.chicken_life_pct
                if chicken_life_pct is None
                else chicken_life_pct
            )
        ),
    )
    return LiveBot(
        session=session,
        class_config=class_config,
        pickit=pickit,
        town=town,
        waypoint=WaypointTravel(session=session, interact=town, ui_array=ui_array),
        monitor=monitor,
        navigator=navigator,
        is_walkable=walkability(navigator),
        perception=perception,
        gated=gated,
        baseline=baseline,
        paths=paths,
        store=store,
        difficulty=difficulty,
        engine_config=engine_config if engine_config is not None else EngineConfig(),
        should_stop=should_stop,
        radius_override=radius_override,
        narrate_ref=narrate_ref,
    )


# -- CLI ---------------------------------------------------------------------------


def describe(bot: LiveBot) -> list[str]:
    """What the wiring resolved to, for the operator to check BEFORE a run.

    Every line here is something that was silently defaultable before this
    module existed. Printing them is cheap; discovering one of them was
    wrong from the game's behaviour is not.
    """
    capacity = bot.pickit.belt_capacity
    # Build one throwaway engine. It sends nothing — the engine is inert
    # until ticked — but constructing it is what proves the run file, the
    # step registry and every per-game collaborator actually assemble. Left
    # out, the first thing to discover a missing step factory would be a
    # created Hell game, and by then the character is standing in it.
    steps = ", ".join(bot.engine_factory(bot.session).step_names)
    # The EFFECTIVE radius, read back after any --radius override rather
    # than echoed from the flag: the number printed here is the number the
    # run will use, which is the only version worth checking pre-flight.
    # `default_registry` carries the same parameter schemas as the wired
    # one and needs no collaborators, which is the whole reason it exists.
    run = load_run(bot.paths.run, default_registry())
    if bot.radius_override is not None:
        run = run.with_radius(bot.radius_override)
    radius = run.radius
    return [
        f"class      {bot.class_config.name} ({bot.paths.class_config.name})",
        f"run        {bot.paths.run.name}: {steps}",
        f"clearance  radius {radius}"
        + (" (--radius override)" if bot.radius_override is not None else "")
        if radius is not None
        else "clearance  no clear_radius step in this run",
        # The sweep takes no parameters of its own — it adopts the
        # clearance's circle off the blackboard — so without this line the
        # pre-flight would say nothing at all about how far it will look,
        # and "radius 96" would read as applying only to the killing.
        "sweep      follows the clearance (same centre, radius and patrol)"
        if radius is not None
        else "sweep      no clearance to follow; sweeps from where it stands",
        # Atlas coverage matters exactly when a survey step is present:
        # the run's whole product is that number moving.
        *(
            [f"survey     atlas root {bot.store.root} (d{bot.difficulty}); "
             "fights only within "
             "survey_engage_radius; coverage reported at the end"]
            if "survey" in steps
            else []
        ),
        f"pickit     {len(bot.pickit.rules)} rules, "
        f"{len(bot.pickit.pending_names)} pending name(s)",
        f"cleanse    {'ENABLED' if bot.cleanse_enabled else 'disabled (pending names)'}",
        f"belt       {bot.class_config.belt.columns} -> capacity {capacity}",
        f"minimums   healing {bot.town.config.min_healing}, "
        f"mana {bot.town.config.min_mana}, rejuv {bot.town.config.min_rejuv}",
        f"chicken    {bot.monitor.config.life_chicken_pct:.0f}% life",
        f"idle bail  {bot.engine_config.idle_bail_s:.0f}s "
        f"(declared wait {bot.engine_config.wait_bail_s:.0f}s), "
        f"refusal limit {bot.engine_config.refusal_limit}",
    ]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - live only
    import argparse
    import sys

    from pd2bot.behavior.run import RunError
    from pd2bot.memory import GameNotRunning, NeedsAdministrator
    from pd2bot.window import WindowNotFound

    parser = argparse.ArgumentParser(
        description="Run the bot: create a Hell game, run the run, leave, repeat."
    )
    parser.add_argument("--games", type=int, default=1, help="how many games")
    parser.add_argument(
        "--chicken", type=float, default=None,
        help="override the class config's life chicken %% (P6 stages B/C)",
    )
    parser.add_argument(
        "--run", type=Path, default=None, help="run file (default: cold-plains)"
    )
    parser.add_argument(
        "--radius", type=int, default=None,
        help="override the run's clear_radius radius (P6 staged acceptance)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="assemble and print the wiring, then exit without sending anything",
    )
    args = parser.parse_args(argv)

    try:
        paths = BotPaths() if args.run is None else replace(BotPaths(), run=args.run)
        bot = build_bot(
            paths=paths,
            chicken_life_pct=args.chicken,
            radius_override=args.radius,
        )
    except (GameNotRunning, NeedsAdministrator, WindowNotFound) as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        lines = describe(bot)
    except RunError as exc:
        # Most likely `--radius` against a run with nothing to apply it
        # to. Refusing beats running the unmodified file: a flag that
        # appears to work and silently does not is the class of failure
        # this project keeps paying for.
        print(exc, file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    if args.dry_run:
        return 0
    if not bot.cleanse_enabled:
        print(
            "\nnote: the inventory cleanse is OFF because the pickit still "
            "names unresolved items; junk will be stashed, not dropped."
        )

    report = bot.cycle().run_games(bot.runner(), max_games=args.games)
    print(f"\n{report.summary() if hasattr(report, 'summary') else report}")
    for index, engine in enumerate(bot.engines(), start=1):
        print(f"\n--- game {index}: {engine.report.summary()} ---")
        for line in engine.report.log:
            print(f"  {line}")
        # The engine's log records reflex fires and step completions; what
        # it CANNOT show is whether the bot ever swung. Run 8 finished the
        # whole Cold Plains pipeline and left no evidence either way, which
        # is the one question stage B exists to answer.
        trace = getattr(engine._executor, "trace", None)
        if trace:
            counts: dict[str, int] = {}
            for entry in trace:
                counts[type(entry.action).__name__] = (
                    counts.get(type(entry.action).__name__, 0) + 1
                )
            print(f"  actions sent: {counts}")
            for entry in trace:
                print(f"    {type(entry.action).__name__}: {entry.detail}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
