"""A scripted Cold Plains, honest enough to be worth failing against.

This is P5's exit test and the go/no-go artifact: the WHOLE behavior stack —
the real engine, the real reflex ladder with the real `config/necro.toml`
numbers, the real necro module, the real steps, the real pickit, and the
real `SafetyMonitor` — driven over a fake game that reacts the way the
client would.

The design rule, learned the expensive way in P3 (nearly every live failure
was an instrument lying, not the game): **the sim must be able to say no.**
A fake that grants every request proves only that the code can ask. So this
one:

- kills monsters by POISON over time, not on the strike, so the module's
  "don't re-stab a dying monster" logic has something to be right about;
- leaves a corpse only where something actually died;
- refuses to let one item be picked up, ever, so the inventory-full guard
  is exercised by a real refusal rather than by a flag someone set;
- makes the hotkey press a REQUEST — the right-skill slot changes only
  because the fake decides it does, so `ensure_right_skill`'s read-back is
  doing real work and a cast on an unverified skill would be visible;
- deals damage on a schedule the bot does not control.

Run it directly to print the decision trace:

    python -m tests.simworld
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pd2bot import offsets
from pd2bot.behavior.actions import (
    Action,
    AttackUnit,
    CastAtPoint,
    CastSelf,
    DrinkPotion,
    InteractObject,
    MoveTo,
    PickUpItem,
)
from pd2bot.behavior.combat import load_class_config
from pd2bot.behavior.engine import BehaviorEngine, EngineConfig
from pd2bot.behavior.execute import GameActionExecutor
from pd2bot.behavior.necro import NecroCombat
from pd2bot.behavior.reflex import ReflexLadder
from pd2bot.behavior.run import build_states, load_run
from pd2bot.behavior.steps import RunServices, build_registry
from pd2bot.nav.mapframe import MapFrame
from pd2bot.perception.exits import ExitScan, LevelExit
from pd2bot.perception.items import CarriedItem, CarriedItems
from pd2bot.perception.player import ActiveSkills, Player
from pd2bot.perception.snapshot import GameSnapshot
from pd2bot.perception.units import GroundItem, Monster
from pd2bot.perception.world import Area
from pd2bot.pickit import Pickit, Rule
from pd2bot.runlog import NullRunLog
from pd2bot.safety import SafetyConfig, SafetyMonitor

REPO = Path(__file__).resolve().parent.parent
TOWN, COLD_PLAINS = offsets.AREA_ROGUE_ENCAMPMENT, offsets.AREA_COLD_PLAINS
TOWN_SPOT = (5880, 5720)
ARRIVAL = (1000, 1000)

HEAL_KIND, MANA_KIND, REJUV_KIND = 606, 611, 530
POISON_TICKS = 4  # how many ticks a struck monster survives its poison


class Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class SimMonster:
    unit_id: int
    position: tuple[int, int]
    hp: int = 100
    poisoned_at: float | None = None
    drops: tuple[tuple[int, int], ...] = ()  # (kind, quality) left on death
    # Multi-area worlds (M6 P4): which area this monster stands in. None
    # keeps the M5 behavior — visible wherever the player is — so every
    # pre-M6 scenario reads exactly as it always did.
    area: int | None = None
    # Identity, for the Countess (kind 734 / unique_no 6) and her court.
    kind: int = 50
    is_boss: bool = False
    unique_no: int | None = None


@dataclass
class ColdPlains:
    """The scripted world. Everything the bot can observe, and the rules by
    which its actions change things."""

    clock: Clock = field(default_factory=Clock)
    area: int = TOWN
    position: tuple[int, int] = TOWN_SPOT
    hp: int = 1000
    max_hp: int = 1000
    mana: int = 400
    max_mana: int = 400
    armor_ratio: float = 1.0
    right_skill: int | None = None
    monsters: list[SimMonster] = field(default_factory=list)
    corpses: list[Monster] = field(default_factory=list)
    revives: list[Monster] = field(default_factory=list)
    ground: list[GroundItem] = field(default_factory=list)
    belt: list[tuple[int, int]] = field(default_factory=list)  # (kind, column)
    inventory: list[int] = field(default_factory=list)  # kinds
    # Scripted events, keyed by tick number.
    damage_at: dict[int, int] = field(default_factory=dict)
    spawn_at: dict[int, list[SimMonster]] = field(default_factory=dict)
    # An accidental pickup: at this tick, a kind appears in the inventory
    # that nobody asked for (a travel click landed on a ground item).
    accident_at: dict[int, int] = field(default_factory=dict)
    junk_kinds: set[int] = field(default_factory=set)
    # An item the game will never let us have (inventory full).
    unpickable: set[int] = field(default_factory=set)
    # -- multi-area worlds (M6 P4) ----------------------------------------
    # Staircases: area -> [(dest area, position)]. Clicking one within
    # reach flips the area id and drops the player at the destination's
    # arrival point — the client's own transition, minus the loading.
    exits: dict[int, list[tuple[int, tuple[int, int]]]] = field(default_factory=dict)
    # Where the player lands on entering each area (waypoint or stairs).
    arrivals: dict[int, tuple[int, int]] = field(default_factory=dict)
    # The warm ExitMemory (maps/exits.json's shape): (area, dest) -> pos.
    exit_memory: dict[tuple[int, int], tuple[int, int]] = field(default_factory=dict)
    # Which area a corpse or ground item lives in. Absent = visible
    # everywhere, which is the M5 single-area behavior.
    unit_areas: dict[int, int] = field(default_factory=dict)
    # Records, for assertions.
    ticks: int = 0
    log: list[str] = field(default_factory=list)
    preamble_runs: int = 0
    travels: list[int] = field(default_factory=list)
    casts_on_unverified_skill: int = 0
    cleanse_runs: list[int] = field(default_factory=list)  # tick numbers
    _next_id: int = 500

    # -- what the bot can see ---------------------------------------------

    def player(self, session=None) -> Player:
        return Player(
            name="MaqiuDoubing", level=91, act=1, position=self.position,
            mode=1, hp=self.hp, max_hp=self.max_hp, mana=self.mana,
            max_mana=self.max_mana, stamina=500, max_stamina=500,
            experience=0, gold=0, gold_stash=700_000,
            strength=122, dexterity=72, vitality=357, energy=31,
        )

    def area_obj(self, session=None) -> Area:
        return Area(level_no=self.area, position=(0, 0), size=(5000, 5000))

    def _here(self, unit_id: int) -> bool:
        """Area filter for corpses and ground items (M5 entries pass)."""
        area = self.unit_areas.get(unit_id)
        return area is None or area == self.area

    def snapshot(self) -> GameSnapshot:
        return GameSnapshot(
            in_game=True,
            taken_at=self.clock(),
            player=self.player(),
            area=self.area_obj(),
            monsters=tuple(
                Monster(
                    unit_id=m.unit_id, kind=m.kind, position=m.position,
                    hp=m.hp, max_hp=100, is_champion=False,
                    is_boss=m.is_boss, is_minion=False,
                    unique_no=m.unique_no,
                )
                for m in self.monsters
                if m.area is None or m.area == self.area
            ),
            allies=tuple(self.revives),
            corpses=tuple(c for c in self.corpses if self._here(c.unit_id)),
            ground_items=tuple(g for g in self.ground if self._here(g.unit_id)),
        )

    def carried(self, session=None) -> CarriedItems:
        items = [
            CarriedItem(
                9000 + i, kind, 2, offsets.ITEM_MODE_IN_BELT, 0,
                offsets.NODE_BELT, (column, 0), 1,
            )
            for i, (kind, column) in enumerate(self.belt)
        ]
        items += [
            CarriedItem(
                8000 + i, kind, 6, offsets.ITEM_MODE_IN_STORAGE,
                offsets.STORAGE_INVENTORY, offsets.NODE_STORAGE, (i % 10, i // 10), 33,
            )
            for i, kind in enumerate(self.inventory)
        ]
        return CarriedItems(items=tuple(items), skipped=0)

    def active_skills(self, session=None) -> ActiveSkills:
        return ActiveSkills(
            left_id=offsets.SKILL_POISON_STRIKE, right_id=self.right_skill
        )

    def is_walkable(self, point: tuple[int, int]) -> bool:
        return True

    # -- the world's own clock --------------------------------------------

    def advance_tick(self, seconds: float) -> None:
        """One tick of the world: poison works, damage lands, packs arrive."""
        self.ticks += 1
        self.clock.advance(seconds)
        now = self.clock()

        # Poison kills, a few ticks after the strike — so a struck monster
        # is dying but not yet dead, which is the whole premise of the
        # module's target selection.
        for monster in list(self.monsters):
            if monster.poisoned_at is None:
                continue
            if now - monster.poisoned_at >= POISON_TICKS * seconds:
                self.monsters.remove(monster)
                self.corpses.append(
                    Monster(
                        unit_id=monster.unit_id, kind=monster.kind,
                        position=monster.position, hp=0, max_hp=100,
                        is_champion=False, is_boss=monster.is_boss,
                        is_minion=False, mode=offsets.MONSTER_MODE_DEAD,
                        unique_no=monster.unique_no,
                    )
                )
                if monster.area is not None:
                    self.unit_areas[monster.unit_id] = monster.area
                for kind, quality in monster.drops:
                    self._next_id += 1
                    self.ground.append(
                        GroundItem(
                            unit_id=self._next_id, kind=kind,
                            position=monster.position, quality=quality,
                        )
                    )
                    if monster.area is not None:
                        self.unit_areas[self._next_id] = monster.area
                self.log.append(f"t{self.ticks}: monster {monster.unit_id} died of poison")

        if self.ticks in self.damage_at:
            amount = self.damage_at[self.ticks]
            self.hp = max(1, self.hp - amount)
            self.armor_ratio = max(0.0, self.armor_ratio - 0.5)
            self.log.append(f"t{self.ticks}: took {amount} damage, hp {self.hp}")

        if self.ticks in self.spawn_at:
            self.monsters.extend(self.spawn_at[self.ticks])
            self.log.append(f"t{self.ticks}: {len(self.spawn_at[self.ticks])} monster(s) arrived")

        if self.ticks in self.accident_at:
            kind = self.accident_at[self.ticks]
            self.inventory.append(kind)
            self.log.append(f"t{self.ticks}: accidentally picked up kind {kind}")

    # -- what the bot's actions do ----------------------------------------

    def press_hotkey(self, vk: int, hotkeys: dict[int, int]) -> None:
        """A hotkey press is a REQUEST. The fake grants it — but the bot
        only learns that by reading the slot back, which is the point."""
        for skill_id, key in hotkeys.items():
            if key == vk:
                self.right_skill = skill_id
                return

    def apply(self, action: Action) -> None:
        """A completed send changes the world."""
        now = self.clock()

        if isinstance(action, MoveTo):
            self.position = action.target
            return

        if isinstance(action, InteractObject):
            # A staircase click within reach takes the transition; one
            # from too far or on empty ground does nothing — a click
            # that "always works" would prove only that the code can ask.
            for dest, position in self.exits.get(self.area, ()):
                if (
                    position == action.position
                    and max(
                        abs(self.position[0] - position[0]),
                        abs(self.position[1] - position[1]),
                    ) <= 20
                ):
                    self.area = dest
                    self.position = self.arrivals.get(dest, ARRIVAL)
                    self.log.append(
                        f"t{self.ticks}: took the stairs to area {dest}"
                    )
                    return
            return

        if isinstance(action, AttackUnit):
            for monster in self.monsters:
                if monster.unit_id == action.unit_id:
                    if monster.poisoned_at is None:
                        monster.poisoned_at = now
                        self.log.append(f"t{self.ticks}: struck {monster.unit_id}")
                    return
            return

        if isinstance(action, CastSelf):
            if self.right_skill != action.skill_id:
                self.casts_on_unverified_skill += 1
            if action.skill_id == offsets.SKILL_BONE_ARMOR:
                self.armor_ratio = 1.0
                self.mana = max(0, self.mana - 35)
                self.log.append(f"t{self.ticks}: bone armor recast")
            return

        if isinstance(action, CastAtPoint):
            if self.right_skill != action.skill_id:
                self.casts_on_unverified_skill += 1
            if action.skill_id == offsets.SKILL_DESECRATE:
                # Desecrate makes corpses only where something died. Nothing
                # dead nearby means nothing happens — the bounded-round
                # logic has to cope with that.
                self.mana = max(0, self.mana - 20)
                self.log.append(f"t{self.ticks}: desecrate cast")
            elif action.skill_id == offsets.SKILL_REVIVE:
                for corpse in list(self.corpses):
                    if corpse.position == action.target:
                        self.corpses.remove(corpse)
                        self.revives.append(
                            Monster(
                                unit_id=corpse.unit_id + 10_000, kind=50,
                                position=corpse.position, hp=100, max_hp=100,
                                is_champion=False, is_boss=False,
                                is_minion=False,
                                alignment=offsets.ALIGNMENT_FRIENDLY,
                            )
                        )
                        self.mana = max(0, self.mana - 45)
                        self.log.append(
                            f"t{self.ticks}: revived {corpse.unit_id} "
                            f"({len(self.revives)} up)"
                        )
                        return
            elif action.skill_id == offsets.SKILL_BLOOD_WARP:
                self.position = action.target
                self.mana = max(0, self.mana - 10)
                self.hp = max(1, self.hp - max(int(0.12 * self.max_hp), 12))
                self.log.append(f"t{self.ticks}: blood warp to {action.target}")
            return

        if isinstance(action, DrinkPotion):
            for entry in list(self.belt):
                kind, column = entry
                if column != action.column:
                    continue
                self.belt.remove(entry)
                if kind in offsets.HEALING_POTION_KINDS:
                    self.hp = min(self.max_hp, self.hp + 400)
                elif kind in offsets.MANA_POTION_KINDS:
                    self.mana = min(self.max_mana, self.mana + 200)
                else:
                    self.hp = self.max_hp
                    self.mana = self.max_mana
                self.log.append(
                    f"t{self.ticks}: drank column {action.column} "
                    f"(hp {self.hp}, mana {self.mana})"
                )
                return
            return

        if isinstance(action, PickUpItem):
            if action.unit_id in self.unpickable:
                return  # the game says no: inventory full
            for item in list(self.ground):
                if item.unit_id == action.unit_id:
                    self.ground.remove(item)
                    if item.kind in offsets.POTION_KINDS:
                        column = (
                            1 if item.kind in offsets.REJUV_POTION_KINDS
                            else 0 if item.kind in offsets.MANA_POTION_KINDS
                            else 2
                        )
                        self.belt.append((item.kind, column))
                    else:
                        self.inventory.append(item.kind)
                    self.log.append(f"t{self.ticks}: picked up kind {item.kind}")
                    return
            return

    # -- the town/waypoint layers, faked at their own seam -----------------

    def cleanse_inventory(self) -> int:
        """The field cleanse at ITS seam: the ctrl-click gesture machinery
        is TownLayer's (unit-tested there); the world just applies the
        outcome — junk kinds leave the inventory."""
        before = len(self.inventory)
        self.inventory = [k for k in self.inventory if k not in self.junk_kinds]
        dropped = before - len(self.inventory)
        self.cleanse_runs.append(self.ticks)
        self.log.append(f"t{self.ticks}: cleanse dropped {dropped} junk item(s)")
        return dropped

    def run_preamble(self):
        """P3's layer is live-proven; here it is a seam, not a re-test."""
        self.preamble_runs += 1
        self.hp, self.mana = self.max_hp, self.max_mana
        self.inventory.clear()
        self.log.append(f"t{self.ticks}: town preamble (healed, inventory emptied)")
        return type("Report", (), {"log": ["heal", "repair", "inventory", "merc"]})()

    def travel_to(self, dest: int) -> None:
        self.travels.append(dest)
        self.area = dest
        self.position = self.arrivals.get(dest, ARRIVAL)
        self.log.append(f"t{self.ticks}: waypoint to area {dest}")

    # -- the traverse seam (M6 P4): exits read like the live scan ---------

    def level_exits(self) -> ExitScan:
        """The current area's staircases, ExitScan-shaped. Every exit is
        visible level-wide — the sim does not model the preset-loading
        horizon, so it proves the traverse WALKS and CLICKS, while the
        seek path's honesty was proven live (T70 run 5)."""
        found = tuple(
            LevelExit(position=position, dest_area=dest)
            for dest, position in self.exits.get(self.area, ())
        )
        return ExitScan(
            exits=found, area=self.area, rooms_walked=len(found),
            rooms=tuple(e.position for e in found),
        )

    def exit_recall(self, here: int, dest: int) -> tuple[int, int] | None:
        return self.exit_memory.get((here, dest))

    def exit_remember(self, here: int, dest: int, position: tuple[int, int]) -> None:
        self.exit_memory[(here, dest)] = position


