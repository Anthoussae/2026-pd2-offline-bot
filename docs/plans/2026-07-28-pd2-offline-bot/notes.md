# Notes — PD2 offline-only bot (planning)

## Initial understanding and goals

- Build a simple, offline-only bot for Project Diablo 2 (PD2), running on Windows.
- Primary purpose: **learning exercise** — study synthetic input generation and
  process-memory reading in a familiar environment with clear feedback.
- Offline-only is a hard constraint and may be hardcoded (user confirmed this is
  permissible for PD2 provided use stays offline; user does not play online).
- Initial scope: one character (poison dagger necromancer), one simple run,
  expandable architecture rather than hard-coded paths.

### Requested capabilities (from user)

1. Creating/leaving games.
2. Run navigation — traverse a map, kill a target; start with 1 simple run,
   expandable to more (logic should be data-driven/expandable).
3. Item collection — pickup prioritization, selection, inventory management.
4. Stash management — deposit after each run; overflow handling.
5. Error/death handling.
6. Movement & combat — parse environment, navigate fights, select/cast spells,
   avoid danger, move efficiently; expandable to future characters/builds.
7. Anything else evident from factfinding (large existing botting community).

### User asks of planning

- Propose the major **technical/architectural questions**.
- Surface the **design decisions**.

## Current state

- Greenfield repo (`2026-pd2-offline-bot`), scaffolded with agent-toolkit docs
  structure. No code yet. Language/stack undecided.

## Discovery log

### What PD2 is, technically

- PD2 is a mod of Diablo II: LoD **1.13c** (legacy engine, 32-bit `Game.exe`),
  not D2R. Client = 1.13c files + PD2's dlls + `pd2data.mpq`, launched via
  PD2Launcher. Season 13 ("Betrayal") began 2026-04-24; seasonal patches can
  move memory offsets.
- PD2's own client-side QoL (maphack-style features, loot filter) is a fork of
  slashdiablo's **BH maphack**, and it is **open source**:
  https://github.com/Project-Diablo-2/BH (C++, AGPL). BH reads the game's
  in-memory structures in-process, so this repo is an authoritative,
  PD2-maintained reference for the client's memory structures/offsets
  (UnitAny, inventory, levels, etc.). Also public: PD2Launcher (C#), d2gl
  (Glide/DDraw→OpenGL wrapper), LootFilters, free-resolution mod.

### Existing botting/tooling landscape (references, not dependencies)

- **kolbot / D2BS** (blizzhackers): the classic legacy-D2 bot — C++ core dll
  *injected* into the game running a JS script engine (kolbot scripts),
  managed by D2Bot#. Reported to partially work with PD2 (in-game only; OOG
  automation broken). Injection-based → not aligned with our learning goals,
  but its scripts encode 20+ years of bot behavior knowledge (chicken logic,
  pickit, town runs, run scripts) worth mining.
- **kolbot-SoloPlay**: profile-driven 1–99 auto-leveling on top of kolbot —
  good reference for behavior/decision logic.
- **Out-of-process memory readers for legacy D2** (same approach we want):
  - `squeek502/d2info` — reads a running legacy D2 game's memory.
  - `Hell4Ge/D2SharpMemory` — C# memory reader for 1.13c.
  - `DiabloRun/DiabloInterface` — streamer tool reading 1.13c/1.14 memory.
  - `mir-diablo-ii-tools/Diablo-II-Address-Table` — collected offsets per
    version incl. 1.13c (note: PD2 code edits may shift some).
- **Map generation / pathfinding**:
  - `blacha/diablo2` (packages/map) — runs the real game code headlessly to
    emit JSON map layout + **collision data** for any (seed, difficulty,
    area). `jcageman/d2mapapi` / `joffreybesos/d2-mapgenerator` — same idea
    as a REST API / generator. Standard approach in modern memory bots:
    read map seed from memory → generate full-area collision map offline →
    A* pathfinding; live memory supplies dynamic state (doors, monsters).
- **D2R bots** (koolo (Go), botty) — architectural references for the
  "out-of-process memory read + synthetic input" pattern, though offsets/
  structures don't transfer from D2R.

### Key technical facts affecting design

- 1.13c is 32-bit; structures are well documented publicly since ~2010.
  PD2's BH fork pins them to the *current* PD2 client.
- A walking character (poison dagger necro, no teleport) needs real collision
  -aware pathfinding — stronger requirement than teleport-sorc bots.
- Offline enforcement is checkable (single-player game state vs realm/TCP;
  simplest robust guard: verify no realm connection / single-player flag in
  memory before acting + only launch offline mode).
- Dev environment note: user is currently on macOS; the bot must run on
  Windows against a live PD2 client — dev/test workflow needs confirming.

## Questions

### Confirmation-style (batched)

- Q1 Perception = out-of-process ReadProcessMemory (no injection, no pixels)
  — suggested: yes (matches learning goals).
- Q2 Build from scratch, using kolbot/BH/etc. only as references — suggested:
  yes.
- Q3 Input = OS-level synthetic input (SendInput), game window foreground;
  input layer behind an interface so PostMessage/background can come later —
  suggested: yes.
