# Notes — M2 perception core (planning)

## Context

Milestone M2 of `docs/plans/2026-07-28-bot-from-scratch/plan.md`, which
flagged it as needing its own planning pass fed by M1's findings.

M1 (spike, passed at T3 — see
`../2026-07-28-bot-from-scratch/spike-log.md`) established:

- pymem attaches to the elevated PD2 client; 64-bit Python reads the
  32-bit process; module base for D2Client.dll located at runtime.
- Player unit chain verified live: `D2Client+0x11BBFC → UnitAny`;
  name/act/position/stats all read correctly.
- **Use the full stat array** (`StatList+0x48`/count `+0x4C`), not the
  base array; only hp/mana/stamina are fixed-point (`>>8`).
- Administrator is mandatory.
- **Blocking requirement for M2**: a readable UI-state indicator.
  BH `Constants.h:65-89` defines the enum (UI_GAME 0x00,
  UI_ESCMENU_MAIN 0x09, UI_NPCSHOP 0x0C, UI_WPMENU 0x14, ...) but
  `D2Ptrs.h:156 GetUiVar_I` is a *function*, so out-of-process we must
  find the underlying array (or another readable signal).
- Verify values semantically, not just structurally (the base/full stat
  bug produced an impossible 961/920 HP that only a human noticed).

## Goal for M2

A real Python package (first durable code in the repo) that exposes a
coherent, tested snapshot of live game state: player, monsters, ground
items, area, map seed, and UI/in-game status — good enough for M3
(navigation) and M4 (game cycle) to build on without touching raw
offsets.

## Discovery log

### Structure chains available from BH headers (2026-07-28 fetch)

Everything below is reachable from the already-verified player unit.

- **Map seed**: `UnitAny.pAct` (+0x1C) → `Act.dwMapSeed` (+0x0C).
  (`Act` also has `pRoom1` +0x10, `dwAct` +0x14, `pMisc` +0x48.)
- **Current area**: `UnitAny.pPath` (+0x2C) → `Path.pRoom1` (+0x1C) →
  `Room1.pRoom2` (+0x10) → `Room2.pLevel` (+0x58) →
  `Level.dwLevelNo` (+0x1D0). `Level` also carries dwPosX/Y +0x1C/0x20
  and dwSizeX/Y +0x24/0x28.
- **Unit enumeration (monsters, ground items)**: rooms hold their units.
  `Room1.pUnitFirst` (+0x74) → walk `UnitAny.pRoomNext` (+0xE4). For the
  surrounding area, `Room1.pRoomsNear` (+0x00) with `dwRoomsNear`
  (+0x24). This avoids needing D2's unit hash table (**which BH does not
  expose** — BH runs in-process and calls game functions instead).
- **Monsters**: `UnitAny.pMonsterData` (+0x14 union) → `MonsterData`
  (D2Structs.h:610): `pMonStatsTxt` +0x00, `NameSeed` +0x14, flag
  bitfield +0x16 (`fNormal/fChamp/fBoss/fMinion`), `anEnchants[9]`
  +0x1C. Monster HP/resistances come from the same StatList mechanism
  already proven on the player.
- **Ground items**: `UnitAny.pItemData` (+0x14 union) → `ItemData`
  (D2Structs.h:510): `dwQuality` +0x00, `dwItemFlags` +0x0C,
  `dwFileIndex` +0x28, `dwItemLevel` +0x2C, prefix/suffix words,
  `ItemLocation` +0x45 (0xFF = on ground/body). `UnitAny.dwTxtFileNo`
  (+0x04) identifies the item type.
- **Live collision** (M3's fallback source, noted here while we're in
  the headers): `Room1.Coll` (+0x20) → `CollMap` — but **BH does not
  define the CollMap layout**, so M3 will need another source (kolbot's
  d2bs source, Diablo-II-Address-Table, d2info).

### Open problem: UI state (M1's blocking finding)

`Constants.h:65-89` gives the enum; `D2Ptrs.h:156` gives
`GetUiVar_I` as a *function* at D2Client+0xBE400 (1.13c slot), not a
variable, and there is no `VARPTR` for the underlying array. Candidate
approaches:

1. **Parse the function's own code.** Read the instruction bytes at
   D2Client+0xBE400 out-of-process and extract the array address from
   the indexed-load instruction. Small, deterministic, self-documenting,
   and re-derivable each season — the address is discovered at runtime
   rather than hardcoded.
2. **Differential memory scan.** Snapshot candidate regions with a menu
   closed vs open and diff. Empirical, needs human cooperation, yields a
   hardcoded address that must be re-found each patch.
3. **Proxy signals** (e.g. inferring from other observable state).
   Weakest; fallback only.

### Beyond BH

Two things BH cannot supply because it runs in-process: the unit hash
table (avoidable — use room traversal) and the CollMap layout (M3
problem). Worth recording as a general limit of the BH-as-reference
strategy.

## Questions

(to be added)

## User answers / scope changes

### 2026-07-28 — confirmation round

- Q1 package `pd2bot/`, `spike/` untouched: **yes**
- Q2 `pyproject.toml` + repo-root `.venv`, Python 3.12: **yes**
- Q3 pytest for pure logic + manual CLI dump tool for live checks: **yes**
- Q4 ruff for lint/format: **yes**
- Q5 dataclasses, fresh read per tick, no caching: **yes**
- Q6 room traversal for unit enumeration: **yes**
- Q7 monster resistances/immunities: **NO — out of scope.** User: assume
  the character/hireling has countermeasures to every resistance type
  and that all enemies are defeatable, even in Hell. Monster model
  therefore carries identity, position, hp fraction and
  normal/champ/boss/minion class only. (Revisit only if a run script
  ever needs to *skip* a monster; recorded under future work.)
- Q9 UI-state discovery: **code-parse first** (read `GetUiVar_I`'s
  instruction bytes, extract the array address at runtime),
  differential menu-open/closed scan as documented fallback and
  cross-check; if both fail, stop and report rather than guess.

### 2026-07-28 — process note from user

Run the agent-toolkit `/teach` skill for M1 and M2 "at the next logical
convenient point". Status: **M1's teach artifact already exists** —
`docs/learning/2026-07-28-reading-a-program-from-outside.md` plus five
glossary entries, written when M1 closed (commit 240db30). M2's teach
step is an explicit deliverable of this plan's final phase.

## Future work ideas

- Monster resistances/immunities (dropped from M2 per Q7) — only if a
  run script ever needs to skip rather than fight something.
- Caching/diffing layer over snapshots, if per-tick full reads ever
  prove too slow (measure before optimising).
- Monster enchantment decoding (`MonsterData.anEnchants[9]`) — display
  and danger-assessment nicety, not needed to fight.
- Item name/affix resolution (prefix/suffix word IDs → readable names)
  needs the game's string tables; M5 pickit may want it, and a rule
  language over `dwTxtFileNo` + quality may suffice without it.