class SimGated:
    """A GatedInput stand-in that routes presses into the world."""

    def __init__(self, world: ColdPlains, hotkeys: dict[int, int]) -> None:
        self.world = world
        self.hotkeys = hotkeys
        self.presses: list[int] = []
        self.clicks: list[tuple] = []

    def press_key(self, vk: int) -> None:
        self.presses.append(vk)
        self.world.press_hotkey(vk, self.hotkeys)

    def click_world(self, wx, wy, button="left", *, stand_still=False):
        self.clicks.append(((wx, wy), button, stand_still))
        return (0, 0)

    # The hover-verified pickup surface (T58). The sim has no cursor and no
    # hover pointer, so hovers are inert and `hovered_item_id` reads None —
    # the executor then takes its blind-click fallback, which is the path
    # `world.apply` has always modelled.
    def project_world(self, wx, wy):
        return (wx, wy)

    def hover_screen(self, sx, sy):
        pass

    def click_screen(self, sx, sy, button="left", *, stand_still=False):
        self.clicks.append(((sx, sy), button, stand_still))


class SimExecutor(GameActionExecutor):
    """The real executor; the world reacts only once a send has completed.

    Subclassing rather than faking is deliberate: the verified-switch path,
    the stand-still modifier and the click ordering are all under test here,
    and a hand-written stand-in would quietly not have them.
    """

    def __init__(self, world: ColdPlains, **kwargs) -> None:
        super().__init__(**kwargs)
        self.world = world

    def _record(self, action, detail=""):
        super()._record(action, detail)
        self.world.apply(action)