- Q4 Hardcoded offline-only guard: bot refuses to act unless the client is in
  single-player mode — suggested: yes.
- Q5 Pin development to current PD2 season/patch; offsets sourced/verified
  from PD2's BH repo; expect seasonal re-verification — suggested: yes.
- Q6 Fixed windowed mode at an agreed resolution as an assumption — suggested:
  yes.
- Q7 First run target: something with a short waypoint-adjacent path (e.g.
  Eldritch in Act 5) — suggested: yes, exact target user's pick.
- Q8 Dev on Mac, run/test on a Windows machine — confirm workflow.

### Discussion-style (one at a time)

- QA Language/stack — Python (pymem/ctypes; fastest learning loop) vs Go
  (koolo precedent) vs C# (native Win32 comfort, D2SharpMemory precedent).
- QB Map knowledge & pathfinding — seed→offline map generation + A* vs live
  memory-read collision vs scripted waypoint paths (hybrid likely).
- QC Behavior architecture — hierarchical FSM vs behavior tree; run scripts
  and character builds as data/plugin classes; pickit rule format.

## User answers / scope changes

### 2026-07-28 — Major reorientation (plan restart)

After the frank reappraisal of kolbot-vs-scratch, the user chose to
**prioritize getting a bot working over building from scratch**. Q1/Q2
(memory-reading, from-scratch) are dropped. New ultimate objective:

- Create a bot **based on kolbot** that runs on PD2 offline on Windows.
- Write a clear **instruction manual**: setup, and configuration for
  specific characters and tasks.
- If possible/advisable, **fork kolbot into the user's own project** to
  tinker with — more user-friendly, easier to customize.
- Write **documentation explaining how kolbot's components function**.
- Teaching objectives: technical elements of interest inside kolbot itself,
  plus the higher-level theme "good approaches for making efficient use of
  and adaptations of existing solutions to software problems".

Near-term user intent: discuss how kolbot works, how to get it running on
their Windows machine, and how to configure it for their offline PD2
character and desired runs. First step requested: download the relevant
kolbot files into the project.

## Questions

(to be added)

### 2026-07-28 — kolbot repo discovery (post-reorientation)

Shallow-cloned `blizzhackers/kolbot` into `kolbot/` (20 MB; full clone timed
out on binary-heavy history — can unshallow later if needed).

- **Actively maintained**: last commit 2026-07-27 (day before cloning).
- Ships binaries in-repo: `D2Bot.exe` (C# manager) and `d2bs/D2BS.dll`
  (injected C++ core). `setup.bat` copies config templates and inits
  submodules; `update.bat` pulls upstream. Deps: VC++ 2010 x86 redist,
  .NET 4.0+.
- Script tree `d2bs/kolbot/`: entry profiles as `.dbj` (D2BotLead,
  D2BotSoloPlay, D2BotMap, D2BotMule, …), `libs/` (core, config, scripts,
  oog, systems, modules, manualplay, SoloPlay now bundled), `pickit/`
  (`.nip` files), `sdk/`, `threads/`.
- Per-class config: `libs/config/Necromancer.js` (+ `Builds/`,
  `Templates/`, `_BaseConfigFile.js`) — kolbot's designed customization
  surface is config overlays, not core edits.
- Single-player support exists in the OOG layer (`libs/OOG.js`,
  `libs/oog/Locations.js` reference single player menu flow).
- **Zero references to PD2/ProjectD2 anywhere in the repo** — the
  kolbot↔PD2 pairing is entirely unofficial/DIY. Compatibility of the
  injected D2BS.dll with PD2's seasonally-patched client remains the
  existential risk; must be validated first (M1 spike).

### 2026-07-28 — Restart-plan confirmation answers

- Q1 (keep `kolbot/` as nested gitignored clone until fork decision): **yes**.
- Q2 (M1 = Windows validation spike first): user asked for elaboration —
  provided (see below); pending explicit yes but plan proceeds on it.
- Q3 (target config): **first run = Countess, not Eldritch** (user
  preference, unless too complex). Assessed: fine — `libs/scripts/Countess.js`
  is a built-in kolbot run; random Tower layouts are handled by kolbot's own
  pathing, so extra complexity is absorbed by the framework, not us. Poison
  dagger necro otherwise unchanged.
- Q4 (manual + component docs in `docs/manual/`, `docs/architecture/`):
  **yes**.
- Q5 (Claude Code on the Windows machine): **pending** — user checking
  whether they can run Claude there.
- QA (fork vs overlay): **overlay** — our repo tracks only our own configs/
  scripts/pickit + a sync mechanism into a stock kolbot clone; hard-fork
  question revisited as an explicit decision point (ADR candidate) at end of
  M2, when core-edit needs are known.
- Q5 resolved: user got Claude running on the Windows machine. Migration =
  push this repo to a private remote → clone on Windows → new Claude session
  there resumes from plan.md/notes.md. Q2 (M1 spike first): implicitly
  yes — M1 phase file written for execution on the Windows machine.

## Future work ideas

(to be added)
