# M1 — Perception + input spike: Python ↔ live PD2 client

**Work item:** M1 · **Size:** sm · **Depends on:** nothing ·
**Runs on:** the Windows machine with PD2 installed.

## Purpose

Prove plan B's two pillars against the real Season-13 offline client,
as cheaply as possible:

1. **Perception**: a Python process can attach to the running PD2 client
   and read correct live game state (player name, HP, position) using
   offsets derived from PD2's own BH source.
2. **Input**: a synthetic OS-level click makes the character visibly move.

Deliverable is *knowledge* captured in `spike-log.md` here, plus the
spike script(s) in `spike/` (throwaway quality allowed, but committed).

## Scope

- Minimal Python environment (verify/install Python 3.11+, venv, pymem).
- Fetch/inspect `BH/D2Ptrs.h` + `BH/D2Structs.h` from
  https://github.com/Project-Diablo-2/BH (main branch) and derive the
  read path for: player unit → name, HP, x/y position, current area.
  Cite the BH source lines for each offset in the spike log.
- Attach with pymem to a client the **user launched normally via
  PD2Launcher** (we attach, never launch), with the offline SP
  character in a game.
- Read the values; verify correctness by having the user act in-game
  (walk → position changes; take a hit / drink potion → HP changes).
- One SendInput click (ctypes) at a screen coordinate → character
  walks there. Window assumed foreground, windowed mode.

## Out of scope

- Any real package structure, abstractions, or config system (M2+).
- Monsters/items/map-seed reading (M2). Pathfinding (M3). Menus (M4).
- Robustness: hardcoding this season's offsets in the spike is fine.

## Preconditions

1. PD2 launched by the user via PD2Launcher, offline single player,
   character `MaqiuDoubing` standing in town, windowed mode.
2. Python 3.11+ on PATH (check `python --version`; if missing, install
   via `winget install Python.Python.3.12`).
3. This repo cloned; internet access for `pip install pymem` and
   fetching BH headers.

## Steps

1. Environment: create `spike/` dir, venv, `pip install pymem`. Record
   exact versions in the spike log.
2. Offset derivation: from BH's `D2Ptrs.h`, note the player-unit
   pointer (D2CLIENT module-relative) and from `D2Structs.h` the
   `UnitAny` layout (position, pPlayerData→szName, pStats or
   hp-by-stat). Document the chain in the spike log with file/line
   citations. Note: stats may require walking the statlist — if HP via
   statlist is fiddly, position + name + level suffice for the spike;
   log the decision.
3. Attach: pymem to the `Game.exe` process; enumerate modules; compute
   absolute addresses (module base + offset). Handle the 32-bit target
   from 64-bit Python (pymem supports this; verify — if it fights back,
   use 32-bit Python and log it).
4. Read loop: print name/position(/HP) at ~10 Hz while the user walks
   around; confirm values track reality.
5. Input: ctypes SendInput — move cursor to a ground point, click;
   confirm the character walks. (Coordinate→world mapping is NOT
   required — any visible movement passes; screen↔world projection is
   M3's problem.)
6. Record everything in `spike-log.md` as you go: versions, offsets
   used + citations, code snippets, what worked, what surprised.

## Success tiers

- **T0** — pymem attaches, modules enumerated.
- **T1** — static reads correct (name, level).
- **T2** — dynamic reads track live changes (position; HP if statlist
  cooperates).
- **T3** — synthetic click visibly moves the character.

**T2 + T3 = spike passes** (both pillars proven). T2 without T3 or vice
versa = partial; diagnose the failing pillar before concluding.

## Review gate: END OF M1 — mandatory stop

Report: tier reached, spike log path, surprises, and whether M2
planning can proceed on this foundation. Decision is the user's. Also
due at this gate: the language/stack **ADR** (docs/adr/) and the
cycle's `/teach` step.

## Agent reminders

- Do not commit unless the user asks.
- Do not expand scope (no monsters, no pathing, no abstractions).
- Never enter or store the user's PD2 online credentials anywhere.
- Do not edit anything under `kolbot/`.
- Time-box: ~half a day; a precise failure diagnosis is a successful
  spike outcome.
- Stop and report if blocked by ambiguity or unexpected design issues.

## Validation

Empirical only: values printed match in-game reality as the user acts;
click produces movement. Capture terminal output samples into the log.

## Definition of done

`spike-log.md` in this planning directory (steps, offsets + citations,
tier reached, surprises, recommendation); spike script(s) in `spike/`;
review-gate conversation held.
