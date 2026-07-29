# P3 — Offline map generation + PD2 fidelity check

Size: `sm`. Dependencies: **P2** (memory collision is the comparison
baseline). Part of the M3 plan ([plan.md](plan.md)).

## Why

Perception sees only the player's room neighbourhood; global routing
needs the whole area's walkability before we've been there. D2
generates each game's maps deterministically from the map seed
(`pd2bot.world.read_map_seed`), so a headless generator running real
game code can produce the full collision grid offline. Approved
roadmap decision (QB): generated maps for global routing, live memory
collision as verifier/fallback.

## Generator: pinned first candidate

**soarqin/d2mapapi_mod** (fork of jcageman/d2mapapi): C++/CMake,
**must be compiled 32-bit**, explicitly supports D2 **1.13c**, and
ships a **`piped` variant** — a child process speaking JSON over
stdio: query = (seed, difficulty 0/1/2, area id) → map offset, size,
crop, **run-length-encoded collision rows** (`-1` terminates a row),
plus exits/NPCs/objects (keep exits in the parsed model — M4/M6 will
want them; ignore the rest for now). It locates a legacy D2 install
via the registry or an explicit path.

Fallbacks, in order, if the build fights back: d2mapapi_mod's `httpd`
variant (REST on :8000), then jcageman/d2mapapi upstream, then
prebuilt release binaries of any of these. **Acceptance is
capability-based**: Python gets (origin, size, grid, exits) for a
(seed, difficulty, area); which wrapper delivers it is an
implementation detail to note in `_DONE.md`.

Build notes: needs a 32-bit toolchain (MSVC x86 or MinGW-w64 i686).
Keep the checkout/build **outside the repo or gitignored** (like
`kolbot/`); commit only the Python client + docs + a pinned
commit/URL in README. Network flakiness on this machine is a known
caveat (M2 `_DONE.md`) — if clones/downloads fail, stop and report.

## Point it at the right game files (fidelity experiment)

The generator loads real game data. Two candidate data dirs:

