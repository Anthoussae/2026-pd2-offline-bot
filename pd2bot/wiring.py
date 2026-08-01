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

from pd2bot import offsets
from pd2bot.behavior.combat import ClassConfig, load_class_config
from pd2bot.behavior.engine import BehaviorEngine, EngineConfig
from pd2bot.behavior.execute import GameActionExecutor
from pd2bot.behavior.necro import NecroCombat
from pd2bot.behavior.reflex import ReflexLadder, read_armor_ratio
from pd2bot.behavior.run import build_states, load_run
from pd2bot.behavior.runner import BehaviorRunner
from pd2bot.behavior.steps import RunServices, build_registry
from pd2bot.cycle import GameCycle
from pd2bot.input import GatedInput
from pd2bot.items import read_carried_items
from pd2bot.mapstore import MapStore
from pd2bot.memory import GameSession
from pd2bot.menuinput import MenuInput
from pd2bot.navigate import live_navigator
from pd2bot.panelinput import PanelInput
from pd2bot.pickit import Pickit, cleanse_keep, load_item_table, load_pickit
from pd2bot.player import read_player
from pd2bot.safety import SafetyConfig, SafetyMonitor
from pd2bot.snapshot import Perception
from pd2bot.town import PreambleReport, TownConfig, TownLayer
from pd2bot.uistate import find_ui_array
from pd2bot.waypoint import WaypointTravel

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config"
RUNS = REPO / "runs"

BELT_ROWS = 4  # a belt column holds 4 potions; capacity is columns x rows


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
    engine_config: EngineConfig = field(default_factory=EngineConfig)
    clock: Callable[[], float] = time.monotonic
    should_stop: Callable[[], bool] | None = None
    _engines: list[BehaviorEngine] = field(default_factory=list)

    @property
    def cleanse_enabled(self) -> bool:
        """False while the pickit vocabulary still has unresolved names —
        the whitelist cannot recognise what it must protect, so dropping is
        disabled outright rather than run with a hole in it."""
        return cleanse_keep(self.pickit) is not None

    def engine_factory(self, session: GameSession) -> BehaviorEngine:
        """Build one game's engine. Everything stateful is fresh here."""
        combat = NecroCombat(
            config=self.class_config.combat,
            is_walkable=self.is_walkable,
            clock=self.clock,
        )
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
        )
        services = RunServices(
            run_preamble=self.town.run_preamble,
            travel_to=self.waypoint.take,
            combat=combat,
            pickit=self.pickit,
            carried=lambda: read_carried_items(session, with_sockets=False),
            clock=self.clock,
            # The field cleanse: the same procedure the town preamble runs,
            # behind a closure so the step never learns what a TownLayer is.
            # None while the vocabulary is incomplete, and the step already
            # treats None as "unavailable" rather than as "nothing to do".
            cleanse=(
                (lambda: self.town.cleanse_inventory(PreambleReport()))
                if self.cleanse_enabled
                else None
            ),
        )
        registry = build_registry(services)
        run = load_run(self.paths.run, registry)
        return BehaviorEngine(
            snapshot=self.perception.snapshot,
            monitor=self.monitor,  # SESSION-scoped: the death latch is in it
            states=build_states(run, registry),
            executor=executor,
            ladder=ladder,
            combat=combat,
            config=self.engine_config,
            clock=self.clock,
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

        return BehaviorRunner(factory)

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
    navigator = live_navigator(session, MapStore(), difficulty)
    perception = Perception(session)
    baseline = SessionBaseline(session)

    town = TownLayer(
        session=session,
        gated=gated,
        panel=PanelInput(session, ui_array=ui_array),
        menu=MenuInput(session, ui_array=ui_array),
        walk_to=navigator.walk_to,
        snapshot=perception.snapshot,
        config=town_config_for(class_config, town_config),
        # The two halves of the cleanse, wired together or not at all.
        # `cleanse_keep` returns None while any keeper is unrecognised, and
        # a None whitelist disables dropping entirely — so a half-resolved
        # vocabulary switches the feature off rather than running it blind.
        keep_item=cleanse_keep(pickit),
        protected_ids=baseline,
        should_stop=should_stop,
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
        engine_config=engine_config if engine_config is not None else EngineConfig(),
        should_stop=should_stop,
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
    return [
        f"class      {bot.class_config.name} ({bot.paths.class_config.name})",
        f"run        {bot.paths.run.name}: {steps}",
        f"pickit     {len(bot.pickit.rules)} rules, "
        f"{len(bot.pickit.pending_names)} pending name(s)",
        f"cleanse    {'ENABLED' if bot.cleanse_enabled else 'disabled (pending names)'}",
        f"belt       {bot.class_config.belt.columns} -> capacity {capacity}",
        f"minimums   healing {bot.town.config.min_healing}, "
        f"mana {bot.town.config.min_mana}, rejuv {bot.town.config.min_rejuv}",
        f"chicken    {bot.monitor.config.life_chicken_pct:.0f}% life",
        f"idle bail  {bot.engine_config.idle_bail_s:.0f}s, "
        f"refusal limit {bot.engine_config.refusal_limit}",
    ]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - live only
    import argparse
    import sys

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
        "--dry-run", action="store_true",
        help="assemble and print the wiring, then exit without sending anything",
    )
    args = parser.parse_args(argv)

    try:
        paths = BotPaths() if args.run is None else replace(BotPaths(), run=args.run)
        bot = build_bot(paths=paths, chicken_life_pct=args.chicken)
    except (GameNotRunning, NeedsAdministrator, WindowNotFound) as exc:
        print(exc, file=sys.stderr)
        return 1

    for line in describe(bot):
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
