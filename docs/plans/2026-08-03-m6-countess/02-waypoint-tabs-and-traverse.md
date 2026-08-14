# P2 — Waypoint act tabs, new destinations, and the traverse step

Part of [plan.md](plan.md) (M6). Size: `sm` (but live-heavy).
Dependencies: P1 (exit reader, area constants). The user must be at
the machine for the calibration drills and traversal drills; request
an R207-style standing mandate for the drill stretch (one 🔶 covering
the batch) rather than per-run gates.

## Scope

Everything that moves the character between areas: the waypoint
panel's act tabs + three new destination rows (Black Marsh, Arcane
Sanctuary, Halls of Pain — R212 Q2), and the new `traverse` run step
that walks out of one area into the next via a clicked staircase/warp,
verified by area id. Ends with the full-descent drill: waypoint →
Black Marsh → Tower → Cellar 1 → … → Cellar 5, supervised.

Out of scope: combat changes (P3), the run file (P4), doors (deferred).

## Implementation

1. **Act tabs** (`uipoints.py`, `waypoint.py`). The waypoint panel has
   act tabs; today's flow never leaves Act I's default list. Add
   calibrated UIPoints for the tabs needed (II for Arcane Sanctuary,
   V for Halls of Pain — calibrate all five while the panel is open if
   cheap), and teach `WaypointTravel` a `(tab, row)` destination shape
   (Act I destinations keep working with no tab click). After a tab
   click, re-verify the panel still open before the row click (the
   PanelInput re-check discipline).
2. **Calibration drill** (T25-battery pattern, one drill run): user
   opens the waypoint panel and hovers on each mark (tabs II and V,
   rows Black Marsh / Arcane Sanctuary / Halls of Pain) on the bot's
   chat prompts; fractions recorded into `uipoints.py` with
   provenance. Destination area ids proven on first travel (area-id
   arrival, as ever) — Arcane Sanctuary and Halls of Pain get their
   `AREA_*` constants verified then too.
3. **The `traverse` step** (`steps.py`, registry entry in `run.py` +
   `build_registry`). Parameters: `dest` (area id). Behavior per tick
   (ticked step — this happens in Hell):
   - Ask P1's reader for the exit toward `dest` in the current area.
     If not yet loaded (distant), walk toward the **remembered exit
     position** — maintained in a small persisted store keyed like
     the atlas (seed, difficulty, area, dest): first successful
     discovery records it; later runs route immediately. Route legs
     via `route_to`, capped hops, ladder consulted between (the
     `_route_leg` pattern).
   - Within reach of the staircase: click it (`GatedInput.
     click_world` at the warp position; the object-clearance rules
     apply to *other* clickables nearby), then poll for the area-id
     change — the waypoint.py trust pattern verbatim: bounded wait,
     re-click on no transition, loud failure naming what it was
     stuck on. On arrival: record the new arrival position on the
     blackboard, done.
   - Combat en route is the posture's business (P3); until P3 lands,
     the existing engage behavior stands — the step only refuses to
     advance while `engage` owns the tick (the `approach` refusal
     pattern).
