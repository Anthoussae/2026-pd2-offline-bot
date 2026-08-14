# M6 Countess — planning notes

Discovery log for the M6 plan. Inputs:
`docs/archive/plans/2026-07-29-m5-trial-run/_DONE.md` (follow-ups
section), the user's 2026-08-03 notes (verbatim below), and code
inspection this session.

## The goal, in the user's own structure (2026-08-03)

Countess runs, target **5–6 minutes** (user does ~4 by hand;
"ambitious, but I think it's possible"). Core elements beyond standard
actions (bone armor, revives, fight/pickup loops):

1. Town chores
2. Waypoint to Black Marsh
3. Navigate to the Forgotten Tower, enter the doorway
4. Navigate to the Tower Cellar doorway, enter
5. Cellar 1 → 2 → … → 5, entering each doorway, killing monsters that
   obstruct the way
6. Navigate Cellar 5, fighting, until the Countess is killed
7. **Take extra care to pick up the Countess' items**

Risks the user foresees: navigation quality over the atlas (may need
development); cellar darkness / line-of-sight churn (loop risk as
things enter/leave sight); enemies blocking doorways; genuinely
dangerous hallways — the Countess and minions must be approached
slowly, revives tanking, **best from the north**; unknown unknowns.

A **test battery** for these runs is an explicit deliverable, requested
alongside the plan.

## Behavior defaults the user requested (2026-08-03)

- **Right-skill parking**: after any right-skill cast (Revive
  especially), toggle back to the bone-armor hotkey — with Revive
  active, ground corpses are selectable and may interfere with pathing
  and item pickup. A couple seconds' grace when several casts queue.
- **Revive priority bump**: 3 revives up matters (safety + speed); the
  bot dilly-dallies over it. Not an emergency — a priority adjustment.
- **Combat postures** (preliminary classification done in
  behavior.md §"Combat posture"): current = cautious; aggressive and
  brisk to be developed later, ideally runtime-switchable. M6's
  descent ("kill what obstructs, move on") is brisk-*shaped* — see Q5.

## Current state (code inspection, 2026-08-03)

**Already banked:**

- **The atlas has the whole route** (T52 run 2): `maps/4e52715f-d2/`
  holds area-001 (town), 002, 003, **006 (Black Marsh — route
  corridor only, by design)**, **020 (Forgotten Tower), 021–025
  (Cellars 1–5)**; Cellar 5 surveyed to zero frontier.
- The full M5 stack: engine/ladder/combat/pickit, patrol clearance,
  route service, sprite-aimed pickup with the label policy, town
  preamble, waypoint travel (panel-edge + area-id proof), the drill
  kit, the narrative log, the bridge.

**Missing, confirmed by inspection:**

- **Waypoint row for Black Marsh**: `WaypointConfig.destination_points`
  has only Cold Plains + Rogue Encampment; rows are calibrated
  UIPoints (`uipoints.py`, T25 battery provenance). Black Marsh (Act 1
  row 5) needs a calibrated row fraction.
- **Cross-area walking does not exist.** No machinery walks from Black
  Marsh into the Tower or between cellar levels.
- **Level exits are not perceived.** `offsets.py` has Room2 basics
  (ROOM2_LEVEL etc.) but no `pRoomTiles`/RoomTile chain — the
  structure BH/kolbot use to find warp tiles ("exits") and their
  destination level. New offsets + a reader needed (BH D2Structs.h
  Room2 0x4C pRoomTiles; RoomTile → pRoom2 → Level → dwLevelNo).
- **Doors**: `COLL_CLOSED_DOOR (0x0800)` is in the walkability BLOCK
  mask — closed doors read as walls, deliberately, since M3. Door
  *objects* are readable (`GameObject`, kinds uncatalogued) and
  animate on open (`mode`). `INTERACTIVE_OBJECT_KINDS` = {waypoint A1,
  stash} only. No door-opening behavior anywhere.
- **Area constants**: only Rogue Encampment (1) and Cold Plains (3)
  are named. Route needs: Black Marsh 6, Forgotten Tower 20, Tower
  Cellar 1–5 = 21–25 (match the atlas file names — verify live).
- **Countess identification**: no super-unique/boss perception. Her
  chamber is in Cellar 5; options in Q7.

