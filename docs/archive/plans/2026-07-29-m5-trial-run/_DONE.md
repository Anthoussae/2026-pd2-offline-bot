---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-03
commit: 0aaf62f (last live-work commit; the closeout docs commit follows
  it — see the branch)
adrs:
  - ../../adr/2026-07-29-behavior-architecture.md (accepted at closeout)
  - ../../adr/2026-08-01-bounded-declared-waits.md
---

# Implementation log — M5 trial run (Cold Plains clearance)

## Outcome

**Done, live-accepted through the full staged ladder.** The bot plays:
town preamble (heal, repair, deposit, belt refill, merc check) →
waypoint to Cold Plains → radius-150 patrol clearance with the necro
skirmish pattern and the R49 reflex ladder → pickit-driven pickup with
sprite-aimed clicks → leave, next game. Staged acceptance A–E passed in
order; **Stage E: 3/3 clean unattended games** (`[CVRL] [CVRL] [CVRL]`,
426/355/364 ticks, monitor silent — no chicken, no idle bail, no death,
zero human input, chicken armed at the config's 35). Report:
`stage-e-acceptance-report.txt` in this dir. **864 tests, ruff clean.**

The milestone also delivered the drill kit (T-numbered live tests with
chat-gated starts and honest verdicts), the narrative log, the
Partyline channel, the automated survey walk, and the elevated-bridge
workflow maturing into standing practice.

## Completed work

- **P1 perception extensions**: carried items (containers, belt
  geometry, all ten potion tiers 602–611, durability), ground items by
  unit mode, objects with `INTERACTIVE_OBJECT_KINDS`, merc/revive
  splits, the active-right-skill read, `label_display_on`.
- **P2 input extensions**: `PanelInput` (the fourth guard — clicks only
  while the named panel is verified open), verified skill switches,
  belt keys, Shift chords with `finally`-guarded release.
- **P3 town + waypoint**: the preamble stations (Akara heal, Charsi
  repair at <70% durability, stash deposit, belt refill by TYPE, merc
  check/resurrect), the `InteractionLayer` (retried panel clicks,
  stray-dialog recovery), waypoint travel with the panel-edge
  discipline and area-id arrival proof.
- **P4 behavior engine (sim-first)**: the ticked engine
  (snapshot → monitor → ladder → step), runs as validated TOML over a
  step registry, the reflex ladder rungs 3–8, `CombatModule` protocol,
  action vocabulary + executor seam, `IdleBail`/never-idle invariant,
  the runner at the `run_games` boundary.
- **P5 combat + pickit**: `NecroCombat` (dash/strike/retreat in capped
  hops, desecrate→revive wall, quiet-field gate, honest desecrate
  budget), the pickit loader + cleanse, `wiring.py` production assembly
  with session-vs-per-game lifetimes, the run CLI.
- **P6 staged acceptance**: stages A–E with every failure root-caused
  and fixed en route (see the next section); Stage D thresholds
  settled (chicken 35, warp/drink numbers as shipped, belt-short =
  notice-and-continue, by-catch = accept-and-cleanse); the R207
  autonomous pickup-accuracy campaign (T57–T67); patrol clearance,
  route-aware legs, the survey system, the Enter/ESC kill switch, the
  stop channel, rung 6.5 (reposition), 7.5 (merc first aid), 7.6 (belt
  hygiene) — all user-driven mid-milestone additions.

## What live verification caught that tests could not

Continuing the M1–M4 tally; M5's haul was the largest and is why the
staged ladder exists:

1. **The clickable sprite draws ~28–48 px above the item's ground
   tile** (T57–T63): tile-projection clicks miss ~29/30. Fixed with
   the measured per-attempt offset schedule; small classes (runes,
   gems, charms) are effectively label-clicked, so the ALT label
   display is memory-verified ON before pickups (T65/T66, flag at
   BH.dll+0x14d2ca).
2. **The hover slot (player+0xE8) is a dead end for clicking**: it
   tracks only real mouse motion; synthetic moves never update it;
   clicks never needed it (T58–T62 — documented so nobody re-digs).
3. **Potion tier blindness**: the shipped kind table knew hp5/mp4–5
   only; hp1–hp4 read as foreign potions (T56/T57). All tiers now in
   the table from the game's own T42 code dump.
4. **Belt-full must be evidence-checked both ways** — the sticky
   misdiagnosis starved a run into a chicken (T56 game 2).
5. **Non-player hp reads on the 0–128 client scale** — a full-health
   merc read "8%" and was fed the belt (T54); `life_pct` everywhere.
6. **The merc chord is Shift+key, not Alt** (R183, by-hand check).
7. **A cast animation is 610–640 ms and eats CLICKS but not
   keypresses** (T48) — the executor waits on the game's own casting
   mode; potions never queue.
8. **Ground items expire; the client's loaded-room horizon (~46–67
   subtiles) binds perception**, not our 80 (T51/T50) — patrol is what
   makes a 150 radius honest.
9. **Seam/border livelocks** (T55 run 2): collect walks that land
   short are free forever without a no-progress budget; progress needs
   a margin; ring points near area seams must be inset (R189 a–c).
