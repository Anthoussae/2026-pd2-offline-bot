# Notes — M3 navigation

## Initial understanding and goals

M3 from the roadmap (`docs/plans/2026-07-28-bot-from-scratch/plan.md`):
navigation — the input layer, a map-generation service (d2mapapi-style),
A*, walk-to/path-following, and the **PD2 map fidelity check**. First
milestone that *sends input*; everything before it only read.

User constraints restated at planning kickoff (2026-07-28):

1. **CollMap layout is NOT in PD2's BH source.** BH's `D2Structs.h`
   gives `Room1.Coll` as a pointer (we already carry `ROOM1_COLL =
   0x20`), but not the pointed-to `CollMap` struct. Source it from
   D2BS's C++ source (the engine under kolbot — its own `D2Structs.h`),
   the Diablo-II-Address-Table repo, or d2info, and cross-check at
   least two of them before trusting it.
2. **Every input send gates on `pd2bot.uistate.can_act()` AND the game
   window being foreground.** That pairing is the codified lesson of
   the M1 "Save and Exit Game" incident (click delivered while the ESC
   menu was open → activated Save and Exit). The perception side
   (`can_act`) exists; the foreground check explicitly belongs to M3's
   input layer (see the docstring on `uistate.can_act`).

## Current state (what M3 builds on)

- `pd2bot/` (M2, commit `f5359ee`): `GameSession` typed reads;
  `Perception`/`GameSnapshot`; `can_act()`; player position in
  **subtiles** (`Path` @ `UNIT_PATH`, WORD x/y); `Area` with
  tile-vs-subtile conversion (`SUBTILES_PER_TILE = 5`); `read_map_seed`.
- `offsets.py` already has the Room chain: `PATH_ROOM1`, `ROOM1_ROOM2`,
  `ROOM1_COLL = 0x20` (flagged for M3), `ROOM1_ROOMS_NEAR`/`_COUNT`,
  `ROOM2_LEVEL`, level pos/size. Citation convention: every offset
  cites its source file:line.
- `spike/probe_click.py` + `spike/probe_foreground.py` (M1): proven
  primitives for window lookup by PID, client-rect → screen coords,
  `SetForegroundWindow` + verify via `GetForegroundWindow`, and
  `SendInput` mouse click. Throwaway quality, but the Win32 recipes work.
- Perception range is the player's room + neighbours (M2 log). Global
  routing therefore needs generated maps; live collision covers only
  the local neighbourhood.

## Discovery log

### The "Save and Exit Game" incident, canonically

`docs/plans/2026-07-28-bot-from-scratch/spike-log.md` (fullest account),
ADR `2026-07-28-runtime-offset-discovery.md`, `uistate.py` module
docstring, `tests/test_uistate.py::test_esc_menu_blocks_input`. The
foreground half is not yet enforced anywhere — M1's probe checks it
inline, but no reusable code does. M3's input layer is where the pairing
becomes structural (single gated send-path, no bypass).

### CollMap layout candidates (user constraint 1)

`kolbot/d2bs/` in our clone is the *script* library (JS), not D2BS's
C++ engine source — `CollMap.js` there is a JS-level cache over the
engine's `getCollision()`, useful behaviorally but layout-free. The
layout sources are external:

- **D2BS C++ source** (github.com/noah-/d2bs → `D2Structs.h`): has
  `CollMap` — pos/size in game (subtile) coords, pos/size in room
  coords, `WORD* pMapStart/pMapEnd` (the collision grid), plus the
  collision bit flags (block-walk, block-line-of-sight, wall, door...).
- **Diablo-II-Address-Table** (community, 2024): same structs kept
  current for 1.13c; second citation.
- **d2info** (2020): third option.

Plan: fetch two independently, diff the struct, land it in `offsets.py`
with both citations, then **verify live** (grid dimensions must equal
room size in subtiles; a wall the player visibly cannot cross must read
as blocked; the tile under the player must read walkable).

### Map generation (d2mapapi and kin)

