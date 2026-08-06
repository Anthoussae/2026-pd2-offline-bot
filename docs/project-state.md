# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

- **Milestone:** M6 — Countess flagship
- **Phase:** P4 — the countess run and the Cellar 5 endgame (P1, P2,
  P3 all DONE; plan: `docs/plans/2026-08-03-m6-countess/`)
- **Next request ID:** R219 (overall counter; R171 was never issued — a
  handoff off-by-one, left as a hole rather than backfilled; check
  `docs/request-index.md` for the highest issued)
- **Next test ID:** T71 (T70 ran 5 times; check `docs/drill-log.md`)

Updated: 2026-08-05 (**P2 COMPLETE, live-proven end to end**: T70 run 5
was THE FULL DESCENT — town → Black Marsh → Forgotten Tower → Cellars
1–5, 796 s, all 7 transitions area-id proven, clean [CVRL], chicken 50
untriggered. `maps/exits.json` banked 11 staircases — the whole route
in BOTH directions — so every later descent is staircase-to-staircase
with zero searching; the ~700 s of first-visit seeking never recurs on
this seed. The session's hard-won lessons, all committed: the tome
misclick recurrence and its four-layer fix + post-mortem
(`docs/reviews/2026-08-05-tome-misclick-feedback.md`); the
preset-loading limit — Room2 preset/warp data only exists for rooms the
client has loaded around the player, so exit scans are
position-dependent — and the seek-and-remember answer (kolbot's
moveToExit shape once ExitMemory is warm); the navigation diagnosis
refuting "the bot has no readable map" with evidence
(`docs/plans/2026-08-03-m6-countess/navigation-diagnosis.md`); T69's
calibrations incl. HALLS_OF_PAIN=123 read live against classic lore.
Countess identity pinned: kind 734, unique_no 6. OPEN observations for
later, logged in drill-log + performance-notes: the bot IGNORED a
dropped Thul rune on Cellar 4 (traverse has no pickup logic — the
prime suspect; decide opportunistic-collect vs by-design before the
first real farm run) and residual dithering/corner-walking (speed
pass; capture a warm-descent trace first). 906 tests, ruff clean.)
NEXT: **P4** — `runs/countess.toml` + the `clear_countess` endgame
step (clear the chamber's neighborhood, approach from the NORTH,
kill condition on the pinned identity with the <15 s sweep fallback,
careful drop pickup), sim-first, go/no-go gate before live; the warm
descent measurement opens the next live session. Then P5 (battery)
and P6 (closeout). PR #1 merged; branch `m6-countess` is the working
line, pushed.
