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
class GiveMercPotion:
    """Shift + one belt column's key: feed the merc that potion (R179;
    chord corrected from Alt to Shift at R183, user-verified).

    Always a healing column in practice — the ladder's merc rung picks a
    column that actually holds one — but the action carries only the
    column, like `DrinkPotion`: the key press is per-column, whatever
    sits there."""

    column: int


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
class InteractObject:
    """Left-click a world object — a staircase, a level-exit doorway.

    The M6 traversal gesture (R212 Q3: cellar connections are a single
    click). Distinct from `MoveTo` because the click must land ON the
    object's position (the client walks the character there and takes
    the transition), and distinct from `AttackUnit` because SHIFT would
    turn it into an attack on the spot.
    """

    position: tuple[int, int]


@dataclass(frozen=True)
class ParkSkill:
    """A verified right-skill SWITCH with no cast (M6 P3).

    Executor-internal: the parking housekeeping records these in the
    trace so a park never reads as a cast. Deciders (ladder, combat
    module, steps) never emit one.
    """

    skill_id: int


@dataclass(frozen=True)
class MoveTo:
    """Walk toward a world position (disengage, retreat, repositioning)."""

    target: tuple[int, int]
    # Which unit this walk is FOR, when it is for one. Purely informational
    # — the executor ignores it and walks to `target` either way.
    #
    # It exists because a failed walk is information about a target, and the
    # caller that has to act on that information is not the one that chose
    # it. `clear_radius` absorbs `NavigationError` so one unreachable monster
    # cannot end the run, and then needs to write that monster off or it
    # re-decides the identical approach every tick forever. The combat module
    # picked the target (`_select_target` prefers never-struck over nearest,
    # so it is not recoverable by guessing), and this is the only honest way
    # for it to say so. None means "not aimed at anything" — a retreat, a
    # lateral drift, a patrol leg — and nothing gets blamed for those.
    toward: int | None = None


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

    `attempt` is which retry this is (0-based). The executor aims each
    attempt at a different point of the item's SPRITE — T63 measured the
    clickable region sitting ~16-40 px above the projected ground tile,
    which is why the tile click missed ~29 times in 30 — and the retry
    schedule is how the same action can honestly differ from the attempt
    it retries (this codebase's own rule).
    """

    unit_id: int
    position: tuple[int, int]
    attempt: int = 0


Action = (
    DrinkPotion
    | GiveMercPotion
    | CastSelf
    | CastAtPoint
    | MoveTo
    | AttackUnit
    | PickUpItem
)


class ActionExecutor(Protocol):
    """Turns actions into input. P5 implements the real one over
    GatedInput + skills; tests record instead of sending."""

    def execute(self, action: Action) -> None: ...
