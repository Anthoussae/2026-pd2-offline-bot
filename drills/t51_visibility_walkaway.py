"""T51 — at what distance does the bot STOP seeing a thing? Measured.

**Read-only as far as the world is concerned: no clicks, no movement, no
skills.** It does talk in chat (status updates, at the user's request), and
chat types characters — so it is not literally send-free, and saying so is
cheaper than a reader discovering it. The user drives the character
throughout; the bot only watches.

## The user's test, and the refinement that makes it decisive

The user's proposal was to drop a series of potions at intervals and count
how many the bot perceives. That is the right instinct — a controlled probe
with known ground truth — and it needs one change to answer the question
rather than merely bracket it.

The question is not "how far can the bot see", it is **which of two things
is the limit**:

  A. **our own filter** — `scan_units` drops every unit outside `radius`,
     and `PERCEPTION_RADIUS` is 80. If this is the bound, raising the
     number works, and T50 already priced it (a scan costs ~7 ms at ANY
     radius, so the number is not buying us any speed).

  B. **the client's own horizon** — the game only populates its unit hash
     table for rooms it has loaded. If this is the bound, raising our
     number buys exactly nothing and the only way to cover ground is to
     walk it.

Counting potions cannot tell those apart, because both look identical from
the outside: the item is not in the snapshot. So every sample here scans
**twice** — once at `PERCEPTION_RADIUS`, once at a radius so large the
filter cannot possibly bite — and watches which one loses the item first.

    lost at 80 but still seen unlimited  ->  OUR FILTER is the bound (A)
    lost at both, at the same distance   ->  THE CLIENT is the bound (B)

A dropped item is the ideal probe for one reason a monster could never
match: **it does not move**, so its world position recorded at drop time
stays true ground truth after it becomes invisible, which is precisely when
we can no longer read it.

## What to do

1. Start this. It records what is already on the ground so your drops are
   distinguishable from the scenery.
2. **Drop an item** — a potion is perfect — at your feet. It locks on and
   says so. Drop several if you like; every new one is tracked separately,
   which is the user's original trail idea and still works.
3. **Walk away in a straight line**, steadily, as far as the area allows.
   Do not pick anything back up.
4. Watch the transitions print. It stops on its own once everything has
   been out of sight for a while, or at `--seconds`.

Cold Plains is a better room than town: it is open, and town ran out of
distance at 57 subtiles in T50, which is not far enough to test 80.

    python drills/t51_visibility_walkaway.py --seconds 240

Cancel at any time with `powershell -File tools\\drill-cancel.ps1`.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pd2bot.drill import (  # noqa: E402
    CANCEL_FILE,
    Drill,
    DrillRun,
    run_drill,
)
from pd2bot.memory import GameSession  # noqa: E402
from pd2bot.player import read_player  # noqa: E402
from pd2bot.units import PERCEPTION_RADIUS, scan_units  # noqa: E402

T51 = Drill(
    test_id="T51",
    title="visibility vs distance — the walk-away test",
    kind="perception",
    sends_input=False,
    instructions=(
        "DROP A POTION at your feet, then WALK AWAY in a straight line.",
        "Drop another every ~20 steps. Each drop is counted back to you.",
        "IT ENDS on its own: 16 drops all out of view, or 3 minutes.",
        "  You will get a 'T51 DONE' message — keep walking until then.",
        "Do not pick anything back up. The bot only READS; you drive.",
        "Cancel any time: powershell -File tools\\drill-cancel.ps1",
    ),
)

# A radius so large `near()` cannot bite. Deliberately the SAME function as
# the real scan rather than a separate unfiltered path: if the two disagreed
# it would have to be for a reason about the game, not about our plumbing.
UNLIMITED = 1_000_000
POLL_S = 0.25
# A new item this close to the player is one the user just dropped, rather
# than something that was always lying there.
DROP_NEAR = 8
# Stop once every tracked item has been invisible (at unlimited) for this
# long — the measurement is over and the walk back is not interesting.
QUIET_S = 12.0
# Patience for the in-loop chat updates, and it must be SHORT.
#
# `Chat` refuses while a blocking panel is open, and retries at the default
# patience for a full minute. Dropping an item means the INVENTORY is open,
# which is exactly when the lock-on message fires — so the default would
# stall the measurement loop for 60 s at the one moment it must not, and
# the drill would miss the whole first stretch of the walk. A status
# message is worth a couple of seconds and not one more; the measurement is
# the point, the narration is a courtesy.
SAY_PATIENCE_S = 2.5
# The end condition, and its absence was a real design fault (user, run 1):
# the drill knew when it was finished and the PERSON WALKING did not, so
# they were left walking with no idea whether to stop. A test the subject
# cannot tell the end of is not finished being designed.
#
# Three ways to stop, whichever comes first, all of them announced in chat
# as they approach:
#   * `--drops` items dropped and every one of them out of view — the
#     measurement is complete, there is nothing left to learn;
#   * `--seconds` elapsed — the wall-clock backstop;
#   * everything out of view for QUIET_S with at least MIN_DROPS made —
#     the early finish for a short walk that already answered the question.
DEFAULT_DROPS = 16
DEFAULT_SECONDS = 180.0
MIN_DROPS = 3


def _chebyshev(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class Probe:
    """One dropped item, and the distances at which it came and went.

    Both directions are recorded, not just the loss. A boundary that is
    clean has every "seen" distance below every "unseen" one; overlap means
    the horizon is fuzzy (or the item was picked up and the run is void),
    and a summary that only printed the first loss would hide that.
    """

    def __init__(self, unit_id: int, kind: int, position: tuple[int, int]) -> None:
        self.unit_id = unit_id
        self.kind = kind
        self.position = position  # ground truth: items do not move
        self.seen_at: dict[str, list[int]] = {"80": [], "all": []}
        self.unseen_at: dict[str, list[int]] = {"80": [], "all": []}
        self.state: dict[str, bool | None] = {"80": None, "all": None}
        self.last_seen_time = time.monotonic()

    def record(self, scope: str, distance: int, visible: bool) -> str | None:
        """Note one observation. Returns a line to print on a TRANSITION."""
        (self.seen_at if visible else self.unseen_at)[scope].append(distance)
        if visible:
            self.last_seen_time = time.monotonic()
        was = self.state[scope]
        self.state[scope] = visible
        if was is None or was == visible:
            return None
        label = "radius 80 " if scope == "80" else "unlimited "
        verb = "REAPPEARED at" if visible else "LOST at"
        return f"    item {self.unit_id}: {label} {verb} d={distance}"

    def summary_row(self) -> str:
        def span(values):
            return f"{min(values)}-{max(values)}" if values else "-"

        return (
            f"  item {self.unit_id:>6} kind {self.kind:>4} at {self.position}\n"
            f"      radius 80    seen d={span(self.seen_at['80'])}   "
            f"not seen d={span(self.unseen_at['80'])}\n"
            f"      unlimited    seen d={span(self.seen_at['all'])}   "
            f"not seen d={span(self.unseen_at['all'])}"
        )

    @property
    def horizon(self) -> int | None:
        """Furthest distance the CLIENT still held it, or None if never lost."""
        if not self.unseen_at["all"]:
            return None
        return max(self.seen_at["all"]) if self.seen_at["all"] else 0


def t51_body(
    run: DrillRun,
    seconds: float = DEFAULT_SECONDS,
    drops: int = DEFAULT_DROPS,
) -> str:
    session = run.session
    player = read_player(session)
    if player is None:
        raise RuntimeError("not in a game — enter one first")
    print(
        f"T51 visibility walk-away — player at {player.position}. "
        "READ-ONLY: nothing is sent.\n"
    )

    baseline = {i.unit_id for i in scan_units(session, radius=UNLIMITED).ground_items}
    print(f"  {len(baseline)} item(s) already on the ground; those are ignored.")
    print("\n  >>> DROP AN ITEM AT YOUR FEET NOW (a potion is ideal).")
    print("  >>> Then walk away in a straight line. Do not pick it back up.\n")

    probes: dict[int, Probe] = {}
    started = time.monotonic()
    last_distance_print = 0.0
    last_chat = time.monotonic()
    last_line = ""
    ending = "the time limit"

    while time.monotonic() - started < seconds:
        if CANCEL_FILE.exists():
            print("\n  cancelled by request.")
            break
        time.sleep(POLL_S)

        player = read_player(session)
        if player is None:
            print("  left the game — stopping.")
            break
        here = player.position

        wide = scan_units(session, radius=UNLIMITED)
        near = scan_units(session, radius=PERCEPTION_RADIUS)
        wide_ids = {i.unit_id for i in wide.ground_items}
        near_ids = {i.unit_id for i in near.ground_items}

        # New drops. Taken from the WIDE scan and gated on being close to
        # the player, so a drop is never confused with scenery that merely
        # came into view as we walked.
        for item in wide.ground_items:
            if item.unit_id in baseline or item.unit_id in probes:
                continue
            if _chebyshev(item.position, here) > DROP_NEAR:
                baseline.add(item.unit_id)  # not ours; ignore it from now on
                continue
            probes[item.unit_id] = Probe(item.unit_id, item.kind, item.position)
            print(
                f"  LOCKED ON item {item.unit_id} (kind {item.kind}) at "
                f"{item.position} — walk away now."
            )
            # Say the count against the target every time, so the person
            # walking always knows how much further this goes.
            run.say(
                f"Drop {len(probes)}/{drops} locked. Keep walking away.",
                patience_s=SAY_PATIENCE_S,
            )

        for probe in probes.values():
            distance = _chebyshev(probe.position, here)
            for scope, ids in (("80", near_ids), ("all", wide_ids)):
                line = probe.record(scope, distance, probe.unit_id in ids)
                if line:
                    print(line, flush=True)
                    # Only the unlimited scan's transitions are worth
                    # interrupting the walk for: the radius-80 one is our own
                    # arithmetic and will always fire at exactly 81, which
                    # tells the person walking nothing they did not know.
                    if scope == "all":
                        run.say(
                            f"Drop at {probe.position}: "
                            f"{'BACK in view' if probe.state['all'] else 'OUT OF VIEW'}"
                            f" at {distance} subtiles.",
                            patience_s=SAY_PATIENCE_S,
                        )
                        last_chat = time.monotonic()

        # A periodic heartbeat so the transcript shows the walk happening
        # even across a stretch with no transitions. Only when something
        # actually CHANGED: run 1 ended with forty identical lines from a
        # character standing still, which is noise pretending to be data.
        now = time.monotonic()
        distances = ", ".join(
            f"{p.unit_id}:d={_chebyshev(p.position, here)}"
            f"{'' if p.state['all'] else ' (gone)'}"
            for p in probes.values()
        )
        if probes and now - last_distance_print >= 5.0 and distances != last_line:
            last_distance_print = now
            last_line = distances
            print(f"    at {here}  {distances}", flush=True)

        # A sparse heartbeat in game, so a long quiet stretch does not read
        # as the drill having died. Deliberately rare: every message opens
        # and closes the chat console, which is not free while walking.
        if probes and now - last_chat >= 45.0:
            last_chat = now
            live = sum(1 for p in probes.values() if p.state["all"])
            left = max(0, int(seconds - (now - started)))
            run.say(
                f"{len(probes)}/{drops} drops, {live} still visible, "
                f"{left}s left. Keep walking.",
                patience_s=SAY_PATIENCE_S,
            )

        # -- the end conditions ------------------------------------------
        all_gone = bool(probes) and all(
            now - p.last_seen_time > QUIET_S for p in probes.values()
        )
        if len(probes) >= drops and all_gone:
            ending = f"all {drops} drops made and out of view"
            print(f"\n  {ending} — done.")
            break
        if all_gone and len(probes) >= MIN_DROPS:
            ending = f"all {len(probes)} drops out of view"
            print(f"\n  {ending} — done.")
            break

    print("\n== Result ==\n")
    if not probes:
        print("  Nothing was dropped, so nothing was measured.")
        raise RuntimeError("nothing was dropped, so nothing was measured")
    for probe in probes.values():
        print(probe.summary_row())

    # The verdict. Stated rather than left to the reader: the whole reason
    # the drill scans twice is to make this call, and a table that needed
    # interpreting would just restart the argument it exists to end.
    print()
    lost_client = [p for p in probes.values() if p.unseen_at["all"]]
    outlived = [
        p for p in probes.values()
        if p.unseen_at["80"] and p.seen_at["all"]
        and max(p.seen_at["all"]) > min(p.unseen_at["80"])
    ]
    reached = max(
        (max(p.seen_at["80"] + p.unseen_at["80"]) for p in probes.values()),
        default=0,
    )
    if not lost_client and reached <= PERCEPTION_RADIUS:
        print(
            f"  INCONCLUSIVE: the walk only reached d={reached}, which never "
            f"tested\n  the {PERCEPTION_RADIUS} boundary. Walk further, or "
            "use a more open area."
        )
    elif outlived:
        horizons = [p.horizon for p in lost_client if p.horizon is not None]
        furthest_wide = max(max(p.seen_at["all"]) for p in outlived)
        print(
            f"  VERDICT (A): OUR FILTER is the binding constraint. The client "
            f"still held\n  the item past {PERCEPTION_RADIUS} — it was visible "
            f"at d={furthest_wide} with the radius\n  lifted, while the real "
            "scan had already lost it. Raising PERCEPTION_RADIUS\n  would "
            "genuinely widen what the bot sees."
        )
        if horizons:
            print(f"  The client's own horizon is out at ~{max(horizons)}.")
    elif lost_client:
        horizons = [p.horizon for p in lost_client if p.horizon is not None]
        print(
            f"  VERDICT (B): THE CLIENT is the binding constraint. The item "
            f"vanished from\n  the hash table at ~{max(horizons)} subtiles "
            f"even with the radius lifted, so\n  raising PERCEPTION_RADIUS "
            f"({PERCEPTION_RADIUS}) would buy "
            f"{'nothing' if max(horizons) <= PERCEPTION_RADIUS else 'only the gap'}"
            ".\n  Covering more ground needs the character to MOVE — which is "
            "what the\n  clearance patrol does and what the pickup sweep still "
            "does not."
        )
    else:
        print(
            f"  The item stayed visible the whole way out to d={reached}, at "
            f"BOTH radii.\n  That is past {PERCEPTION_RADIUS} without a loss, "
            "which should be impossible for\n  the filtered scan — worth a "
            "second look at the numbers above."
        )
    print("\nT51 complete. Nothing was sent to the game.")
    horizons = [p.horizon for p in lost_client if p.horizon is not None]
    # Tell the person walking it is over, in the game, before the harness's
    # own CONCLUDED line — they are looking at the screen, not the console,
    # and "when do I stop?" was run 1's actual failure.
    run.say(f"T51 DONE — {ending}. You can stop walking.", patience_s=10.0)
    return (
        f"stopped on {ending}; {len(probes)} drop(s); walk reached d={reached}; "
        + (
            f"client horizon {min(horizons)}-{max(horizons)} subtiles "
            f"over {len(horizons)} measurement(s)"
            if horizons
            else "nothing was ever lost from the hash table"
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="T51 — visibility vs distance")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--drops", type=int, default=DEFAULT_DROPS)
    args = parser.parse_args()
    status = run_drill(
        T51,
        lambda run: t51_body(run, seconds=args.seconds, drops=args.drops),
        run=DrillRun(GameSession()),
    )
    raise SystemExit(0 if status == "PASS" else 1)
