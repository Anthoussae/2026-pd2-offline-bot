# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

- **Milestone:** M6 — Countess flagship
- **Phase:** P4 — the countess run and the Cellar 5 endgame (P1, P2, P3
  DONE; plan: `docs/plans/2026-08-03-m6-countess/`)
- **Next request ID:** R224 (overall counter; R171 was never issued — a
  handoff off-by-one, left as a hole rather than backfilled; check
  `docs/request-index.md` for the highest issued)
- **Next test ID:** T75 (T72 ran twice, T73 twice, T74 twice; check
  `docs/drill-log.md`)

Updated: 2026-08-06. Branch `m6-countess`, pushed, **PR #2 open**
(`https://github.com/Anthoussae/2026-pd2-offline-bot/pull/2`). 1000
tests, ruff clean. The repo has no CI workflows — local validation is
the gate.

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
absence. ADR: `docs/adr/2026-08-05-run-event-log.md` (**proposed** —
T72 run 2 is the evidence for accepting it).

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

## NEXT: the first live Countess run

Everything upstream of the Countess is now live-proven. The endgame is
not.

- `runs/countess.toml` + `clear_countess` are **sim-proven only** — both
  the seen-kill path and the blinded-read sweep. Never run against the
  game.
- R219 answered: screen-north confirmed, staging point (12531, 11036)
  **deferred to live judgment** — the operator watches the approach and
  says whether it reads right. That judgement is still outstanding.
- Chicken **35** for a proper run (R212 Q8); 50 for cellar drills.
- The run will be the first live exercise of `stash.*` and `npc.*`
  (T72's preamble had nothing to deposit).

The launch goes out as **T71 run 3** (a re-run of an existing drill
keeps its ID — T70/T72 precedent; T75 stays reserved for the next new
drill). The ordered pre-launch re-check (review 001's lesson) is DONE,
2026-08-06: the drill's three gates are sound (a chickened cycle,
a short descent, and a missing `clear_countess` all fail), but the STEP
under them had the same hole one layer down — a chamber sweep whose
points were all skipped as unreachable still concluded "provably
absent", so a bot pinned short of the chamber could complete the run
objective having seen nothing. Fixed in ce3ba82: skips are counted, and
a completed pass with skips and no corpse is the same loud stop as a
spent budget. The old absence test was itself the false path (static
player) and now genuinely walks. Launch gate: R223 (pending — the user
tabs in and says go).

## After that

- **P5 battery** — the warm-descent timing measurement is its first live
  act, and it now has real instrumentation to measure with.
- **Speed pass** — `docs/plans/2026-08-03-m6-countess/performance-notes.md`
  holds the evidence, including the newest: ~3 of the Tower's 4.3 s is
  the staircase retry window held while standing on the stairs. It
  carries a warning not to "fix" it without a measurement, because the
  eager version of that retry was T70's original bug.
- **Deferred, deliberately**: enemy-death events (R220 Q6),
  `item.accidental`, the collision recorder writing rooms under the
  wrong area id during an area flip (seen in `area-020.json` and
  `area-025.json`).

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
