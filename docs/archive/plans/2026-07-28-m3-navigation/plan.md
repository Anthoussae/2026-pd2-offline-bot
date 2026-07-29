---
kind: plan
size: md
depth: implementation
status: done
repo: 2026-pd2-offline-bot
created: 2026-07-28
completed: 2026-07-28
commit: pending
adr: expected
---

# M3 — Navigation

## Size and why

`md`: five phases, each `sm` and executable by one agent, but with a
hard safety boundary (P1 introduces the first input-sending code), an
external build dependency (P3's map generator), and live-verification
checkpoints that benefit from phase seams. Roadmap parent:
[../2026-07-28-bot-from-scratch/plan.md](../2026-07-28-bot-from-scratch/plan.md)
(M3 row).

## Goal

The bot can walk. Concretely: given the live PD2 client in a game, the
bot computes a path from the player's position to a target point in the
current area using generated map data cross-checked against live
memory-read collision, and follows it with gated synthetic clicks —
reliably, without ever sending input when a UI panel or another window
would swallow it.

## Acceptance criteria

- **Input gate**: no code path can send input to the game without
  passing `uistate.can_act()` **and** a game-window-is-foreground check
  in the same guard. This is structural (one gated send path), not a
  convention. The M1 "Save and Exit Game" incident class is closed.
- **Collision**: `CollMap` layout landed in `offsets.py` with two
  independent non-BH citations; live grids read for the player's room
  neighbourhood; verified against visible walls in-game.
- **Map knowledge** *(re-scoped at the P3 gate, 2026-07-28 — user
  decision, see notes.md)*: whole-area walkability comes from the
  **explored-map atlas** — live-read room grids persisted per (seed,
  difficulty, area) and merged on every sighting; a survey walk of Cold
  Plains populates it; the atlas survives a game restart (same seed →
  same file). The original criterion (generator child process + PD2
  fidelity check) is deferred future work: built, blocked, documented
  in generator-status.md.
- **Walking**: from the Cold Plains waypoint, the bot walks to a
  point ≥ 60 subtiles away and back, 5/5 attempts, with stuck
  detection and re-pathing demonstrated at least once (forced or
  natural).
- Unit tests for all pure logic (A*, RLE decode, projection math,
  path simplification); `python -m pytest -q` green.
- Map-knowledge ADR written (roadmap ADR (b) is due at M3).

## Scope boundaries

**In**: input layer (mouse move/click, keypress), world→screen
projection, CollMap reading, generator integration + fidelity check,
A*, within-area walk-to with stuck handling.

**Out** (deferred): area transitions/waypoints/stairs (M4/M6), menus
and out-of-game clicking (M4), combat and clearing-while-stuck (M5),
doors/barrels (M4+), background/PostMessage input (future work),
stamina/walk-run management beyond "leave the game in run mode".

## Discovery summary

See [notes.md](notes.md). Key facts: M2's `can_act()` exists and its
docstring assigns the foreground check to this milestone. `ROOM1_COLL =
0x20` is staged but the pointed-to `CollMap` layout is **not in BH** —
source from D2BS C++ `D2Structs.h` + Diablo-II-Address-Table (or
d2info), two citations minimum. Map generator: **soarqin/d2mapapi_mod**
(fork of jcageman/d2mapapi) — 32-bit C++/CMake, supports 1.13c,
`piped` variant speaks JSON over stdio with RLE-encoded collision;
also emits exits/NPCs/objects (useful from M4 on). Fidelity risk:
generators emit vanilla layouts, PD2 ships `pd2maps.mpq`; mitigation
candidates = point the generator at the ProjectD2 data dir, else
per-area vanilla-equivalence verdicts from the fidelity check.
Kolbot's `Pather.js` mined for the follow-loop shape (node radius,
fail-counted re-path with shorter spacing, nearest-walkable
adjustment).

## Files/modules expected to change

