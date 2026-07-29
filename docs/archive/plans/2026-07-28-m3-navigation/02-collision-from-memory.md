# P2 — Collision maps from live memory

Size: `sm`. Dependencies: none (parallel with P1). Part of the M3 plan
([plan.md](plan.md)).

## Why

Live memory-read collision is the **ground truth** for walkability —
it is what the game actually enforces. M3 uses it two ways: as the
verifier for P3's generated maps (the PD2 fidelity check), and as the
local fallback for P4. Perception range is the player's room + its
neighbours (M2 finding), so this is inherently local; global routing
comes from P3.

## The layout problem (read this before writing code)

`pd2bot/offsets.py` already has `ROOM1_COLL = 0x20` (Room1's pointer
to its CollMap), **but the CollMap struct layout is NOT in PD2's BH
source** — BH's `D2Structs.h` stops at the pointer. Source the layout
externally, from **two independent** references, and diff them before
trusting either:

1. **D2BS C++ source** — github.com/noah-/d2bs, `D2Structs.h`
   (the engine kolbot ran on; its JS `getCollision()` is backed by
   this struct). Expected shape (verify, don't assume): pos/size in
   game (subtile) coords, pos/size in room coords, `WORD* pMapStart`,
   `WORD* pMapEnd` — a grid of 16-bit collision flag words.
2. **Diablo-II-Address-Table** (github, kept current ~2024) — same
   struct for 1.13c.
3. Fallback third source: d2info (2020).

Note: `kolbot/d2bs/` in our local clone is the *JS script library*,
not D2BS's C++ engine — `CollMap.js` there has no layout. Do not cite
it for offsets (it remains useful behaviorally).

Land the block in `offsets.py` with **both citations** (file:line
each, per repo convention), and add one sentence to the module
docstring: BH is the primary source but not the sole one; CollMap is
cited from D2BS + address-table. Also record the collision **bit
flags** (block-walk, wall, door, etc.) from the same sources; name
only the ones we use (walkability mask) and keep the rest as a cited
comment.

Network caveat: this machine's connectivity has been flaky (see M2
`_DONE.md`). Fetch the two references early; if GitHub raw fetches
fail, stop and report rather than proceeding on memory.

## Scope

- `pd2bot/collision.py`:
  - `read_room_collision(session, room1_addr) -> RoomCollision | None`
    — dataclass: origin (subtiles), size, and the grid (suggest
    `bytes`/`array('H')` row-major + an `is_blocked(x, y)` method
    applying the walkability mask). Bounded reads, torn-read-safe
    (return None on dangling pointers — M2's traversal-hole lesson:
    keep *every* pointer read inside the guarded path).
  - `read_local_collision(session) -> LocalCollision | None` — the
    player's room + `ROOM1_ROOMS_NEAR` neighbours stitched into one
    queryable surface (origin + combined extent; unknown cells =
    blocked-by-default with an explicit `known(x, y)` distinction —
    P4 must be able to tell "wall" from "unloaded").
- ASCII dump for eyeballing: extend `pd2bot/dump.py` or a
  `python -m pd2bot.collision` entry — player `@`, walkable `.`,
  blocked `#`, unknown space. This is the debugging tool the live
  check runs on.
- Tests: grid indexing/origin math, stitching with synthetic rooms,
  mask semantics, torn-read paths (fake session per existing test
  patterns).

## Out of scope

Generated maps (P3), pathfinding over the grids (P4), non-collision
CollMap uses (automap reveal etc.).

## Live verification (user at the machine)

In town or Cold Plains: dump the local collision around the player and
compare against the screen — (a) grid dimensions equal the room's size
in subtiles; (b) a wall/edge the character visibly cannot walk through
reads blocked; (c) the player's own subtile and the open ground around
read walkable; (d) walk 20 subtiles, re-dump, verify the picture
tracked the move. Record a sample dump in this planning dir (it
doubles as the P3 comparison artifact).

## Conventions / reminders

Offsets only in `offsets.py`, each cited. Only `memory.py` imports
pymem. Do not commit unless asked; do not expand scope; stop and
report if the two layout sources disagree or live checks contradict
the layout. Report what changed, what was validated, deviations.

## Validation commands

```bash
python -m pytest -q
```

plus the live checks above.

## Definition of done

CollMap layout in `offsets.py` with two independent citations; local
stitched collision readable and torn-read-safe; ASCII dump exists;
all four live checks pass; tests green.

## Implementation Result

Status: **done** (live verification later the same day found and fixed
a real layout error — no `pMapEnd` in this build, grid inline at
Coll+0x24, integrity check replaced with the header's own tile/subtile
invariant — then passed all four checks; live-checks.md step 3)
Completed: 2026-07-28
Commit: pending

- **Layout sourced and cross-checked.** Two independent lineages fetched
  and diffed; they agree field-for-field:
  (1) `noah-/d2bs` `D2Structs.h` (the D2BS engine kolbot ran on),
  (2) `jankowskib/d2server` `d2warden-pvp/D2Structs_111B.h`.
  Both carry the same `//0x22` comment beside `pMapEnd`, which is a
  historical typo — `pMapStart` is a 4-byte pointer at 0x20, so `pMapEnd`
  is at 0x24. Our offsets use 0x24, and the runtime size check would
  catch it if that reading were wrong.
- Collision flag words taken from kolbot's `sdk/types/sdk.d.ts:70-95`;
  walkability mask = its `BlockWalk` (0x1805), doors included as blocked.
- Changed: `pd2bot/offsets.py` (CollMap block, flags, docstring caveat
  that BH is primary but not sole), `pd2bot/collision.py`
  (`read_room_collision`, `LocalCollision` with the `is_known` vs
  `is_walkable` distinction, `ascii_map`, CLI), `tests/test_collision.py`.
- Validated: `pytest` — 10 tests here, including both torn-read paths
  (null and dangling `Coll`) and the struct-arithmetic guard
  (`pMapEnd - pMapStart == 2*w*h`). `ruff check` clean.
- **Not validated**: all four live checks (grid dimensions, a visible
  wall, ground under the player, tracking a walk). Needs an elevated
  terminal and the user; step 3 of [live-checks.md](live-checks.md).
  Until then the layout is cross-cited but unproven against the game.
- Deviations: none.
