# M1 spike log — kolbot ↔ PD2 offline validation

Machine: Windows 11 Home (james's PC). Session date: 2026-07-27.
Log convention: recorded as-I-go, per 01-windows-spike.md.

## Environment / preconditions

- **PD2 install found:** `C:\Program Files (x86)\Diablo II\ProjectD2\`
  (Game.exe, PD2Launcher.exe, BH.dll, ProjectDiablo.dll, PD2_EXT.dll,
  pd2data.mpq present). Parent dir is a D2 LoD install with
  `D2XP_IX86_1xx_114d.mpq` present — note: base install may be 1.14d;
  PD2's ProjectD2 subfolder carries its own 1.13c-era dlls, which is
  normal for PD2. Recent play confirmed: pd2 daily logs `D2260727.txt`
  (today) and a save character `MaqiuDoubing` + `pd2_shared.stash` in
  `..\Save\` (with `Save\ProjectD2\` subfolder also present).
- **VC++ 2010 x86 runtime:** present (`C:\Windows\SysWOW64\msvcr100.dll`,
  `msvcp100.dll`). ✓
- **.NET Framework:** 4.8.09032 (Release 533320). ✓ (needs 4.0+)
- **kolbot:** shallow clone of blizzhackers/kolbot at repo `kolbot/`
  (cloned 2026-07-27, upstream last commit 2026-07-27).
- Git: 2.26.2.windows.1 (old but functional). GitHub auth via gh CLI 2.96.0
  set up this session.

## Steps taken

1. `kolbot/setup.bat` (via its `+setup/setup.ps1` directly, since the .bat
   ends in a blocking `pause`): submodules `d2bs/kolbot/libs/SoloPlay` and
   `limedrop` cloned OK; all config templates copied; exit 0. Note: run it
   with PowerShell directly to avoid the interactive `pause`.
2. Read blizzhackers docs (restructure branch): `d2bot/ManagerSetup.md`,
   `kolbot/ManualPlay.md`, `kolbot/FAQ.md`. Key extracts:
   - Profile: Mode=Single Player exists; `-w` param required for D2BS;
     `Entry Point` selects the `.dbj` starter; CD-key list can be left
     blank to "use original key with D2 installation".
   - `D2BotMap.dbj` = manual-play starter (reveals map, loads char config)
     — minimal moving parts, good first injection test.
   - Docs advise running D2Bot.exe as Administrator.
   - Settings has a "D2 Version" dropdown (doc mentions 1.14d; PD2 is
     1.13c-based — watch this).
3. Launched `kolbot/D2Bot.exe` (v20.6.7.100) — starts fine, window up,
   no exceptions logged. First launch was WITHOUT admin; will retry
   elevated if injection fails with access errors.
4. `data/profile.json` stays empty until a profile is saved in the GUI;
   D2Bot# manager source is not public (no schema to hand-write) →
   profile created via GUI (which the manual will document anyway).

5. Profile `PD2-Spike` created in D2Bot# GUI (schema now visible in
   `data/profile.json`): Mode=Single Player, Character=MaqiuDoubing,
   Difficulty=Hell, Params=`-w`, Entry=D2BotMap.dbj,
   Path=`C:\Program Files (x86)\Diablo II\ProjectD2\Game.exe`.
   Start → console: `Attempt to access invalid address`. No game window,
   no Game.exe process, nothing in exceptions.log / d2bs logs (fails
   before injection).
6. Version check of the targets:
   - PD2 `Game.exe`: FileVersion **1.0.13.60 = 1.13c**.
   - Base install `Game.exe` (parent dir): **1.14d** (1.14.1.68).
7. D2Bot# Settings → D2 Version offers **only 1.13d and 1.14d** — no
   1.13c. Retried with 1.13d: same error at 23:26. Blizzhackers FAQ
   confirms this exact message = D2 version mismatch.
8. Community research (web):
   - Historical solution was **pd2bs** — a D2BS build for PD2 using a
     1.14d version hack + [Borega/pd2bs-scripts](https://github.com/Borega/pd2bs-scripts)
     kolbot overlay. Release URL (`shako.org/pd2bs-release.zip`) is now
     **404**; scripts repo last pushed **2022-08**; blizzhackers thread
     (2023–2024) says the maintainer stopped distributing it (~S4) and
     PD2's security now detects the version hack (online concern;
     offline moot, but no binary exists to try).
   - kolton/d2bot-with-kolbot (archived lineage): branches are only
     master / patch-113d / patch-113d-core15 — **no 1.13c build**
     available there either; 1.13c support predates PD2.
   - Remaining "PD2 bot" offers are paid/RMT (ownedcore/elitepvpers) —
     against kolbot's own rules and out of bounds for this project.

## Findings

- **Stock kolbot cannot attach to PD2's client**: PD2 is 1.13c; current
  kolbot supports 1.13d/1.14d only. Failure is immediate (pre-launch
  memory access), before any injection attempt.
- **No public, current PD2-compatible D2BS build exists** (pd2bs dead
  since ~S4; nothing else surfaced).
- The kolbot toolchain itself vs. this machine: baseline test against
  the vanilla install (below) distinguishes machine/config error from
  true incompatibility.

9. Baseline test (`Vanilla-B` profile, cloned from PD2-Spike, pointed at
   base `Game.exe`, D2Bot Settings=1.14d): game window opened and
   instantly crashed in a relaunch loop (D2Bot auto-restart) — profile
   counters recorded Crashes:14/Restarts:28; user force-closed D2Bot.
   No exceptions.log or d2bs log output (client dies pre-D2BS-logging).
   **Root cause found**: base install `Game.exe` is FileVersion
   1.14.1.68 = **1.14b**, not 1.14d (1.14.3.71) — baseline was also
   version-mismatched, just failing later (launches, then crashes)
   than the 1.13c case (aborts pre-launch). Patching vanilla to 1.14d
   would validate the toolchain fully but is outside the spike's
   purpose; skipped per phase-file guidance ("don't spend the spike on
   it").

## Conclusions

1. **kolbot ↔ PD2 offline is a NO with current public tooling.** Stock
   kolbot supports only 1.13d/1.14d; PD2's client is 1.13c; D2Bot#
   aborts before launch/injection ("Attempt to access invalid
   address", FAQ-documented as version mismatch).
2. The historical community bridge (pd2bs: D2BS + 1.14d version-hack)
   is publicly dead — no downloadable binary, scripts repo stale since
   2022, maintainer stopped distributing (~S4).
3. No machine/config fault: D2Bot# itself runs correctly; both observed
   failures are fully explained by version mismatches.
4. Side finding: the base vanilla install is 1.14b; kolbot could work
   on it if patched to 1.14d (relevant only if the project ever wants a
   vanilla-D2 target as a consolation option).

## Tier reached

**Below T0.** D2Bot# never successfully launched PD2's Game.exe.
Diagnosis complete and precise (version incompatibility, not
environment) — per the phase file this is a successful spike outcome.

## Recommendation (input to the M1 review gate; decision is the user's)

Options, roughly in order of assessed viability:

- **(B) Resurrect the original from-scratch plan** (out-of-process
  memory reading via ReadProcessMemory + SendInput, offsets sourced
  from PD2's own open-source BH fork; kolbot's JS scripts mined as a
  behavioral reference, which was their main value anyway). Most
  tractable path to a PD2 offline bot; matches the pre-reorientation
  plan already in notes.md. Recommended.
- **(A) Port/adapt D2BS to PD2 1.13c ourselves** (D2BS is open source;
  PD2's BH gives current offsets). High-effort C++ RE project with
  uncertain payoff; would replace M2 entirely.
- **(C) Ask the PD2 community/Discord** whether a current pd2bs build
  exists privately. Cheap to try, low odds, offline-use framing
  essential; paid/RMT offers are out of bounds.
- **(D) Retarget vanilla D2** (patch 1.14b→1.14d, stock kolbot works).
  Abandons PD2 — likely unacceptable, listed for completeness.
