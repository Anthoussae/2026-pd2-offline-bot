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

Updated: 2026-08-02 (~20:20; the potions cycle is live-validated — T54
run 4 PASS, and the T55 timed patrol went 1032 → 458 → 217 s across
three runs as R185-R190 landed: upkeep quiet-field gate + honest
budget, heal/repair skip thresholds, sweep-on-evidence, collect budget,
progress margin, seam-point filter, the Shift merc chord, the 0-128
merc hp scale, and the Enter/ESC operator kill switch. PR #1 still open
awaiting the user's merge decision)