4. **Live drills**, in order, each a T-numbered Drill Kit entry:
   - **T-exit-read**: stand in Black Marsh (via the new waypoint
     row), probe exits, compare against the atlas + user's eyes. Q1's
     area-id assertions run here.
   - **T-traverse-one**: Black Marsh → Forgotten Tower, one
     transition, supervised.
   - **T-descent**: the full chain to Cellar 5. Logs every
     super-unique seen (P1's Countess-id capture). Chicken 50 for
     these (R212 Q8). Danger note (user): cellar hallways are
     genuinely dangerous — hands near the controls, the kill switch
     is live.

## Docs

`navigation.md`: replace the "cross-area walking is not built"
paragraph with the traverse design (exit read + remembered positions +
area-id proof). `perception.md` exits paragraph gains the live-proof
citation. Calibrations recorded with provenance in `uipoints.py`.

## Review gate

End of phase. Artifacts for the user: the T-descent drill row (PASS
expected), the exit-position store contents, and the answer to "did
the RoomTile read suffice, or is the fallback calibration survey
needed?" (notes.md Q10 — a user decision either way).

## Agent reminders

Do not commit unless asked. No scope expansion (no doors, no combat
tuning here). A transition is proven by area id, never by the click.
Stop and report if exits misread — the fallback survey is a designed
alternative, not an improvisation. Report deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus the three drills logged in `docs/drill-log.md`.

## Definition of done

Tabs + three rows calibrated and live-used; `traverse` implemented,
sim-tested (scripted world with a fake exit + area flip) and
live-proven by T-descent reaching Cellar 5; exit store persisting;
Countess's super-unique id captured if she was seen (else deferred to
P5's first full run); review gate answered.

## Implementation Result

Status: **done — code and live halves both** (the review gate's
question answered: the RoomTile read suffices WITH the seek fallback;
the user's manual calibration survey was never needed)
Completed: 2026-08-05
Commit: d2e612f (and the arc before it: e4921b6 code half, 2407667
calibrations, 0df707a tome fix, 613315c seek-and-remember)

Live record (details in docs/drill-log.md and the captured logs):
- **T69 PASS 4/4**: act tabs I/II/V + Black Marsh / Arcane Sanctuary /
  Halls of Pain rows calibrated; tab-aware WaypointTravel shipped.
  AREA_BLACK_MARSH=6 verified; HALLS_OF_PAIN=123 read live (contradicts
  classic lore); ARCANE_SANCTUARY=74 still an expectation.
- **T70 runs 1-4**: the failure ladder that shaped the final code —
  announcement-not-foreground lesson; the tome misclick recurrence
  (fixed in four layers + post-mortem in docs/reviews/); the Cellar 1
  no-exit failure that exposed the preset-loading limit and produced
  seek-and-remember.
- **T70 run 5 PASS: the full descent**, town → Cellar 5, 796 s, all 7
  transitions area-id proven, clean [CVRL]. maps/exits.json holds 11
  staircases (the route in both directions) — every later descent is
  staircase-to-staircase with zero searching.
- Countess constants pinned: kind 734, unique_no 6 (T68 + R216).
- Carried forward: performance-notes.md (warm-descent measurement
  first; staircase pacing and CastInFlight contention priced), the
  ignored-Thul-rune investigation (traverse has no pickup logic), and
  the dithering/corners troubleshoot — all for P4/P5/optimization.

- Changed: `actions.py` (`InteractObject` — the single-click staircase
  gesture); `execute.py` (plain left click, no SHIFT, cast-in-flight
  respected); `exits.py` (`ExitMemory` — persisted exit positions keyed
  (seed, difficulty, area, dest) in `maps/exits.json`, corrupt-safe);
  `steps.py` (`TraverseStep`: posture on first tick, arrival proven by
  area id only, combat owns any tick it claims, exit from memory
  first + live RoomTile read as authority with write-back, route legs
  via `_route_leg`, paced + bounded staircase re-clicks, loud
  `NavigationError` on no-exit / no-route; registry entries in both
  vocabularies); `wiring.py` (exit closures, seed read live per call).
- Validated: **899 tests** (7 new: traverse walk/click/arrival with
  blackboard + memory write-back, memory-first + paced re-clicks,
  loud no-exit, combat-owns-tick, exit-memory round-trip/corrupt-file,
  InteractObject click shape), ruff clean.
- Early live wins banked out of order (T68, read-only, 2026-08-05):
  the exit read proven in Cellar 5 (area 25 named, staircase to 24
  located); Countess candidate kind 734 / unique_no 6 pending the
  user's eye (R216); the wName heuristic found dead and reworked.
- Remaining for the live half: the calibration battery (act tabs II/V,
  Black Marsh / Arcane Sanctuary / Halls of Pain rows), T-exit-read in
  Black Marsh (Q1 area-id asserts), T-traverse-one, T-descent — all
  under the R217 standing mandate; then this phase's review gate.
