# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

> ## ⛔ HALTED 2026-08-07 — a chicken-starvation DEATH, safety fix owed
>
> The M6 P5 acceptance run (T71, chicken 35) **died in Tower Cellar 4**:
> a blocking `walk_to` spun for **24 seconds** stuck 3 subtiles from the
> exit amid a 26–29 hostile pack, and the `SafetyMonitor` only runs at
> the TOP of each tick — so a blocked engine cannot chicken. The death
> latch worked (halted after death, game untouched); the *chicken* was
> starved. **Full analysis + preserved run log:**
> `docs/reviews/2026-08-07-chicken-starvation-death/`. **Do NOT launch
> any input-sending run until the monitor can no longer be starved.** A
> fix DECISION is owed (poll safety inside `walk_to` / hard-cap its
> block / both / a separate chicken process — the operator's idea). NOT
> caused by the pickup changes (the block was in traverse's walk to the
> exit). See the startup prompt / handoff below.

- **Milestone:** M6 — Countess flagship
- **Phase:** P4 — the countess run and the Cellar 5 endgame (P1, P2, P3
  DONE; plan: `docs/plans/2026-08-03-m6-countess/`). **Active side
  workstream: pickup reliability**, `docs/plans/2026-08-06-pickup-reliability/`
  — approved R224, precedes the M6 P5 acceptance battery. **P1–P5 DONE**
  (offline): instruments, T76/T77 calibration, the item-exception
  registry (scrolls + maps), honest failure diagnosis (a pile miss no
  longer suppresses all loot), draw-order collection. Only **P6**
  remains — a live remeasure vs the 18/31 baseline. The click path is
  accepted as erratic; the frame-perfect command path was ruled out (no
  memory writes / injection, operator 2026-08-06).
- **Next request ID:** R228 (overall counter; R171 was never issued — a
  handoff off-by-one, left as a hole rather than backfilled; check
  `docs/request-index.md` for the highest issued)
- **Next test ID:** T80 (T75 unused; T76/T77 ran during the pickup
  calibration; T78/T79 were on the now-abandoned item-acquisition
  branch; **T71 ran 5× — run 5 DIED 2026-08-07** (chicken-starvation).
  The harness counts every row with the id; check `docs/drill-log.md`)

Updated: 2026-08-06. Branch `m6-countess`, pushed, **PR #2 open**
(`https://github.com/Anthoussae/2026-pd2-offline-bot/pull/2`). 1035
tests, ruff clean. The repo has no CI workflows — local validation is
the gate.

**Direction explored and ABANDONED (2026-08-06):** a frame-perfect
pickup by GID command (kolbot's mechanism) was investigated on branch
`item-acquisition-spike`. It required out-of-process **memory writes** /
a remote call — and the operator declined that class of technique
outright (*"without using dll injections etc."*). The project returned
to this line by rewind. **Do not re-propose command-by-GID, memory-write
actuation, or injection.** The architecture is read-only + `SendInput`,
full stop. What survives: the measured analysis and the finding that the
click pickup path is erratic (a pile's pick rate swings on noise; the
labels-OFF lead did not replicate). See
`docs/archive/plans/2026-08-06-item-acquisition-ABANDONED/`. Pickup work
continues within the SendInput constraint via
`docs/plans/2026-08-06-pickup-reliability/`.

## Where things actually stand

**The bot can cross the template room.** T72 run 2 (2026-08-06): town →
Black Marsh → Forgotten Tower → Tower Cellar 1, 51 s, clean `[CVRL]`,
both transitions. The Forgotten Tower crossing itself was **4.3 s / 16
ticks** — it had been 173 s / 184 ticks and a loud give-up.

**Two things landed this session, and the second explains the first.**

### 1. The run event log (new, `docs/architecture/run-log.md`)

Every run writes `logs/runs/<stamp>-<runname>/events.jsonl` — schema'd,
append-only, **always on**. Read it with:

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog
```

Envelope: monotonic `seq`, ISO wall clock, seconds-since-start, area id
+ name. Every spatial field carries three frames — world, area-local
(`local`), and character-relative (`rel`/`dist`/`bearing`, screen
compass, R219). Event families: `tick` (with a
snapshot/ladder/step/maintain timing split and hostile/ally/critter/item
counts), `step.decision` (every decision, not just noted ones),
`action.*`, `item.*`, `stash.*`, `npc.*`, `waypoint.*`,
`area.transition`, `combat.write_off`, `chicken`, `death`, `refusal`,
`reflex`. Rules: never raises, never blocks, never interprets, honest
absence. ADR: `docs/adr/2026-08-05-run-event-log.md` — **accepted**
(2026-08-06). The plan is **closed and archived**
(`docs/archive/plans/2026-08-05-run-event-log/`, `_DONE.md`); `item.vanished`,
`item.accidental` and enemy-death events were deferred, named there.

### 2. The phantom-hostile fix

T71/T72 attacked two units 23 times each in a room the operator states
never contains hostiles. They were **decorative bats** (kind 159,
MonStats code `B9`). The bot's hostility test was "did it prove it is
friendly?" — and real monsters do not prove that either: all 39
hostiles in Cellar 1 lack the alignment stat exactly as the bats do.

Discriminator, MEASURED (T74): **a combatant carries combat stats.**
Fallen/Goatman/merc carry level, resistances, experience; the bat
carries hp, max-hp and three animation rates and nothing else.
`offsets.COMBAT_RATED_STATS` records the measurement;
`Monster.combat_rated` and `UnitScan.critters` implement it —
non-combatants are reported, never targeted. Backed by a futile-strike
write-off in `necro.py` (`futile_strikes`) for the family nobody has met
yet; both its signatures are transient, nothing is remembered across
runs.

## THE COUNTESS IS DEAD — the flagship works end to end

**T71 run 4, 2026-08-06: PASS.** 930 s, clean `[CVRL]`, 6/6 traverses,
`clear_countess` completed, her corpse read at **(12541, 11088)**, drop
zone published and swept, `pickup` collected the drop (two runes among
it). No chicken, no death, no idle bail, 22 reflex fires. Artifacts:
`logs/runs/20260806-025952-countess` (2259 events) and
`logs/run-20260806-025952.log`.

Pre-launch, the ordered re-check (review 001's lesson) found the same
hole one layer below the drill: a chamber sweep whose points were all
skipped as unreachable still concluded "provably absent". Fixed in
ce3ba82 — skips void the absence proof and stop loudly; the old absence
test was itself the false path and now genuinely walks.

### What the run did NOT settle

- **The staging beat never ran.** `notes["countess"]` was never written
  and no staging narration exists, because `engage` is consulted BEFORE
  the phase dispatch in `ClearCountessStep.step` and owned every tick
  from the neighborhood clearance to her death: 22 of 27 `clear_countess`
  decisions are the bare `acted` with no note that only the engage
  branch produces. With hostiles in perception the step cannot reach
  `_stage_tick`, and the Countess always has a court.

  **CLOSED by the operator, 2026-08-06 — deferred, low priority.** They
  watched the run and reported the bot approached from *"what I would
  call the south, not the north, but it worked out fine"*, and asked for
  the preferred approach direction to be registered as low priority and
  deferred. So R219(b) needs no further judgement: the tactic is not
  load-bearing. If it is ever revived, the question is a design one —
  does staging-before-contact need to pre-empt `engage`, or is it a beat
  that only fires on an empty approach? Do not re-run to observe it; it
  cannot occur as written.
- **`stash.*` and `npc.*` are still unexercised.** Zero of each: the
  inventory held only the three unmovables, so there was nothing to
  deposit. Same gap T72 had.
- **The kill was almost entirely poison.** One `action.attack` in the
  whole endgame (13 in the run). She and her court died to poison, the
  revives and the merc.

### Wanted items were left on the floor (asked 2026-08-06, from the log)

**13 items the pickit wanted were clicked and never came up**, against
18 collected. Every `action.pickup_attempt` is by definition a wanted
item, so that stream — not `item.dropped` — is the honest census. Two
were valuable:

- **Flawless emerald** (kind 691), Tower Cellar Level 1 at
  (12644, 5146) — 8 click attempts, never collected.
- **Nef rune** (kind 702), Tower Cellar Level 5 at (12544, 11084) — 3
  attempts, never collected. A Hel rune two subtiles away (unit 840,
  (12545, 11083)) *was* collected, so this is not a pickit miss.

The other 11 were potions: C1 ×3, C2 ×2, C3 ×2, C4 ×1, C5 ×3. Most
show exactly 8 attempts — `pickup_click_attempts`, i.e. the budget
spent — and **11 of the 13 emitted no `item.abandoned` at all**: only
the two walk-based write-offs ("walks kept arriving short") are logged.
A click-budget write-off is silent, so the log cannot currently answer
"what did we fail to pick up" without correlating attempts against
collections by unit id.

**`item.dropped` also had a blind spot covering four of the five
floors** — it fired only from `note_wanted_sightings`, which
`TraverseStep` does not call, so the floors the bot descended through
recorded no wanted drops at all. **FIXED 2026-08-06** (operator's
request): it is emitted from `_PickupMixin.log_wanted_drops`, called by
`wanted_items` — the one enumerator every collecting step shares — on
the pickit's verdict alone, independent of any radius or full-belt
filter. Every whitelisted drop is now on the record with its timestamp
and location whether or not anything could be done about it. Three
tests pin it; `docs/architecture/run-log.md` records why the placement
is load-bearing.

### The numbers (see `performance-notes.md` for the evidence)

The descent is **~9 minutes against the 5–6 minute target**, and the
staircases are not the cost — they are seconds. Two things dominate:
opportunistic pickup on the traversal floors (143 pickup attempts; the
speed-pass knob is the pickit's rules, not the step), and a **navigator
oscillation around close targets** that burned ~120 s of the 186 s
endgame in four ticks while the character moved ~17 subtiles. That is
almost certainly the "dithers and walks into corners" the user reported
after T70 run 5, now traced and priced.

**Instrument to add before theorising about it:** `send()` swallows
`NavigationError` into `services.log`, so a walk that burned 35 s and
failed emits **no run-log event** — those four ticks are visible only as
durations with nothing inside them. Close that gap first; the method
note in this file was paid for four times already.

## IN FLIGHT: pickup reliability (plan approved R224, 2026-08-06)

`docs/plans/2026-08-06-pickup-reliability/` — 5 phases, `md`.

**P1 DONE** (no game needed): a spent click budget now emits
`item.abandoned` with reason, click count, the aim points actually
spent, and the neighbour count; `send()` swallowing a `NavigationError`
now emits `nav.failed`; `runlog --pickup` prints the census.
`item.collected` also carries `attributed_to` when another item's click
produced it — the "clicked A, got B" case as a standing metric (P4
pulled forward, telemetry only, zero behaviour change). Baseline
captured and reproduced by the tool: **18/31 (58%)**, in
`baseline-t71-run4.txt`.

**P2 WRITTEN, NOT LAUNCHED** — `drills/t76_pickup_calibration.py`, per
the operator's instruction to stop at the live boundary. It stages
solo/pair/pile arrangements across item classes, walks the aim schedule
against each target, and records *which unit* each click produced. Its
verdict logic is unit-tested, including the criterion that it **cannot
PASS on solo rounds alone** (the T72 lesson, in the criteria rather than
a comment). Round 0 is a read-only probe for whether label geometry is
readable — the highest-value five minutes in the plan.

Deliberately NOT done without the game: the behavioural half of P4
(splitting "inventory full" from "the click missed"). It changes what
the bot does, it cannot be validated here, and stacking unvalidated
behaviour changes is the band the stage-B review was called over.

### Why this precedes the M6 P5 acceptance

Recommended 2026-08-06 after reviewing the plans. **Do not go straight
to P5's acceptance stages.** The reasoning, so it can be argued with:

1. **The operator has declared the current state not shippable** —
   *"this level of delay and potential failure is too high for the
   working bot"* — and P5's Stage D is the stage that would certify it.
2. **Stage D would pass while failing.** Its criterion is "Countess
   confirmed dead each run, drops swept". A bot losing 13 of 31 wanted
   items sweeps the drop zone and reports success. That is exactly the
   "a test that can pass without doing the thing it tests" shape this
   repo has now paid for three times (review 001, `ClearRadiusStep`'s
   docstring, T72's criteria).
3. **It is in M6's scope, and the speed problem is not.** The plan's
   goal names *"take extra care over her drops"* and scopes in "careful
   pickup"; it explicitly scopes OUT "speed optimization beyond the
   battery's report". So pickup accuracy is M6 work now; the ~9-minute
   descent is a follow-up with measurements already banked.
4. **Live time is the scarce resource.** Each full run costs ~15 min
   plus the operator's presence. Three acceptance runs spent on a known
   ~42% pickup failure buys an acceptance record worth re-doing.

Order within the phase — measure before changing anything:

1. **Close the two remaining instrument gaps** (small, and the method
   note demands it): a click-budget write-off emits no `item.abandoned`
   (11 of the 13 misses were silent), and `send()` swallows
   `NavigationError` so a walk that burned 35 s and failed emits nothing
   at all. `item.dropped`'s traversal blind spot is already fixed.
2. **A pickup-accuracy drill on a CELLAR floor with mixed item classes**
   — T64/T67 measured this on town ground with potions and gems; the
   failures are on cellar floors, and T65 run 4 already found an item
   class (kind 619) with 245 probes and zero hits.
3. **Then fix** — treating the navigator oscillation as possibly the
   same problem, since a click issued from the wrong stand-off position
   fails no matter how good the aim schedule is. Candidate levers are
   listed in the plan notes; the note there warns against starting with
   the pickit rules, which hide the accuracy problem while buying back
   descent time.

Full evidence: `docs/plans/2026-08-03-m6-countess/notes.md` →
"NAMED TUNING ITEM: pickup accuracy and the pickup logic as a whole".
**This wants its own `yona-plan` pass** — it is a workstream, not a
tweak, and the repo's workflow says plan first for non-trivial work.

## After that

- **P5 battery** — with pickup attempted-vs-collected recorded in every
  stage report, so the fix has a before-number (18/31) to beat. The
  warm-descent timing is already MEASURED (the table in
  `performance-notes.md`), so the battery's first act is spent; what
  remains is repeat runs for variance, since one run's monster density
  moves clearance times by tens of seconds.
- **P6 closeout**, then **M7** (manual, architecture docs, cleanup
  sweep) — the roadmap's last row.
- **Speed pass** — deferred by M6's own scope boundary, evidence banked
  in `performance-notes.md`. Ranked by measured cost: the
  pickup-on-descent rules, the navigator oscillation (~120 s in the
  chamber alone), then ~3 of the Tower's 4.3 s in the staircase retry
  window held while standing on the stairs. Every one carries a warning
  not to "fix" it without a measurement — the eager version of that
  retry was T70's original bug, and four confident hypotheses about the
  Tower were wrong before the log answered it.
- **Housekeeping, small**: the run-event-log plan
  (`docs/plans/2026-08-05-run-event-log/`) is still `status: active` and
  needs its closeout/archive; its ADR is still **proposed**, and its own
  acceptance condition ("once the log answers a question the old
  instrumentation could not") is now met several times over — T72 run 2
  and T71 run 4 both turned on it. Worth offering as a decision.
- **The staging question** — a design decision, not a bug; closed as
  low priority by the operator.
- **Deferred, deliberately**: enemy-death events (R220 Q6),
  `item.accidental`, the collision recorder writing rooms under the
  wrong area id during an area flip (seen in `area-020.json` and
  `area-025.json`), and — **new, operator's call 2026-08-06, LOW
  priority** — the Countess's preferred approach direction (they watched
  the run approach from the south and judged it fine).

## Hard-won facts (do not re-derive)

- The atlas and A* are correct. Area 20 is a 19x19 walkable box; arrival
  and staircase both known and walkable; A* returns one leg. Proven
  twice — `navigation-diagnosis.md` and its T71 addendum.
- Monsters re-roll **per game**; the map is fixed per
  character+difficulty. "That room is empty" is not a property any run
  can rely on — but the Forgotten Tower genuinely never has hostiles,
  and the bats are what earlier runs were fighting.
- Hell "immunity" is 100% resistance, **not** invulnerability: mixed
  damage, poison-resistance pierce, and the merc's Pus Spitter casting
  Lower Resist all break it. Nothing is durably unkillable.
- Countess identity: kind 734, unique_no 6 (T68 + R216, in `offsets.py`).
- `maps/exits.json` holds 11 staircases — the whole route both
  directions, so warm descents never search.
- Room2 preset/warp data only exists for rooms the client has loaded
  around the player, so exit scans are position-dependent (T70).
- Tomes 533/534 are UNMOVABLE like the Cube (the twice-hit misclick —
  `docs/reviews/2026-08-05-tome-misclick-feedback.md`).
- HALLS_OF_PAIN=123 read live; ARCANE_SANCTUARY=74 is still an
  expectation.

## Live protocol

Bridge auto-starts at logon; if closed, `Start-ScheduledTask -TaskName
pd2bot-bridge` and probe. Drills announce in GAME chat — launch only
when the operator says they are tabbed in. Launch via queue files with a
`.timeout` sidecar; wait with a background until-loop. Abort paths:
`abort` in chat, ESC/Enter in the field, `tools/drill-cancel.ps1`, or
the mouse. **The cancel file is sticky — clear it after use.**
Partyline is ON.
