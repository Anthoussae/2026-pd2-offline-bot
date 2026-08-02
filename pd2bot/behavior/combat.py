"""The class-agnostic combat interface and the per-class TOML config.

Runs never name a class (R46 Q6): a run says `clear_radius`, and WHICH
module answers — and with which skills, hotkeys and thresholds — comes from
the class config. Only the necro's config ships in M5; its combat module
implementation is P5's work, and this module defines the seam it fills.

The loader is deliberately strict. TOML was chosen because the user reads
and tunes these files (R46 Q3), and a hand-edited file fails in exactly one
dangerous way: a typo'd key silently defaulting. So unknown keys anywhere
are a loud load-time error, as are missing required keys and wrong types —
the failure mode the robustness priority forbids is the quiet one, not the
noisy one.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pd2bot.behavior.actions import Action
from pd2bot.behavior.necro import CombatConfig
from pd2bot.behavior.reflex import ReflexConfig
from pd2bot.input import VK_F1, VK_F2, VK_F3, VK_F4, VK_F5, VK_F6
from pd2bot.snapshot import GameSnapshot

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pd2bot.behavior.engine import EngineContext


class ConfigError(RuntimeError):
    """A class config could not be loaded; the message names the key."""


class CombatModule(Protocol):
    """What a class must provide. Implementations live per class (P5:
    necro.py) and are chosen by config, never by a run.

    Both methods DECIDE; neither sends. They return declarative actions the
    engine executes, or None for "nothing to do", and they may keep whatever
    per-instance state their rotation needs (the necro's skirmish pattern is
    stateful by nature: dash in, strike, run back out).
    """

    def engage(self, snap: GameSnapshot, ctx: EngineContext) -> Action | None:
        """Advance the fight by one decision: pick a target, position, or
        strike. None means nothing worth fighting is in reach."""
        ...

    def upkeep(self, snap: GameSnapshot, ctx: EngineContext) -> Action | None:
        """Class-specific maintenance that is not the armor recast (the
        ladder owns that): for the necro, desecrate -> revive up to the
        configured count. Called by the ladder's rung 8, never in town."""
        ...

    def approach(
        self, snap: GameSnapshot, position: tuple[int, int]
    ) -> Action | None:
        """Close on somewhere the RUN wants fought that `engage` will not.

        Every module gets to decide what "in a fight" means, and a run step
        gets to want something dead that the module's own reach does not
        cover — the clearance measures from its arrival point, the module
        from the player. Without this seam those two disagree silently and
        the step waits forever for a kill nobody is going to make (review
        001). Return None to mean "not mine to do": the target is already
        in reach, or a fight is in progress and its pauses are deliberate.
        """
        ...


class FakeCombatModule:
    """A scripted stand-in for engine and ladder tests.

    Feed it the actions to return, in order; it records every call. The
    engine cannot tell it from a real module, which is the point — P4 proves
    the engine and ladder against this, and P5 only has to prove the necro
    module against the same protocol.
    """

    def __init__(
        self,
        engage_script: Sequence[Action | None] = (),
        upkeep_script: Sequence[Action | None] = (),
        approach_script: Sequence[Action | None] = (),
    ) -> None:
        self._engage = list(engage_script)
        self._upkeep = list(upkeep_script)
        self._approach = list(approach_script)
        self.engage_calls = 0
        self.upkeep_calls = 0
        self.approach_calls = 0

    def engage(self, snap: GameSnapshot, ctx: object = None) -> Action | None:
        self.engage_calls += 1
        return self._engage.pop(0) if self._engage else None

    def upkeep(self, snap: GameSnapshot, ctx: object = None) -> Action | None:
        self.upkeep_calls += 1
        return self._upkeep.pop(0) if self._upkeep else None

    def approach(
        self,
        snap: GameSnapshot,
        position: tuple[int, int],
        via: tuple[int, int] | None = None,
    ) -> Action | None:
        self.approach_calls += 1
        return self._approach.pop(0) if self._approach else None


# -- the class config ----------------------------------------------------------

_HOTKEY_VKS = {
    "F1": VK_F1, "F2": VK_F2, "F3": VK_F3,
    "F4": VK_F4, "F5": VK_F5, "F6": VK_F6,
}

_BELT_TYPES = ("healing", "mana", "rejuv")


@dataclass(frozen=True)
class BeltConfig:
    """The permanent belt layout (R53) and the loud-halt minimums (R48)."""

    columns: tuple[str, str, str, str]
    min_healing: int
    min_mana: int
    min_rejuv: int


