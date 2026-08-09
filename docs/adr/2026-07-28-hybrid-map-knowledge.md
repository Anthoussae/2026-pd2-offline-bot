# Map knowledge: remember what we walk, live memory stays ground truth

Date: 2026-07-28 (M3; revised the same day at the P3 review gate)
Status: accepted

## Context

Navigation needs to know where the bot can walk. Perception (M2) reads
collision grids from the live client, but only for the player's room and
its immediate neighbours — that is all the game keeps loaded. Global
routing ("walk from the waypoint to the far side of Cold Plains") needs
the whole area's walkability, including places not visited *in this
game*.

Two facts shaped the decision:

1. **Single-player maps are fixed.** D2 saves the map layout per
   character per difficulty; it only re-rolls on a difficulty change
   (user-supplied insight at the review gate). This bot runs one
   character, Hell only — so every game sees the identical map, and
   anything once learned about the layout stays true.
2. **The offline generator route is blocked on this machine.** The
   original plan was a headless map generator (d2mapapi_mod) running the
   game's own map code per (seed, difficulty, area). It was cloned and
   built (32-bit, hand-compiled — recipe in the M3 planning dir's
   `generator-status.md`), and the Python client for it exists and is
   tested (`pd2bot/mapdata.py`). But the only Diablo II 1.13c DLLs
   present are PD2's, and they cannot be loaded headlessly: PD2's
   modified `Storm.dll` proxy-loads its extension hooks, and PD2's
   bundled SGD2FreeRes display mod pops a modal error dialog and hangs
   any process that is not the real game. Working around it means either
   sourcing vanilla 1.13c DLLs or stubbing PD2 code until the maps it
   generates are no longer PD2's.

## Options considered

1. **Live memory only, no memory of the past** — walk blind every game,
   re-discovering collision room by room. No lookahead, terrible routes,
   nothing learned between runs.
2. **Offline generator (original plan)** — global maps from a child
   process. Blocked as described; even unblocked (vanilla DLLs), its
   output is vanilla 1.13c and PD2 modifies some maps, so it would need
   a standing fidelity-check against live memory.
3. **Injection / calling game functions in-process** — ruled out by the
   project's architecture ADR.
4. **Explored-map atlas (chosen)** — persist every room grid perception
   reads to disk, keyed by (map seed, difficulty, area); merge on every
   sighting; plan on the union of atlas + live grids, live winning where
   loaded. Because SP maps are fixed, the atlas converges on the full
   map and never goes stale.

## Decision

- `pd2bot/mapstore.py`: `MapStore` / `ExploredArea` persist room grids
  as JSON under `maps/` (gitignored — machine-local save-data,
  regenerable by walking). Rooms are keyed by (origin, size); a re-seen
  room replaces its old grid (latest reading wins — collision words
  carry some dynamic state such as doors).
- The navigator plans on `OverlayGrid(base=atlas, overlay=live)`:
  **live memory collision remains the authority** wherever rooms are
  loaded; the atlas fills in everywhere else.
- Recording is a side effect of existing: the navigate CLI records
  visible rooms about once a second while walking, and a `--survey` mode
  records while the *user* walks, sending no input. One survey walk per
  new area is the expected workflow (Cold Plains now, Tower for M6).
- The **seed in the file key is the staleness guard**: a difficulty
  swap, a new character, or any layout re-roll produces a different
  seed, which misses the cache — the bot starts honestly blank instead
  of trusting a wrong map. No explicit invalidation logic exists or is
  needed.
- Known gap, accepted: difficulty is not yet read from memory (M4
  candidate); callers state it, defaulting to Hell.

## The generator is deferred, not deleted

`pd2bot/mapdata.py` (protocol client + RLE decoder, unit-tested), the
built `d2mapapi_piped.exe`, the version-forcing patch, and the PD2_EXT
stub all remain — dormant. They become relevant if the bot ever needs
maps it has not walked (arbitrary seeds, other characters, pre-planning
unvisited areas). The unblock path is documented in
`generator-status.md`: supply vanilla 1.13c DLLs, then run the fidelity
check that `mapdata.py --fidelity` already implements.

## Consequences

- Zero external runtime dependencies for navigation; the whole map
  pipeline is ~150 lines of tested Python reading the game we actually
  play, so PD2's map modifications are *in* the data by construction —
  no fidelity question for the MVP.
- Each new area costs one survey walk before global routing works there;
  until surveyed, the bot can still creep by re-planning at the live
  frontier.
- **Only terrain is persisted.** D2's collision words double as an
  occupancy grid (monsters, players, items, corpses), which the first
  survey walk exposed: a single area recorded 247 updates as monsters
  moved, and `IS_ON_FLOOR` — which counts as unwalkable — would have
  frozen a passing corpse into the atlas as a permanent wall. `record()`
  strips `COLL_TRANSIENT_MASK` before storing; live reads keep the full
  flags, since present occupancy is real and the live overlay outranks
  the atlas anyway.
- Doors remain a known edge: a door seen closed stays closed in the
  atlas until re-seen. The live overlay corrects it wherever it matters,
  and M4's door handling will revisit.
- Route planning for M5/M6 can assume full-area knowledge only after the
  survey walk of those areas is done — a one-time, one-minute cost each.

*(2026-08-09: module paths above predate the package restructure; see
docs/adr/2026-08-09-package-layout.md for the current layout.)*
