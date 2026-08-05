# Project state

The single authoritative source for *where the project is*. Request
markers (`🔶 M<m> P<p> R<n>`) and Drill Kit test headers read their M/P
from here — update it at every milestone or phase transition, in the
same commit as the transition itself.

- **Milestone:** M6 — Countess flagship
- **Phase:** P2 — waypoint tabs and traverse (P1 and P3 are DONE; plan:
  `docs/plans/2026-08-03-m6-countess/`)
- **Next request ID:** R218 (overall counter; R171 was never issued — a
  handoff off-by-one, left as a hole rather than backfilled; check
  `docs/request-index.md` for the highest issued)
- **Next test ID:** T69 (T68 = the Cellar 5 read-only perception probe,
  2026-08-05; check `docs/drill-log.md`)

Updated: 2026-08-03 (PR #1 MERGED per R213 — main carries all of M5;
branch `m6-countess` is the working line, one branch per milestone
adopted. **P1 done** `4680df1`: exit perception via the RoomTile chain
[BH-cited, cross-checked against d2mapapi_mod], boss identity
[unique_no + wName, provisional is_super_unique — the Countess's id
gets LEARNED in the P2 descent drill], area ids 6/20/21–25
provisional, `dump --exits` probe. **P3 done** `6a5f8f9`:
cautious/brisk/aggressive posture presets selected per run step
[necro.toml tables, P5-tunable first guesses], right-skill parking
[executor maintain(), 2 s grace], revive urgency [hold keyed to a
recent wall cast + timed desecrate-budget refresh], and the four
carried P3 review issues fixed [sightings wantedness, seam null-area,
survey stride 4, atlas revision cache key]. 892 tests, ruff clean.
Standing guidance [R214]: everything possible WITHOUT the bridge or
game client; in-game testing later.) NEXT: P2 — Black Marsh/Arcane
Sanctuary/Halls of Pain waypoint rows + act tabs (calibration drills,
LIVE), the `traverse` step, T-exit-read/T-traverse/T-descent drills —
the first live session; ask for a standing-mandate 🔶 for the drill
batch. P2's CODE half (the traverse step + sim) can be pre-built
without the game if the user wants it before their live session; P4
needs P2's traverse either way.
