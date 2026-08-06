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
