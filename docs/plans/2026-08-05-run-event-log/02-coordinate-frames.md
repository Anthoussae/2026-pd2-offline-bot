# P2 — Coordinate frames

Part of [plan.md](plan.md). Size: `sm`. Dependencies: none (can run
beside P1). Review gate: none.

## Scope

`pd2bot/mapframe.py`: turn a world position into the three frames every
spatial event carries (Q3), plus a compass bearing.

Out of scope: emitting events (P3), changing anything the navigator or
the atlas does.

## Why

World subtiles are absolute and correct but unreadable: the Forgotten
Tower failure reads as "player (10006, 8002), staircase (10002, 8013)",
where the interesting fact — *eleven subtiles apart in a nineteen-wide
room* — has to be computed by hand every time. Area-local coordinates
make it legible at a glance, and character-relative coordinates make a
movement command self-explaining.

## Implementation

**`MapFrame`** — built per area, from the live `Area`:

- `origin` — the area's own origin in subtiles
  (`Area.bounds_subtiles[:2]`, i.e. `Area.position × SUBTILES_PER_TILE`).
- `size` — width/height in subtiles, from `Area.bounds_subtiles`.
- `to_local(world) -> (x, y)` — `world − origin`. The Tower arrival
  becomes roughly (6, 2) and its staircase (2, 13).
- `to_world(local) -> (x, y)` — the inverse, for completeness.
- `contains(world) -> bool` — delegates to the area's own bounds.

**Fallback when the live area is unreadable.** Prefer the live `Area`;
fall back to the atlas's stored bounds for that area id; if neither is
available, `origin = (0, 0)` and a `frame: "world"` marker on the event
saying local == world. Never invent an origin — an event whose frame is
unknown must say so (P1's honest-absence rule).

**`describe(world, player=None, frame=None) -> dict`** — the payload
every spatial event embeds:

```json
{
  "world": [10002, 8013],
  "local": [2, 13],
  "rel": [-4, 11],
  "dist": 11,
  "bearing": "SE",
  "frame": "area-020"
}
```

- `rel` — `world − player`, absent when no player position is available.
- `dist` — Chebyshev, the metric the whole codebase already uses for
  reach, ranges and budgets (`_chebyshev` in `steps.py`, `necro.py`).
  Same metric everywhere means log distances compare directly against
  `click_range`, `engage_radius`, `pickup_reach`.
- `bearing` — **screen** compass, not world axes. Screen-north is the
  world (−1, −1) diagonal (R219, user-confirmed): the projection is
  `sx = wx − wy`, `sy = wx + wy`, so decreasing both moves up-screen.
  Pure `−x` is NW and pure `−y` is NE. This is the operator's frame —
  the log should say "the staircase is SE of you" and mean what they see.

Bearing derivation belongs here, and `steps.py::_screen_north_point`
should be re-expressed in terms of this module rather than repeating the
convention — one definition of screen-north in the codebase.

## Testing

- `to_local`/`to_world` round-trip.
- The real Tower numbers: origin (10000, 8000), arrival → (6, 2),
  staircase → (2, 13), `dist` 11 — the case the plan exists for.
- All eight bearings, asserted against the screen projection, including
  that world `(−1, −1)` is `"N"` and world `(−1, 0)` is `"NW"`.
- Unreadable area → `frame: "world"`, local == world, and no invented
  origin.
- `_screen_north_point` still returns the same answers after being
  re-expressed (its existing tests must pass unchanged).

## Style and conventions

House style: comments carry the evidence. The bearing convention cites
R219 and says plainly that it is the screen frame, because an agent
reading `(-1,-1) == north` without that will "fix" it.

## Docs

Module docstring is the reference for the frames; the schema doc in P7
links to it.

## ADR expectation

**None** — the coordinate convention is recorded in P1's ADR as part of
the log format.

## Agent reminders

- Do not commit unless asked.
- Do not change the navigator, the atlas, or any pathing behavior — this
  phase is pure presentation.
- Do not suppress warnings or disable tests.
- Stop and report if the live `Area` origin turns out not to match the
  atlas room origins (that would be a real finding about the map layer,
  not a logging detail).
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

`MapFrame` and `describe` exist and are tested against the real Tower
geometry; screen-north has exactly one definition in the codebase; suite
green and ruff clean.