Roadmap notes (2026-07-28 freshness check): jcageman/d2mapapi (pushed
2025-11) — runs real game code headlessly, layout + collision per
(seed, difficulty, area). Known variants: the original REST-style
service and a piped-stdio fork used by the koolo D2R bot. Either way it
is a child process the Python side talks to; it needs a D2 1.13c
install to load game data (we have one). Web check pending — pin the
exact variant + build story during P3, not now (network on this machine
has been flaky; see M2 caveats).

**Fidelity risk** (explicit milestone task, roadmap QB): generators
emit *vanilla* 1.13c layouts; PD2 modifies some maps (`pd2maps.mpq`).
The check: for areas we care about (Cold Plains first, Tower later),
compare generated collision against live memory-read collision room by
room while walking. Memory-read collision is the ground truth — it is
what the game actually enforces.

### Kolbot behavioral reference (mined this round)

`Pather.js` `move()`/`walkTo()` loop, distilled: path = node list;
walk node to node with a per-node arrival radius (2-4 subtiles,
tighter after failures); on failure, re-path with *shorter* node
spacing and count failures; adjust unreachable nodes to nearest
walkable within a radius; doors/barrels handled en route (M4+ for us);
stamina managed (walk vs run). Stuck detection = "position stopped
changing while a move is pending", answered by re-click, then re-path,
then (their case) clearing mobs — ours can defer clearing to M5.

### Input mechanics (facts to build on)

- D2 click-to-move: left-click on world ground; character walks toward
  the click. Held-click continuous movement exists but discrete clicks
  suffice for node following (kolbot does discrete `clickMap` per node).
- We must project **world subtile → screen pixel**: D2's isometric
  camera centers on the player; one subtile ≈ 16px horizontal, 8px
  vertical on screen: `dx_screen = (dx - dy) * 16`, `dy_screen =
  (dx + dy) * 8` relative to screen center, where dx,dy are subtile
  deltas from the player. Must be verified empirically in P1 (click a
  known offset, confirm the character lands where predicted) — treat
  the formula as a hypothesis, not a fact.
- Fixed windowed mode at an agreed resolution is already the approved
  convention (roadmap decision 3). M1 probes read the client rect at
  runtime, which stays the right move (no hardcoded resolution).

## Questions

Triage: the big architecture decisions (stack, hybrid map knowledge,
input approach) were already user-approved in the roadmap round. The
remaining choices are implementation-level; suggested answers below are
adopted as working assumptions (autonomous session) — flag disagreement
and the plan adjusts.

| # | Question | Context | Suggested answer (adopted) |
|---|---|---|---|
| Q1 | Build order: collision-from-memory before map generation? | Live CollMap is ground truth and the verifier for generated maps; without it the fidelity check has nothing to compare against. | Yes — P2 collision, P3 generator |
| Q2 | Which map generator variant? | REST vs piped fork; both wrap the same game code. Network flakiness on this machine makes "clone and evaluate what builds" the honest plan. | Decide in P3; acceptance = (seed,difficulty,area)→grid from Python, not which wrapper |
| Q3 | Where does the input gate live? | A single `Input` class whose send path checks can_act()+foreground itself, vs trusting callers to check. | Gate inside the send path; no public unguarded send. Optional `unsafe_` menu-scoped variant deferred to M4 (menus legitimately need clicks while not in-game) |
| Q4 | A* granularity | Per-subtile A* over stitched room grids vs room-graph-then-local. Cold Plains areas are small; per-subtile is simplest and testable pure-Python. | Per-subtile A* first; optimize only if measured slow |
| Q5 | Walk-to scope | Full travel (waypoints, area transitions) vs within-area walking only? Roadmap gives area transitions to M4/M6. | M3 = within current area: walk from A to B reliably. Area transitions out of scope |

## User answers / scope changes

### 2026-07-28 — P3 review gate: generator direction (user proposal)

