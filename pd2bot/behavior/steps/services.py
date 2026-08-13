"""RunServices: the shared services container every step receives.

Split from steps.py 2026-08-09; bodies unchanged.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pd2bot.behavior.steps.util import (
    _default_alert,
    _default_log,
)
from pd2bot.perception.items import CarriedItems
from pd2bot.pickit import Pickit
from pd2bot.runlog import NullRunLog
from pd2bot.runlog.narrate import noop as narrate_noop


@dataclass
class RunServices:
    """Everything the steps need, bound once when the registry is built."""

    run_preamble: Callable[[], object]
    travel_to: Callable[[int], object]
    combat: object  # a CombatModule
    pickit: Pickit
    carried: Callable[[], CarriedItems]
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    # The loaded posture names (M6 P3), for BUILD-time validation of a
    # step's `posture` parameter. Empty = no postures in this environment
    # (sims, drills), and naming one is then a loud build error rather
    # than a runtime surprise.
    postures: frozenset[str] = frozenset()
    # The route leash (R241): `route_line_for(area_id)` -> RouteLine or
    # None. None for the whole field = no leash anywhere (sims, tests,
    # pre-leash wiring) — every consumer must tolerate that.
    route_line_for: Callable[[int], object | None] | None = None
    # Mandatory pickup orders (R241 item 7): an OrderBook, or None when
    # the pilot flag is off (the default — Cold Plains pilots it first).
    order_book: object | None = None
    # Leash numbers, threaded from ClassConfig.route at wiring time.
    route_stray_subtiles: float = 12.0
    route_return_hostile_radius: int = 12
    # Tuning that belongs to the steps rather than to a class.
    clear_settle_s: float = 5.0
    pickup_radius: int = 30  # opportunistic pickups during clearance
    pickup_reach: int = 4  # close enough to click an item and have it land
    pickup_attempts: int = 3  # WALKS toward an item before calling it stuck
    # CLICKS per item before calling it stuck — one per T63 sprite-offset,
    # so the budget and the aim schedule are the same length by design:
    # every write-off means every measured aim point was actually tried.
    pickup_click_attempts: int = 8
    pickup_retry_s: float = 1.5  # between attempts on the same item
    alert: Callable[[str], None] = _default_alert
    # Where per-decision detail goes. Separate from `alert`, which is for
    # things a human must act on; this is the run's record.
    log: Callable[[str], None] = _default_log
    # The NARRATIVE channel (R179): one line per broad act, wall-clock
    # stamped by the Narrator behind it. Deliberately coarser than `log`
    # — the contract lives in pd2bot/narrate.py, and every call site here
    # is an editorial decision. Defaults to a no-op so sims and drills
    # stay silent unless they opt in.
    narrate: Callable[[str], None] = narrate_noop
    # Pickup bookkeeping, shared by every step that collects loot.
    #
    # It lives HERE rather than on a step because it must outlast the step
    # that recorded it. Clearance and the sweep both pick things up, and
    # when each kept its own memory the sweep re-attempted an item
    # clearance had already given up on — six clicks on an unpickable
    # unique instead of three (found in the P5 sim). Two steps doing the
    # same thing must not differ in what they remember: that is the same
    # asymmetry that cost three live runs in P3, where the heal retried a
    # missed click and the repair did not.
    inventory_full: bool = False
    attempts: dict[int, int] = field(default_factory=dict)
    last_try: dict[int, float] = field(default_factory=dict)
    stuck: set[int] = field(default_factory=set)
    # The inventory cleanse (R117). `cleanse` is the procedure itself
    # (TownLayer.cleanse_inventory behind a closure at wiring time; the
    # sim scripts its own); None means unavailable — which it IS while the
    # pickit vocabulary has unverified ids (pickit.cleanse_keep returns
    # None, and the wiring passes that straight through). A failed pickup
    # queues one; it runs at the next safe moment, defined as no live
    # hostile within `cleanse_safe_radius` — the cleanse stands still with
    # panels open, which is precisely what must never happen in a fight.
    cleanse: Callable[[], int] | None = None
    cleanse_queued: bool = False
    # Close whatever blocking panel is up (TownLayer.close_panels behind a
    # closure at wiring time). None means unavailable, and the steps treat
    # it as "nothing I can do" rather than as "nothing to do".
    #
    # The field needs this because a panel outside town is not recoverable
    # by waiting: `GatedInput` refuses every send while one is open, so the
    # bot decides correctly and reaches the game with none of it. Stage B's
    # tenth attempt opened the waypoint menu with a mis-placed cast and
    # spent its remaining 10 s being refused, then chickened out with the
    # area untouched. The town layer has closed stray panels since R85; the
    # field simply had no way to ask.
    clear_panels: Callable[[], None] | None = None
    # -- the patrol (2026-08-01) ------------------------------------------
    #
    # `clear_radius` decides the area is clear when no live monster is
    # within `radius` of the centre — and it can decide that from a
    # STANDSTILL only while the radius fits inside perception. T51
    # measured perception on 2026-08-01: items vanish at 46-67 subtiles,
    # room-quantised, NOT the 80 `units.PERCEPTION_RADIUS` claims (that
    # constant never binds; the client's loaded-room horizon does).
    # `runs/cold-plains.toml` asks for 150, so it has always been
    # declaring clear a circle it can see under a third of.
    #
    # The patrol walks the circle instead. Numbers live here rather than
    # in the run file because they are judgement calls nobody should have
    # to restate per run; the run file carries the one number the user
    # actually tunes, which is the radius.
    patrol_points: int = 8  # sample points evenly spaced around the ring
    # The ring's radius as a FRACTION of the clearance radius. A fraction
    # on purpose (user request: "make the radius value easy to alter"):
    # an absolute ring would stay put while the circle grew around it, so
    # changing the one number would silently stop covering the edge.
    patrol_ring: float = 0.66
    # Subtiles per leg. `walk_to` BLOCKS until arrival (navigate.py), so a
    # leg is time the reflex ladder is not being consulted — the same
    # reason `NecroCombat._dash_target` caps a dash at 8. A little longer
    # than a dash because nothing is being fought yet.
    patrol_step: int = 12
    patrol_reach: int = 6  # close enough to call a point visited
    # Legs WITHOUT GETTING CLOSER before giving up on a point, so a point
    # we can walk toward but never reach cannot hold the run open forever.
    #
    # Counted as lack of progress rather than as a number of legs, which
    # was the first cut and was wrong: consecutive ring points are ~48
    # subtiles apart, so three 12-subtile legs always fell one short and
    # the sim abandoned SEVEN OF EIGHT points while reporting green.
    # A budget that has to be re-derived whenever the ring or the leg
    # length changes is not a budget, it is a coincidence.
    patrol_attempts: int = 3
    # -- writing off a monster we cannot get to ---------------------------
    #
    # The same idea as `stuck` for items and as `patrol_attempts` for ring
    # points, arriving late because `clear_radius` only recently stopped
    # ending the run over it. `send` absorbs `NavigationError` so one
    # unreachable target cannot fail the cycle — correct, and incomplete on
    # its own: nothing then wrote the monster off, so the step re-decided
    # the identical approach every tick and the clearance could never
    # finish. The user watched it "hesitate at great length when an enemy
    # was behind a wall".
    #
    # Ticks of closing on one monster WITHOUT GETTING CLOSER before giving
    # up on it. Progress rather than effort, the same correction the patrol
    # needed: a budget counted in attempts has to be re-derived whenever
    # anything about the geometry changes, and is a coincidence rather than
    # a budget.
    monster_attempts: int = 3
    # How far a written-off monster must MOVE to earn another try.
    #
    # Monsters differ from ring points and from items in the one way that
    # matters here: they walk. The write-off says "unreachable from where it
    # was standing", and a monster that has since left that spot has
    # invalidated the only evidence behind it — which is this codebase's own
    # rule that a retry which cannot differ from the attempt it retries is
    # not a retry. Without this, a monster that gives up on its own wall and
    # walks into the open would be ignored for the rest of the game.
    unreachable_forget: int = 10
    # How far to step off a waypoint after arriving on one (user request).
    # The character lands ON the waypoint with the cursor still over it,
    # which makes the next few clicks — and any ground-targeted cast — a
    # coin flip on opening its menu. Moving off first is cheaper than
    # avoiding it from on top of it.
    waypoint_step_off: int = 10
    # Potion types the belt has refused this game. Kept apart from
    # `inventory_full` because they are different facts with different
    # remedies: the cleanse can free inventory grid space, and nothing
    # the bot does in the field can empty a full belt column.
    #
    # Since T56 (2026-08-02) the set is EVIDENCE-CHECKED both ways rather
    # than sticky: a type only enters it while the live belt count really
    # is at capacity (a click that fails with room in the belt is a MISS,
    # and misses write off the item, not the type), and it leaves the set
    # the moment drinking makes room again — "nothing the bot does in the
    # field can empty a full belt column" forgot that the ladder empties
    # them all game long, and a game that starts with one transiently full
    # column must not end it ignoring the potions it is starving for.
    belt_full: set[str] = field(default_factory=set)
    # Items we have clicked and not yet seen leave the ground: unit_id ->
    # (kind, potion type, position, clicked-at). Pure telemetry — the
    # confirmation narrates the arrival with a belt census, which is what
    # makes the narrative log answer "did the potions actually arrive?"
    # (T56's log showed the same coordinates "picked" twice and the belt
    # still short, and nobody could say what really happened).
    pending_pickup: dict[int, tuple] = field(default_factory=dict)
    # What the most recent pickup click was aimed at: (unit_id, position,
    # when). Telemetry for the "clicked A, got B" case — T71 run 4 had 9
    # of its 13 misses sitting within 2 subtiles of an item that DID come
    # up, so the click was landing on the neighbour. Knowing that turns a
    # one-off forensic finding into a standing measurement.
    last_click: tuple[int, tuple[int, int], float] | None = None
    cleanse_safe_radius: int = 40
    # -- cleanse drop hygiene (R175, user-diagnosed live) ------------------
    #
    # The R173 run found the loop: the cleanse drops junk AT THE FEET,
    # right where the failed pickup is about to click again, and the click
    # scoops the junk straight back. Dropped items appear at the pointer
    # (user observation, watching it happen). So: never drop within this
    # distance of an item we intend to click, and after dropping, get at
    # least this far from the pile before clicking anything. 8 is
    # comfortably past the sprite-overlap zone (a click hits items within
    # a subtile or two) without costing real walking time.
    cleanse_standoff: int = 8
    # Where the last cleanse dropped its junk; None = no pile to avoid.
    # Shared service state, not step state, for the usual reason: both the
    # clearance and the sweep cleanse, and the pile does not care which
    # step made it.
    cleanse_dropped_at: tuple[int, int] | None = None
    # Items that already got their one post-cleanse retry. The cleanse
    # frees space and the bot steps clear of the pile, so the retry
    # genuinely differs from the attempt that failed — once. A second
    # failure of the same item cannot be explained by junk-at-the-feet
    # again, so it is final for this game: re-queueing another cleanse for
    # it is the retry-that-cannot-differ this codebase keeps refusing.
    cleanse_retried: set[int] = field(default_factory=set)
    # The reason the last tick's QUEUED cleanse did not run, so the
    # deferral event fires once per streak instead of once per tick
    # (hostiles linger for many ticks). None = not currently deferred.
    # Telemetry only — never read for a decision.
    cleanse_deferred_reason: str | None = None
    # Hygiene-walk patience (review 2026-08-02, issue 001). The walk-away
    # and step-off walks are the "acted but achieved nothing" shape the
    # survey's fight gate had: a walk clamped at a wall ARRIVES (honest
    # arrival) without gaining an inch, and an unbounded retry of it pins
    # the bot with every watchdog blind — each tick sends real input.
    # Progress = distance from the repel point growing; `patrol_attempts`
    # progress-free walks spend the patience and the hygiene yields
    # (drop anyway / accept the pile risk), which is the R173 trade again:
    # one risky cleanse beats a pinned character.
    hygiene_walk_best: int | None = None
    hygiene_walk_attempts: int = 0
    # Collect-walk patience (R189, T55 run 2's border livelock): per item,
    # the closest a collect walk has gotten and how many walks have gained
    # nothing since. The walk to the seam item ARRIVED 5 subtiles short of
    # pickup reach every time, clicked nothing, and therefore spent
    # nothing — collect's only budget counted CLICKS. Walks that get no
    # closer now pay the same budget every other mover pays
    # (`pickup_attempts`), and the item is written off as stuck.
    collect_closest: dict[int, int] = field(default_factory=dict)
    collect_stalls: dict[int, int] = field(default_factory=dict)
    # Progress must beat the best distance by this margin to reset a
    # no-progress budget (R189): T55 run 2's ping-pong occasionally
    # landed a single subtile closer, and that hair of "progress" kept
    # the patrol budget resetting forever. Slow-but-real closing still
    # survives — two subtiles over a few legs re-earns the budget.
    patrol_progress_margin: int = 2
    # The sightings memo (T3, R186 — the user's per-run scratch-note
    # idea, verbatim): every wanted item the CLEARANCE saw, by unit id,
    # at the position it was seen. Entries are reaped once the spot is
    # back in view and the item is gone (collected or despawned), and
    # `stuck` items do not count as pending. The sweep re-walks the ring
    # ONLY while this holds something unaccounted for — the full re-walk
    # of ground the clearance just patrolled was ~60-120 s of the run,
    # spent mostly confirming emptiness. Dies with the run, like every
    # RunServices field: a memo, not a memory.
    #
    # Value = (position, kind, potion type or None). Kind and type exist
    # so `pending_sightings` can re-ask WANTEDNESS at sweep time (review
    # 002, potions-live-validation): an item recorded as wanted can stop
    # being wanted — a mana potion sighted early, then belt_full["mana"]
    # set — and a memo that cannot re-check kept the sweep walking the
    # ring for a bottle nobody would pick up on arrival.
    wanted_seen: dict[int, tuple[tuple[int, int], int, str | None]] = field(
        default_factory=dict
    )
    # -- the survey step (R175/R176) ---------------------------------------
    #
    # Both closures are wired closures over the map store (wiring.py) so
    # the step never learns what a MapStore is — the same treatment
    # `cleanse` gets. None = no survey service in this environment, and
    # the step finishes immediately rather than guessing.
    survey_targets: Callable[[], list[tuple[int, int]]] | None = None
    survey_coverage: Callable[[], str] | None = None
    # -- the traverse step (M6 P2) -----------------------------------------
    #
    # Wired closures over the exit reader and the exit memory, so the
    # step never learns what a GameSession or an ExitMemory is (the
    # survey-closure treatment). None = unavailable in this environment;
    # the step waits on the reader and treats missing memory as cold.
    level_exits: Callable[[], object | None] | None = None  # -> ExitScan
    exit_recall: Callable[[int, int], tuple[int, int] | None] | None = None
    exit_remember: (
        Callable[[int, int, tuple[int, int]], None] | None
    ) = None
    # -- the route service (R181) ------------------------------------------
    #
    # `route_to(target)` plans A* over the navigator's grid (atlas + live
    # overlay) and returns the simplified waypoint list, or None when NO
    # PATH EXISTS. Read-only — no clicks, no walking — and cached briefly
    # by the wiring, because re-planning every tick is the tick-rate waste
    # this repo keeps refusing. None (the field, not the answer) means no
    # service is wired: open-ground sims and drills fall back to the old
    # straight-line hops via `_route_leg`.
    route_to: Callable[
        [tuple[int, int]], list[tuple[int, int]] | None
    ] | None = None
    # Fight only what comes this close while surveying (R176 Q1): a
    # survey is not a clearance, and the reflex ladder plus chicken stay
    # on above this either way.
    survey_engage_radius: int = 30
    # Hard cap on survey walking, as legs. A backstop against convergence
    # bugs, not a tuning knob — but sized for a big Hell area with
    # give-up retries included (~13 subtiles a leg, so this is several
    # kilometres of walking). The first Cold Plains attempt showed the
    # real risk is a LOOP that never sends survey legs at all, which this
    # cannot catch; `survey_fight_patience` is what catches that.
    survey_max_legs: int = 500
    # Consecutive fighting ticks in which neither the distance to the
    # gating monster nor its hp improves before the survey writes it off
    # and walks on. ~10 s at the engine's tick rate: far longer than any
    # deliberate combat pause (restrike 1 s, revives ~2 s), far shorter
    # than the 14 minutes the first Cold Plains survey burned on a
    # monster it could approach forever and reach never.
    survey_fight_patience: int = 20
    # Whether this game has already alerted about a target on unsurveyed
    # ground (R176 Q2: no auto-survey mid-run — say it loudly, once, and
    # recommend the survey run instead). Once, because the same run will
    # often give up on several such targets and each repeat of the alert
    # buys nothing.
    unsurveyed_alerted: bool = False
    # -- the run event log (P6/P7) ----------------------------------------
    #
    # The steps' own events: area transitions, wanted drops, collections,
    # accidental pickups, the cleanse. Defaults to the null sink so the
    # sim and unit tests stay silent; `wiring.py` passes the real log.
    runlog: object = field(default_factory=NullRunLog)
    frame: Callable[[], object] | None = None
    # Wanted items already announced this run, by unit id — `item.dropped`
    # fires on the TRANSITION into the wanted set, so a rune lying on the
    # floor for thirty ticks is one event, not thirty.
    seen_drops: set[int] = field(default_factory=set)
    # -- the tag-mode battery (R248, TEST KIT) ------------------------------
    #
    # Wired closures, every one None/unknown by default so sims, drills
    # and every existing run are untouched. The battery step REFUSES to
    # run without the ones it needs rather than improvising around them
    # — a calibration that silently measured the wrong thing would be
    # worse than one that refuses (the T72 lesson, applied to test kit).
    #
    # One inventory item ctrl+right-clicked to the floor, effect-verified
    # (TownLayer.drop_item — stash must be CLOSED, inventory OPEN).
    drop_item: Callable[[object], bool] | None = None
    # The inventory panel, opened verified (TownLayer.press_inventory_open).
    open_inventory: Callable[[], None] | None = None
    # Carried items WITH sockets, for whitelist verdicts on what is about
    # to be dropped — socket-conditioned keep rules cannot be judged from
    # the cheap read (`carried`, with_sockets=False), the R132 lesson.
    carried_with_sockets: Callable[[], CarriedItems] | None = None
    # The ground-label display state (BH.dll's flag, T66): True/False, or
    # None = unreadable. The battery refuses on None — the flag lives in
    # the loot filter's own module, so unreadable means the modes under
    # test do not exist in this client.
    label_state: Callable[[], bool | None] | None = None
    # One press of the character's real Show Items key (R247 bindings).
    press_show_items: Callable[[], None] | None = None
    # One press of the default-tags toggle ("F" — bound NOWHERE on disk,
    # see the R248 plan's discovery; pressed blind until the T91 probe
    # finds its state flag).
    press_filter_toggle: Callable[[], None] | None = None
    # The default-tags state, once T91 pins its flag. None = no reader
    # wired — the battery then tracks parity blind and says so.
    filter_state: Callable[[], bool | None] | None = None
    # Flip the executor's label enforcement (see
    # GameActionExecutor.enforce_label_display): mode 1 measures pickup
    # with labels OFF, which the enforcing executor would sabotage one
    # click in.
    set_label_enforcement: Callable[[bool], None] | None = None
    # Operator-facing chat line (Chat.say behind a closure that absorbs
    # refusals). The battery announces every mode switch and the final
    # reconciliation; None falls back to `alert`.
    say: Callable[[str], None] | None = None
    # -- the countess endgame (M6 P4) --------------------------------------
    #
    # Judgement calls that belong to the step, not the run file — the run
    # file carries what the user tunes (the chamber anchor, the radii).
    #
    # How far screen-north of the chamber anchor the staging point sits.
    # Screen-north is the world (-1,-1) diagonal (the projection is
    # sx=(wx-wy), sy=(wx+wy): decreasing both is "up"). 25 is outside
    # the aggressive posture's engagement bubble but inside one or two
    # advance legs — staged, not camped.
    staging_distance: int = 25
    # The chamber sweep's whole budget (R212 Q7: "<15 s"). One short
    # in-and-out pass so a blind corner cannot hide her; spent across
    # every entry into the sweep, not per entry, so a countess who blinks
    # in and out of perception cannot stretch it forever.
    sweep_budget_s: float = 15.0
    # Ticks the advance will hold for the revive wall without the wall
    # GROWING before it advances anyway, loudly. The brake is the user's
    # tactic (revives tank the approach); the bound exists because a
    # fresh cellar with nothing dead nearby can never raise a wall, and
    # a brake that cannot release is a hang, not a tactic (~10 s at tick
    # rate — the survey's fight-patience shape).
    advance_revive_patience: int = 20


# -- blocking steps ------------------------------------------------------------



