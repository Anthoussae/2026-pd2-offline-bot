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
