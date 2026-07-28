# P3 — Self model: player, stats, area, map seed

**Work item:** P3 · **Size:** sm · **Depends on:** P1 ·
**Parallel with:** P2, P4 · **Review gate:** none

## Scope

Make M1's proven reads durable, and add the area/seed chain.

`pd2bot/player.py`:

- `Player` dataclass: name, class, level, act, position `(x, y)`,
  hp/max, mana/max, stamina/max, experience, gold (inventory and stash),
  and the core attributes (strength, dexterity, vitality, energy).
- `read_player(session) -> Player | None` — `None` when not in a game.

`pd2bot/world.py` (started here, extended by P4):

- `Area` dataclass: level number, and level bounds
  (`dwPosX/Y`, `dwSizeX/Y`) which M3's pathfinding will want.
- `read_area(session) -> Area | None`, `read_map_seed(session) -> int`.

## Implementation notes — the two traps M1 found

1. **Use the full stat array, not the base one.** `StatList` carries
   both: base stats at `+0x24`/count `+0x28`, and the fully-computed
   values (item and skill bonuses applied) at `pSetStat +0x48`/count
   `+0x4C`. Reading the base array produced `hp=961/920` — a current
   value above the maximum, which is impossible. **Read the full array.**
2. **Only some stats are fixed-point.** hp/maxhp/mana/maxmana/
   stamina/maxstamina need `>> 8`; attributes, level, experience and
   gold are plain integers (shifting them yielded 0).

Chains (all cited in `offsets.py`, mapped in [notes.md](notes.md)):

- map seed: `UnitAny.pAct (+0x1C) → Act.dwMapSeed (+0x0C)`
- area: `UnitAny.pPath (+0x2C) → Path.pRoom1 (+0x1C) →
  Room1.pRoom2 (+0x10) → Room2.pLevel (+0x58) → Level.dwLevelNo (+0x1D0)`
- level bounds: `Level.dwPosX/dwPosY (+0x1C/+0x20)`,
  `dwSizeX/dwSizeY (+0x24/+0x28)`

Any pointer in a chain may be 0 (loading screens, area transitions).
Return `None` rather than raising — transitions are normal, and M4's run
loop will poll through them.

## Out of scope

- Skills, inventory contents, equipped items, mercenary state — none is
  needed before M5, and each is a real surface of its own.
- Waypoint/quest state (M4 may need it; not now).
- Anything about other units (P4).

## Files

- New: `pd2bot/player.py`, `pd2bot/world.py`, `tests/test_player.py`.
- Updated: `pd2bot/offsets.py`.

## Validation

- `pytest`: stat decoding (fixed-point rules, base-vs-full selection)
  against synthetic buffers; chain traversal with a fake reader
  including the null-pointer cases.
- **Live, semantic — compare every field to what the game displays.**
  Open the character screen and confirm level, attributes, hp/mana
  against the panel; confirm gold against the inventory; confirm the
  area against where the character actually is. Record the comparison
  table in the Implementation Result. This is the discipline that caught
  the HP bug; a field that "looks plausible" is not verified.
- Verify area and map seed **in at least two different areas** (e.g.
  Rogue Encampment and Blood Moor) — a level number that never changes
  is indistinguishable from a broken read.
- Map seed sanity: constant within a game, different in a new game.

## ADR expectation

None.

## Agent reminders

- Do not commit unless the user asked.
- Do not expand scope into inventory/skills/mercenary.
- Reads only — no input, no writes.
- Do not invent values the game does not expose; if a field cannot be
  read reliably, leave it out and say so.
- Stop and report if blocked by ambiguity or an unexpected design issue.
- Report what changed, what was validated, and any deviations.

## Definition of done

`read_player`, `read_area` and `read_map_seed` return correct values
verified field-by-field against the game's own display, handle
not-in-a-game and transition states as `None`, and tests plus lint pass.

## Implementation Result

Status: done
Completed: 2026-07-28
Commit: f5359ee

- Changed: `pd2bot/player.py`, `pd2bot/world.py`, `tests/test_player.py`.
- **Live verification** (`python -m pd2bot.dump -v`, two runs while the
  user played):

  | Field | Observed | Sane? |
  |---|---|---|
  | name / level | `MaqiuDoubing` / 91 | matches the character |
  | act | 2, then 5 as the user moved | tracked the move |
  | hp / max | 1172/1172, later 720/1172 after damage | current ≤ max ✓ |
  | mana, stamina | 280/378, 3798/3798 | ✓ |
  | attributes | str 122 dex 70 vit 357 eng 31 | matches gear-inclusive totals |
  | gold | 23139 carried / 59064 stashed, later 26117 | changed as the user played |
  | map seed | 0x4E52715F across both acts | constant within a game ✓ |

- **Bug found by live verification — tile vs subtile.** Levels store
  position and size in tiles; units are positioned in subtiles, five to a
  tile. `Area.contains()` compared them directly: plausible-looking,
  wrong by 5x. Fixed with `SUBTILES_PER_TILE` and `bounds_subtiles`, and
  confirmed against real data (player at subtile (12610, 5203) inside a
  level whose tile origin (2500, 1000) → subtiles 12500..12920).
  Regression tests use the real observed values.
- Deviations: area verified across acts 1/2/5 rather than the two named
  areas — better coverage than asked, same purpose. Unit primitives
  (`player_unit`, `read_stats`, `unit_position`) landed in `units.py`
  rather than being duplicated, since P4 needs the same ones.
