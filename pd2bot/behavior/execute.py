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

from pd2bot import offsets
from pd2bot.behavior.actions import (
    Action,
    AttackUnit,
    CastAtPoint,
    CastSelf,
    DrinkPotion,
    GiveMercPotion,
    InteractObject,
    MoveTo,
    ParkSkill,
    PickUpItem,
)
from pd2bot.input import VK_MENU, GatedInput, InputRefused
from pd2bot.memory import GameSession
from pd2bot.player import read_player
from pd2bot.skills import (
    SkillSwitchFailed,
    belt_drink,
    belt_give_merc,
    ensure_right_skill,
)
from pd2bot.units import label_display_on

# Where an item is actually CLICKABLE, relative to the projection of its
# ground tile — measured by T63 (2026-08-03), the drill that ended a
# five-drill hunt: position clicks DO pick items (no hover state needed;
# the hover pointer was a red herring for clicks), but the sprite draws
# UPWARD from its tile, so the tile projection itself misses ~29 times in
# 30 (T57). T63's direct-click matrix landed at (0, -28) with labels off
# and (-16, -40) with labels on. One offset per retry, best guesses
# first: the schedule is what makes retry N differ from retry N-1.
_PICKUP_OFFSETS: tuple[tuple[int, int], ...] = (
    (0, -28), (-16, -40), (16, -28), (0, -16), (-16, -28), (0, -40),
    (16, -40), (0, -48),  # the LABEL band (T65 v4): small classes —
    # runes, gems, charms — are effectively label-clicked; their ground
    # sprites survived 58-147 direct probes while both v4 hits landed
    # at y=-48. Labels are ensured ON below, so the tail can reach them.
)


class ExecutionError(RuntimeError):
    """An action could not be carried out. The message names the action."""


