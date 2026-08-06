# M6 performance notes — where the seconds go

Timing evidence collected as the drills run, kept for the later
optimization pass (the 5–6 minute Countess target, R212). **Nothing
here is a bug**: every delay below is a safety or verification
mechanism doing its job. The question this file exists to answer is
which of them are buying something we still need.

Raw evidence: `t70-stage-one-log.txt` (the full engine trace).

## T70 stage one — town → Black Marsh → Forgotten Tower (2026-08-05)

**35 s total**, clean `[CVRL]`, one transition. User's own words:
*"looked good to me — a little slow (there was a pause before entering
the tower, and another pause before clicking on the stairs)."*

| segment | time | what it was |
|---|---|---|
| town preamble | 3 s | heal skipped (100%), no repair, 1 item stashed, 3 unmovable skipped, merc alive |
| waypoint | 7 s | walk to the town waypoint, panel edge, act tab, row click, load, step-off |
| traverse | 16 s | 4 ticks refused on `CastInFlight`, walk to the exit, 3 staircase clicks |
| done | 0 s | — |

### Pause 1 — "before entering the tower"

Right after the waypoint step, four consecutive ticks logged:

    step traverse: send did not land — CastInFlight: a cast is still
    resolving; MoveTo would land inside the animation and spend it

Interleaved with `reflex upkeep: combat-module upkeep`. So: on arrival
in Black Marsh the ladder correctly starts building the revive wall
(desecrate → revive) and recasting bone armor, and the traverse step's
walk keeps arriving inside those cast animations (T48: 610–640 ms
each) and being refused. The step re-decides each tick and eventually
gets through.

**Cost:** a few seconds per area entry, and it will repeat at **every**
one of the descent's seven transitions.

**Hypotheses to test later, cheapest first:**
1. The wall is being built at a moment it is not needed — we have just
   arrived, nothing is engaged yet. The quiet-field gate (R185 A) only
   suppresses upkeep with no hostile in perception; Black Marsh's
   arrival probably has one somewhere in range. A *travelling* posture
   might defer wall-building until contact, since brisk's whole premise
   is that we are passing through.
2. Movement and casting genuinely contend for the same tick. Nothing is
   wrong with losing a tick to a cast — but four in a row suggests the
   step retries at tick rate into a known-busy window instead of
   waiting out the animation it can already see.

### Pause 2 — "before clicking on the stairs"

    step traverse: clicked the staircase (attempt 1)
    step traverse: clicked the staircase (attempt 2)
    step traverse: clicked the staircase (attempt 3)

Three clicks, paced by `exit_retry_s = 5.0`, so **≈10 s of the 16 s
traverse was this pacing alone** — the single largest cost in the run.

**Near-certain cause:** the first click is not a transition, it is a
*walk order*. The step clicks from up to `click_range` (18 subtiles)
away; the client walks the character there and only then takes the
stairs. The 5 s retry fires while that walk is still in progress and
re-issues the identical order, which is harmless but achieves nothing.

**The fix when we optimize:** make the retry **progress-aware** rather
than time-based — the same distinction the patrol already draws
(`patrol_progress_margin`, R189 b). A re-click is only warranted when
the character has *stopped getting closer* to the exit; while it is
still closing, the click did exactly what it should have. Failing that,
simply clicking from closer in (a smaller `click_range`) converts most
of the walk into normal capped legs, which the ladder gets to interrupt
— strictly better than a blocking approach anyway.

**Expected saving:** most of ~10 s per transition. Over the descent's
seven transitions that is on the order of **a minute**, against a 5–6
minute budget — the biggest single win identified so far.

## Standing measurements to compare against

- Cold Plains patrol steady state: ~220 s ± 20 (T55, M5).
- Cast animation: 610–640 ms; keypresses unaffected (T48).
- Client loaded-room horizon: 46–67 subtiles (T51).

## Method note

Per-step durations come from the narrative log (R179), which the engine
writes for every run. When the optimization pass starts, the first move
is to re-read a fresh descent trace rather than trusting these
numbers — they are one run each, and monster density alone moves
clearance times by tens of seconds.

