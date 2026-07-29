# P4 — A* pathfinding and walk-to

Size: `sm`. Dependencies: P1 (gated input + projection), P2 (local
collision), P3 (generated grids). Part of the M3 plan
([plan.md](plan.md)).

## Why

This phase turns "we can see and we can click" into "we can go
somewhere": plan a route over the generated grid, follow it with
gated clicks, notice when reality disagrees (blocked, stuck, drifted)
and re-plan. It is the last functional phase of M3 and carries the
milestone's acceptance walk.

## Scope

### `pd2bot/pathing.py` — pure logic, no I/O, fully unit-testable

- A* over a grid implementing the shared grid protocol (P2/P3 both
  provide it): 8-directional, diagonal cost √2, no corner-cutting
  through blocked diagonals; unknown cells (P2's stitched view)
  treated as blocked for planning.
- Path simplification: collapse runs of nodes with clear
  line-of-walkability (Bresenham over the grid) into waypoint nodes
  spaced ≤ ~12 subtiles apart. Two reasons for the cap, both hard
  constraints: each waypoint must be **on-screen** to be clickable
  (P1's `is_on_screen`), and short hops keep deviation detectable.
  (Kolbot walks 10–15-subtile node spacing — same ballpark.)
- `nearest_walkable(grid, x, y, radius)` — for targets that land on a
  blocked cell (mined from kolbot's `getNearestWalkable`).

### `pd2bot/navigate.py` — the follow loop (live I/O)

Loop per waypoint, mined from kolbot `Pather.move()`/`walkTo()` and
adapted to snapshots:

1. Snapshot; if `can_act` false → wait (do not fight the UI; a
   blocking panel means a human or a death screen — after a timeout,
   abort with a typed error, never dismiss panels in M3).
2. If within arrival radius (~3 subtiles) → next waypoint.
3. Else `click_world(waypoint)` through the P1 gate; poll position.
4. **Stuck** = position change below a small epsilon across ~1.5s
   while a move is pending → first re-click, then re-plan from the
   live position with the *local* (P2) grid overlaid on the generated
   grid (live truth wins where known), then nearest-walkable-adjust
   the waypoint; count failures, give up after N (~5) with a typed
   error carrying positions tried (M4's error handling will consume
   it).
5. Off-route drift beyond a threshold → re-plan (cheap; A* on these
   grids is fast).

Deliberately **not** handled here: doors/barrels, monsters blocking
(Hell necro walking into packs is an M5 concern — the acceptance walk
picks a quiet route or the user clears it), stamina beyond leaving
run mode as found, teleport.

### CLI + tests

- `python -m pd2bot.navigate --to X Y` (and `--demo` for the
  acceptance walk: fixed offset out and back).
- Tests: A* correctness on crafted grids (corridor, U-trap, no-path),
  no-corner-cutting property, simplification spacing/on-screen cap,
  nearest-walkable, stuck-detector state machine with a scripted fake
  (position traces → expected actions). Live loop logic gets a fake
  session/input; no live I/O in unit tests.

## Live verification — the milestone acceptance

At the Cold Plains waypoint (Hell, `MaqiuDoubing`), user at the
machine: `--demo` walks to a point ≥ 60 subtiles away and back,
**5/5 attempts**. At least one stuck/re-path cycle demonstrated
(natural, or forced by clicking the character into a corner first).
Log each attempt (start, target, waypoints, re-plans, duration) into
this planning dir.

## Conventions / reminders

All input through P1's gate — no exceptions, including demos. Pure
logic stays import-clean of pymem/user32. Do not commit unless asked;
do not expand scope (doors, combat, transitions are later
milestones); stop and report if the follow loop needs behavior not in
this file. Report what changed, what was validated, deviations.

## Validation commands

```bash
python -m pytest -q
python -m pd2bot.navigate --demo   # live acceptance, user present
```

## Definition of done

Pure-logic tests green; acceptance walk 5/5 with logs recorded; stuck
handling demonstrated; typed failure surfaces instead of infinite
retries.

## Implementation Result

Status: **done** — acceptance walk **PASS 5/5** later the same day
(ten ~60-subtile walks, all arrived; stuck→re-plan demonstrated
naturally in demo 3; the ladder also absorbed a human mouse-touch).
Two hardening changes came out of live work: the give-up counter now
resets on progress (slow ≠ failed — user-raised move-speed concern),
and the demo picks a verified-reachable target instead of a blind
offset (R15). See live-checks.md step 6.
Completed: 2026-07-28
Commit: pending

- Changed: `pd2bot/pathing.py` (A* with no-corner-cutting, octile
  heuristic, expansion cap; `line_walkable`; `simplify` to ≤12-subtile
  waypoints; `nearest_walkable`; `OverlayGrid` for live-over-generated),
  `pd2bot/navigate.py` (`Navigator` with the escalation ladder and
  injected clock/sleep, `WalkResult` log record, `--to`/`--demo` CLI with
  optional generator wiring), `tests/test_pathing.py`,
  `tests/test_navigate.py`.
- Validated: `pytest` — 21 tests across the two files. The follow loop is
  tested against a scripted fake world in virtual time: reaching a
  target, the already-there case, an invisible wall producing re-clicks
  then re-plans then a typed `NavigationError`, an obstacle that clears
  between plans (re-plan then success), a brief UI panel waited out, and
  a permanent one failing loudly. `ruff check` clean.
- **Not validated**: the live acceptance walk (5/5 at the Cold Plains
  waypoint) — needs elevation, the user present, and ideally the P3
  generator decision, since without generated maps only targets inside
  the loaded room neighbourhood are reachable. Step 6 of
  [live-checks.md](live-checks.md).
- Deviations: `OverlayGrid` landed in `pathing.py` (this phase) rather
  than P3's `mapdata.py` — it is pure grid logic with no protocol
  knowledge, and it belongs beside the other Grid implementations.