@dataclass
class SimRun:
    """One assembled bot over one scripted world."""

    world: ColdPlains
    engine: BehaviorEngine
    executor: SimExecutor
    gated: SimGated

    @property
    def trace(self):
        return self.executor.trace

    def action_names(self) -> list[str]:
        return [type(e.action).__name__ for e in self.trace]

    def report(self) -> str:
        """The decision trace, as the review gate reads it."""
        lines = ["# Sim decision trace", ""]
        lines.append(f"ticks: {self.engine.report.ticks}")
        lines.append(f"steps completed: {', '.join(self.engine.report.steps_completed)}")
        lines.append(f"reflex fires: {len(self.engine.report.reflex_fires)}")
        lines.append("")
        lines.append("## Engine log")
        lines += [f"- {line}" for line in self.engine.report.log]
        lines.append("")
        lines.append("## Actions sent")
        lines += [f"- {entry}" for entry in self.trace]
        lines.append("")
        lines.append("## What the world did")
        lines += [f"- {line}" for line in self.world.log]
        return "\n".join(lines)


def build_sim(
    world: ColdPlains,
    *,
    monkeypatch=None,
    idle_bail_s: float = 10.0,
    idle_bail_quiet_s: float | None = None,
    tick_s: float = 0.5,
    alert=None,
    run_file: str = "cold-plains.toml",
    narrate=None,
    runlog=None,
) -> SimRun:
    """Assemble the real stack over `world`.

    `monkeypatch` patches the two module-level readers the production code
    calls directly (the skill read-back and the player read inside the
    executor). Without it the caller must patch them itself.
    """
    config = load_class_config(REPO / "config" / "necro.toml")
    # The shipped pickit's vocabulary awaits the T39 id drill — its rules
    # correctly match nothing for unverified names — so the sim runs the
    # production loader/evaluator over a RESOLVED equivalent: the same
    # rule shapes (potion reserves, quality tiers) with ids the scripted
    # world actually drops. The shipped file's own parsing is covered by
    # test_pickit.py.
    pickit = Pickit(
        rules=(
            Rule(name="healing", action="belt",
                 kinds=frozenset(offsets.HEALING_POTION_KINDS),
                 potion_reserve=2, potion_type="healing"),
            Rule(name="mana", action="belt",
                 kinds=frozenset(offsets.MANA_POTION_KINDS),
                 potion_reserve=2, potion_type="mana"),
            Rule(name="rejuv", action="belt",
                 kinds=frozenset(offsets.REJUV_POTION_KINDS),
                 potion_reserve=2, potion_type="rejuv"),
            Rule(name="quality loot", action="keep",
                 qualities=frozenset({5, 6, 7, 8})),
            # The rune rule (M6 P4, the T70 Thul): kind 702 is the id the
            # T67 accuracy melange validated for "all runes" live.
            Rule(name="runes", action="keep", kinds=frozenset({702})),
        ),
        belt_capacity={"healing": 8, "mana": 4, "rejuv": 4},
    )

    if monkeypatch is not None:
        monkeypatch.setattr(
            "pd2bot.input.skills.read_active_skills", world.active_skills
        )
        monkeypatch.setattr("pd2bot.behavior.execute.read_player", world.player)
        # Skill verification polls; give it the world's clock so no test
        # ever sleeps for real.
        monkeypatch.setattr("pd2bot.input.skills.time.sleep", lambda s: None)

    gated = SimGated(world, config.hotkeys)
    log = runlog if runlog is not None else NullRunLog()

    def area_frame():
        return MapFrame.from_area(world.area_obj())

    executor = SimExecutor(
        world,
        session=None,
        gated=gated,
        walk_to=lambda target: world.apply(MoveTo(target)),
        hotkeys=config.hotkeys,
        clock=world.clock,
        # The hover probe ring sleeps between cursor moves; in the sim
        # those are real seconds nobody is simulating. No time passes.
        sleep=lambda seconds: None,
        # The run event log (the run-event-log plan): the sim drives the
        # PRODUCTION emit path, so "does the log agree with what the bot
        # did?" is a question the test suite can answer.
        runlog=log,
        frame=area_frame,
        skill_names={sid: name for name, sid in config.skills.items()},
    )

    combat = NecroCombat(
        config=config.combat,
        is_walkable=world.is_walkable,
        clock=world.clock,
        postures=config.postures,
    )
    ladder = ReflexLadder(
        config.reflex,
        carried=world.carried,
        armor_ratio=lambda: world.armor_ratio,
        is_walkable=world.is_walkable,
        combat_upkeep=lambda snap: combat.upkeep(snap),
        clock=world.clock,
    )
    monitor = SafetyMonitor(
        None,
        SafetyConfig(life_chicken_pct=config.chicken_life_pct),
        read_player_fn=world.player,
        read_area_fn=world.area_obj,
        alert=lambda: None,
    )
    services = RunServices(
        run_preamble=world.run_preamble,
        travel_to=world.travel_to,
        combat=combat,
        pickit=pickit,
        carried=world.carried,
        clock=world.clock,
        # The settle waits for a CLIENT to finish loading, which the sim
        # does not model — so it costs no world time here. Advancing the
        # world through it would shift every scripted spawn instead.
        sleep=lambda seconds: None,
        cleanse=world.cleanse_inventory,
        # The loaded posture names (M6 P3): countess.toml names brisk and
        # aggressive, and a sim that could not validate them would refuse
        # the very run file the gate exists to prove.
        postures=frozenset(config.postures),
        # The traverse seam (M6 P4): the world plays the exit reader and
        # the exit memory, the same closures wiring.py builds live.
        level_exits=world.level_exits,
        exit_recall=world.exit_recall,
        exit_remember=world.exit_remember,
        **({"alert": alert} if alert is not None else {}),
        **({"narrate": narrate} if narrate is not None else {}),
    )
    registry = build_registry(services)
    run = load_run(REPO / "runs" / run_file, registry)
    engine = BehaviorEngine(
        snapshot=world.snapshot,
        monitor=monitor,
        states=build_states(run, registry),
        executor=executor,
        ladder=ladder,
        combat=combat,
        # Both idle deadlines default to the SAME number here (R115). The
        # engine gives an empty field a longer leash than a hunted one,
        # which is right in Hell and only noise in a scripted world — a
        # caller that cares about the distinction passes both.
        config=EngineConfig(
            tick_interval_s=tick_s,
            idle_bail_s=idle_bail_s,
            idle_bail_quiet_s=(
                idle_bail_s if idle_bail_quiet_s is None else idle_bail_quiet_s
            ),
        ),
        clock=world.clock,
        runlog=log,
        frame=area_frame,
        # The engine's inter-tick sleep IS the world's clock: one tick of
        # bot time is one tick of world time, so poison, damage and
        # cooldowns all advance together.
        sleep=lambda seconds: world.advance_tick(seconds),
        **({"narrate": narrate} if narrate is not None else {}),
    )
    return SimRun(world=world, engine=engine, executor=executor, gated=gated)