@dataclass(frozen=True)
class ClassConfig:
    """Everything class-specific, loaded from config/<class>.toml."""

    name: str
    skills: dict[str, int]  # skill name -> live-captured id
    hotkeys: dict[int, int]  # skill id -> VK, the skills.py table shape
    belt: BeltConfig
    reflex: ReflexConfig
    combat: CombatConfig
    # Rung 2 — NOT the ladder's: handed to SafetyConfig by the cycle wiring.
    chicken_life_pct: float

    @property
    def revive_target(self) -> int:
        """Convenience: the number the ladder's upkeep rung aims at."""
        return self.combat.revive_target


def _require(table: dict, key: str, kind: type, where: str):
    if key not in table:
        raise ConfigError(f"{where}: missing required key {key!r}")
    value = table[key]
    # bool is an int subclass; a bare isinstance would bless `true` as 1.
    if kind in (int, float) and isinstance(value, bool):
        raise ConfigError(f"{where}.{key}: expected {kind.__name__}, got bool")
    if kind is float and isinstance(value, int):
        return float(value)
    if not isinstance(value, kind):
        raise ConfigError(
            f"{where}.{key}: expected {kind.__name__}, "
            f"got {type(value).__name__}"
        )
    return value


def _reject_unknown(table: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(map(repr, unknown))} — a "
            "typo'd threshold silently defaulting is exactly the failure "
            "this loader exists to prevent (known: "
            f"{', '.join(sorted(allowed))})"
        )


# [reflex] keys that copy straight into ReflexConfig fields, with types.
_REFLEX_NUMBERS: dict[str, type] = {
    "rejuv_below_pct": float,
    "escalate_hostiles": int,
    "escalate_radius": int,
    "warp_hostiles": int,
    "warp_radius": int,
    "warp_hp_pct": float,
    "warp_loss_pct": float,
    "warp_loss_window_s": float,
    "warp_min_mana": int,
    "warp_cost_pct": float,
    "warp_cost_floor": int,
    "warp_verify_move": int,
    "warp_retry_s": float,
    "retreat_distance": int,
    "heal_below_pct": float,
    "heal_cooldown_s": float,
    "mana_below_pct": float,
    "mana_cooldown_s": float,
    "reposition_loss_pct": float,
    "reposition_window_s": float,
    "reposition_still_subtiles": int,
    "reposition_step": int,
    "reposition_cooldown_s": float,
    "disengage_hp_pct": float,
    "merc_heal_below_pct": float,
    "merc_heal_retry_s": float,
    "armor_recast_below_pct": float,
    "armor_retry_s": float,
}


# [combat] keys that copy straight into CombatConfig fields, with types.
_COMBAT_NUMBERS: dict[str, type] = {
    "engage_radius": int,
    "melee_range": int,
    "dash_step": int,
    "retreat_subtiles": int,
    "reposition_subtiles": int,
    "object_clearance": int,
    "restrike_s": float,
    "wait_for_revives_s": float,
    "revive_engaged_range": int,
    "revive_target": int,
    "approach_with_revives": int,
    "revive_search_radius": int,
    "desecrate_rounds": int,
    "desecrate_settle_s": float,
    "revive_settle_s": float,
}