10. **Desecrate near a waypoint opens its menu** — ground casts now
    keep `object_clearance` from clickables (stage B run 10).
11. **Unit ids re-roll as rooms reload** — per-item budgets keyed by
    id reset silently (T57); pickup memory is position-based.

## Validation

- `pytest -q` → **864 passed** (193 at M4 close). `ruff check .` clean.
- Stage records: T55 (patrol steady state ~220 s), T56 run 3 (Stage C
  2/2 clean, deposit loop end-to-end), T64/T67 (pickit accuracy:
  wanted arrive, junk stays), Stage E 3/3
  (`stage-e-acceptance-report.txt`).
- Full request trail: `docs/instruction-log.md` R44–R210 (all resolved
  at closeout).

## Deviations from the plan

1. The plan's stages assumed threshold *tuning*; Stage D instead
   confirmed every shipped number (the tuning had happened continuously
   under supervision, R163/R185/R186).
2. The pickup-accuracy campaign (T57–T67) was unplanned — Stage C's
   failure opened it; it ran under the R207 standing mandate rather
   than per-run gates, and its results (sprite offsets, label policy)
   are now architecture.
3. The patrol, survey system, route service, kill switch, stop channel,
   narrative log, Partyline, drill kit, and rungs 6.5/7.5/7.6 were all
   mid-milestone user-driven additions — each with its own plan or
   review artifact, absorbed into this milestone rather than deferred.
4. T62 (glide lawnmower) bookmarked unrun — mooted by T63's answer.

## Documentation

`docs/architecture/behavior.md` (new); the behavior ADR **accepted**
with P6 amendments; `perception.md`/`game-cycle.md`/`navigation.md`
pointer updates; README (run CLI + operator-tunable files); CLAUDE.md
(M5 done-line, four guarded paths); roadmap row + ADR expectation (c)
delivered; teach explainer
`docs/learning/2026-08-03-layers-reflexes-and-guards.md` + 8 glossary
entries; instruction log reconciled (stragglers R20/R73/R149/R158/
R175/R202/R205/R207 closed; M5 reduction observations added).

## Follow-ups — the M6 planning inputs

**The M6 target** (user, 2026-08-03): Countess runs — town chores →
waypoint to Black Marsh → Forgotten Tower → Tower Cellar 1–5 (doorways
each level, killing what obstructs) → clear Level 5 to the Countess →
kill her → **take extra care over her drops**. Time target 5–6 min
(user does ~4 by hand — ambitious but plausible). A test battery
should be developed alongside (the user's explicit ask). Permanent
capital already banked: **T52 run 2 surveyed the whole route** — Black
Marsh corridor (36 rooms, route-survey by design), Tower 3, Cellars
19/20/14/14/17 rooms, Cellar 5 at zero frontier.

Risks the user foresees, plus what M5 adds to each:

- **Navigation/pathfinding at route scale**: how well the bot really
  uses the atlas over a five-level descent; cross-area *walking*
  (Black Marsh → Tower is on foot, not waypoint) does not exist yet —
  M5's seam lessons (inset, progress margins, per-area grids) are the
  groundwork. May need real development.
- **Doors**: collision treats closed doors as walls; the cellars are
  full of them. Deferred since M3; now due.
- **Cellar darkness / line-of-sight churn**: objects entering and
  leaving perception risks loops — M5's write-off budgets and the
  loaded-room-horizon measurements are the tools to bring.
- **Doorway-blocking enemies** and **genuinely dangerous hallways**:
  approach slowly, revives tanking, best from the north into the
  Countess chamber (user tactics — encode, don't invent).

**Behavior defaults the user has already requested** (2026-08-03,
implement in M6):

- **Right-skill parking**: after any right-skill cast (Revive above
  all), toggle back to the bone-armor hotkey — with Revive active,
  ground corpses are selectable and may interfere with pathing and
  pickup. Allow a couple seconds' grace when several revives queue.
- **Revive wall priority bump**: 3 revives up matters for safety and
  speed; the bot dilly-dallies over it. Not an emergency rung — a
  priority adjustment in the upkeep/offense balance.
- **Combat postures**: current behavior classified as "cautious" in
  behavior.md's posture section (the knobs and code seams are mapped
  there); build "aggressive" and "brisk", ideally runtime-switchable.

**Carried-over open items**:

- Open P3 issues from the potions-live-validation review: 002
  (sightings memo keeps no-longer-wanted items pending) and 003 (seam
  filter silently skipped when the first patrol tick has no area);
  plus the session review's tracked P3s (frontier stride vs narrow
  doorways — directly relevant to the cellars — and the survey cache
  key).
- Deferred features: corpse retrieval/death recovery (user decision,
  M4), TP tome + bone wall (bound, unused), vendor UI (belt-short
  stays notice-and-continue).
- Key-bindings introspection (read the client's hotkey config from the
  .key file or memory) — drill-kit follow-up from R183.
- Navigator label-band nudge — optional polish from the accuracy
  campaign, moot for M5.
- Re-verification drills after any patch/window change:
  behavior.md §"Re-verification drill after a patch".
