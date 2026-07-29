# P3 generator: build succeeded, headless init blocked

> **RESOLVED 2026-07-28, same day (P3 review gate):** the user chose a
> fourth option none of the three below — skip generation entirely for
> the MVP, because single-player maps are fixed per character per
> difficulty, and instead **persist the live-read collision grids**
> (the explored-map atlas, `pd2bot/mapstore.py`). See the rewritten
> map-knowledge ADR and notes.md. The generator work below stays
> dormant; this document is its state and unblock path if it is ever
> revived. `fidelity-results.md` will never be written for M3 — with
> atlas data read from the real PD2 game, there is nothing to check
> fidelity *against*.

Status as of 2026-07-28. The generator cannot initialize on this machine
without vanilla 1.13c DLLs.

## What works

- **Clone**: `soarqin/d2mapapi_mod` at `C:\dev\2026-pd2-bot\d2mapapi_mod`
  (sibling of the repo, per the ADR — nothing vendored in).
- **Build**: 32-bit `d2mapapi_piped.exe` builds cleanly. CMake ≥ 3.13 was
  *not* needed: VS 2017 Build Tools ships CMake 3.12, and downloading a
  newer one stalled on the same flaky network M2 hit, so the seven
  sources were compiled directly:

  ```
  cl /nologo /std:c++17 /O2 /EHsc /FIalgorithm /DD2MAPAPI_VERSION=\"1.3.0\"
     /I. /Ijson piped.cpp collisionmap.cpp mapdata.cpp pathfinder.cpp
     d2map.cpp offset.cpp session.cpp /Fe:d2mapapi_piped.exe
     /link advapi32.lib
  ```

  (`/FIalgorithm` because the upstream header uses `std::min/max` without
  including `<algorithm>`; `advapi32` for its registry lookup. Run from a
  **32-bit** VS prompt — `vcvars32.bat`.)
- **Python client** (`pd2bot/mapdata.py`): protocol and RLE decoding are
  implemented and unit-tested against the format documented in upstream's
  `collisionmap.h`. It talks to the process correctly — every failure
  below was reported *through* it, cleanly.

## Why it will not initialize

The generator needs a set of Diablo II **1.13c DLLs** to load headlessly.
This machine has exactly one such set: PD2's own, in
`...\Diablo II\ProjectD2\`. (The base `Diablo II\` folder has Game.exe and
the vanilla MPQs but **no game DLLs** — PD2 keeps them in its own dir.)
Three blockers, peeled one at a time:

1. **Version fingerprinting fails.** Upstream identifies the client by
   CRC32 of `Game.exe` (fallback `Storm.dll`). PD2 modifies both, so no
   entry matches and it bails with "Failed to load DLLs!". Worked around
   with a local patch: a `D2MAPAPI_FORCE_VERSION=113c` environment
   override in `offset.cpp` (plus a diagnostic print naming the failing
   DLL — upstream is silent about which one). Both edits are local to the
   sibling checkout, not the repo.
2. **`Storm.dll` will not load** (error 1114, "DLL initialization routine
   failed"). PD2's Storm imports three `version.dll` functions from
   **`PD2_EXT.dll`** instead — a proxy-DLL arrangement that drags PD2's
   in-process extension hooks into anything that loads Storm. Worked
   around with a three-export pass-through stub
   (`d2mapapi_mod/pd2_ext_stub/`) placed next to the generator exe, where
   the DLL search order finds it first. **The game install was not
   touched**; PD2's real `PD2_EXT.dll` is untouched in its own folder.
3. **SGD2FreeRes blocks, and this is the wall.** With Storm loading, the
   next PD2 DLL in the chain pops a modal dialog and hangs the process:

   > File: ...SlashGaming-Diablo-II-API\src\cxx\file\file_version_info.cc
   > Line: 158 — Windows function error on GetFileVersionInfoSizeW with
   > error code 0x715

   That is PD2's bundled *SlashGaming Diablo II Free Resolution*
   (`SGD2FreeRes.dll` / `SGD2FreeDisplayFix.dll`) demanding version
   resources from a file it cannot find headlessly (0x715 =
   `ERROR_RESOURCE_TYPE_NOT_FOUND`). It is a display-resolution mod — of
   no use whatsoever for generating collision maps.

## The decision this needs (P3 review gate)

Each further step trades away the thing that made PD2's dir attractive.
Three options, ranked:

1. **Vanilla 1.13c DLLs (recommended).** Get a plain Diablo II 1.13c DLL
   set (the classic install PD2 was layered onto, a separate 1.13c
   install, or a 1.13c patch archive) into a folder of its own and point
   `--d2` at it. The generator then runs exactly the code it was written
   for. Cost: generated maps are *vanilla*, so the fidelity check becomes
   load-bearing — which is precisely the plan the roadmap already
   approved, and the check is built and waiting.
2. **Keep stubbing PD2's chain.** Stub SGD2FreeRes next, then whatever
   surfaces behind it. Each stub makes "we are running PD2's real map
   code" less true, and a Frankenstein set that produces *silently*
   wrong maps is worse than vanilla maps we know to verify. Not
   recommended.
3. **Ship M3 without generated maps.** Live collision alone (P2) already
   supports walking anywhere inside the loaded room neighbourhood — the
   acceptance walk distance (~60 subtiles) is near that boundary. Global
   routing then waits for M4/M5. Cheapest, and the navigator already
   degrades to this automatically when no `--exe` is passed.

Nothing in the Python code depends on which way this goes: `mapdata.py`
takes any working `d2mapapi_piped.exe`, and `OverlayGrid` treats generated
maps as an optional base under live truth.
