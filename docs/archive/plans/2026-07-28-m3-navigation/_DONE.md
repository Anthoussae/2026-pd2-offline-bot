---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-07-28
commit: pending
adrs:
  - docs/adr/2026-07-28-hybrid-map-knowledge.md
---

# Implementation log — M3 navigation

## Outcome

**Done, live-verified end to end.** The bot walks: given a target in a
surveyed area, it plans over its remembered map, follows the plan with
gated clicks, notices when reality disagrees, and recovers. Acceptance
walk **5/5** (ten ~60-subtile legs, all arrived, 2.9–6.7 s each), with
the stuck→re-plan ladder demonstrated naturally and a human mouse-touch
absorbed mid-walk. 121 tests pass; `ruff check` clean.

The milestone's shape changed once, at the P3 review gate, for the
better: the external map generator was **replaced by the explored-map
atlas** after the user pointed out that single-player maps are fixed per
character per difficulty. Live-proven the same day: one seed folder
survived save-exit-and-new-game, and a re-survey of known ground
recorded zero.

## Completed work

- **P1** `window.py` / `screen.py` / `input.py` / `navdemo.py`: one
  gated send path (can_act + foreground, re-checked at the moment of
  sending, no bypass); world↔screen projection; gate/click-test/
  calibrate CLIs. Live: gate refusals 3/3 in the real client — the
  "Save and Exit Game" class is closed against reality.
- **P2** `collision.py` + CollMap block in `offsets.py`: room grids
  read and stitched, `is_known` vs `is_walkable` honesty, ASCII dump
  with screen-direction obstacle summary, `--debug` chain diagnostics.
- **P3 (re-scoped)** `mapstore.py`: per-(seed, difficulty, area) atlas,
  terrain-only (occupancy bits stripped), atomic saves, corrupt files
  degrade to honest blankness. Survey mode + auto-recording while
  walking. The generator work remains dormant but real: d2mapapi_mod
  builds 32-bit via direct `cl` (no CMake), with a version-force patch
  and a PD2_EXT stub; blocked by PD2's SGD2FreeRes popping a modal
  dialog headlessly. Unblock path documented in `generator-status.md`.
- **P4** `pathing.py` / `navigate.py`: A* (no corner cutting, octile,
  expansion cap), path simplification under the *measured* click-reach
  cap, `OverlayGrid` (live > atlas), the follow loop with the
  re-click → re-plan → give-up ladder, progress-resets on the give-up
  counter (slow ≠ failed), reachable-target demo.
- **P5** docs, sweep, teach (see the phase file's result).

## What live verification caught that tests could not

Continuing M1/M2's tally of semantic errors only reality finds:

1. **The projection scale.** Config files *implied* 1.44×; the classic
   formula said 1×; measured walks said **1.25×** (20/10 px/subtile,
   ratio exactly 2.000). Both documents were wrong; the character was
   right.
2. **The CollMap layout.** Two independent community headers agree on a
   `pMapEnd` field; the live client stores the grid inline at
   Coll+0x24 and no such field exists. My "corrected" 0x24 reading was
   wrong too — the debug dump settled it, and the integrity check now
   uses the header's own tile/subtile 5× invariant.
3. **Occupancy persisted as terrain.** First survey: 247 "rooms" — the
   user predicted monster collision would contaminate the survey before
   the data confirmed it. Corpses would have become permanent walls via
   IS_ON_FLOOR. Fixed by stripping transient bits at the persistence
   boundary only.
4. **Single clicks have a reach limit** (~320 px; beyond completes only
   60–70%) — surfaced by calibration residuals; it, not screen size, is
   the real justification for the 12-subtile waypoint cap.

Also demonstrated live: gate refusals, seed stability across a full
game cycle, and the user-raised move-speed concern (slow-but-moving
never reads as stuck or failed — locked in by simulation tests).

## Validation commands and results

- `python -m pytest -q` → **121 passed**.
- `python -m ruff check .` → clean (first milestone with real lint;
  M2's caveat closed). `ruff format` deliberately deferred repo-wide.
- Live: `docs/archive/plans/2026-07-28-m3-navigation/live-checks.md`
  records every step with outputs; requests and outcomes are in
  `docs/instruction-log.md` (R3–R16).

## Deviations from the plan

1. **P3 re-scoped at its review gate** (user decision): explored-map
   atlas instead of generator + fidelity check. `fidelity-results.md`
   intentionally never written — atlas data comes from the real PD2
   game, so there is nothing to check fidelity against.
2. `OverlayGrid` landed in `pathing.py` rather than P3's module (pure
   grid logic).
3. No captured-generator-response fixture (generator never ran);
   mapdata tests use payloads built from upstream's documented format.
4. Mid-milestone additions at user request: the move-speed robustness
   pass, and the user request protocol (instruction-log.md + toolkit
   skill edits — the latter live in `agent-toolkit/`, uncommitted
   there).

## Documentation updated

`docs/architecture/navigation.md` (new), README (atlas + tools),
CLAUDE.md, roadmap M3 row, the map-knowledge ADR (rewritten once, at
the re-scope), `docs/instruction-log.md` (new, with protocol),
teach explainer + 9 glossary entries.

## ADRs created

`docs/adr/2026-07-28-hybrid-map-knowledge.md` — remember-what-we-walk
for map knowledge; live memory stays ground truth; generator deferred
with its unblock path. (Gated-input ADR deliberately not written: the
design was forced by the M1 incident, not chosen among alternatives —
documented in navigation.md instead.)

## Follow-up work outside this milestone

- **Perception defects found and fixed during closeout (R17–R25).**
  Chasing M2's unverified ground-item caveat uncovered a chain of real
  bugs, all now fixed, tested, and verified live:
  1. *Ground items* — the ItemData location byte (0x45 per BH) does not
     mean what the header claims: a dropped item reads 247, belt and
     equipped items read 255, so the filter hid real drops and invented
     phantoms at inventory grid coordinates. Now filtered on unit mode
     (3 on-ground / 5 dropping).
  2. *Unit enumeration* — room traversal misses most units. With a merc,
     two skeletons and a dropped item present it found one type-1 unit
     and no items. Switched to the client unit hash table
     (`D2CLIENT.pUnitTable`), which is how BH and kolbot enumerate.
  3. *Friend vs foe* — mercenaries and summons are unit type 1 like
     hostiles; only `STAT_ALIGNMENT == 2` separates them. Scans now
     return `monsters` and `allies` separately (user-spotted: the dump
     was reporting their own Rogue as a monster).
  4. *Locality* — the hash table is global, so it listed the entire
     stash and expired summons. Added an 80-subtile perception radius.
  5. *Duplication* — units are reachable from multiple bucket heads;
     the iterator now de-duplicates by id (49 rows → 14 for the same
     scene).
  `docs/architecture/perception.md` rewritten accordingly. This makes
  **nine** header-vs-reality corrections across M3; the pattern is the
  milestone's main lesson.
- `ruff format` repo-wide as its own commit.
- Commit `agent-toolkit/` protocol changes and push so the Mac inherits.
- The 125-re-record churn bit in fresh games (suspect DarkArea 0x0010):
  benign, instrumented; identify via `--survey` in a new game and add
  to `COLL_TRANSIENT_MASK` if confirmed.
- M4 wants: difficulty read from memory (atlas key currently stated by
  the caller), menu-scoped input method with its own guard, door
  handling, and consuming `NavigationError` in the game cycle.