def cold_plains_scenario() -> ColdPlains:
    """The choreography the gate reviews.

    A pack at the arrival point, a second wave that turns up mid-fight, a
    damage spike big enough to trip the escape rung, drops worth picking up
    (and one that never comes up), all over a world that kills by poison.
    """
    world = ColdPlains()
    world.belt = [
        (MANA_KIND, 0), (REJUV_KIND, 1),
        (HEAL_KIND, 2), (HEAL_KIND, 2), (HEAL_KIND, 3),
    ]
    world.monsters = [
        SimMonster(1, (1006, 1000), drops=((HEAL_KIND, 2),)),
        SimMonster(2, (1010, 1004), drops=((999, 6),)),  # a rare: pickit keeps
        SimMonster(3, (1004, 1008), drops=((997, 7),)),  # a unique that STICKS
    ]
    # A straggler arrives after the first pack is dying, so clearance has to
    # notice and reset its settle timer rather than declaring victory.
    # Its drop is magic quality — no rule matches, so it must be left.
    world.spawn_at = {14: [SimMonster(4, (1012, 1000), drops=((998, 4),))]}
    # The spike: >25% of max hp inside the ladder's 2 s window -> rung 4.
    world.damage_at = {6: 350}
    # The inventory-full moment. Item 504 is the unique dropped by monster
    # 3 (ids are handed out in death order from 500), and the game will
    # never let it be picked up — so the guard has to give up on it, say so,
    # and stop attempting non-potion pickups without stalling the run.
    world.unpickable = {504}
    # The accidental pickup (R117): mid-fight a travel click grabs a piece
    # of junk. The failed pickup of 504 queues the cleanse; it must run
    # only once nothing is left alive nearby, and the junk must be gone by
    # the end of the run.
    world.accident_at = {10: 700}
    world.junk_kinds = {700}
    return world