**Carried-over P3 review issues** (fold in): potions-live-validation
002 (sightings memo keeps no-longer-wanted items pending) and 003
(seam filter silently skipped when the first patrol tick has no area);
session review's tracked P3s: frontier stride vs narrow doorways
(directly relevant to cellars), survey cache key.

## Design sketch (pre-questions)

- **Traversal step** (`traverse`, new): given a destination area id,
  ask perception for the current area's exit toward it (RoomTile
  warp), route to it via the atlas, walk in capped hops (ladder
  consulted between), fight only what obstructs a corridor around the
  route (survey_engage_radius precedent, ~befits "brisk-shaped"),
  handle doors en route, enter, verify by area id (the waypoint.py
  trust pattern), record arrival on the blackboard. One step, used
  seven times in the run file.
- **Doors**: navigator-level — when the planned route crosses a
  closed-door collision cell (or a door object sits within reach of
  the next leg), click the door object, verify open by object mode
  change or collision re-read, re-plan. Doors are the *navigator's*
  problem, not a run step: they appear en route, anywhere.
- **The run file** (`runs/countess.toml`): town_preamble → waypoint 6
  → traverse 20 → traverse 21 → … → traverse 25 → clear/kill in 25 →
  pickup (careful mode) → done.
- **Countess endgame**: approach her chamber from the north (the
  user's tactic — encode as route preference), revives-first
  protocol already exists (`approach_with_revives`), kill until no
  live hostiles in the chamber region, then a thorough pickup pass
  with a generous radius and the label policy on.
- **Right-skill parking**: executor-level — after `CastAtPoint`/
  `CastSelf` resolves, if no further cast is pending within a grace
  window (~2 s), press the bone-armor hotkey (verified switch, no
  cast). Kills the corpse-selectable hazard globally.
- **Revive priority**: upkeep currently yields to armor pacing and
  fires per-tick alternating with offense; the bump = let the
  desecrate→revive loop claim consecutive ticks when below
  `revive_target` and hostiles are present (or raise its standing in
  the upkeep rung's internal order). Numbers via config.
- **Test battery**: a T-drill per new mechanism, then staged
  acceptance mirroring M5's ladder (supervised segment runs → full
  supervised run → threshold review → unattended acceptance), with a
  per-segment time budget summing to the 5–6 min target.

## Questions

### Confirmation-style (batched)

| # | Question | Context | Suggested answer |
|---|---|---|---|
| Q1 | Verify area ids live before coding them in (6/20/21–25)? | Atlas file names imply them; one bridge dump while standing in each is free during the first traversal drill | Yes — drill reads them en route |
| Q2 | Black Marsh waypoint row: calibrate via a T25-style hover battery (user hovers, ~2 min)? | The two known rows don't establish list spacing safely; calibration is the proven pattern | Yes, one short calibration drill |
| Q3 | Doors handled by the navigator (click-verify-replan), not a run step? | Doors appear anywhere en route; the navigator already owns obstacle escalation | Yes |
| Q4 | Traversal fights only a corridor around the route (not full clearance)? | The user's "kill monsters that obstruct the way"; survey_engage_radius precedent | Yes, radius configurable |
| Q5 | Build traversal combat as the first real "brisk" posture preset (named in config), rather than a one-off radius? | Note 2 wants postures eventually; the descent IS brisk-shaped — doing it as a named preset seeds the framework without building the full switchboard | Yes — minimal preset mechanism, cautious stays the default elsewhere |
| Q6 | Right-skill parking implemented in the executor with a ~2 s grace? | Uniform, covers every cast site; grace avoids thrash during revive bursts | Yes |
| Q7 | Countess kill condition = no live hostiles within the chamber region (no boss-identification perception this milestone)? | Simplest honest test; super-unique flags exist in memory but are new perception work; her drops get picked either way | Yes — defer boss-ID unless the battery proves it necessary |
| Q8 | Chicken stays 35 for supervised stages, raised (say 50) only for the first cellar drills? | M5's staged-threshold pattern, in reverse: cellars are more dangerous than Cold Plains | Yes |
| Q9 | Fold the four carried-over P3 review issues into M6's cleanup phase? | Two are pickup/patrol correctness; frontier-stride is cellar-relevant | Yes |

### Discussion-style

- **Q10 (exit discovery)**: read level exits from memory (Room2 →
  pRoomTiles → RoomTile → destination level — the BH/kolbot-standard
  structure, new offsets to derive and live-verify) — versus a
  data-driven alternative (record transition positions during a
  survey walk). Memory-read is suggested: it works in any area
  without a survey pass, it is the same lineage as everything else,
  and T52 did not record transitions. **Suggested: memory-read; the
  atlas remains the routing authority.** (ADR candidate: extends the
  hybrid map-knowledge decision.)

## Answers (R212, 2026-08-03)

- **Q1 yes** — verify area ids live during the first traversal drill.
- **Q2 yes, expanded**: calibrate Black Marsh AND, while at it, the
  Act II **Arcane Sanctuary** and Act V **Halls of Pain** rows — which
  requires calibrating the **act tabs** of the waypoint panel too.
- **Q3 NO — doors deferred.** Not needed for MVP: the Countess route
  has no doors that must be opened; each cellar connection is a
  **staircase — a single click moves the character into the new
  zone**. Recorded as future work: bundle doors with chests/boxes/
  barrels and teleporter gates as "interactive objects", dealt with
  together later.
- **Q4 yes, with the Cellar 5 exception**: the run's objective is the
  Countess and her minions; other kills only for safety or passage —
  EXCEPT on Cellar 5, where it is advisable to kill all nearby
  enemies first so the Countess encounter has no gaggle attacking.
- **Q5 yes, and sharpened into a posture schedule**: **brisk** from
  Black Marsh through Cellar 4, then **aggressive** on Cellar 5.
  Aggressive is still cautious in one sense — it backs off from
  groups that close on the character — but attacks whenever safely
  feasible, especially isolated enemies. (So M6 builds BOTH new
  postures, not just brisk.)
- **Q6 yes** — executor-level right-skill parking, ~2 s grace.
- **Q7 yes, plus two refinements**: (a) a quick (<15 s) sweep into and
  back out of the Countess chamber to ensure she is not standing in a
  blind corner; (b) **investigate reading her directly** — the user
  asks whether the bot can read with certainty which monsters are
  nearby and their names/characteristics. Likely yes (MonsterData
  carries super-unique/boss identification in the BH structs) — P1
  investigates; if it lands, "Countess dead" is read, not inferred,
  and the sweep becomes the fallback.
- **Q8 yes** — raised chicken for early cellar drills only; **note:
  return to 35 for proper runs** (recorded in the battery phase).
- **Q9 yes** — the four carried P3 review issues fold into cleanup.
- **Q10 memory-read confirmed.** If the RoomTile read proves
  insufficient, the user designed a fallback calibration survey:
  user controls manually; at each level exit they type "Exit" in chat
  and hover the mouse over the exit; the bot records/calibrates that
  exit; repeat from Black Marsh to Cellar 5. (The chat-command +
  hover-capture drill machinery from T20/T25 covers this shape.)

**R211**: closeout commit approved; user also invited `/yona-review`
and/or `/yona-push` at the agent's judgment — push done via the
yona-push shape (commit → push → PR #1 updated → checks watched); a
full review artifact skipped for a docs-only closeout (one code
comment changed), reasoning recorded in the R211 outcome.

## NAMED TUNING ITEM: pickup accuracy and the pickup logic as a whole

**Operator's call, 2026-08-06, after T71 run 4** (the first complete
Countess run): *"we need to refine item pickup accuracy considerably
more, and the whole pickup logic more. This level of delay and
potential failure is too high for the working bot."*

This is the P5 battery's "open tuning items named for the closeout's
follow-ups" clause firing, and it is the largest one M6 has produced.
It is a **workstream, not a tweak** — big enough to want its own
planning pass rather than an improvisation inside P5.

### The evidence, measured (not estimated)

From `logs/runs/20260806-025952-countess`, correlating
`action.pickup_attempt` against `item.collected` by unit id:

- **31 wanted items attempted, 18 collected, 13 never came up** — a
  ~42% failure rate on items the pickit had already decided it wanted.
- Two were valuable, not just potions: a **flawless emerald** (kind
  691) on Cellar 1 at (12644, 5146) after 8 attempts, and a **Nef
  rune** (kind 702) in the Countess's chamber at (12544, 11084) after
  3 — while a Hel rune two subtiles away *was* collected. The pickit
  was right; the click was not.
- Most failures show exactly 8 attempts: `pickup_click_attempts`, the
  full budget, spent and lost.
- **Cost**: `pickup` took 192 s of a 930 s run, and pickup on the
  traversal floors is the single largest component of a descent that
  ran ~9 min against a 5–6 min target. 143 pickup attempts for 18
  items.

### What is already known about the causes (do not re-derive)

- **Sprite aim is measured, not guessed** (T63/T65): labels-off aim is
  (0, -28), labels-on (-16, -40), and `pickup_click_attempts = 8` is
  deliberately the length of the aim schedule so a write-off means
  every measured aim point was tried. So the 8-attempt failures are
  *the schedule exhausting*, which means either the schedule is
  incomplete for these item classes or the character is standing
  somewhere the schedule cannot reach from.
- **T65 run 4 already found a total-miss case**: 245 probes on kind
  619, zero hits. Item classes differ and the hitbox map is partial.
- **The navigator oscillation** (performance-notes.md, same run) puts
  the character in the wrong place to click from: it walks past a goal
  ~5 subtiles either side and gives up after "5 plan cycles without
  progress". Pickup accuracy and walk accuracy are probably **one
  problem**, and fixing the clicking alone may not move the number.
- Ground items also perturb the clicks themselves — the click audit
  shows travel clicks being nudged around items ("GOAL-EXEMPT", "near
  miss"), which is the avoid-radius machinery interacting with pickup.
- **The hold-to-move discovery below (R215) is likely load-bearing
  here**, not just a misclick fix: if travel clicks cannot scoop
  items, the interaction between walking and picking up largely
  dissolves.

### Instrument gaps to close FIRST (the method note, again)

Both found by questions the log could not answer on 2026-08-06:

1. **A click-budget write-off is silent.** 11 of the 13 misses emitted
   no `item.abandoned`; only walk-based give-ups are logged. Until
   that exists, "what did we fail to pick up, and why" needs unit-id
   correlation by hand.
2. **A failed walk emits nothing at all.** `send()` swallows
   `NavigationError` into `services.log`, so the four 25–35 s ticks in
   the endgame are visible only as durations with nothing inside them.

(`item.dropped` no longer having a traversal-floor blind spot is
**FIXED**, 2026-08-06 — see `docs/architecture/run-log.md`.)

### Shape of the work when it is scheduled

Measure before changing anything. A pickup-accuracy drill already
exists in spirit (T64/T67, "sparse melange"); the new one wants mixed
item CLASSES on a cellar floor, not town ground, with the run-event log
on. Then decide between: extending the aim schedule per item class,
fixing the stand-off position the click is issued from, hold-to-move
for travel legs, and tightening the pickit's rules so the descent
stops fetching potions it does not need. **Do not start with the
pickit rules** — that hides the accuracy problem rather than fixing it,
though it is the cheapest way to buy back descent time.

## Future work / out of scope notes

- **Hold-to-move (user discovery, 2026-08-04, R215)**: holding the left
  button down makes the character move to the destination WITHOUT
  picking up any items — movement that does not interact with the game
  world. If the bot can replicate it (button-down, hold, release as a
  distinct input primitive), travel clicks stop being able to scoop
  items at all, retiring a whole misclick class the avoid-radius work
  only shrank. Plan shape: (1) a cheap read-only-risk T-drill at a
  convenient live juncture — hold LMB toward a destination across
  deliberately dropped junk; PASS = arrival with zero pickups; (2) if
  proven, an input primitive (`GatedInput.hold_move`?) whose new
  territory is the GUARD: a held button spans ticks, so the contract
  needs "release immediately when the guard goes false" — the first
  input that outlives its own permission check; (3) adopt in the
  navigator's travel legs (and possibly collect approaches) if the
  drill's behavior holds under monsters/objects en route. Natural
  junctures: alongside the P5 battery, or a spare moment in a P2/P5
  live session. Not scheduled into a phase yet — noted for the next
  planning pass that touches input or navigation.

- Aggressive posture (full framework + runtime switching UI) — beyond
  the minimal preset of Q5.
- Boss-identification perception (super-unique flags, monster names)
  — only if Q7's simple condition proves insufficient.
- Vendor UI, corpse retrieval, TP tome — remain deferred (M5 _DONE).
- Key-bindings introspection (R183 follow-up) — nice-to-have for the
  hotkey re-verification drill.