def load_class_config(path: str | Path) -> ClassConfig:
    """Parse and validate one class TOML. Every problem is a loud
    ConfigError naming the key; nothing ever silently defaults."""
    path = Path(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    where = path.name

    _reject_unknown(
        data, {"name", "skills", "hotkeys", "belt", "reflex", "combat"}, where
    )
    name = _require(data, "name", str, where)

    # [skills] — arbitrary names, integer ids (the live-captured constants).
    skills_raw = _require(data, "skills", dict, where)
    skills: dict[str, int] = {}
    for skill_name, skill_id in skills_raw.items():
        if isinstance(skill_id, bool) or not isinstance(skill_id, int):
            raise ConfigError(
                f"{where}.skills.{skill_name}: expected an integer skill id"
            )
        skills[skill_name] = skill_id

    # [hotkeys] — every key must name a [skills] entry; values are F-keys.
    hotkeys_raw = _require(data, "hotkeys", dict, where)
    hotkeys: dict[int, int] = {}
    for skill_name, key_name in hotkeys_raw.items():
        if skill_name not in skills:
            raise ConfigError(
                f"{where}.hotkeys.{skill_name}: not a [skills] entry "
                f"(known: {', '.join(sorted(skills))})"
            )
        if not isinstance(key_name, str) or key_name not in _HOTKEY_VKS:
            raise ConfigError(
                f"{where}.hotkeys.{skill_name}: expected one of "
                f"{', '.join(sorted(_HOTKEY_VKS))}, got {key_name!r}"
            )
        hotkeys[skills[skill_name]] = _HOTKEY_VKS[key_name]

    # [belt] — the R53 layout plus minimums.
    belt_raw = _require(data, "belt", dict, where)
    _reject_unknown(
        belt_raw,
        {"columns", "min_healing", "min_mana", "min_rejuv"},
        f"{where}.belt",
    )
    columns = _require(belt_raw, "columns", list, f"{where}.belt")
    if len(columns) != 4 or any(c not in _BELT_TYPES for c in columns):
        raise ConfigError(
            f"{where}.belt.columns: expected exactly 4 entries drawn from "
            f"{', '.join(_BELT_TYPES)}, got {columns!r}"
        )
    for required_type in _BELT_TYPES:
        if required_type not in columns:
            raise ConfigError(
                f"{where}.belt.columns: no {required_type!r} column — the "
                "ladder's drink rungs would have nowhere to press"
            )
    belt = BeltConfig(
        columns=tuple(columns),
        min_healing=_require(belt_raw, "min_healing", int, f"{where}.belt"),
        min_mana=_require(belt_raw, "min_mana", int, f"{where}.belt"),
        min_rejuv=_require(belt_raw, "min_rejuv", int, f"{where}.belt"),
    )

    # [reflex] — the R49 numbers, plus which skills the ladder's two casting
    # rungs use, by NAME resolved against [skills] (class-agnostic: nothing
    # here knows the words "bone armor").
    reflex_raw = _require(data, "reflex", dict, where)
    _reject_unknown(
        reflex_raw,
        set(_REFLEX_NUMBERS)
        | {"chicken_life_pct", "armor_in_town", "escape_skill", "armor_skill"},
        f"{where}.reflex",
    )
    numbers = {
        key: _require(reflex_raw, key, kind, f"{where}.reflex")
        for key, kind in _REFLEX_NUMBERS.items()
    }
    chicken_life_pct = _require(
        reflex_raw, "chicken_life_pct", float, f"{where}.reflex"
    )
    armor_in_town = _require(reflex_raw, "armor_in_town", bool, f"{where}.reflex")
    for ref_key in ("escape_skill", "armor_skill"):
        ref = _require(reflex_raw, ref_key, str, f"{where}.reflex")
        if ref not in skills:
            raise ConfigError(
                f"{where}.reflex.{ref_key}: {ref!r} is not a [skills] entry"
            )

    # Belt columns -> ladder columns, derived rather than repeated: one
    # source for the layout means R53 cannot be half-updated.
    heal_columns = tuple(i for i, c in enumerate(columns) if c == "healing")
    reflex = ReflexConfig(
        mana_column=columns.index("mana"),
        rejuv_column=columns.index("rejuv"),
        heal_columns=heal_columns,
        warp_skill_id=skills[reflex_raw["escape_skill"]],
        armor_skill_id=skills[reflex_raw["armor_skill"]],
        armor_in_town=armor_in_town,
        **numbers,
    )

    # [combat] — what the class module itself consumes: the skirmish
    # numbers and the two maintenance skills, again resolved by name.
    combat_raw = _require(data, "combat", dict, where)
    _reject_unknown(
        combat_raw,
        set(_COMBAT_NUMBERS) | {"desecrate_skill", "revive_skill"},
        f"{where}.combat",
    )
    combat_numbers = {
        key: _require(combat_raw, key, kind, f"{where}.combat")
        for key, kind in _COMBAT_NUMBERS.items()
    }
    for ref_key in ("desecrate_skill", "revive_skill"):
        ref = _require(combat_raw, ref_key, str, f"{where}.combat")
        if ref not in skills:
            raise ConfigError(
                f"{where}.combat.{ref_key}: {ref!r} is not a [skills] entry"
            )
    combat = CombatConfig(
        desecrate_skill_id=skills[combat_raw["desecrate_skill"]],
        revive_skill_id=skills[combat_raw["revive_skill"]],
        **combat_numbers,
    )

    return ClassConfig(
        name=name,
        skills=skills,
        hotkeys=hotkeys,
        belt=belt,
        reflex=reflex,
        combat=combat,
        chicken_life_pct=chicken_life_pct,
    )
