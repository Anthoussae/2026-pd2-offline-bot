# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

- **Milestone:** M6 — Countess flagship
- **Phase:** P4 — the countess run and the Cellar 5 endgame (P1, P2,
  P3 all DONE; plan: `docs/plans/2026-08-03-m6-countess/`)
- **Next request ID:** R220 (overall counter; R171 was never issued — a
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
NEXT: **P4 implemented, gate pending (R219)** — `runs/countess.toml`,
the `clear_countess` step (neighborhood clear via composed
ClearRadiusStep; atlas-derived north staging, blackboard-recorded;
revive-brake advance; kill condition = pinned identity dead OR
provably absent after the budgeted 15 s sweep, alive-and-unreachable
a LOUD stop), the T70 Thul question RESOLVED as opportunistic-collect
in traverse (shared mixin, combat-declined ticks only), and full sim
coverage (countess + blinded-read scenarios; 921 tests, ruff clean).
Gate artifacts in the plan dir: `p4-sim-trace-countess.md`,
`p4-sim-trace-absent.md`, `p4-staging-derivation.md`.

**R219 answered** (2026-08-05): screen-north convention CONFIRMED; the
staging point DEFERRED to live judgment (coordinates on a grid were the
wrong instrument — show the behavior, don't describe it); GO given.

**T71 run 1 FAILED and the endgame is still unproven live.** It never
reached Cellar 5: the run died at the SECOND transition, in the
Forgotten Tower, clicking the Cellar 1 staircase 5 times from 11
subtiles away without the area changing. Run 2 was cancelled before it
started (debugging). What the investigation established, in order of
confidence: the atlas and pathfinding are PROVEN INNOCENT (area 20 is a
fully-recorded 19x19 walkable box; A* returns one leg; seed matches;
routing was never even invoked because 11 <= click_range 18). The real
defect is that **TraverseStep recorded 5 of ~150 decisions**, so the
artifact could not say what the bot was doing — now fixed with a
run-length-collapsed decision trace carrying position and
distance-to-stairs. Two earlier diagnoses ("the fight owned the ticks",
"the staircase was contested") are recorded as UNSUPPORTED, not fixed;
the `exit_block_radius` rule they produced is kept on its own merits
only. Leading untested hypothesis: `InteractObject` clicks the raw tile
projection with no offset, while T63 measured tile clicks missing
sprites ~29/30 — so a staircase click may be executing as a walk order.
Evidence: `t71-tower-decision-log.md`, `navigation-diagnosis.md`
addendum. NEXT LIVE ACT: re-run T71 and read the trace — it
distinguishes the three candidate causes by the position column alone.
Then P5 (battery; warm-descent measurement) and P6 (closeout). PR #1
merged; branch `m6-countess` is the working line. 924 tests, ruff clean.
