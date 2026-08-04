# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

- **Milestone:** M6 — Countess flagship
- **Phase:** P1 — transit and boss perception (plan:
  `docs/plans/2026-08-03-m6-countess/`, ready for `yona-implement`)
- **Next request ID:** R213 (overall counter; R171 was never issued — a
  handoff off-by-one, left as a hole rather than backfilled; check
  `docs/request-index.md` for the highest issued)
- **Next test ID:** T68 (T67, the sparse melange, ran 2 passes on
  2026-08-03 — an earlier note here said "next: T67" in error; check
  `docs/drill-log.md`)

Updated: 2026-08-03 (M5 CLOSED and committed `f1c6276` per R211; the
M6 plan is WRITTEN per R212's answers — plan.md + phases 01–06 in
`docs/plans/2026-08-03-m6-countess/`, notes.md carries the full Q&A).
Headlines of the R212 decisions: doors DEFERRED (staircase clicks are
the cellar transitions; doors bundle later with chests/barrels/
teleporter gates as "interactive objects"); postures brisk (Black
Marsh → Cellar 4) AND aggressive (Cellar 5) both get built; waypoint
work includes act tabs + Arcane Sanctuary + Halls of Pain rows; exit
discovery is memory-read (RoomTile chain) with the user's calibration
survey as designed fallback; boss-read perception investigated in P1
(<15 s chamber sweep as fallback); chicken 50 for early cellar
drills, 35 for proper runs. NEXT: `yona-implement` on P1 (transit +
boss perception; sim/unit work, no live time) — P3 is parallelizable
with it; P2's calibrations + traversal drills are the first live
session and deserve a standing-mandate 🔶. PR #1 (m5-trial-run) is
open awaiting the user's merge decision.