def patrol_scenario() -> ColdPlains:
    """A pack that only a patrol will ever meet.

    `cold_plains_scenario` puts everything within a few subtiles of the
    arrival point, which is why a standstill clearance always passed it —
    and why both 2026-08-01 live runs completed without a single attack.
    Here the monsters sit ~70 subtiles out: inside the patrol circle, far
    outside anything the character can reach by standing still.

    Caveat worth stating, because a green test would otherwise imply more
    than it shows: this sim does NOT model perception's 80-subtile cutoff
    — its snapshot lists every monster in the world. So it proves the
    patrol WALKS, FINDS and FINISHES; it cannot prove the coverage
    argument, which is geometry and lives in the step's comments.
    """
    world = ColdPlains()
    world.belt = [
        (MANA_KIND, 0), (REJUV_KIND, 1),
        (HEAL_KIND, 2), (HEAL_KIND, 2), (HEAL_KIND, 3),
    ]
    world.monsters = [
        SimMonster(1, (ARRIVAL[0] + 70, ARRIVAL[1]), drops=((HEAL_KIND, 2),)),
        SimMonster(2, (ARRIVAL[0], ARRIVAL[1] + 68)),
    ]
    return world


def countess_route(world: ColdPlains) -> None:
    """The descent's scripted geography, shared by the P4 scenarios.

    Areas 6 -> 20 -> 21 ... 25, arrival and staircase per area, the exit
    memory pre-warmed — the WARM-descent shape, which is every run after
    T70 run 5 banked the staircases. Area 25 uses the real seed's own
    numbers (T68/T70): arrival by the up-staircase at (12635, 11061),
    the chamber anchor at (12548, 11036) — so the sim's staging geometry
    is the live run's staging geometry, not a convenient invention.
    """
    world.belt = [
        (MANA_KIND, 0), (REJUV_KIND, 1),
        (HEAL_KIND, 2), (HEAL_KIND, 2), (HEAL_KIND, 3),
    ]
    route = [6, 20, 21, 22, 23, 24, 25]
    world.arrivals = {
        6: (1000, 1000), 20: (1200, 1200), 21: (1400, 1400),
        22: (1600, 1600), 23: (1800, 1800), 24: (2000, 2000),
        25: (12635, 11061),
    }
    for here, dest in zip(route, route[1:], strict=False):
        stairs = (
            world.arrivals[here][0] + 35, world.arrivals[here][1] + 35,
        )
        world.exits.setdefault(here, []).append((dest, stairs))
        world.exit_memory[(here, dest)] = stairs
        # The stairs back up, for honesty (nothing uses them here).
        world.exits.setdefault(dest, []).append((here, world.arrivals[dest]))


