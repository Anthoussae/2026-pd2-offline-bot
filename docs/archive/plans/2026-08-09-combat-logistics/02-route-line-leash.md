# P2 — the route line and the leash

Size: md. Dependencies: P1 (nominal). Review gate: none (live
acceptance under the standing mandate).

## Scope

**A. The line store** (`pd2bot/nav/routeline.py`, new): a RouteLine is
an ordered list of (x, y) world waypoints for one (map seed, area id),
stored as JSON under `maps/<seed>/lines/<area_id>.json` beside the
atlas (seed-bound save-data, gitignored already). Load/save/list;
validation on load (monotone progress not required — lines may bend).
Geometry helpers: nearest point on the polyline to a position (segment
projection), stray vector (distance + direction back), progress along
the line (arc-length fraction). Pure functions, unit-testable without
the game.

**B. The recorder** (map-agnostic, reusable for any future run): drill
`drills/t84_record_line.py` — operator walks the intended route; the
drill samples the player position each tick (read-only), thins the
trace with the existing waypoint simplification (`nav/pathing.py`
simplify), previews the waypoint count, and saves the RouteLine for
(current seed, current area). Chat announcements per the drill
protocol; typing `done` in chat (or ESC per T-protocol) ends recording.
Re-recording an area overwrites after a confirm.

**C. The leash signal**: `RunServices` gains an optional
`route_line`; `TraverseStep` (and `ClearRadiusStep` when a line
exists) computes stray distance/direction each tick and EMITS
`route.stray` events (distance, direction, progress) whenever stray
exceeds a threshold (`[route] stray_subtiles`, default 12, in
necro.toml — loader-validated). Run TOMLs may name `line = true` on a
step to require the area's line (build-time failure if missing, the
_checked_posture precedent).

**D. Posture-conditioned return**: when strayed beyond threshold and
the step has no higher-priority work, return TO THE NEAREST LINE POINT
(not the origin): cautious/aggressive postures require zero hostiles
within the engagement radius before returning; brisk returns
immediately (fighting only what obstructs, per its definition). The
berserk rule (return only at zero nearby enemies) lands with P3 —
leave the policy hook keyed by posture name → policy enum here.

## Out of scope

Auto-generating lines from A* (future); leash-driven abort;
Countess-run lines (recorded later at the operator's leisure — the
tool is the deliverable, Cold Plains is the acceptance case).

## Live acceptance (standing mandate)

1. Operator records the Cold Plains line (T84).
2. One `--run cold-plains` with the leash active: the event log shows
   `route.stray` events during combat excursions and returns to the
   line; no navigation regressions (nav.failed not worse than
   baseline).

## Validation

Unit tests: polyline geometry (projection, stray vector, progress),
store round-trip, recorder thinning against a scripted trace, return
policy per posture against the sim. Event kind documented in
run-log.md. pytest + ruff green; commit per convention.

## Reminders

The leash must poll safety in any wait it introduces (bounded +
polls — the unstarvable rule). No hardcoded thresholds. Stop and report
if TraverseStep's existing route legs and the line disagree confusingly
in practice — do not improvise a merge of the two route concepts
without recording the design.
