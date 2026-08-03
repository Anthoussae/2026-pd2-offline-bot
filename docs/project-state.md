# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

- **Milestone:** M5 — trial run (Cold Plains clearance)
- **Phase:** P6 — staged live acceptance
- **Next request ID:** R211 (overall counter; R171 was never issued — a
  handoff off-by-one, left as a hole rather than backfilled; check
  `docs/request-index.md` for the highest issued)
- **Next test ID:** T67 (check `docs/drill-log.md`)

Updated: 2026-08-03 (Stage E PASSED 3/3 — see R210; all stages A-E complete, closeout items 1-10 remain). Earlier note: Stage C run 1 (T56) went 1 of 2 clean —
game 2 CHICKENED at 47% on a starved belt — and the resulting pickup
investigation (T57-T63, R192-R203, all in the instruction log) ended
with the root causes FIXED and LIVE-PROVEN (T59 run 3, 3/3): potion
tier blindness (only hp5/mp4-5 were recognized — hp1-hp4 read as
foreign/no-stock), sticky belt-full misdiagnosis (now evidence-checked
against live belt counts both ways), and the click aim (the clickable
sprite draws ~28-40 px ABOVE the projected ground tile — clicks now
follow the T63-measured per-attempt offset schedule,
`pickup_click_attempts` 6). Dead ends, recorded: the hover pointer
(player+0xE8) tracks only REAL mouse motion and clicks do NOT need it;
synthetic moves (SetCursorPos AND SendInput, absolute or relative)
never update the game's hover state — labels highlight off the polled
position. The Alt label TOGGLE is verified live (`VK_MENU`) but not
wired into the runtime. T62 (glide lawnmower) bookmarked, likely moot.
864 tests, ruff clean; all of tonight is UNCOMMITTED. NEXT: R204
restock healing potions -> T56 run 3 (Stage C rerun: radius 150,
chicken 50, 2 clean games with the deposit observed) -> Stage D
(🔶 thresholds; add the belt-short notice-continue policy to that
conversation) -> Stage E -> closeout items 1-10, then the M6 yona-plan
pass. Open P3 review issues 002-003 unchanged.