def countess_scenario() -> ColdPlains:
    """The flagship, end to end: the choreography the P4 gate reviews.

    A Thul-shaped rune on a traversal floor (the T70 run 5 miss — it must
    be collected en route now), a corridor straggler that obstructs, the
    champion pack by the Cellar 5 stairs (the neighborhood clearance's
    reason), and the Countess herself in her chamber — pinned identity,
    poison-killed like everything else, dropping a rune and a unique
    that the chamber-region pickup must lift.
    """
    world = ColdPlains()
    countess_route(world)
    # The T70 miss, restaged: a wanted rune beside the Cellar 2 path.
    world.ground.append(
        GroundItem(unit_id=880, kind=702, position=(1615, 1612), quality=2)
    )
    world.unit_areas[880] = 22
    world.monsters = [
        # A corridor straggler close enough to obstruct (brisk bubble 12).
        SimMonster(40, (1820, 1818), area=23),
        # The gaggle at the stairs: the boss-flagged champion T68 read
        # beside her floor's arrival, plus a courtier.
        SimMonster(
            65, (12614, 11056), area=25, kind=21, is_boss=True, unique_no=0
        ),
        SimMonster(64, (12620, 11050), area=25),
        # The Countess: the pinned identity, at her T68-read position.
        SimMonster(
            66, (12548, 11036), area=25, kind=734, is_boss=True, unique_no=6,
            drops=((999, 7), (702, 2)),
        ),
    ]
    return world


