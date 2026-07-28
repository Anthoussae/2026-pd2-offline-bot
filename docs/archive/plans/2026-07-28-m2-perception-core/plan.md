---
kind: plan
size: md
depth: implementation
status: done
completed: 2026-07-28
commit: e859128
repo: 2026-pd2-offline-bot
created: 2026-07-28
adr: possible
---

# M2 — Perception core

Milestone M2 of the roadmap
[`docs/plans/2026-07-28-bot-from-scratch/plan.md`](../2026-07-28-bot-from-scratch/plan.md),
which required its own planning pass once M1's findings existed.

## Size and why

`md` / implementation: five `sm` phases. One phase (P2, UI state) is
genuinely uncertain and carries a review gate; the rest is
well-understood work whose structure chains are already mapped in
[notes.md](notes.md).

## Goal

A Python package `pd2bot/` — the first durable code in this repo —
exposing a coherent snapshot of live game state: player, current area,
map seed, nearby monsters and ground items, and UI/in-game status. Good
enough that M3 (navigation) and M4 (game cycle) never touch raw offsets.

## Acceptance criteria

- `python -m pd2bot.dump` prints a full, correct snapshot of the live
  game, and every field has been verified against what the game visibly
  displays (see Validation).
- `is_in_game()` and `ui_state()` correctly distinguish: menus,
  in-game with no panel, and in-game with the ESC menu / inventory /
  shop open.
- Monsters and ground items in and around the player's room are
  enumerated with identity, position, and (monsters) hp fraction and
  champ/boss/minion class.
- Map seed and current area (level number) are read correctly, verified
  across at least two different areas.
- All offsets live in one module, each citing its BH source line.
- `ruff check` and `pytest` pass.

## Scope boundaries

- **Perception only. No input, no movement, no decisions.** (M3+.)
- Not in scope: monster resistances/immunities (user decision — assume
  the character and hireling can handle any resistance and that all
  enemies are defeatable); pathfinding and collision maps (M3); item
  name/affix resolution beyond type + quality (M5 may revisit);
  caching or diffing of snapshots (measure first, optimise later).

## Discovery summary

See [notes.md](notes.md). All structure chains needed are documented in
Project-Diablo-2/BH's headers and reachable from the player unit that
M1 already verified live: map seed via `Act.dwMapSeed`, current area via
`Path→Room1→Room2→Level.dwLevelNo`, and units via room traversal
(`Room1.pUnitFirst` → `UnitAny.pRoomNext`, plus `pRoomsNear`).

Two things BH cannot supply, because it runs in-process and calls game
functions instead: D2's unit hash table (avoided — room traversal
replaces it) and the `CollMap` layout (an M3 problem, sourced
elsewhere). **UI state is the open problem** and is P2's whole job.

## Architecture decisions (user-approved)

- Package `pd2bot/` at the repo root; `spike/` stays untouched as the
  historical record of M1.
- `pyproject.toml` + repo-root `.venv` on Python 3.12; **ruff** for
  lint/format; **pytest** for tests.
- State model = plain dataclasses, read fresh each tick, no caching.
- Unit enumeration by room traversal, not by locating the unit hash
  table.
- UI-state discovery: parse `GetUiVar_I`'s instruction bytes to find the
  UI array at runtime; differential (menu open vs closed) scan as
  documented fallback and cross-check.

## Files and docs expected to change

- New: `pyproject.toml`, `pd2bot/*.py`, `tests/*.py`,
  `docs/architecture/perception.md`.
- Updated: `README.md` (how to set up the venv and run the dump tool),
  `.gitignore` if needed.
- `docs/learning/` gains the M2 explainer (see P5).

## ADR expectations

`possible`: if P2's runtime code-parse technique works, record it — it
is an unusual choice with lasting seasonal-maintenance consequences.
Straightforward struct reading needs no ADR.

## Validation strategy

Two layers, because a live game process cannot be unit-tested:

1. **Automated**: `pytest` over pure logic (stat decoding, fixed-point
   rules, room/unit traversal against synthetic buffers, UI-state
   parsing given recorded bytes) + `ruff check`.
2. **Live, semantic**: `python -m pd2bot.dump` against the running
   client, with each field compared to what the game displays on screen.
   **This is a process rule, not a good intention** — M1 read a
   structurally correct but semantically wrong max-HP (base vs
   fully-computed stat arrays) that only a human sanity check caught.
   Record the comparison in each phase's Implementation Result.

Live checks require the client running and **Administrator** (PD2 runs
elevated; unelevated `OpenProcess` is denied).

## Phases

| Phase | Size | Summary | Files/modules | Review gate |
|---|---|---|---|---|
| P1 | sm | Package skeleton + session layer (attach, elevation check, module base, typed reads) and the single offsets module | [01-package-and-session.md](01-package-and-session.md) | None |
| P2 | sm | UI + game state detection — the blocking piece for all later input work | [02-ui-state.md](02-ui-state.md) | **Yes** |
| P3 | sm | Self model: player, stats, current area, map seed | [03-player-and-area.md](03-player-and-area.md) | None |
| P4 | sm | World model: monsters and ground items via room traversal | [04-world-units.md](04-world-units.md) | None |
| P5 | sm | Snapshot API, dump CLI, tests, architecture docs, cleanup, teach step | [05-snapshot-and-docs.md](05-snapshot-and-docs.md) | None |

**Order and parallelism:** P1 first. P2 next because it is the only
uncertain piece and it blocks M3/M4 — fail fast. P3 and P4 are
independent of P2 and of each other once P1 lands. P5 last.

## Conventions

- Every offset lives in `pd2bot/offsets.py` with a comment citing its
  BH source file and line. Never inline a magic number elsewhere.
- Reads are passive and safe; this milestone writes nothing to the
  game's memory and sends no input.
- Where a value can be wrong-but-plausible, prefer reading what the game
  computes over recomputing it ourselves.
