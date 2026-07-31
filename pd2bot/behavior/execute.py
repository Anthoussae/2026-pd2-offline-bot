"""Turning decisions into input: the one place actions become keys and clicks.

Everything above this file emits declarative `Action` objects and touches
nothing. This is where those become real sends, which makes it the only
module in the behavior layer with anything to prove live — deliberately
small for that reason.

Two rules it enforces on behalf of every caller:

1. **No cast on an unverified skill.** Every `Cast*` action goes through
   `skills.ensure_right_skill`, which presses the hotkey and then reads the
   active right-skill id back from memory before returning. A cast sent on
   the skill the game *actually* has selected — rather than the one we asked
   for — is how Blood Warp gets cast when Desecrate was meant, teleporting a
   hurt character instead of making corpses. `SkillSwitchFailed` propagates:
   nothing is clicked.
2. **Attacks stand still.** The strike is a left-click on the monster with
   SHIFT held (`stand_still`), the game's attack-in-place modifier. Without
   it a left-click on a monster just out of reach walks the character into
   the pack — the opposite of the skirmish pattern's intent. The input layer
   already flanks the modifier with settle delays (R113's same-frame race).

Everything is recorded in a `trace`: an ordered list of what was sent and
why. That list is P5's gate artifact and P6's post-mortem tool — when a live
run does something surprising, the trace says which decision produced it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot.behavior.actions import (
    Action,
    AttackUnit,
    CastAtPoint,
    CastSelf,
    DrinkPotion,
    MoveTo,
    PickUpItem,
)
from pd2bot.input import GatedInput
from pd2bot.memory import GameSession
from pd2bot.player import read_player
from pd2bot.skills import belt_drink, ensure_right_skill


class ExecutionError(RuntimeError):
    """An action could not be carried out. The message names the action."""


@dataclass(frozen=True)
class TraceEntry:
    """One executed action, as the trace records it."""

    at: float
    action: Action
    detail: str = ""

    def __str__(self) -> str:
        name = type(self.action).__name__
        return f"{name}{'  ' + self.detail if self.detail else ''}"


@dataclass
class GameActionExecutor:
    """The real executor: actions -> gated input, every cast verified."""

    session: GameSession
    gated: GatedInput
    walk_to: Callable[[tuple[int, int]], object]
    hotkeys: dict[int, int]  # skill id -> VK, from the class config
    clock: Callable[[], float] = time.monotonic
    trace: list[TraceEntry] = field(default_factory=list)

    def _record(self, action: Action, detail: str = "") -> None:
        self.trace.append(TraceEntry(self.clock(), action, detail))

    def execute(self, action: Action) -> None:
        if isinstance(action, DrinkPotion):
            belt_drink(self.gated, action.column)
            self._record(action, f"key {action.column + 1} ({action.potion_type})")
            return

        if isinstance(action, CastSelf):
            # Self-cast in place: verify the switch, then right-click where
            # we are standing. Bone armor lands on the caster wherever the
            # click goes, but aiming at our own feet keeps the click off any
            # bystander — the travel-click hazard (R111) applies to casts too.
            ensure_right_skill(
                self.session, self.gated, action.skill_id, hotkeys=self.hotkeys
            )
            player = read_player(self.session)
            if player is None:
                raise ExecutionError(
                    f"cannot self-cast skill {action.skill_id}: player unreadable"
                )
            self.gated.click_world(*player.position, button="right")
            self._record(action, f"skill {action.skill_id} verified, self-cast")
            return

        if isinstance(action, CastAtPoint):
            ensure_right_skill(
                self.session, self.gated, action.skill_id, hotkeys=self.hotkeys
            )
            self.gated.click_world(*action.target, button="right")
            self._record(
                action, f"skill {action.skill_id} verified, at {action.target}"
            )
            return

        if isinstance(action, AttackUnit):
            # SHIFT held: attack in place. A bare left-click on a monster out
            # of melee range walks us into the pack instead of striking.
            self.gated.click_world(*action.position, stand_still=True)
            self._record(action, f"unit {action.unit_id} at {action.position}")
            return

        if isinstance(action, PickUpItem):
            # No stand-still here, deliberately: SHIFT would turn this into
            # an attack on empty ground where the item lies.
            self.gated.click_world(*action.position)
            self._record(action, f"item {action.unit_id} at {action.position}")
            return

        if isinstance(action, MoveTo):
            self.walk_to(action.target)
            self._record(action, f"to {action.target}")
            return

        raise ExecutionError(f"no execution path for {action!r}")


@dataclass
class RecordingExecutor:
    """Records actions without sending anything. The sim's executor.

    Not merely a test double: the end-to-end sim drives the whole behavior
    stack through this, and the resulting trace is what the go/no-go gate
    reviews. `on_execute` lets a scripted world react to an action the way
    the game would (a strike kills a monster, a drink empties a belt slot).
    """

    on_execute: Callable[[Action], None] | None = None
    clock: Callable[[], float] = time.monotonic
    trace: list[TraceEntry] = field(default_factory=list)

    @property
    def actions(self) -> list[Action]:
        return [entry.action for entry in self.trace]

    def execute(self, action: Action) -> None:
        self.trace.append(TraceEntry(self.clock(), action))
        if self.on_execute is not None:
            self.on_execute(action)
