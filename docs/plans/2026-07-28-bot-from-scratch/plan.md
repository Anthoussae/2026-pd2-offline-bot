---
kind: plan
size: lg
depth: roadmap
status: active
repo: 2026-pd2-offline-bot
created: 2026-07-28
adr: expected
---

# PD2 bot from scratch — roadmap plan

## Size and why

`lg` / roadmap: seven milestones; M2–M5 each need their own planning
pass fed by the preceding milestone's findings. M1 is executable
directly from [01-perception-input-spike.md](01-perception-input-spike.md).

## Goal

Build a bot for the user's Project Diablo 2 **offline single-player**
client on Windows, from scratch, using **out-of-process memory reading +
synthetic input** — plus an instruction manual (`docs/manual/`),
architecture documentation (`docs/architecture/`), and teaching
artifacts per the `/teach` skill.

Supersedes the kolbot-based roadmap
(`docs/archive/plans/2026-07-28-pd2-offline-bot/`) after its M1 spike
proved kolbot incompatible with PD2's 1.13c client (see that dir's
`spike-log.md`). Kolbot remains as a gitignored *behavioral reference*
at `kolbot/`.

First character: poison dagger necromancer, **Hell** difficulty,
character `MaqiuDoubing` (has all relevant waypoints). Travel style: on
foot, killing everything en route (safer; suits the corpse-fueled kit).
First end-to-end target: **Cold Plains clearance around the waypoint**;
flagship target: **Countess**. Future goals: more runs, more classes —
so run definitions and class behavior stay data/module-driven.

## Acceptance criteria

- Bot attaches to the running PD2 offline client (launched normally via
  PD2Launcher — we attach, not launch), creates a single-player game,
  runs the target run, picks/stashes items per rules, handles
  death/errors, leaves and re-enters games unattended.
- A newcomer with a Windows PC could reproduce setup from
  `docs/manual/` alone.
- `docs/architecture/` documents our bot's design plus what was mined
  from BH/kolbot.

## Scope boundaries

- Offline single-player is the design target and scope. **No hardcoded
  offline-enforcement machinery** (user decision 2026-07-28): sole
  user, patch-gated from Blizzard T&Cs. PD2's online realm is not a
  target of this project.
- No DLL injection, no pixel-scraping (perception is memory-read only).
- Not in scope: leveling automation, multi-boxing, muling.

## Discovery summary

See [notes.md](notes.md). Key facts: PD2 client = D2 1.13c;
**Project-Diablo-2/BH** (the mod's own open-source maphack, C++, pushed
2026-07-14) pins the current season's memory structures/offsets in
`BH/D2Structs.h`, `BH/D2Ptrs.h`; **pymem** active; **d2mapapi** (C#,
2025-11) generates map layout + collision from (seed, difficulty, area)
by running real game code — with a known fidelity risk vs PD2-modified
areas (explicit check in M3).

## Architecture decisions (user-approved, 2026-07-28)

1. **Python** stack (pymem + ctypes/SendInput). ADR expected.
2. **Perception**: out-of-process ReadProcessMemory; offsets derived
   from PD2's BH source; pinned per season, re-verified on patches.
3. **Input**: OS-level SendInput, game window foreground, fixed
   windowed mode at an agreed resolution; input behind an interface so
   background/PostMessage methods can come later.
4. **Map knowledge**: seed-based offline map generation + A* for global
   routing; live memory-read collision as fallback/verifier. ADR
   expected.
5. **Behavior**: hierarchical FSM engine; runs as declarative data;
   pickit rules as data (kolbot `.nip` as design reference); per-class
   combat module + per-class config, class-agnostic runs (kolbot's
   three-layer pattern). ADR expected.

## Repo layout

- Bot code layout decided in M2 planning (Python package structure).
  M1 spike code lives in `spike/` (kept, throwaway-quality allowed).
- `kolbot/` — gitignored reference clone; never edited.
- Planning/reviews/learning/manual/architecture per agent-toolkit
  structure.

## Milestones

| Milestone | Size | Summary | Needs own planning? |
|---|---|---|---|
| M1 | sm | Perception + input spike: attach to live PD2 client, read player name/HP/position via BH-derived offsets, one synthetic click moves the character. Phase file: [01-perception-input-spike.md](01-perception-input-spike.md) | No — executable now. **Review gate at end** |
| M2 | md | Perception core: player, monsters, ground items, map seed, area, menu/in-game state detection | **Done 2026-07-28** → [docs/archive/plans/2026-07-28-m2-perception-core/](../../archive/plans/2026-07-28-m2-perception-core/plan.md) |
| M3 | md | Navigation: input layer, map-gen service (d2mapapi), A*, walk-to/path-following, **PD2 map fidelity check** | Yes |
| M4 | md | Game cycle: create/leave SP game via menus, death/error handling, chicken logic, run-loop skeleton | Yes |
| M5 | md | Trial run end-to-end: FSM + necro combat module + pickit + stash — Cold Plains clearance (Hell) | Yes |
| M6 | md | Countess flagship: multi-area travel, Tower descent, boss kill, expanded pickit | Light planning |
| M7 | sm | Manual, architecture docs, cleanup sweep (TODOs, debug prints, stale docs, scope creep) | No |

## ADR expectations

`expected`: (a) language/stack choice; (b) map-knowledge approach;
(c) behavior architecture (FSM + data layers). Write them as their
milestones complete (a: M1, b: M3, c: M5). Straightforward config or
run-data additions need no ADR.

## Validation strategy

Empirical, on this Windows machine, against the live offline client:
observed end-to-end behavior + spike/run logs captured into the
planning dirs. Python-side: type checks/lint once a real package exists
(M2+); unit tests for pure logic (pathfinding, pickit parsing) from M3
on. Each milestone ends with the `/teach` step per CLAUDE.md.

## Constraints and conventions

- Attach to a client the user launched normally (PD2Launcher) — never
  launch Game.exe ourselves (avoids the mod-not-loaded trap kolbot's
  manager fell into).
- Don't edit `kolbot/` — reference only.
- Windows-machine sessions: read this plan + notes.md first; log
  findings back into the planning dir.
- Offsets/structures: cite the BH source line when deriving each one
  (traceability for seasonal re-verification).
