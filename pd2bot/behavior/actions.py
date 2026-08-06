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

from dataclasses import dataclass, field
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
    # The item's type number, carried purely so the run log can NAME what
    # was reached for (the run-event-log plan, P3). The executor cannot
    # resolve it — it only has a unit id — and a log that says "picked up
    # something" answers none of the questions a log exists for. Optional
    # so every existing construction site keeps working; unset renders as
    # an honest "unknown" rather than a guess.
    #
    # `compare=False` for the same reason `MoveTo.toward` is informational:
    # the kind does not change what this action DOES, so two pickups of
    # the same item at the same aim are the same action whether or not
    # the caller happened to know its type. Equality is about the deed.
    kind: int | None = field(default=None, compare=False)


# Where an item is actually CLICKABLE, relative to the projection of its
# ground tile — measured by T63 (2026-08-03), the drill that ended a
# five-drill hunt: position clicks DO pick items (no hover state needed;
# the hover pointer was a red herring for clicks), but the sprite draws
# UPWARD from its tile, so the tile projection itself misses ~29 times in
# 30 (T57). T63's direct-click matrix landed at (0, -28) with labels off
# and (-16, -40) with labels on. One offset per retry, best guesses
# first: the schedule is what makes retry N differ from retry N-1.
#
# It lives HERE rather than in the executor because `PickUpItem.attempt`
# is an index into it — the action's own contract — and because the step
# that writes an item off has to report WHICH aim points were spent
# (P1 of the pickup-reliability plan). A schedule only the executor
# could see made "all 8 attempts failed" an unanswerable statement.
PICKUP_AIM_POINTS: tuple[tuple[int, int], ...] = (
    (0, -28), (-16, -40), (16, -28), (0, -16), (-16, -28), (0, -40),
    (16, -40), (0, -48),  # the LABEL band (T65 v4): small classes —
    # runes, gems, charms — are effectively label-clicked; their ground
    # sprites survived 58-147 direct probes while both v4 hits landed
    # at y=-48. Labels are ensured ON by the executor, so the tail can
    # reach them.
)


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