User proposal at the gate: **skip the external map generator for the
MVP.** Rationale (user's, confirmed correct): in single player, map
layout is fixed per character per difficulty — it only re-rolls on a
difficulty change. The bot only does Hell runs on `MaqiuDoubing`, so
every run sees the identical map. Therefore: if we can read the current
layout, that suffices for now; note generated-maps / arbitrary-layout
navigation as future work.

Agent assessment: proposal adopted (see reply of the same date).
Replaces the generator with an **explored-map cache** — persist the live
memory-read room grids (P2) to disk keyed by (seed, difficulty, area),
merge every time the bot sees more rooms, reuse forever. Ground-truth by
definition (it *is* PD2's real collision), so the fidelity check becomes
moot for the MVP. The seed key doubles as the safety: if the layout ever
does change (difficulty swap, new character), the cache misses instead
of lying. Consequences: P3 re-scoped from "generator integration +
fidelity" to "explored-map cache"; hybrid-map-knowledge ADR to be
rewritten to record this decision (generator = considered, built,
blocked by PD2's DLLs, deferred); `mapdata.py` + the built generator
stay dormant for a future cycle; area coverage now requires seeing the
rooms once (one survey walk per new area, or slower frontier creep).

## Implementation findings (2026-07-28)

Things learned while building that the planning round could not know:

- **CollMap layout confirmed from two sources, with a shared typo.**
  D2BS and d2server headers agree field-for-field, and both label
  `pMapEnd` `//0x22` — impossible, since `pMapStart` is a 4-byte pointer
  at 0x20. We use 0x24. Noted in `offsets.py` so nobody "corrects" it
  back.
- **The generator does not need CMake.** VS 2017 Build Tools ships CMake
  3.12 (upstream wants ≥3.13) and downloading a newer one hit the same
  slow-network problem M2 documented. Compiling the seven sources
  directly with `cl` works and is now the documented recipe.
- **PD2's DLLs are not headless-loadable.** Three layers of obstruction,
  ending at PD2's bundled SGD2FreeRes display mod popping a modal dialog.
  Full write-up in [generator-status.md](generator-status.md). This kills
  the "point the generator at PD2's own data dir" hope from the planning
  round (Q: it would have made the fidelity question moot) and puts the
  fidelity check back at the center, exactly as the roadmap's QB assumed.
- **Everything live is gated on Administrator.** The bot reads an
  elevated process, so every live check needs an elevated terminal. An
  agent session cannot self-elevate, so *all* live verification in this
  milestone is user-run: [live-checks.md](live-checks.md) is the
  runbook, written to be executed top to bottom.
- **ruff finally installed** (M2 caveat closed): `ruff check` is clean
  across the repo. `ruff format` would rewrite 15 files including M2's —
  deliberately not run, to keep M3's diff reviewable. Follow-up: run it
  repo-wide as its own commit.

## Documentation surfaces likely to change

- `docs/architecture/` — new `navigation.md` (or `input.md` +
  `navigation.md`; decide by size when writing): the input gate, the
  projection, CollMap reading, generator integration, A*.
- `docs/adr/` — **map-knowledge ADR is due this milestone** (roadmap:
  ADR (b) lands at M3). Likely a second small ADR for the gated-input
  design if it proves decision-like rather than obvious.
- `README.md` — new dependency (map generator child process) + any new
  run instructions.
- `docs/learning/` — teach explainer + glossary per CLAUDE.md (A*,
  collision map, heuristic already in glossary from the roadmap round;
  candidates this round: isometric projection, ground truth/fidelity,
  interface/gate).
- `offsets.py` docstring — currently says BH is *the* source of truth;
  CollMap arrives with non-BH citations, so the docstring's claim needs
  a sentence acknowledging secondary sources.

## Future work ideas

- **Generated maps for never-walked layouts** (deferred from P3, user
  decision at the gate): revive the dormant d2mapapi_mod integration
  (`mapdata.py` + built exe) if the bot ever needs to navigate a layout
  it has not surveyed — arbitrary seeds, new characters each season, or
  pre-planning unvisited areas. Unblock path documented in
  generator-status.md (vanilla 1.13c DLLs, then the fidelity check).
- Background/PostMessage input method behind the same interface
  (roadmap decision 3 anticipates it) — would free the user's desktop
  while botting; not M3.
- Persisting generated maps per (seed, area) on disk to avoid
  regenerating across runs — cheap, but only if generation proves slow.
- Automap-based visual debugging (draw the planned path over a dump of
  the collision grid) — likely falls out of P4 testing anyway as a dev
  tool.
