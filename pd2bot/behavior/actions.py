"""Declarative actions: what the behavior layer WANTS, not how it is sent.

The ladder and the combat modules emit these; an `ActionExecutor` turns them
into actual input. The split is what makes P4 honestly sim-only: every test
asserts on the emitted action objects, and the one piece that touches the
real input paths (P5's executor) is small enough to verify live on its own.

Executing an action is where P2's guarantees get spent: a `Cast*` action
means "verified switch first" (skills.ensure_right_skill — no cast is sent
on an unverified skill), and a `DrinkPotion` is a gated belt keypress. The
executor owns those translations; nothing above it may bypass them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DrinkPotion:
    """Press one belt column's drink key (column 0-3 -> keys 1-4)."""

    column: int
    potion_type: str  # "healing" | "mana" | "rejuv" — for the log, not logic


@dataclass(frozen=True)
class CastSelf:
    """Switch to `skill_id` (verified) and cast it on ourselves in place."""

    skill_id: int


@dataclass(frozen=True)
class CastAtPoint:
    """Switch to `skill_id` (verified) and cast at a world position."""

    skill_id: int
    target: tuple[int, int]


@dataclass(frozen=True)
class MoveTo:
    """Walk toward a world position (disengage, retreat, repositioning)."""

    target: tuple[int, int]


@dataclass(frozen=True)
class AttackUnit:
    """Left-click a monster: the necro's whole offense (R47 — the left
    skill is permanently Poison Strike and never switches)."""

    unit_id: int
    position: tuple[int, int]


@dataclass(frozen=True)
class PickUpItem:
    """Left-click an item on the ground to pick it up.

    Distinct from `AttackUnit` even though both are left-clicks, because
    the modifier differs and getting it wrong is silent: an attack holds
    SHIFT (strike in place), and a pickup must NOT — shift-clicking an item
    on the ground attacks the air where it lies.
    """

    unit_id: int
    position: tuple[int, int]


Action = (
    DrinkPotion | CastSelf | CastAtPoint | MoveTo | AttackUnit | PickUpItem
)


class ActionExecutor(Protocol):
    """Turns actions into input. P5 implements the real one over
    GatedInput + skills; tests record instead of sending."""

    def execute(self, action: Action) -> None: ...
