# P1 — plan-cost telemetry and the locomotion report

Size: sm. Dependencies: none. Review gate: none.

## Scope

Two instruments, both permanent, both offline-testable:

1. **`nav.plan` events** — every pathfinding attempt becomes a run-log
   event with its cost, so a 20 s flood can never again hide inside a
   tick duration.
2. **The locomotion report** (`pd2bot/runlog/locomotion.py`) — an
   offline reducer that turns any run log into the movement numbers the
   acceptance gate (P4) will be judged on.

Out of scope: changing ANY movement behavior. This phase only measures.

## 1. nav.plan events

`Navigator` (pd2bot/nav/navigate.py) gets an optional `on_plan`
callback, following the exact precedent of its `audit` callback
(constructor arg, defaults to None, never raises into the walk —
wrap the call in `try/except Exception: pass`).

Call it in `_walk_to` around the plan block (the
`nearest_walkable` + `astar` + `simplify` sequence), with:

- `start`, `goal` (the A* endpoints), `target` (the caller's ask)
- `duration_s` (wall time of the plan block, `time.perf_counter` style
  via the injected clock is fine — but note the clock is monotonic
  already)
- `outcome`: `"path"` / `"no_path"` / `"no_walkable_cell"`
- `path_cells`, `waypoints` (0 when no path)

Wire it in `wiring.build_bot` → `live_navigator`: add an `on_plan`
parameter to `live_navigator` that forwards to the Navigator, and in
`build_bot` pass a closure that emits
`runlog.event("nav.plan", ...)`. Careful: the runlog is PER-RUN and the
navigator is SESSION-scoped — use the same repoint pattern the monitor
uses (`self.monitor.runlog = runlog` in `engine_factory`): a mutable
holder the closure reads, repointed per engine build. The
`route_service` in wiring runs its own `astar` — give it the same
telemetry (emit `nav.plan` with `source="route_service"`; the walk
path's events carry `source="walk"`).

Events only fire when a runlog is wired; the CLI/drill paths (no
callback) are unchanged. NullRunLog discipline applies: check
`runlog.enabled` before gathering anything costly (see events.py's
NullRunLog docstring).

Document the new event kind in `docs/architecture/run-log.md`
(one entry in the kind table, matching its style).

## 2. The locomotion report

New module `pd2bot/runlog/locomotion.py` + CLI
(`python -m pd2bot.runlog.locomotion <run-dir>`), pure over
`runlog.events.load()`, reusing `compare.py`'s dialect handling
(`tick` and `observe.sample` both carry `player.world`; import its
constants rather than redefining: `POSITION_KINDS`, `IDLE_SPEED`,
`JUMP_SUBTILES`).

Per area segment AND per run, report:

- duration, samples
- gross route (summed inter-sample distance) vs **net displacement**
  (straight-line sum over segment endpoints) — the backtracking ratio
- moving time / idle time, duty cycle (%), effective speed (st/s)
- idle spans ≥ 2 s: count, longest, and each span's wall-clock `t`
  plus the `step` field of the tick that ended it (bot logs only —
  attribute where the stall lived)
- ticks with `dur_s` over a threshold (default 4 s, flag
  `--slow-tick 4`): list each with its `t`, duration, step, and any
  `nav.failed` / `nav.plan` events inside its window
- `nav.plan` summary when present: count, total time, worst, outcomes
- pickups and (human logs) kills, as compare.py counts them

Output is plain aligned text like `render_comparison`'s. No verdicts —
numbers and attributions only.

## Validation

- Unit tests (`tests/runlog/test_locomotion.py`): synthetic event lists
  covering gross-vs-net, duty cycle, slow-tick listing with a
  `nav.failed` inside the window, and the `nav.plan` summary. Style:
  tests/runlog/test_compare.py.
- Navigator `on_plan` tests (`tests/nav/` alongside existing navigate
  tests): scripted fake grid, assert events for the path and no-path
  outcomes, and that a raising callback does not break the walk.
- Run the report over BOTH standing logs and paste the output into
  notes.md (this re-prices the baseline with per-stall attribution —
  the before-picture P4 compares against):

```
python -m pd2bot.runlog.locomotion logs/runs/20260813-083614-cold-plains
```

```
python -m pd2bot.runlog.locomotion logs/runs/20260813-192249-human-coldplains
```

- Full suite + ruff green.

## Conventions and reminders

- Comment density/idiom: match compare.py and navigate.py (docstrings
  say WHY, constants carry their measurement history).
- Do not commit unless the operator asked; do not expand scope; report
  deviations. Stop and report if the runlog repoint pattern turns out
  not to fit (do not invent a second wiring pattern silently).

## Definition of done

Both instruments in, tests green, ruff clean, run-log.md updated, both
standing logs re-priced into notes.md.

## Implementation Result

Status: done
Completed: 2026-08-13
Commit: pending

- Changed: Navigator `on_plan` callback (navigate.py) emitting on all
  three plan outcomes; `live_navigator(on_plan=)` passthrough; wiring
  `plan_sink` holder repointed per engine build + `note_plan` emitter;
  `route_service(on_plan=)` telemetry; new `pd2bot/runlog/locomotion.py`
  report + CLI; `nav.plan` documented in run-log.md.
- Validated: 9 new tests (6 locomotion, 3 on_plan); full suite 1324
  green, ruff clean; both standing logs re-priced (output in notes.md —
  the report names the two A* floods inline and attributes all 26 idle
  spans to clear_radius).
- Deviations: none. Note found in passing: the baseline also carries a
  17.1 s town_preamble tick and a 5.6 s waypoint tick (recorded in
  notes.md future work; out of scope).