New: `pd2bot/window.py` (game window tracking/foreground),
`pd2bot/input.py` (gated SendInput), `pd2bot/screen.py` (projection —
or fold into input.py if small), `pd2bot/collision.py` (CollMap
reading), `pd2bot/mapdata.py` (generator client + decode),
`pd2bot/pathing.py` (A* + path ops), `pd2bot/navigate.py` (walk-to
loop), `tests/test_*` for each, `tools/` or `pd2bot/` CLI entry for
nav demos (follow `pd2bot.dump` precedent: module `__main__`-style CLI
via `python -m`).

Changed: `pd2bot/offsets.py` (CollMap block + docstring caveat on
non-BH sources), `README.md` (generator dependency + build/run),
`docs/architecture/` (new `navigation.md`), roadmap plan M3 row.

## Documentation expected to change

- `docs/architecture/navigation.md` — input gate design, projection,
  collision reading, generator protocol, A*/follow loop.
- `docs/adr/` — map-knowledge ADR (generated maps + live verification
  hybrid); write during P3 when the evidence is in hand.
- `README.md` — d2mapapi_mod build/placement, new CLI demos.
- `docs/learning/` — teach explainer + glossary (P5).
- `offsets.py` module docstring — BH is no longer the *sole* source.

## Key decisions (made in planning, see notes.md Questions)

1. Collision-from-memory lands **before** the generator (it is the
   ground truth the fidelity check compares against).
2. Generator choice pinned to d2mapapi_mod's piped variant as first
   candidate; acceptance is capability-based, so falling back to the
   httpd variant or jcageman original is a P3-internal call.
3. The input gate lives **inside** the send path (`GatedInput.click()`
   checks and refuses; there is no public unguarded send). Menu-scoped
   input for out-of-game states is M4's problem and will be a separate
   explicit method with its own narrower guard, not a bypass.
4. A* per-subtile over stitched grids first; room-graph optimization
   only if measured slow.
5. M3 walking is within-area only.

## Validation strategy

Per repo convention: pytest for pure logic; live verification on this
Windows machine against the running client for everything that touches
reality, comparing every readout against what the game displays. Live
checks are listed per phase; the "compare against the game's own
display/behavior" rule caught four semantic bugs in M1/M2 and is
mandatory, not optional. Input-sending live tests require the user at
the machine (they can yank the mouse).

## Phases

| Phase | Size | Summary | Files/modules | Review gate | Notes |
|---|---|---|---|---|---|
| P1 | sm | Gated input layer: window tracking, foreground, single gated send path, projection, one gated walk-click live test | `window.py`, `input.py`, `screen.py`, tests | None (live test is inherently supervised) | Independent of P2 |
| P2 | sm | CollMap: source layout (2 citations), read + stitch room grids, ASCII dump, live wall check | `offsets.py`, `collision.py`, tests | None | Independent of P1 |
| P3 | sm | Generator: build d2mapapi_mod, piped client, RLE decode, **PD2 fidelity check**, map-knowledge ADR | `mapdata.py`, `vendor/` or sibling checkout, tests | End-of-phase: fidelity verdict + ADR reviewed by user | Needs P2 |
| P4 | sm | A* + walk-to: pathfinding, simplification, follow loop w/ stuck detection, Cold Plains 5/5 walk | `pathing.py`, `navigate.py`, tests | None | Needs P1+P2+P3 |
| P5 | sm | Cleanup, docs, README, teach step, TODO/debug sweep; opportunistic: ruff + ground-item live check (M2 leftovers) | docs, all | End-of-milestone review | — |

P1 and P2 are parallelizable. P3's fidelity verdict is the milestone's
main unknown — surface it to the user at the P3 gate rather than
silently accepting vanilla maps.

## ADR expectations

`expected`: map-knowledge ADR at P3 (roadmap commitment). `possible`:
gated-input ADR at P1 if the design ends up decision-like (single
gate, refusal semantics, no bypass) rather than obvious — the
implementer should draft it only if there were real alternatives to
argue against.

## Implementation log convention

Implementation is recorded by `yona-implement` in `_DONE.md` in this
directory when the milestone completes; phase files may gain short
`Implementation Result` sections as phases land. Do not rename files.
