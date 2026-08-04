# P1 — Transit and boss perception

Part of [plan.md](plan.md) (M6). Size: `sm`. Dependencies: none —
first phase. Parallelizable with P3. Live verification of everything
here rides P2's drills; this phase ships code + unit tests + a
read-only probe script.

## Scope

Teach perception two new things: **where the current area's exits are
and where they lead** (the traverse step's foundation), and **which
monster is the Countess and whether she is alive** (the endgame's
kill condition, R212 Q7). Plus the route's area-id constants.

Out of scope: any input-sending, the traverse step itself (P2), door
objects (deferred entirely, R212 Q3).

## Implementation

1. **RoomTile chain offsets** (`offsets.py`). Derive from BH
   `D2Structs.h` with file+line citations, the M2 discipline:
   `Room2.pRoomTiles`, `RoomTile.pRoom2` (destination), `RoomTile.
   pNext`, `RoomTile.nNum` (warp index). Cross-check against a second
   lineage (d2bs / D2Warden headers) as collision.py did — the two
   agreeing is the acceptance bar for trusting a struct BH alone
   documents thinly.
2. **Exit reader** (new `pd2bot/exits.py`, or `world.py` if it stays
   tiny). For the player's current area: walk the loaded Room2s
   (via Room1 → ROOM1_ROOM2, the existing constants), collect
   RoomTiles, resolve each destination level id, and return
   `LevelExit(position, dest_area)` records — position from the warp
   room's tiles (the staircase's world location). Defensive traversal
   rules apply verbatim (bounded walks, unreadable nodes skipped and
   counted — the unit-hash-table posture). **Caveat to handle**: only
   the loaded room neighbourhood is walkable in memory; distant exits
   may not be enumerable until approached. The reader returns what is
   loaded and says so; the traverse step (P2) compensates by routing
   toward the atlas-known exit position first (recorded on first
   discovery — see P2).
3. **Boss identity** (`units.py`). Extend monster reading with the BH
   `MonsterData` fields: the boss/champion/minion flag bits and
   `wUniqueNo` (super-unique id). Expose `Monster.is_super_unique`
   and the raw id; the Countess's own id is LEARNED live (P2's
   descent drill logs every super-unique seen; her id gets a named
   constant with the drill as provenance) — do not trust a wiki
   number. "Countess dead" then = her unit read with a dead mode, or
   absent from a scan that provably covers her chamber (both recorded;
   P4 consumes).
4. **Area constants** (`offsets.py`): `AREA_BLACK_MARSH = 6`,
   `AREA_FORGOTTEN_TOWER = 20`, `AREA_TOWER_CELLAR_1..5 = 21..25`,
   names into `AREA_NAMES`. Mark them provisional-until-P2 (Q1: the
   first traversal drill asserts each against the live read; the
   atlas file names are strong prior evidence).
5. **Probe script** (`drills/` or a `dump` flag): dump the current
   area's visible exits (position, destination, distance) and any
   super-uniques in perception — the read-only tool P2's drills and
   any future re-verification lean on. Follow the T-drill file
   conventions in `pd2bot/drill.py`.

## Testing

Unit tests against fixed byte buffers (the M2 pattern, see
`tests/test_units.py` / `test_world.py`): exit-chain decoding incl.
truncated/torn structures; boss-flag decoding; dedup of exits reported
by several rooms. No live assertions in pytest — the game is P2's.

## Docs

`perception.md`: an "exits" paragraph and a boss-identity paragraph in
the M5-extensions section (or a small M6 section). Defer polishing to
P6; land the facts now while fresh.

## Agent reminders

Do not commit unless asked. Do not expand scope (no door kinds, no
generic boss database — the Countess is the deliverable). Do not
suppress warnings or disable tests. Stop and report if BH's RoomTile
layout does not match reality (the fallback calibration survey is
designed in notes.md — do not improvise it without a user decision).
Report what changed, what was validated, deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

Offsets cited and cross-checked; exit reader + boss read implemented
with defensive traversal; area constants in; probe tool ready; unit
tests green; ruff clean. Live proof deferred to P2 by design.
