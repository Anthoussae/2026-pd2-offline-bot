# P4 — The Countess run and the Cellar 5 endgame

Part of [plan.md](plan.md) (M6). Size: `sm`. Dependencies: P2
(traverse), P3 (postures). Sim-first; ends at a go/no-go gate before
any live run (the M5 P5 precedent).

## Scope

The run file and the two endgame steps that make Cellar 5 different
from a traversal. Sim coverage over the whole run shape.

Out of scope: live runs (P5), threshold tuning (P5), any new
perception (P1 delivered it or the plan stops).

## Implementation

1. **`runs/countess.toml`** (new; commented like cold-plains.toml):

   - `town_preamble`
   - `waypoint` dest = Black Marsh (6)
   - `traverse` dest = 20 (Forgotten Tower), posture = "brisk"
   - `traverse` dest = 21 … `traverse` dest = 25, posture = "brisk"
     (five entries; each verifies its own arrival — no step counts
     floors)
   - `clear_countess` (below), posture = "aggressive"
   - `pickup` (adopts the endgame's zone off the blackboard; labels
     ensured on — the existing executor policy)
   - `done`

2. **`clear_countess` step** (`steps.py`; registry + validation as
   ever). The user's tactics encoded, not invented:
   - **Clear the neighborhood first** (R212 Q4 exception): a bounded
     clearance around the Cellar 5 arrival/approach — kill nearby
     enemies so the Countess encounter has no gaggle. Reuses the
     clear_radius machinery with a modest radius.
   - **Approach from the north, slowly** (user): route to a staging
     point NORTH of the chamber (chamber location from the atlas —
     area-025 is fully surveyed; the staging point derived from the
     chamber's bounding geometry, recorded on the blackboard for the
     drill to display), advance in short legs with the
     revives-tanking gate (`approach_with_revives` holds as the
     brake; the wait-for-revives beat already exists).
   - **Kill condition** (R212 Q7): primary — P1's boss read: the
     Countess's super-unique id seen with a dead mode, or provably
     absent. Fallback (and the sanity pass either way): the **<15 s
     chamber sweep** — one short in-and-out pass through the chamber
     so a blind corner cannot hide her; budgeted, narrated, and it
     feeds the same scan.
   - On confirmation: record the drop zone (chamber region) on the
     blackboard for `pickup`, narrate the kill, done. If the sweep
     ends with her provably alive and unreachable, loud stop-and-
     report — never a silent give-up on the run's whole objective.
3. **Careful pickup**: `pickup` already adopts a blackboard region;
   verify the chamber region form fits (center+radius vs the
   clearance circle) and extend minimally if not. Her drops (runes)
   are small-class items — the label policy and offset-schedule tail
   are exactly the machinery the accuracy campaign built; nothing new
   expected here beyond the region handoff.
4. **Sim coverage** (`tests/test_behavior_sim.py` + simworld): a
   scripted multi-area world (fake exits flipping area ids) running
   the full countess run: traverses with posture switches, the
   neighborhood clear, the north staging, a scripted Countess that
   dies, the sweep path when the boss read is blinded, the drop-zone
   pickup handoff. The trace is the gate artifact.

## Docs

Run-file comments (the operator reads these); `behavior.md` gains the
endgame paragraph; drill-kit note if the sweep narration adds a
convention.

## Review gate

Go/no-go before live: present the sim trace summary, the run file, and
the staging-point derivation (plotted coordinates vs the atlas) for
the user's judgment — they know the chamber; the north approach is
theirs to confirm on the map before the character walks it.

## Agent reminders

Do not commit unless asked. Encode the user's tactics; where the
chamber geometry is ambiguous, ask (🔶) rather than guess. No new
perception, no threshold edits (P5's). Report deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

Run file validates and builds; `clear_countess` implemented with both
kill-condition paths; sim run end-to-end green with the trace
reviewed; go/no-go gate answered by the user.
