# Bounded pathfinding: "no path found within budget" is an honest answer

Status: accepted (2026-08-14, R256 Q1 / R257 P2)

## Context

The explored-map atlas records only ground the client has loaded, and
unknown ground is deliberately unwalkable for planning. That premise
has a sharp corner: two recorded cells can be *locally* adjacent but
disconnected **within the recorded map** — the real connection runs
through ground nobody has read yet. Asked for a path between them,
unbounded A* proves the negative the only way it can: by flooding every
reachable recorded cell.

Measured (2026-08-13, T92 follow-up): on the Cold Plains atlas (115
rooms), one such query — eight subtiles start to goal, both walkable —
took **20.15 s** to answer "no path", against 3 ms for a healthy
25-cell path. The two-strike no-route rule (itself correct: one answer
can be a torn read) asked twice, freezing a live run for 47 s. A
previous guard existed (`SearchLimitExceeded` at 200 000 expansions)
and was worse than nothing: it never bound (the flood exhausted the
component first), and it RAISED an exception no production caller
caught — a latent tick crash.

## Decision

`pathing.astar` takes a node budget; production callers use a
distance-scaled default (`default_node_budget`: floor 2 000, cap
25 000 expansions, 30·d² between). A search that exhausts its budget
**returns None** — the same answer an exhausted open set gives.

The vocabulary is the decision. Callers already treat None honestly:
confirm with a second ask over a fresh grid, then write the target off
with expiry-on-movement (`clear.py::_no_route`,
`patrol.py::_route_denied`). Budget exhaustion therefore needs no new
caller code, no new exception type, and no new failure mode. Every plan
reports its price (`nav.plan` run-log event: duration, nodes expanded,
`budget_exhausted`), so a budget stop is always distinguishable from a
proven no-path on the record.

Constants were sized empirically (~10 000 expansions/s on this
machine): the floor answers the replayed flood in 0.057 s and sits far
above any real path's expansion count (a 25-cell path expanded 68
nodes; the largest plan in a 481 s run was 331 cells); the cap bounds
the true worst case at ~1.3-2.4 s — inside the acceptance bar of "no
tick over 4 s" with margin. The cap was lowered from a first guess of
50 000 the same hour after measurement showed 4.86 s there.

## Consequences

- A genuinely reachable far target can, in principle, be refused by an
  exhausted budget. Accepted: the floor makes it rare, write-off
  expiry-on-movement makes it recoverable, and eleven live acceptance
  runs recorded **zero** `budget_exhausted` events on real paths.
- "No path" is now cheap enough that callers may ask freely; the
  two-strike rule stays.
- Alternatives considered and deferred: connectivity caching /
  component labeling over the atlas (adds cache-invalidation coupling
  to every room record for a problem the budget already bounds), and
  keeping the raise (falsified — nothing caught it).

## Evidence

`docs/plans/2026-08-13-clear-radius-locomotion/notes.md` (discovery,
constants, battery record); baseline log
`logs/runs/20260813-083614-cold-plains` t+155.9/t+177.8; regression
tests in `tests/nav/test_pathing.py`.
