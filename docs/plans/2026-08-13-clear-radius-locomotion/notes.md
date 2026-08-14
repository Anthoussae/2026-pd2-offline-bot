# Notes — clear_radius locomotion speed pass

## Goal (operator's words, 2026-08-13 evening)

Reduce the long idle periods and time-consuming navigation difficulties
in `clear_radius`. The operator's from-the-chair description of the
bot's Cold Plains movement, all named undesirable:

- moves in **small bursts**
- **walks back and forth** often
- **retraces its steps**
- **dithers about**
- **wanders in random directions**
- **backtracks**
- **stands still for long periods**

The plan may propose more diagnostic tests to pin culprits before
fixes, though the T92 logs already give a good sense.

## Evidence in hand (R255/T92, 2026-08-13)

Same character/build/gear both sides; human covered approximately the
same area as the bot's route (operator's word, stated with confidence —
the T92 coverage caveat is hereby resolved).

| Cold Plains | human | bot (20260813-083614) |
|---|---|---|
| duration | 53 s | 454 s |
| route | 611 st | 1728 st |
| ground speed | 16.5 st/s | 6.0 st/s |
| idle (spans ≥2 s) | 16 s (1) | 178 s (26, max 47 s) |
| combat exposure | 40 s | 388 s |

- ALL bot idle spans sit in `clear_radius` (139 s attributed; upkeep 3 s).
- The 47 s span = two back-to-back ~21 s ticks, each ending
  `nav.failed: no path from (5216,5717) to (5218,5709)` — 8 subtiles.
- Rough decomposition of the 401 s gap: ~170 s stop-start pacing,
  ~160 s idle stalls, ~65 s longer route (now known NOT to be
  coverage-necessary, since the human covered the same area in 611 st —
  so the extra ~1100 st IS largely oscillation/backtracking waste).
- Banked prior evidence: performance-notes.md — navigator limit-cycle
  oscillation (~120 s in the Cellar 5 endgame, clicks nudged around
  ground items), CastInFlight refusals stealing movement ticks,
  progress-aware exit-retry pacing, "the last four confident fixes in
  this area were wrong."

## Discovery log

### The 47 s stall: REPRODUCED OFFLINE, cause pinned (2026-08-13 evening)

The baseline's two back-to-back ~21 s ticks each ended
`nav.failed: no path from (5216,5717) to (5218,5709)`. Replayed on the
saved atlas (seed 1314025823, Hell, Cold Plains, 115 rooms, bounds
(4880,5360)-(7540,6540)) with `scratchpad/astar_probe.py` logic:

    atlas-only astar: NO PATH in 20.153s
    reachable control: path len 25 in 0.003s

Both cells are known AND walkable, 8 subtiles apart — but in different
connected components OF THE ATLAS (the real connection runs through
unrecorded ground, and unknown ground is blocked by design,
navigate.py). `pathing.astar` has NO node budget, so an unreachable
goal floods every recorded cell before answering None. The two-strike
no-route rule (T55 run 1) then asks AGAIN over a fresh grid — doubling
the worst case. 42 s per occurrence, and it will recur whenever a
combat target or ring point stands on a locally-disconnected pocket.

### Where the movement time goes (code reading)

Mechanics, with file anchors:

- **Leg caps**: combat dash hops ≤ 8 st (`necro.py dash_step`), patrol
  legs ≤ 12 st (`services.patrol_step`, via `util._hop`). One
  MoveTo per TICK in clear_radius (engage/approach return one action).
  Between legs the character stands while the next tick decides
  (tick interval 0.2 s + snapshot + step logic; baseline ticks run
  0.3-1.9 s). Bursts of 8-12 st with pauses = the operator's "small
  bursts", and the measured 6.0 st/s effective vs 16.5 human.
- **Strike-retreat-dash cycle** (`necro.py engage`): after EVERY strike,
  retreat `retreat_subtiles` (12) away, then re-select, then dash back
  in 8-st hops; `restrike_s` 1.0 holds. This is the operator's own
  R47.9/R163 doctrine (standing still is what kills this character) —
  and it is ALSO the measured "walks back and forth / retraces steps":
  gross route inflates (retreat 12 + dash 8 back = 20 st walked, net
  -4), and combat exposure is 388 s of the bot's 454 s Cold Plains.
  Context: the human took 79 total damage clearing the same field.
- **Walk budget** (`navigate.py WALK_BUDGET_SECONDS` 2.0): every
  walk_to call is capped at 2 s; callers re-ask next tick. Correct for
  safety; contributes tick-boundary pauses.
- **Drift/reposition** (`_reposition`, `reposition_subtiles` 4): when
  everything nearby is poisoned, the module drifts instead of standing
  (operator-ordered, R163) — reads as "dithering" but is deliberate;
  small legs.
- **Hazard nudging** (`_nudged_click_point`): clicks pushed off ground
  items/interactives — path wiggle, small cost.
- **Engine tick** 0.2 s interval; snapshot 16-63 ms — not a dominant
  cost by itself.

### Sizing the 401 s Cold Plains gap (T92 + the above)

