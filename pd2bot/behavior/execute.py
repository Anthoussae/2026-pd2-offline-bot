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

from pd2bot import mapframe, offsets
from pd2bot.behavior.actions import (
    PICKUP_AIM_POINTS,
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
from pd2bot.runlog import NullRunLog
from pd2bot.skills import (
    SkillSwitchFailed,
    belt_drink,
    belt_give_merc,
    ensure_right_skill,
)
from pd2bot.units import label_display_on

# The aim schedule now lives beside the action whose `attempt` field
# indexes it (`actions.PICKUP_AIM_POINTS`), so the step that writes an
# item off can report which points were actually spent. Aliased here
# because this module is where it is consumed.
_PICKUP_OFFSETS = PICKUP_AIM_POINTS


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


class ActionLogging:
    """Turning executed actions into run-log events.

    A plain mixin rather than a dataclass base, deliberately: both
    executors are dataclasses with required fields, and a dataclass base
    carrying defaults would force those fields to carry defaults too.
    Each executor declares the log fields itself; this class owns only
    the behaviour.

    Shared by the real executor and the sim's `RecordingExecutor` for the
    same reason `_PickupMixin` is shared by the clearance and the sweep:
    two implementations of one job drift, and the one that drifts is the
    one nobody was watching. It also makes "does the log agree with the
    trace?" a question the sim can answer.

    Live reads come from the host class through `_here()` and
    `_vitals()`, because a recorder has no game to read.
    """

    def _read_position(self) -> tuple[int, int] | None:
        """Where the character is, live. Overridden by each host."""
        return None

    def _here(self) -> tuple[int, int] | None:
        """Where the character was WHEN THE ACTION WAS DECIDED.

        Captured before the send, not after, and the difference is not
        cosmetic: `walk_to` BLOCKS until arrival, so a position read
        after a `MoveTo` is the destination. Every relative coordinate
        would then read "0 away", which is worse than no coordinate —
        it looks like data and says nothing. Caught by reading the
        first sim log this instrumentation produced.
        """
        return getattr(self, "_pos_before", None)

    def _capture_position(self) -> None:
        """Called at the top of `execute`, only when the log is on."""
        if getattr(getattr(self, "runlog", None), "enabled", False):
            self._pos_before = self._read_position()

    def _vitals(self) -> dict:
        return {"hp": None, "mana": None, "vitals_unread": True}

    def _frame(self):
        if getattr(self, "frame", None) is None:
            return mapframe.MapFrame.unknown()
        try:
            got = self.frame()
        except Exception:  # noqa: BLE001 - the log never breaks a run
            return mapframe.MapFrame.unknown()
        return got or mapframe.MapFrame.unknown()

    def _skill_name(self, skill_id: int) -> str:
        return (getattr(self, "skill_names", None) or {}).get(
            skill_id
        ) or f"skill {skill_id}"

    def _item_name(self, kind: int | None) -> str:
        """A code-anchored name, or an honest `kind <n>` (R144).

        Never a guess: a numeric review once approved six wrong elite
        armours and the bot picked up a Wire Fleece believing it was a
        Kraken Shell. A diagnostic log that repeated that mistake would
        be indistinguishable from a correct one.
        """
        if kind is None:
            return "unknown"
        resolve = getattr(self, "item_names", None)
        if resolve is not None:
            try:
                name = resolve(kind)
            except Exception:  # noqa: BLE001
                name = None
            if name:
                return name
        return f"kind {kind}"

    def _log_action(self, action: Action, detail: str = "") -> None:
        """One event per executed action. Never raises, never interprets.

        Emitted AFTER the send completed, so an event means "this reached
        the game". A refusal never arrives here — it raises out of
        `execute` — and the engine records those separately, which keeps
        "sent" and "attempted" from blurring together. That distinction
        is the point: T71's five staircase clicks were all sends, and
        nothing recorded the 144 seconds between them.
        """
        log = getattr(self, "runlog", None)
        if log is None or not getattr(log, "enabled", False):
            # Checked BEFORE any gathering: `_here()` and `_vitals()` are
            # live memory reads, and a silent log that still paid for
            # them would make the instrument observable in the behaviour
            # it instruments.
            return
        try:
            frame = self._frame()
            here = self._here()

            def place(point):
                return frame.describe(point, here)

            screen = getattr(self, "_last_click_screen", None)
            screen = list(screen) if screen else None

            if isinstance(action, MoveTo):
                log.event(
                    "action.move", target=place(action.target),
                    toward=getattr(action, "toward", None), origin=place(here),
                )
            elif isinstance(action, AttackUnit):
                log.event(
                    "action.attack", unit_id=action.unit_id,
                    target=place(action.position),
                )
            elif isinstance(action, CastAtPoint):
                log.event(
                    "action.cast", skill_id=action.skill_id,
                    skill=self._skill_name(action.skill_id),
                    target=place(action.target), detail=detail,
                )
            elif isinstance(action, CastSelf):
                log.event(
                    "action.cast_self", skill_id=action.skill_id,
                    skill=self._skill_name(action.skill_id),
                    at=place(here), detail=detail,
                )
            elif isinstance(action, InteractObject):
                log.event(
                    "action.interact", target=place(action.position),
                    click_screen=screen, detail=detail,
                )
            elif isinstance(action, PickUpItem):
                log.event(
                    "action.pickup_attempt", unit_id=action.unit_id,
                    item=self._item_name(action.kind), item_kind=action.kind,
                    target=place(action.position), attempt=action.attempt,
                    click_screen=screen, detail=detail,
                )
            elif isinstance(action, DrinkPotion):
                log.event(
                    "action.drink", column=action.column,
                    potion=action.potion_type, **self._vitals(),
                )
            elif isinstance(action, GiveMercPotion):
                log.event(
                    "action.merc_feed", column=action.column, **self._vitals()
                )
            elif isinstance(action, ParkSkill):
                log.event(
                    "action.park_skill", skill_id=action.skill_id,
                    skill=self._skill_name(action.skill_id),
                )
            else:
                # A new action type records itself rather than vanishing.
                log.event(
                    f"action.{type(action).__name__.lower()}",
                    action=repr(action), detail=detail,
                )
        except Exception:  # noqa: BLE001 - instrumentation is never fatal
            return


@dataclass
class GameActionExecutor(ActionLogging):
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
    # -- the run event log (the run-event-log plan, P3) ---------------------
    #
    # `_record` is the single funnel every executed action passes through:
    # `execute()` has one path per action type and every one ends here.
    # That makes it the right place — and the only maintainable one — to
    # turn actions into events, because an action that skips `_record`
    # has no trace today either, so the invariant is already load-bearing
    # rather than newly imposed.
    #
    # Defaults to the null sink so tests and drills that build a bare
    # executor stay silent; `wiring.py` passes the real log (R220 Q11:
    # anything touching the live game logs unconditionally).
    runlog: object = field(default_factory=NullRunLog)
    # How a world position becomes world/local/relative coordinates. A
    # callable rather than a MapFrame because the frame changes with the
    # area, and the executor must not have to be told when.
    frame: Callable[[], object] | None = None
    skill_names: dict[int, str] = field(default_factory=dict)
    item_names: Callable[[int], str | None] | None = None
    _cast_deadline: float | None = None
    _park_deadline: float | None = None
    # The screen point of the last world click, kept on the way past so
    # `_record` can report where a click actually aimed. Directly load
    # bearing for the open Forgotten Tower question — does a staircase
    # click land where the staircase is — and free, because `click_world`
    # already computes it and throws it away.
    _last_click_screen: tuple[int, int] | None = None

    def _record(self, action: Action, detail: str = "") -> None:
        self.trace.append(TraceEntry(self.clock(), action, detail))
        self._log_action(action, detail)

    def _read_position(self) -> tuple[int, int] | None:
        """Best effort and deliberately quiet: a failed read costs a log
        field, never the action."""
        try:
            player = read_player(self.session)
        except Exception:  # noqa: BLE001
            return None
        return player.position if player is not None else None

    def _vitals(self) -> dict:
        """HP and mana at send time. The operator asked for vitals on
        every potion, merc feed and chicken event, because "why did it
        drink?" cannot be answered without them."""
        try:
            player = read_player(self.session)
        except Exception:  # noqa: BLE001
            player = None
        if player is None:
            return {"hp": None, "mana": None, "vitals_unread": True}
        return {
            "hp": player.hp, "max_hp": player.max_hp,
            "mana": player.mana, "max_mana": player.max_mana,
        }

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
        # Where the character stands BEFORE anything is sent, for the
        # log's character-relative frame. `walk_to` blocks until arrival,
        # so reading it afterwards would report every destination as
        # "0 away" — data-shaped and meaningless. Free when logging is
        # off (the capture checks first).
        self._capture_position()
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
            # The projected screen point is KEPT (the run-event-log plan)
            # rather than discarded: "where did the click actually aim?"
            # is the open Forgotten Tower question, and the value is
            # already computed right here.
            self._last_click_screen = self.gated.click_world(*action.position)
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
class RecordingExecutor(ActionLogging):
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
    # The same log fields the real executor carries, so the sim drives
    # the PRODUCTION emit path rather than a lookalike (the mixin's
    # docstring says why that matters).
    runlog: object = field(default_factory=NullRunLog)
    frame: Callable[[], object] | None = None
    skill_names: dict[int, str] = field(default_factory=dict)
    item_names: Callable[[int], str | None] | None = None
    # Supplied by a sim that models a player; left None, events stay
    # honest about the frames they could not compute.
    player_position: Callable[[], tuple[int, int] | None] | None = None
    vitals: Callable[[], dict] | None = None
    _last_click_screen: tuple[int, int] | None = None

    @property
    def actions(self) -> list[Action]:
        return [entry.action for entry in self.trace]

    def _read_position(self) -> tuple[int, int] | None:
        if self.player_position is None:
            return None
        try:
            return self.player_position()
        except Exception:  # noqa: BLE001
            return None

    def _vitals(self) -> dict:
        if self.vitals is None:
            return {"hp": None, "mana": None, "vitals_unread": True}
        try:
            return self.vitals()
        except Exception:  # noqa: BLE001
            return {"hp": None, "mana": None, "vitals_unread": True}

    def execute(self, action: Action) -> None:
        self._capture_position()
        self.trace.append(TraceEntry(self.clock(), action))
        self._log_action(action)
        if self.on_execute is not None:
            self.on_execute(action)