## T70 descent rerun — the seek run (2026-08-05)

**796 s total, PASS, clean.** First-visit costs dominated: the four
cellar seeks (198 + 221 + 57 + 220 s) were the once-per-seed discovery
walks, now banked in `maps/exits.json` (11 staircases, both
directions). The numbers that carry forward:

| segment | first visit | expected warm |
|---|---|---|
| preamble + waypoint | 19 s | ~19 s |
| → Tower | 16 s | ~10-15 s |
| → Cellar 1 | 58 s | walk + fight only |
| → C2/C3/C4/C5 | 198/221/57/220 s (seeking) | walk + fight only |

The warm descent — staircase-to-staircase over remembered exits, brisk
posture brushing past non-blockers — is the real baseline for the
5–6 min Countess budget and should be measured on the next run before
any optimization work. Watch also: `reflex upkeep fired 25x` mid-seek
(wall maintenance churn while walking through hostile rooms — the P3
urgency hold working, but worth pricing).

## User observations from the descent run (2026-08-05, from the chair)

1. **A dropped Thul rune on Cellar 4's floor was ignored.** Almost
   certainly not a pickit or perception failure: the `traverse` step
   has no pickup logic at all — collection belongs to `clear_radius`
   and `pickup`, and the descent run file contains neither. A wanted
   rune on a traversal floor is invisible to *behavior* even while
   perception lists it. For the Countess run this matters: runes are
   the point. Options when picked up (P4 or the optimization pass):
   give traverse the clearance's opportunistic-collect (bounded by
   `pickup_radius`, only when no hostile owns the tick), or declare
   traversal floors no-pickup by design and accept the cost. The first
   matches the user's expectations; investigate before choosing.

   **RESOLVED (P4, 2026-08-05): opportunistic-collect.** The
   investigation found `TraverseStep` already carries `_PickupMixin`
   (for panels and sends), so the collect is the shared machinery —
   same budgets, same write-offs, same shared memory as the clearance
   and the sweep, not a third implementation that could drift. Gated
   exactly as sketched: only on ticks combat declined (with brisk that
   IS "no hostile owns the tick"), bounded by `pickup_radius`, the walk
   held only while a click resolves (`pickup_retry_s`, ≤1.5 s). Cost on
   a clean corridor: zero ticks. Covered by the P4 sim (the restaged
   Thul comes up mid-traverse and the run still arrives) and a unit
   test. Speed-pass note: each collected item costs its clicks plus
   the walk to it — if warm-descent timing ever tightens, the knob is
   the pickit's rules, not the step.
2. **The bot still dithers and walks into corners** at times. To
   troubleshoot when speed work begins — suspects, in order: seek legs
   aiming at room centres that sit near walls (nearest_walkable
   correction produces corner targets), combat drift's lateral steps in
   tight cellar corridors, and CastInFlight contention stealing
   movement ticks. First move: capture a warm-descent trace and read
   the MoveTo targets against the atlas.

## Staircase click pacing — measured, for the speed pass (T72 run 2)

**Evidence, 2026-08-06.** With the critter filter in, the Forgotten
Tower crossing is 16 ticks / 4.3 s (it was 184 ticks / 173 s). The whole
sequence, from the run log:

    t+35.3  arrived in Forgotten Tower at (10006, 8002)
    t+35.7  clicked the staircase (attempt 1)      <- from 5 away
    t+36.0  waiting out the last click (5 away)
    t+36.2  waiting out the last click (1 away)    <- the walk closed
            ... 12 more ticks, all "1 away" ...
    t+39.6  clicked the staircase (attempt 2)      <- transitioned

**Roughly 3 of those 4.3 seconds are `waiting out the last click` at a
distance of ONE subtile.** The character is standing on the stairs and
the step is waiting out `exit_retry_s` (3.0 s) before re-clicking.