def countess_absent_scenario() -> ColdPlains:
    """The blinded-boss-read path: she is never in perception at all.

    The kill condition's fallback must walk the budgeted chamber sweep
    and conclude PROVABLY ABSENT — loudly distinct from a seen kill —
    rather than waiting forever on a read that will never answer.
    """
    world = ColdPlains()
    countess_route(world)
    world.monsters = [
        SimMonster(
            65, (12614, 11056), area=25, kind=21, is_boss=True, unique_no=0
        ),
    ]
    return world


def main() -> int:  # pragma: no cover - the artifact generator
    """Print the decision trace. `python -m tests.simworld > trace.md`,
    or `python -m tests.simworld countess` for the M6 P4 gate artifact
    (`countess-absent` for the blinded-read sweep path)."""
    import sys

    import pd2bot.behavior.execute as execute_mod
    import pd2bot.input.skills as skills_mod

    which = sys.argv[1] if len(sys.argv) > 1 else "cold-plains"
    world, run_file, budget = {
        "cold-plains": (cold_plains_scenario, "cold-plains.toml", 400),
        "countess": (countess_scenario, "countess.toml", 900),
        "countess-absent": (countess_absent_scenario, "countess.toml", 900),
    }[which]
    world = world()
    skills_mod.read_active_skills = world.active_skills
    execute_mod.read_player = world.player
    skills_mod.time.sleep = lambda s: None

    alerts: list[str] = []
    narrations: list[str] = []
    sim = build_sim(
        world, alert=alerts.append, run_file=run_file,
        narrate=narrations.append,
    )
    for _ in range(budget):
        if sim.engine.tick():
            break
        world.advance_tick(0.5)
    report = sim.report()
    if narrations:
        report += "\n\n## Narrative (R179)\n" + "\n".join(
            f"- {line}" for line in narrations
        )
    if alerts:
        report += "\n\n## Alerts raised\n" + "\n".join(f"- {a}" for a in alerts)
    print(report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
