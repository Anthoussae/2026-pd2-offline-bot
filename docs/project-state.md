# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

- **Milestone:** M5 — trial run (Cold Plains clearance)
- **Phase:** P6 — staged live acceptance
- **Next request ID:** R192 (overall counter; R171 was never issued — a
  handoff off-by-one, left as a hole rather than backfilled; check
  `docs/request-index.md` for the highest issued)
- **Next test ID:** T56 (check `docs/drill-log.md`)

Updated: 2026-08-02 (~21:00, session end). The potions cycle is
live-validated (T54 run 4 PASS; T55 timed patrols 1032 → 458 → 217 →
236 s — steady state ~220 s). Session reviewed:
`docs/reviews/2026-08-02-potions-live-validation/` (P1 stop-vs-death-
latch order fixed in review; P3 issues 002-003 open). PR #1 body
updated, still open awaiting the user's merge decision. NEXT: finish
M5 P6 per `docs/plans/2026-07-29-m5-trial-run/06-staged-acceptance-
closeout.md` — Stage C (supervised full run, radius 150, R49
thresholds), Stage D (🔶 threshold decision, chicken back to 35%?),
Stage E (3 clean UNATTENDED games), then closeout items 1-10 (
behavior.md, ADR → accepted, README/CLAUDE.md/roadmap, archive the M5
plan) — and then the M6 (Countess) yona-plan pass, for which the
border/seam lessons and multi-area routing are the key inputs.