Why it happens: the progress-aware pacing (R189 b shape) restarts its
clock on every subtile of progress, then holds the full retry window
once progress stops. That is correct as written — it exists because a
time-based retry re-issued walk orders mid-walk and cost ~10 s per
transition (T70) — but it has no notion of "the walk has ARRIVED and the
click simply did not take".

**Candidate for the speed pass** (do NOT act on this without a
measurement; the last four confident fixes in this area were wrong):
when the character is inside `melee_range`-ish of the exit and has
stopped closing, the walk is over and the retry window is buying
nothing. A shorter window in that specific state — or re-clicking
immediately once distance stops falling AND is small — would return
~2-3 s per transition. Over the Countess route's seven transitions that
is on the order of 15-20 s against a 5-6 minute budget.

Cross-check before touching it: T70's original defect was re-clicking
too EAGERLY. Any change here must keep the case it fixed (a click whose
walk is still closing must not be re-issued) and must be measured on a
warm descent, not reasoned about.

## The first warm descent, and the endgame's real cost (T71 run 4)

**Evidence, 2026-08-06.** The first complete Countess run: 930 s, PASS,
`[CVRL]`. This is the warm-descent measurement the section above asked
for — every staircase came from `maps/exits.json` ("remembered"), so
nothing searched.

| segment | time | note |
|---|---|---|
| preamble + waypoint | 24 s | nothing to deposit, nothing to repair |
| → Forgotten Tower | 14 s | |
| → Cellar 1 | 4 s | the fixed crossing, holding |
| → Cellar 2 | 179 s | |
| → Cellar 3 | 145 s | |
| → Cellar 4 | 96 s | |
| → Cellar 5 | 81 s | |
| `clear_countess` | 186 s | |
| `pickup` | 192 s | |

**The descent alone is ~9 minutes against a 5–6 minute budget**, and
the staircases are not where it goes — they are seconds. Two things
dominate, and both are now measured rather than suspected.

### 1. Opportunistic pickup is the descent's biggest cost

The traversal floors were carpeted with potions and the bot took nearly
all of them: 143 `action.pickup_attempt` events, 18 `item.collected`.
Cellar 1's 179 s and Cellar 2's 145 s are mostly this. It is the
feature working exactly as designed (P4 resolved the ignored-Thul
observation in its favour) — but the speed-pass note written then is
now priced: *the knob is the pickit's rules, not the step*. Healing
potions were being fetched with the belt already stocked and the
character at full health.

### 2. The navigator oscillates around close targets — ~120 s in the chamber

Four ticks in the Cellar 5 endgame took **34.9 s, 33.0 s, 24.9 s and
27.7 s** — 120 s of the 186 s endgame, during which the character moved
about 17 subtiles in total. The click audit says what happened, and it
is a limit cycle, not a stall:

    click (12578, 11083) ... goal (12571, 11082)
    click (12567, 11084) ... goal (12571, 11082)
    click (12578, 11083) ... goal (12571, 11082)
    click (12567, 11084) ... goal (12571, 11082)

The character walks past the goal to one side, then past it to the
other, ~5 subtiles either way, never landing inside reach — until the
navigator gives up with *"gave up after 5 plan cycles without
progress"*. Seven of those give-ups happened across the run, three of
them in the endgame.

This is almost certainly the **"dithers and walks into corners"** the
user reported from the chair after T70 run 5, now with a trace and a
price. Note the ground-item interaction visible in the same audit
lines: the clicks are being placed and nudged around nearby ground
items, and the chamber floor was covered in them.

**Do not "fix" this from the audit alone.** What is measured is the
oscillation and its cost; what is NOT measured is why the walk
overshoots — click projection, the nudge, the plan's waypoint spacing
and the arrival test are all live suspects, and the last four confident
fixes in this area were wrong. The instrument to add first is on the
give-up path: `send()` swallows `NavigationError` into `services.log`,
so a walk that burned 35 s and failed produces **no run-log event at
all** — the four expensive ticks are visible only as tick durations
with nothing inside them. That gap should be closed before the cause
is theorised about.