class CastInFlight(InputRefused):
    """A cast animation is still playing; this CLICK would land inside it.

    An `InputRefused` subclass on purpose, because it means exactly what a
    refusal means to everything above: nothing reached the game, so decide
    again next tick. The engine already absorbs it (`SEND_DID_NOT_LAND`),
    marks no activity for it, and re-decides — which is precisely the
    handling this wants, and the reason it is not a new concept.
    """


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
    sleep: Callable[[float], None] = time.sleep
    # How long to keep asking the game whether the cast is still playing
    # before giving up on the question. NOT the animation length — that is
    # read, not assumed. This only bounds the reading, so a mode that never
    # returns to idle (a misread, a client state nobody anticipated) costs
    # one deferred action rather than the run. T48 measured 610-640 ms, so
    # 1.5 s is well past any real cast.
    cast_wait_cap_s: float = 1.5
    # Right-skill parking (M6 P3, user note 1): after the LAST cast of a
    # burst resolves, switch the right skill back to `park_skill_id`
    # (bone armor). While Revive is the active right skill, ground
    # corpses are selectable and interfere with pathing and item pickup.
    # The grace is what lets a 3-revive burst finish without thrashing:
    # every cast pushes the deadline out, so only quiet arms the park.
    # None = parking off (sims, drills that build the executor bare).
    park_skill_id: int | None = None
    park_grace_s: float = 2.0
    trace: list[TraceEntry] = field(default_factory=list)
    _cast_deadline: float | None = None
    _park_deadline: float | None = None

    def _record(self, action: Action, detail: str = "") -> None:
        self.trace.append(TraceEntry(self.clock(), action, detail))

    def _cast_sent(self) -> None:
        """Remember that a cast is resolving, so the next click can wait."""
        self._cast_deadline = self.clock() + self.cast_wait_cap_s
        if self.park_skill_id is not None:
            self._park_deadline = self.clock() + self.park_grace_s

    def maintain(self) -> None:
        """Once-per-tick housekeeping the engine grants the executor.

        Today that is exactly one duty: right-skill parking (M6 P3). When
        the park deadline has passed with no further cast — and no cast
        animation is still resolving — switch the right skill back to the
        parked skill. A SWITCH only, through the verified path; no click,
        so nothing is cast. Failures are paced, not retried at tick rate
        (the stage B run 9 rule): a refused or dropped switch pushes the
        deadline out one grace and the next quiet tick tries again.
        """
        if self.park_skill_id is None or self._park_deadline is None:
            return
        if self.clock() < self._park_deadline or self._still_casting():
            return
        try:
            ensure_right_skill(
                self.session, self.gated, self.park_skill_id,
                hotkeys=self.hotkeys,
            )
        except (InputRefused, SkillSwitchFailed):
            self._park_deadline = self.clock() + self.park_grace_s
            return
        self._park_deadline = None
        self._record(
            ParkSkill(self.park_skill_id),
            f"right skill parked back to {self.park_skill_id} (no cast)",
        )

    def _still_casting(self) -> bool:
        """Is our own cast animation still playing? Asked of the GAME.

        The user, who has done it by hand: bone armor has a slow cast and a
        command sent straight after it interrupts the animation, so the cast
        is spent and the buff never lands. From the bot's side that looks
        exactly like a recast loop — the armor keeps reading down, the rung
        keeps firing — which is what stage B run 9 shows.

        The first fix for that was a fixed 0.4 s `sleep` right here, and
        review 002 was right about it twice over: it blocked the tick the
        survival ladder needs, and the number was a guess. T48 then measured
        the thing: the player's own unit mode reads `PLAYER_MODE_CASTING`
        for 610-640 ms per cast, which the 0.4 s did not even cover.

        So this waits on the EFFECT, the discipline used everywhere else in
        this codebase (the drop, the deposit, the skill switch) — one stat
        read, no sleeping, and the caller re-decides next tick. Only clicks
        wait: T48 also showed a hotkey press sent 110 ms INTO an animation
        registers within 62 ms, so keypresses (every potion the ladder
        drinks) are unaffected and survival keeps its fastest response.

        Read only after one of OUR casts, and only until `cast_wait_cap_s`:
        a stat read per tick for nothing is the cost review 003 is about.
        """
        if self._cast_deadline is None:
            return False
        if self.clock() > self._cast_deadline:
            self._cast_deadline = None
            return False
        player = read_player(self.session)
        if player is None or player.mode != offsets.PLAYER_MODE_CASTING:
            self._cast_deadline = None
            return False
        return True

    def execute(self, action: Action) -> None:
        if isinstance(action, DrinkPotion):
            # Deliberately BEFORE the cast check: a drink is a keypress, and
            # T48 proved keypresses land mid-animation. The ladder's fastest
            # rungs must never queue behind an animation.
            belt_drink(self.gated, action.column)
            self._record(action, f"key {action.column + 1} ({action.potion_type})")
            return

        if isinstance(action, GiveMercPotion):
            # A keypress chord, same reasoning as DrinkPotion: T48 proved
            # keypresses land mid-animation, so no cast check queues it.
            belt_give_merc(self.gated, action.column)
            self._record(action, f"shift+key {action.column + 1} (merc)")
            return

        # Everything below CLICKS, and a click inside a cast animation is the
        # command that spends the cast (review 002, measured by T48).
        if self._still_casting():
            raise CastInFlight(
                f"a cast is still resolving; {type(action).__name__} would "
                "land inside the animation and spend it — re-deciding next "
                "tick instead"
            )

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
            self._cast_sent()
            self._record(action, f"skill {action.skill_id} verified, self-cast")
            return

        if isinstance(action, CastAtPoint):
            ensure_right_skill(
                self.session, self.gated, action.skill_id, hotkeys=self.hotkeys
            )
            self.gated.click_world(*action.target, button="right")
            self._cast_sent()
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

        if isinstance(action, InteractObject):
            # A plain left click at the object's position: the client walks
            # the character to it and interacts (a staircase transitions).
            # No SHIFT (that would attack the spot), and the arrival is
            # never trusted from the click — the traverse step polls the
            # area id, the waypoint.py discipline.
            self.gated.click_world(*action.position)
            self._record(action, f"object at {action.position}")
            return

        if isinstance(action, PickUpItem):
            # No stand-still here, deliberately: SHIFT would turn this into
            # an attack on empty ground where the item lies.
            self._pick_up(action)
            return

        if isinstance(action, MoveTo):
            self.walk_to(action.target)
            self._record(action, f"to {action.target}")
            return

        raise ExecutionError(f"no execution path for {action!r}")

    def _pick_up(self, action: PickUpItem) -> None:
        """Click the item's SPRITE, not its tile (T63).

        The projection lands on the ground tile; the clickable sprite
        draws above it. Each retry aims at the next point of the measured
        schedule, so the retries genuinely differ. If the offset point
        falls outside the safe click region (an item at the screen edge),
        the raw tile click is the honest fallback — labelled, so the
        trace shows which aim was actually used.
        """
        # The label policy (T66): labels must be SHOWING for the small
        # classes to be clickable at all, and the flag makes the toggle
        # parity-safe — read, press only when provably off, re-read next
        # attempt. Unknown (None) means do not touch the key.
        if label_display_on(self.session) is False:
            try:
                self.gated.press_key(VK_MENU)
                self.sleep(0.1)
            except InputRefused:
                pass
        try:
            base = self.gated.project_world(*action.position)
            dx, dy = _PICKUP_OFFSETS[action.attempt % len(_PICKUP_OFFSETS)]
            self.gated.click_screen(base[0] + dx, base[1] + dy)
            self._record(
                action,
                f"item {action.unit_id} at {action.position} sprite click "
                f"({dx}, {dy}), attempt {action.attempt}",
            )
        except InputRefused:
            self.gated.click_world(*action.position)
            self._record(
                action,
                f"item {action.unit_id} at {action.position} "
                "offset unusable — raw tile click",
            )


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
    sleep: Callable[[float], None] = time.sleep
    # No cast settle here, and the omission is the point: the real
    # executor waits on the game's own casting mode, which a recorder has
    # no way to observe. It previously carried a `cast_settle_s` field it
    # never once slept on — dead config that read like a shared behaviour.
    trace: list[TraceEntry] = field(default_factory=list)

    @property
    def actions(self) -> list[Action]:
        return [entry.action for entry in self.trace]

    def execute(self, action: Action) -> None:
        self.trace.append(TraceEntry(self.clock(), action))
        if self.on_execute is not None:
            self.on_execute(action)
