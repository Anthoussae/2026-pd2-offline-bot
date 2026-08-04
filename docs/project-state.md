# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

- **Milestone:** M6 — Countess flagship (planning)
- **Phase:** none yet — the M6 `yona-plan` pass is the current work
- **Next request ID:** R211 (overall counter; R171 was never issued — a
  handoff off-by-one, left as a hole rather than backfilled; check
  `docs/request-index.md` for the highest issued)
- **Next test ID:** T68 (T67, the sparse melange, ran 2 passes on
  2026-08-03 — an earlier note here said "next: T67" in error; check
  `docs/drill-log.md`)

Updated: 2026-08-03 (M5 CLOSED: stages A–E all passed — Stage E 3/3
clean unattended, report archived — and closeout items 1–10 done:
`docs/architecture/behavior.md` written, the behavior ADR accepted with
P6 amendments, pointer docs/README/CLAUDE.md/roadmap updated, teach
step done, sweep clean at 864 tests + ruff, instruction log reconciled
with all stragglers resolved and M5 reduction observations added, plan
dir archived at `docs/archive/plans/2026-07-29-m5-trial-run/` with
`_DONE.md`). The M6 planning inputs — the Countess route battery, the
T52 route-survey capital, doors, cross-area walking, combat postures,
right-skill parking, the revive priority bump, carried-over P3 review
issues — are collected in that `_DONE.md`'s follow-ups section. NEXT:
the M6 `yona-plan` pass, then implementation phases per its plan.
PR #1 (m5-trial-run) is open awaiting the user's merge decision.
