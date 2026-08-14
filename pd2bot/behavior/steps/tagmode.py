"""TagModeBatteryStep: the name-tag pickup calibration battery (R248/R250).

TEST KIT, like `deplete_belt` — no real run names it. One step runs the
operator's three-mode experiment in a single town game, to the R250
structure (the operator's own, replacing the scatter-walk design that
wedged on 2026-08-13):

    block A  rounds 1A..5A  NO NAME TAGS      (ALT off)
    block B  rounds 1B..5B  LOOT FILTER TAGS  (one ALT press)
    block C  rounds 1C..5C  DEFAULT TAGS      (one F press)

The battery owns the label display for every round — the executor's
label enforcement is suspended throughout (it would otherwise fight
the battery for the toggle) and re-armed at each round's end.

Per round: drop every inventory item EXCEPT the Horadric Cube and the
two tomes in ONE PILE where the character stands (no walking — the
walk-to-scatter-points design is what orbited NPCs and clicked the
stash) → announce the round → run the normal whitelisted-pickup
protocol for at most `round_seconds` → announce the score (collected /
dropped whitelisted / unwanted collected) → gather EVERYTHING back and
reconcile the census before the next round may begin.

**The drop list is the operator's, not the exception registry's**
(R250: "drops all items except the horadric cube, tome of identify,
and tome of town portal. There should be 18 items total"). That
deliberately overrides the registry's no-drop protections for potions,
scrolls and maps INSIDE THIS BATTERY ONLY: the ctrl is settled on both
sides of the drop click (R113), and the census reconciliation catches
the consequence if a slip ever fires the bare right-click (a drunk
potion or a merged scroll shows up as a count mismatch, loudly).

**Misclicks are expected, not fatal** (R250 item 1): every tick, any
phase, a blocking panel that the phase did not open — a stash, an NPC
dialog — is closed and the battery carries on. The chat console is
exempt, always: the human opening it is most likely typing `abort`,
which now stops RUNS too (wiring.run_stop_channel).

**The gather is the operator's job** (R251 feedback): the moment a
round is scored the battery asks them to pick everything up and goes
hands-off — a human with a mouse clears the pile in seconds, and the
bot clicking alongside would fight them for items. The hold announces
every ~20 s (a real chat send, so the engine's wait accounting never
mistakes it for a hang) and says "resuming." when the floor is clear.

**Losses are announced, never fatal** (launch 3's lesson, twice over):
each drop is confirmed against the FLOOR — an item that left the
inventory but never landed was consumed by a slipped click (launch 3
drank a healing potion this way) and is excluded from the census; and
a census that still fails to reconcile (stackables merge on pickup,
which a count census reads as loss) is announced and recorded as
`battery.loss`, then the battery continues. The operator is present by
mandate; `abort` is theirs.

Measurement rides the run event log: `battery.*` events mark the
boundaries, the item stream carries the per-item record, and every
event is wall-clock stamped by the envelope. Tabulate with
`python -m pd2bot.runlog <dir> --tagmode`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from pd2bot import offsets
from pd2bot.behavior.engine import EngineContext, StepOutcome
from pd2bot.behavior.steps.pickup import _PickupMixin
from pd2bot.behavior.steps.util import _chebyshev
from pd2bot.perception.snapshot import GameSnapshot
from pd2bot.perception.uistate import blocking_panels

# What NEVER goes on the floor (R250, the operator's exact list). The
# cube's protection is policy (R172); the tomes' right-click side
# effects outlive any slip. Everything else in the main inventory drops.
_BATTERY_KEEP = frozenset({
    offsets.CUBE_KIND,
    offsets.TOME_OF_IDENTIFY_KIND,
    offsets.TOME_OF_TOWN_PORTAL_KIND,
})
# The blocks, in the operator's order — NOT interleaved (R250 supersedes
# the R248 interleave): 5xA, then ALT, 5xB, then F, 5xC.
_BLOCKS = (
    ("A", 1, "NO NAME TAGS"),
    ("B", 2, "LOOT FILTER TAGS"),
    ("C", 3, "DEFAULT TAGS"),
)
# Toggle retries before the battery refuses, and how long a press gets
# to land before its flag is re-read (the engine ticks faster than the
# flags settle; re-reading stale is a double press).
_MODE_PRESSES_MAX = 4
_TOGGLE_SETTLE_S = 0.6
# The gather hold's re-announce interval (each announcement is a real
# chat send, which is what keeps the engine's wait accounting honest).
# The gather is the OPERATOR'S job by design (R251 feedback: a human
# with a mouse clears the pile in seconds; the bot took a minute and
# then asked anyway) — the bot goes hands-off the moment the round is
# scored.
_HOLD_NAG_S = 20.0
# Floor-landing confirmation polls per drop before an item is declared
# consumed. A just-dropped item takes a beat to enter the unit table
# (the T43 lesson), so one stale read must not misjudge a good drop.
_FLOOR_CONFIRM_POLLS = 3


@dataclass
class TagModeBatteryStep(_PickupMixin):
    """The three-mode battery, R250 structure. See the module docstring."""

    rounds: int = 5
    round_seconds: int = 30
    radius: int = 30  # the arena: everything happens within this of the pile
    min_wanted: int = 2  # refuse to run a 15-round battery over less
    # Which blocks to run, in order — "ABC" is the full battery; "C"
    # reruns one mode (added when the 07:40 launch banked complete A
    # and B blocks and the watchdog stall ate C: re-paying for two
    # finished blocks to reach the third is operator time wasted).
    blocks: str = "ABC"
    # The F parity fallback for environments with no filter_state reader
    # (the live wiring HAS one since T91). Also the restore target.
    filter_initially_on: bool = False
    confirm_seconds: int = 6  # abort window after a BLIND F press
    name: str = "tagmode_battery"

    # -- phase machine state (one small thing per tick) ---------------------
    _phase: str = "begin"
    _block_i: int = 0
    _round: int = 1  # 1-based within the block
    _filter_on: bool | None = None  # tracked F parity (blind fallback)
    _labels_initial: bool | None = None  # restored at the end
    _mode_presses: int = 0
    _filter_presses: int = 0
    _settle_until: float | None = None
    # -- per-round state ----------------------------------------------------
    _anchor: tuple[int, int] | None = None
    _pre_drop_counts: Counter | None = None
    _dropped: int = 0
    _drop_total: int | None = None
    _manifest_kinds: set[int] = field(default_factory=set)
    # Floor-landing confirmation (launch 3's lesson): drop_item verifies
    # "gone from the inventory", but a slipped ctrl DRINKS a potion (or
    # uses a scroll/map) and that also reads as gone — launch 3 dropped
    # 18, landed 17, and one healing potion was simply drunk. Each drop
    # is now confirmed against the floor before the next; an item that
    # never lands is announced, excluded from the census, and the
    # battery CONTINUES (one wasted potion must not end 15 rounds).
    # (kind, ground count of that kind before the drop, polls so far).
    _floor_confirm: tuple[int, int, int] | None = None
    _consumed: Counter = field(default_factory=Counter)
    _test_started: float | None = None
    _test_announced: bool = False
    _wanted_start: int = 0
    _junk_start: int = 0
    _gather_started: float | None = None
    _last_nag: float = 0.0
    _rounds_done: int = 0

    # -- small shared helpers ------------------------------------------------

    def _say(self, text: str) -> None:
        """Operator-facing line: chat when wired, alert otherwise."""
        if self.services.say is not None:
            try:
                self.services.say(text)
                return
            except Exception as exc:  # noqa: BLE001 - a refused chat line
                self.services.log(f"battery: chat refused ({exc})")
        self.services.alert(text)

    def _block_list(self) -> tuple:
        return tuple(b for b in _BLOCKS if b[0] in self.blocks.upper())

    def _block(self) -> tuple[str, int, str]:
        return self._block_list()[self._block_i]

    def _round_label(self) -> str:
        return f"{self._round}{self._block()[0]}"

    def _fail(self, why: str) -> StepOutcome:
        """End the battery honestly and loudly (the T72 lesson)."""
        self._say(f"BATTERY STOPPED: {why}")
        self.services.runlog.event("battery.end", completed=False, why=why,
                                   rounds_done=self._rounds_done)
        self._phase = "done"
        return StepOutcome(done=True, acted=True, note=f"battery stopped: {why}")

    def _reset_pickup_bookkeeping(self) -> None:
        """Fresh budgets per phase: round 3 must not inherit round 2's
        write-offs, nor a spurious inventory-full mark."""
        s = self.services
        s.attempts.clear()
        s.last_try.clear()
        s.stuck.clear()
        s.pending_pickup.clear()
        s.collect_closest.clear()
        s.collect_stalls.clear()
        s.wanted_seen.clear()
        s.inventory_full = False
        s.last_click = None

    def _droppables(self, carried) -> list:
        return [
            i for i in carried.main_inventory if i.kind not in _BATTERY_KEEP
        ]

    def _census(self) -> Counter:
        """Kind counts over the main inventory AND the belt: a gathered
        potion routes to the belt, and a census that only read the grid
        would report it lost (found in design review, R250)."""
        carried = self.services.carried()
        return Counter(
            i.kind for i in (*carried.main_inventory, *carried.belt)
        )

    def _inv_open(self, snap: GameSnapshot) -> bool:
        return snap.ui is not None and offsets.UI_INVENTORY in snap.ui.open_panels

    def _ground_in_arena(self, snap: GameSnapshot, kinds: set[int]) -> list:
        if self._anchor is None:
            return []
        return [
            g for g in snap.ground_items
            if g.kind in kinds
            and _chebyshev(g.position, self._anchor) <= self.radius
        ]

    def _recover_stray_panels(
        self, snap: GameSnapshot, expected: frozenset[int]
    ) -> bool:
        """Close any blocking panel this phase did not open (R250 item 1:
        misclicks — a stash, an NPC dialog — are inevitable and must cost
        one ESC, not the battery). The chat console is exempt, always:
        a human opening it is most likely typing `abort` (T54 run 4)."""
        if snap.ui is None or not snap.ui.blocks_input:
            return False
        stray = (
            snap.ui.open_panels
            & frozenset(blocking_panels())
            - expected
            - {offsets.UI_CHAT_CONSOLE}
        )
        if not stray or self.services.clear_panels is None:
            return False
        names = ", ".join(snap.ui.names) or "an unnamed panel"
        self.services.log(
            f"battery: closing a stray panel ({names}) — a misclick, "
            "recovered and carrying on"
        )
        self.services.clear_panels()
        return True

    # -- the tick ------------------------------------------------------------

    def step(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        handler = {
            "begin": self._tick_begin,
            "set_mode": self._tick_set_mode,
            "drop": self._tick_drop,
            "test": self._tick_test,
            "gather": self._tick_gather,
            "final": self._tick_final,
        }.get(self._phase)
        if handler is None:
            return StepOutcome(done=True, note="battery already ended")
        return handler(snap, ctx)

    # -- begin: refuse early, announce, or go --------------------------------

    def _tick_begin(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        s = self.services
        missing = [
            what for what, service in (
                ("drop_item", s.drop_item),
                ("open_inventory", s.open_inventory),
                ("carried_with_sockets", s.carried_with_sockets),
                ("label_state", s.label_state),
                ("press_show_items", s.press_show_items),
                ("press_filter_toggle", s.press_filter_toggle),
                ("set_label_enforcement", s.set_label_enforcement),
            ) if service is None
        ]
        if missing:
            return self._fail(
                f"not wired for this environment (missing {', '.join(missing)})"
            )
        if not self._block_list():
            return self._fail(
                f"blocks={self.blocks!r} names no known block (A, B, C)"
            )
        if not snap.in_town:
            return self._fail("must run in town — no waypoint step belongs "
                              "in a battery run file")
        if snap.player is None:
            return StepOutcome(done=False, waiting=True, note="no player read")
        labels = s.label_state()
        if labels is None:
            return self._fail(
                "the label flag is unreadable (BH.dll absent?) — the modes "
                "under test do not exist without the loot filter"
            )
        self._labels_initial = labels
        self._filter_on = (
            s.filter_state() if s.filter_state is not None else None
        )
        if self._filter_on is None:
            self._filter_on = self.filter_initially_on
        carried = s.carried_with_sockets()
        if carried.truncated:
            return self._fail("the carried-items read is truncated — "
                              "refusing to judge droppability from it")
        droppables = self._droppables(carried)
        wanted = [
            i for i in droppables
            if s.pickit.wants(i, None, mode="permissive")
        ]
        kept = len(carried.main_inventory) - len(droppables)
        if len(wanted) < self.min_wanted:
            return self._fail(
                f"only {len(wanted)} whitelisted droppable item(s) in the "
                f"inventory (need {self.min_wanted}) — restock and relaunch"
            )
        names = ", ".join(sorted({self._logged_name(i.kind) for i in wanted}))
        block_names = "/".join(b[0] for b in self._block_list())
        self._say(
            f"TAG-MODE BATTERY (R250): {self.rounds} rounds x blocks "
            f"{block_names}, {self.round_seconds}s each. Dropping "
            f"{len(droppables)} item(s) in one pile ({len(wanted)} "
            f"whitelisted: {names}); keeping the cube and the tomes "
            f"({kept}). 'abort' in chat stops everything."
        )
        s.runlog.event(
            "battery.begin",
            rounds=self.rounds, blocks=block_names,
            round_seconds=self.round_seconds,
            droppable=len(droppables), whitelisted=len(wanted), kept=kept,
            wanted_kinds=sorted({i.kind for i in wanted}),
            labels_initial=labels, filter_on=self._filter_on,
            filter_readable=s.filter_state is not None,
        )
        self._phase = "set_mode"
        return StepOutcome(done=False, acted=True, note="battery begins")

    # -- set_mode: block transitions, flag-verified ---------------------------

    def _tick_set_mode(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        s = self.services
        if self._recover_stray_panels(snap, frozenset()):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        # A toggle press bought a settle (or abort) window: hold it open.
        if self._settle_until is not None:
            if self.services.clock() < self._settle_until:
                return StepOutcome(done=False, waiting=True,
                                   note="toggle settling")
            self._settle_until = None
        block, mode, described = self._block()
        target_labels = mode != 1
        labels = s.label_state()
        if labels is None:
            return self._fail("the label flag stopped reading mid-battery")
        if labels != target_labels:
            if self._mode_presses >= _MODE_PRESSES_MAX:
                return self._fail(
                    f"{self._mode_presses} Show Items presses never moved "
                    "the label flag — the binding is not doing what the "
                    "keyfile says"
                )
            self._mode_presses += 1
            s.press_show_items()
            self._settle_until = self.services.clock() + _TOGGLE_SETTLE_S
            return StepOutcome(done=False, acted=True,
                               note=f"labels -> {'on' if target_labels else 'off'}")
        if mode != 1:
            target_filter = mode == 3  # default tags ON
            state = (
                s.filter_state() if s.filter_state is not None
                else self._filter_on
            )
            if state != target_filter:
                if self._filter_presses >= _MODE_PRESSES_MAX:
                    return self._fail(
                        f"{self._filter_presses} F presses never moved the "
                        "style flag — F is not doing what T91 measured"
                    )
                self._filter_presses += 1
                s.press_filter_toggle()
                self._filter_on = target_filter
                if s.filter_state is None:
                    # Blind fallback: announce, hold an abort window open.
                    self._say(
                        f"pressed F — tags should now read "
                        f"{'DEFAULT' if target_filter else 'FILTER'}-styled. "
                        "'abort' if they do not."
                    )
                    self._settle_until = (
                        self.services.clock() + self.confirm_seconds
                    )
                else:
                    self._settle_until = (
                        self.services.clock() + _TOGGLE_SETTLE_S
                    )
                return StepOutcome(done=False, acted=True, note="F pressed")
        # The battery owns the display for the whole round: enforcement
        # off in EVERY mode, or the executor would fight the battery for
        # the toggle (since R254 the standing policy presses tags OFF —
        # which would sabotage blocks B and C exactly the way the old
        # force-ON policy sabotaged block A).
        s.set_label_enforcement(False)
        s.runlog.event(
            "battery.mode",
            block=block, mode=mode,
            labels_on=labels, filter_on=self._filter_on,
            filter_readable=s.filter_state is not None,
            enforcement=False,
        )
        self._phase = "drop"
        return StepOutcome(done=False, acted=True,
                           note=f"block {block} mode set ({described})")

    # -- drop: one pile, where the character stands ---------------------------

    def _tick_drop(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        s = self.services
        if snap.player is None:
            return StepOutcome(done=False, waiting=True, note="no player read")
        if self._recover_stray_panels(snap, frozenset({offsets.UI_INVENTORY})):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        if self._drop_total is None:
            # First drop tick of the round: the pile forms HERE.
            self._anchor = snap.player.position
            self._pre_drop_counts = self._census()
            self._dropped = 0
            self._drop_total = len(
                self._droppables(s.carried_with_sockets())
            )
            self._manifest_kinds = set()
            self._consumed = Counter()
            self._floor_confirm = None
        # Floor-landing confirmation: the previous drop left the
        # inventory, but did it reach the GROUND? A slipped ctrl fires
        # the bare right-click — launch 3 drank a healing potion this
        # way and the census read it as a loss.
        if self._floor_confirm is not None:
            kind, prior, polls = self._floor_confirm
            landed = len(self._ground_in_arena(snap, {kind}))
            if landed > prior:
                self._floor_confirm = None
            elif polls < _FLOOR_CONFIRM_POLLS:
                self._floor_confirm = (kind, prior, polls + 1)
                return StepOutcome(done=False, waiting=True,
                                   note="confirming the drop landed")
            else:
                self._floor_confirm = None
                self._consumed[kind] += 1
                self._say(
                    f"note: a {self._logged_name(kind)} left the inventory "
                    "but never hit the floor — consumed by a slipped "
                    "click. Excluded from the census; continuing."
                )
                s.runlog.event(
                    "battery.consumed", item_kind=kind,
                    block=self._block()[0], round_no=self._round,
                )
        carried = s.carried_with_sockets()
        droppables = self._droppables(carried)
        if not droppables:
            if self._inv_open(snap):
                if s.clear_panels is not None:
                    s.clear_panels()
                return StepOutcome(done=False, acted=True, note="closing panels")
            s.runlog.event(
                "battery.round", stage="drop_end",
                block=self._block()[0], round_no=self._round,
                mode=self._block()[1], dropped=self._dropped,
            )
            self._reset_pickup_bookkeeping()
            self._phase = "test"
            self._test_started = None
            self._test_announced = False
            return StepOutcome(done=False, acted=True,
                               note=f"{self._dropped} item(s) dropped")
        if not self._inv_open(snap):
            s.open_inventory()
            return StepOutcome(done=False, acted=True, note="opening inventory")
        item = droppables[0]
        prior = len(self._ground_in_arena(snap, {item.kind}))
        if not s.drop_item(item):
            # The inventory.py rule: a drop that did not land means the
            # gesture is not doing what we asked; more attempts risk bare
            # right-clicks.
            return self._fail(
                f"kind {item.kind} would not drop — not aiming the same "
                "gesture at more items"
            )
        self._dropped += 1
        self._manifest_kinds.add(item.kind)
        self._floor_confirm = (item.kind, prior, 0)
        return StepOutcome(done=False, acted=True,
                           note=f"dropped kind {item.kind} "
                           f"({self._dropped}/{self._drop_total})")

    # -- test: the measured phase ---------------------------------------------

    def _wanted_left(self, snap: GameSnapshot) -> int:
        """Manifest-kind items still on the floor that the pickit wants
        RIGHT NOW. Kind-based on purpose: ground unit ids churn."""
        carried = self.services.carried()
        return sum(
            1 for g in self._ground_in_arena(snap, self._manifest_kinds)
            if self.services.pickit.decide(g, carried)[0] != "skip"
        )

    def _tick_test(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        s = self.services
        if self._recover_stray_panels(snap, frozenset()):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        now = self.services.clock()
        if self._test_started is None:
            block, mode, described = self._block()
            self._say(f"round {self._round_label()} - mode {described}")
            ground = self._ground_in_arena(snap, self._manifest_kinds)
            carried = s.carried()
            wanted = [g for g in ground
                      if s.pickit.decide(g, carried)[0] != "skip"]
            self._wanted_start = len(wanted)
            self._junk_start = len(ground) - len(wanted)
            self._test_started = now
            s.runlog.event(
                "battery.round", stage="test_start",
                block=block, round_no=self._round, mode=mode,
                wanted_on_ground=self._wanted_start,
                junk_on_ground=self._junk_start,
                wanted_kinds=sorted({g.kind for g in wanted}),
            )
        self.confirm_pickups(snap)
        elapsed = now - self._test_started
        wanted_left = self._wanted_left(snap)
        finished = wanted_left == 0 and not s.pending_pickup
        timed_out = elapsed >= float(self.round_seconds)
        if finished or timed_out:
            ground = self._ground_in_arena(snap, self._manifest_kinds)
            junk_left = sum(
                1 for g in ground
                if s.pickit.decide(g, s.carried())[0] == "skip"
            )
            # Boundary honesty (tagmode review, issue 002): a click sent
            # just before the cap whose item leaves the ground one tick
            # LATER is not a miss — it is still RESOLVING, and scoring
            # it as `wanted_left` biased every timed-out round (only
            # they can end with clicks in flight). Reported as its own
            # count rather than folded into either side; the census
            # reconciliation was always immune (the item lands in the
            # inventory and counts there).
            resolving = sum(
                1 for g in ground
                if g.unit_id in s.pending_pickup
                and s.pickit.decide(g, s.carried())[0] != "skip"
            )
            got = self._wanted_start - wanted_left
            wanted_left -= resolving
            junk_got = max(self._junk_start - junk_left, 0)
            block, mode, _ = self._block()
            self._say(
                f"round {self._round_label()} score: {got}/"
                f"{self._wanted_start} whitelisted, {junk_got} unwanted, "
                f"{elapsed:.1f}s"
                + (f", {resolving} click(s) still resolving" if resolving else "")
            )
            s.runlog.event(
                "battery.round", stage="test_end",
                block=block, round_no=self._round, mode=mode,
                elapsed_s=round(elapsed, 2), timed_out=timed_out,
                collected=got, wanted_left=wanted_left,
                resolving=resolving,
                junk_collected=junk_got,
            )
            self._reset_pickup_bookkeeping()
            # The bot's pickup work is over for this round; re-arm the
            # standing label policy before handing the floor over.
            s.set_label_enforcement(True)
            self._phase = "gather"
            self._gather_started = None
            return StepOutcome(
                done=False, acted=True,
                note=f"round {self._round_label()} over "
                f"({'timeout' if timed_out else 'clean'}) — over to the operator",
            )
        if snap.player is not None:
            assert self._anchor is not None
            items = self._draw_order(
                self.wanted_items(snap, self._anchor, self.radius)
            )
            if items and self.collect(snap, ctx, items[0]):
                return StepOutcome(done=False, acted=True)
        return StepOutcome(done=False, waiting=True, note="test running")

    # -- gather: the operator's job, immediately (R251 feedback) ----------------

    def _tick_gather(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        """The bot never collects between rounds: a human with a mouse
        clears the pile in seconds, so the ask comes the moment the
        round is scored, and the bot stays hands-off — clicking now
        would fight the operator for the same items."""
        s = self.services
        if self._recover_stray_panels(snap, frozenset()):
            return StepOutcome(done=False, acted=True, note="closed a stray panel")
        now = self.services.clock()
        if self._gather_started is None:
            self._gather_started = now
            self._last_nag = now
            remaining = self._ground_in_arena(snap, self._manifest_kinds)
            self._say(
                f"round {self._round_label()} done — please pick up all "
                f"the items ({len(remaining)} on the floor); resuming "
                "when it is clear."
            )
            s.runlog.event(
                "battery.assist", block=self._block()[0],
                round_no=self._round, remaining=len(remaining),
            )
            return StepOutcome(done=False, acted=True, note="asked the operator")
        self.confirm_pickups(snap)  # closes out the test phase's pendings
        remaining = self._ground_in_arena(snap, self._manifest_kinds)
        if not remaining and not s.pending_pickup:
            counts = self._census()
            expected = (self._pre_drop_counts or Counter()) - self._consumed
            reconciled = counts in (expected, self._pre_drop_counts)
            s.runlog.event(
                "battery.round", stage="gather_end",
                block=self._block()[0], round_no=self._round,
                mode=self._block()[1],
                elapsed_s=round(now - self._gather_started, 2),
                reconciled=reconciled,
                consumed={str(k): n for k, n in self._consumed.items()},
            )
            if not reconciled:
                # Announced and RECORDED, never fatal (R251: launch 3
                # ended a healthy battery over one drunk potion, and
                # stackables can merge on pickup, which a count census
                # reads as loss). The operator is watching; abort is
                # theirs.
                missing = expected - counts
                gained = counts - expected
                s.runlog.event(
                    "battery.loss",
                    block=self._block()[0], round_no=self._round,
                    missing={str(k): n for k, n in missing.items()},
                    gained={str(k): n for k, n in gained.items()},
                )
                detail = []
                if missing:
                    detail.append(
                        "missing "
                        + ", ".join(
                            self._logged_name(k) for k in missing
                        )
                    )
                if gained:
                    detail.append(
                        "extra "
                        + ", ".join(self._logged_name(k) for k in gained)
                    )
                self._say(
                    f"census note ({'; '.join(detail)}) — a stack may "
                    "have merged or an item was consumed. Recorded; "
                    "continuing."
                )
            self._say("resuming.")
            self._rounds_done += 1
            return self._advance()
        # Keep the hold audible: each nag is a real chat send, so the
        # engine's wait accounting sees action, never a hang.
        if now - self._last_nag >= _HOLD_NAG_S:
            self._last_nag = now
            spots = ", ".join(str(g.position) for g in remaining[:4])
            self._say(
                f"waiting on {len(remaining)} item(s) ({spots}) — "
                "resuming once the floor is clear."
            )
            return StepOutcome(done=False, acted=True, note="hold nag")
        return StepOutcome(done=False, waiting=True,
                           note="waiting for the operator")

    def _advance(self) -> StepOutcome:
        """Next round, next block, or the final restore."""
        self._drop_total = None
        self._test_started = None
        self._gather_started = None
        self._mode_presses = 0
        self._filter_presses = 0
        self._anchor = None
        label = self._round_label()
        self._round += 1
        if self._round > self.rounds:
            self._round = 1
            self._block_i += 1
        if self._block_i >= len(self._block_list()):
            self._phase = "final"
        else:
            # set_mode is a no-op within a block (the flags already
            # agree); at a block boundary it presses ALT or F once.
            self._phase = "set_mode"
        return StepOutcome(done=False, acted=True,
                           note=f"round {label} reconciled "
                           f"({self._rounds_done} done)")

    # -- final: restore the client the way we found it --------------------------

    def _tick_final(self, snap: GameSnapshot, ctx: EngineContext) -> StepOutcome:
        s = self.services
        s.set_label_enforcement(True)
        if self._settle_until is not None:
            if self.services.clock() < self._settle_until:
                return StepOutcome(done=False, waiting=True,
                                   note="toggle settling")
            self._settle_until = None
        labels = s.label_state()
        if (
            self._labels_initial is not None
            and labels is not None
            and labels != self._labels_initial
            and self._mode_presses < _MODE_PRESSES_MAX
        ):
            self._mode_presses += 1
            s.press_show_items()
            self._settle_until = self.services.clock() + _TOGGLE_SETTLE_S
            return StepOutcome(done=False, acted=True, note="restoring labels")
        filter_now = (
            s.filter_state() if s.filter_state is not None else self._filter_on
        )
        if (
            filter_now != self.filter_initially_on
            and self._filter_presses < _MODE_PRESSES_MAX
        ):
            self._filter_presses += 1
            s.press_filter_toggle()
            self._filter_on = self.filter_initially_on
            self._settle_until = self.services.clock() + _TOGGLE_SETTLE_S
            return StepOutcome(done=False, acted=True, note="restoring F")
        self._say(
            f"TAG-MODE BATTERY COMPLETE: {self._rounds_done} round(s) "
            "reconciled, nothing left on the floor."
        )
        s.runlog.event("battery.end", completed=True,
                       rounds_done=self._rounds_done)
        self._phase = "done"
        return StepOutcome(done=True, acted=True,
                           note=f"battery complete ({self._rounds_done} rounds)")