~170 s stop-start pacing (leg duty cycle), ~160 s idle stalls (42 s =
one A* flood pair; the rest 4-9 s spans during combat presence),
~65 s extra route — now known to be waste, not coverage (operator
confirmed equal coverage; and much of the extra 1100 st is
retreat/dash gross-vs-net).

### What already exists to build on

- `nav.capped` events (93 in baseline) — leg telemetry exists, but no
  plan-cost event and no per-leg duty-cycle report.
- `runlog/compare.py` (T92) — the measurement harness for any
  before/after; the human log is the standing benchmark.
- Postures (M6 P3): named presets already swap combat configs per step —
  the natural home for any combat-movement relaxation.
- The stack sampler — attributes any silent stall to a code line.
- performance-notes.md warning, repeated: "the last four confident
  fixes in this area were wrong" — every change here gets measured
  before AND after, no exceptions.

## Questions and answers

**R256, answered 2026-08-13 evening:**

- **Q1 (bound A*): YES.** Node budget; budget-exhausted = no-route →
  the existing write-off path.
- **Q2 (telemetry): YES.** Permanent plan-cost events + a locomotion
  report over existing logs.
- **Q3 (longer quiet-field legs): YES.** Measured before/after.
- **QA (combat movement): OPERATOR RULING, bigger than offered —
  "switch the bot's default combat behavior to Berserk, henceforth.
  We may shelve the skirmish stance entirely; for the foreseeable
  future, please set Berserk as the default posture. I'm fairly
  convinced that it's not just the fastest, but the safest too
  (best defense is a good offense)."** So: berserk (`style="charge"`,
  R241 — no post-strike retreat, no wait-for-revives, no wall gate;
  the reflex ladder owns survival) becomes the DEFAULT posture at
  module construction; the cautious skirmish beat stays defined in
  config but nothing selects it by default. Run steps may still name
  postures per step (they override the default, as today).
- **QB (acceptance): Cold Plains segment < 180 s, zero ticks over
  4 s, idle < 45 s** — measured with `runlog.compare` (+ new
  locomotion report) against both the old bot baseline
  (20260813-083614) and the human benchmark (20260813-192249).

## P1 re-pricing (the before-picture, from the new locomotion report)

`python -m pd2bot.runlog.locomotion <dir>`, 2026-08-13 evening:

**Bot baseline (20260813-083614), Cold Plains 454 s:**
route 1728 st gross / 70 st net · speed 3.8 st/s (gross/duration) ·
duty 61% (moving 276 s / idle 178 s) · 26 idle spans, the top one 47.1 s
at t+132.6 in clear_radius · **ticks over 4 s: 4** — town_preamble
17.1 s, waypoint 5.6 s, and the two ~21 s clear_radius ticks each
showing `nav.failed: no path` inline (the A* floods). Every idle span
that carries a step tag says clear_radius.

**Human benchmark (20260813-192249), Cold Plains 53 s:**
route 611 st gross / 29 st net · speed 11.5 st/s · duty 69%
(moving 37 s / idle 16 s) · one idle span (2.4 s) · no slow ticks.
(The 55.6 s town idle is the pre-run wait while the operator read the
briefing — trimmed by first-movement in all comparisons.)

Reading: the duty cycles are closer than expected (61% vs 69%) — the
dominant difference is the SPEED WHILE MOVING (276 s to cover 1728 st
= 6.3 st/s moving vs the human's 611/37 = 16.5) and the gross route
itself. Supports the leg-cap/burst diagnosis and the berserk ruling
(retreat-dash gross inflation) over a pure "stands around" story; the
idle 178 s is still 4× the human's even excluding the floods. Two slow
ticks OUTSIDE Cold Plains (town_preamble 17.1 s, waypoint 5.6 s) are
noted for the record; out of this plan's scope.

## P2 final constants (measured on the real atlas, 2026-08-13)

`BUDGET_FLOOR = 2_000`, `BUDGET_CAP = 25_000`,
`BUDGET_PER_SUBTILE_SQ = 30`; node rate ~10k expansions/s.

- The replayed 20.15 s flood: **0.057 s** (budget_exhausted, floor).
- Healthy 25-cell path: 0.002 s, 68 nodes expanded (the real-path
  multiple that justifies the floor).
- Worst case at the production cap (far unreachable ask): **1.33 s**
  (the cap was lowered 50k → 25k mid-phase after the first measurement
  showed 4.86 s at 50k — over the QB "no tick > 4 s" bar).
- Budget-exhausted answers are None = the standing no-route semantics;
  the old `SearchLimitExceeded` (raised, never caught, never bound at
  200k) was REMOVED — a latent crash path, demonstrated by a P1 test
  before the fix.

## Future work / out of scope ideas

- Connectivity caching / component labeling over the atlas, if the P2
  node budget ever proves too blunt.
- Pipelined clicks / leg overlap in the walk loop, if P4 shows the
  duty cycle still lagging the human after longer legs.
- The town_preamble 17.1 s tick and waypoint 5.6 s tick (baseline log)
  — outside this plan; candidates for a later town pass.
