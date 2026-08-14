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

## P4 battery record (2026-08-13 evening, runs at logs/runs/)

| run | config | CP | CP idle | ticks>4s (CP) | stuck walks | note |
|---|---|---|---|---|---|---|
| baseline | pre-pass | 454s | 178s | 2 (21s each) | - | 20260813-083614 |
| 1 (211224) | P1-P3 | 473s | 162s | 0 | 88 / 183s | blocked dashes found -> R259 |
| 2 (213311) | +walk-in | 219s | 86s | 0 | 23 / 48s | huge gain; rune picked |
| 3 (213927) | same | 128s* | 30s* | 0 | 37 / 78s | *LEAKED 202s into Blood Moor -> R260 |
| 4 (215438) | +seam gate | 233s | 100s | 0 | 37 / ~78s | far-dash 13s spans |
| 5 (220121) | +dash 16 (tuning 1) | 278s | 81s | 0 | 41 / 85s | knob useless -> REVERTED |

Standing results: A* floods gone every run (192-356 plans, worst
0.69s); zero CP ticks over 4s every run; berserk endurance perfect
(hp min 1009-1249 of 1335 across five full clearances, monitor
silent, reflex 5-15 fires/run); seam gate held in runs 4-5.

Residual family, present in ALL runs and grown with attack volume:
~2s capped walks with near-zero movement across ALL leg types (13
dashes + 28 patrol/closing legs in run 5). Hypothesis with the best
fit: MOVE-CLICKS EATEN BY THE ATTACK SWING - berserk swings nearly
continuously (105-199 attacks/run), a move-click landing mid-swing
no-ops exactly like the known CastInFlight contention
(performance-notes, T70), and nothing guards walks against SWING
animations. Un-fixed cost: 50-85s/run of idle plus route inflation.

Battery continued (post-R261 fix, commit 0c27971):

| run | config | CP | CP idle | ticks>4s (CP) | stuck walks | note |
|---|---|---|---|---|---|---|
| 6 (231456) | +stall bucket/shake | - | - | - | - | TOWN FLAKE: stash panel refused 3x (known pre-existing intermittent, R244 era); CP never ran |
| 6b (231651) | same | 277s | 88s | 0 | 42 / 86s | COMPLETE; max idle span 9.5s; 3 unreachable write-offs (bucketed ladder working); shake-first did NOT cut the stuck total - the 42 blocks are DIFFUSE (scattered one-off targets, families rarely accumulate to the shake threshold) |

Where this leaves the numbers: the config is stable at ~230-280s CP /
~85-100s idle across runs 2, 4, 6b. Every NAMED family is dead (A*
floods, walk-into-pack, seam leak, 13s repeat-click). The residual is
~40 diffuse ~2s blocked walks per run - each a different spot/target,
consistent with click-movement vs unit collision as a mechanic, not a
single bug. Targets (<180s / <45s) not met by roughly 1.5-2x.

Battery continued (R262 tuning, walk-budget revert bd0cde4):

| run | config | CP | CP idle | ticks>4s (CP) | stuck walks | note |
|---|---|---|---|---|---|---|
| 7 (235331) | = 6b config | 215s | 71s | 0 | 24 / 50s | operator-watched; wandering window decomposed (chase-abandon-retrace + blocked ring point) -> R262 |
| 8 (001358) | +R262 all three | FAILED 19s | - | - | - | the 1s walk budget broke town approaches (NPC-nudge exits need end-of-call time); REVERTED same hour |
| 9 (001607) | chase gate + ring2 + 2s budget | **178s PASS** | 62s | **0 PASS** | 30 / 62s | first clean sub-180 run; route 884st (lowest; chase gate working); no whitelisted drops rolled; hp min 1163 |

Run 9 = the current config's first acceptance pass on 2 of 3 targets
(CP <180 PASS, ticks PASS, idle 62 vs 45 MISS). Formal three-pass
acceptance would need runs 10-11 consecutive under this config.

Formal acceptance attempt (config frozen at bd0cde4):

| run | CP | CP idle | ticks>4s (CP) | census | note |
|---|---|---|---|---|---|
| 9 (001607) | 178s PASS | 62s miss | 0 PASS | no drops rolled | |
| 10 (002319) | 149s PASS | 48s miss (by 3) | 0 PASS | 2/2, 0 junk | best run of the night |
| 11 (002708) | - | - | - | - | TOWN STASH FLAKE #2 -> spun off as its own task |
| 11b (002834) | 246s miss | 95s miss | 0 PASS | 2/2, 0 junk | pickup step re-walked 4 ring points (78s) to account for sightings - correctness by design (T3/R186), and the run's clear itself was ~168s |

Formal three-consecutive-pass NOT achieved: CP 149-246s across the
trio, idle 48-95s. Variance sources now characterized: monster
density, drop luck, and the sighting-accounting ring re-walk (which
is correctness, not waste). Zero slow ticks in CP in EVERY run since
P2 - that target is simply solved. hp minimum across all 11 launches:
1009/1335.