- Base D2 1.13c: `C:\Program Files (x86)\Diablo II\` → vanilla maps.
- **PD2's own dir**: `...\Diablo II\ProjectD2\` (contains
  `pd2maps.mpq`) → possibly PD2's modified maps, if the generator's
  MPQ loading picks them up.

Try PD2's dir first; if the generator can't consume it, fall back to
vanilla + rely on the fidelity check. Do not silently assume either
works.

## The PD2 fidelity check (the milestone's main unknown)

PD2 modifies some maps (`pd2maps.mpq`); generators emit vanilla
layouts unless the experiment above changes that. For each area of
interest — **Cold Plains + Stony Field** now (trial-run route),
**Black Marsh / Tower vicinity** if cheap (flagship route) — while
standing in the area in a live game:

1. Generate the area's grid for the current seed/difficulty (Hell).
2. Read live local collision (P2) at several spots as the user walks
   around (aim for ≥ 3 rooms per area, including an area edge).
3. Compare cell-by-cell over the overlapping window; report mismatch
   percentage and *where* mismatches cluster.

Verdict per area: `identical` / `differs (how)` / `generator used PD2
data`. Write the verdicts into this planning dir
(`fidelity-results.md`) — M5/M6 route planning depends on them.

## Scope

- `pd2bot/mapdata.py`: child-process client (spawn, query, restart on
  death), RLE decode into the same grid representation P2 uses
  (shared dataclass or a common protocol — do not invent a second
  grid type), area-id constants for the areas we name (cited to the
  standard area-id table), exits in the model.
- Fidelity-check runner: a CLI entry (`python -m pd2bot.mapdata
  --fidelity`) usable while the user plays; writes the comparison
  report.
- Tests: RLE decoding against captured real responses (record one
  JSON response as a fixture), grid alignment math, client protocol
  framing (no live child process in unit tests).
- **Map-knowledge ADR** (`docs/adr/`): the hybrid — generated maps
  for global knowledge, live memory collision as ground-truth
  verifier/fallback; alternatives considered (wander-and-read-only:
  no lookahead; injection/calling game functions: ruled out by
  architecture); consequences (external 32-bit build dependency,
  seasonal re-verification, fidelity caveat with per-area verdicts).
  This is roadmap ADR (b), committed for M3 — write it here while the
  evidence is fresh.

## Out of scope

Pathfinding (P4), caching generated maps to disk (future work unless
generation is measurably slow — if so, note it, don't build it),
non-collision map features beyond exits.

## Review gate — end of phase

Stop and present to the user: the fidelity verdicts per area (with
mismatch numbers), which generator variant/data-dir combination ended
up working, and the draft ADR. Question for the user: are the
verdicts good enough to route on generated maps for the trial-run
areas, or do we need the PD2-data-dir path to work before M5?

## Conventions / reminders

Do not commit unless asked. Do not expand scope. Do not vendor the
generator's source into the repo. Stop and report if blocked (build,
network, protocol). Report what changed, what was validated,
deviations.

## Validation commands

```bash
python -m pytest -q
python -m pd2bot.mapdata --fidelity   # live, user in-game
```

## Definition of done

Python obtains grids+exits for (seed, difficulty, area); RLE decode
unit-tested against a real captured response; fidelity check run for
the named areas with verdicts recorded in `fidelity-results.md`;
map-knowledge ADR drafted; review gate held.

## Implementation Result

Status: **BLOCKED — needs a user decision at the review gate**
Date: 2026-07-28
Commit: pending

Full diagnosis: **[generator-status.md](generator-status.md)**. Summary:

- **Done**: generator cloned (sibling of the repo, nothing vendored) and
  built 32-bit — without CMake, which was too old locally and too slow to
  download; the seven sources compile directly with `cl` (exact command
  in generator-status.md, mirrored in the README).
  `pd2bot/mapdata.py` implements the piped protocol and RLE decode, with
  9 unit tests against the format upstream documents in `collisionmap.h`
  (including the short-row and overlong-run edge cases). Map-knowledge
  **ADR written**: `docs/adr/2026-07-28-hybrid-map-knowledge.md`.
  `OverlayGrid` (in `pathing.py`) implements the live-over-generated
  authority order the ADR describes.
- **Blocked**: the generator cannot initialize on this machine. It needs
  1.13c game DLLs; the only set present is PD2's, which (a) fails
  upstream's CRC fingerprinting, (b) proxies `Storm.dll` through
  `PD2_EXT.dll`, and (c) — the actual wall — pulls in PD2's bundled
  SGD2FreeRes display mod, which pops a modal error dialog
  (`GetFileVersionInfoSizeW`, 0x715) and hangs. Two local workarounds
  were built for (a) and (b) and are documented; (c) is where it stops.
- **The gate question for the user**: supply a **vanilla 1.13c DLL set**
  (recommended — the fidelity check then does exactly the job the roadmap
  planned for it), keep stubbing PD2's chain (not recommended — each stub
  makes "PD2's real map code" less true), or ship M3 without generated
  maps (the navigator already degrades to live-collision-only when no
  `--exe` is passed).
- **`fidelity-results.md` deliberately does not exist yet.** The check is
  built (`python -m pd2bot.mapdata --fidelity`) and unit-tested, but it
  has never run against the game, so there are no verdicts to record.
- Deviations: no captured-real-response fixture — the test payloads are
  hand-built from upstream's documented format, since no real response
  could be obtained. Replace them with a captured one once the generator
  runs.

## Resolution (2026-07-28, review gate)

The user resolved the gate with an option better than any listed above:
**skip generation for the MVP entirely.** Single-player maps are fixed
per character per difficulty; the bot runs Hell only on one character,
so the map never changes — the bot can simply *remember* what
perception reads. Implemented the same day as `pd2bot/mapstore.py`
(the explored-map atlas: room grids persisted under `maps/` keyed by
seed/difficulty/area, merged on every sighting, seed key as staleness
guard) + `tests/test_mapstore.py` (7 tests), with the navigate CLI
recording while walking and a `--survey` mode for the initial
walkthrough. The map-knowledge ADR was rewritten to record this
decision; the generator artifacts stay dormant with their unblock path
documented in [generator-status.md](generator-status.md). Generated
maps for never-walked layouts are future work (noted in notes.md).
