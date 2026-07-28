---
kind: plan
size: lg
depth: roadmap
status: superseded
superseded-by: docs/plans/2026-07-28-bot-from-scratch/
superseded-date: 2026-07-28
repo: 2026-pd2-offline-bot
created: 2026-07-28
adr: possible
---

> **Superseded 2026-07-28** after M1's spike verdict: kolbot cannot run
> on PD2 (1.13c unsupported; community bridge dead — see
> `spike-log.md`). M1 itself completed successfully (diagnosis
> delivered). M2–M5 never started. Successor plan:
> `docs/plans/2026-07-28-bot-from-scratch/` (from-scratch Python
> memory-reader + synthetic input).

# PD2 offline kolbot — roadmap plan

## Size and why

`lg` / roadmap: five milestones, of which M2 (PD2 adaptation) likely needs
its own planning pass once M1's findings exist. M1 is executable directly
from [01-windows-spike.md](01-windows-spike.md).

## Goal

Create a working bot **based on kolbot** for Project Diablo 2, **offline
single-player only**, on Windows — plus:

1. A clear **instruction manual** (`docs/manual/`): how to set kolbot+PD2 up
   from scratch and how to configure it for specific characters and tasks.
2. **Component documentation** (`docs/architecture/`): how kolbot's parts
   (D2Bot#, D2BS, script libs, pickit, threads, OOG) actually function.
3. Customization via the **overlay approach**: this repo tracks only our own
   configs/run-scripts/pickit + sync mechanism; stock kolbot stays a
   pristine, updatable clone (gitignored at `kolbot/`).
4. Teaching artifacts per the agent-toolkit `/teach` skill; the project's
   teaching theme is *making efficient use of, and adapting, existing
   software solutions* — plus whatever is technically interesting inside
   kolbot (dll injection, in-process JS engine, NIP rule language, …).

First concrete target: **poison dagger necromancer running Countess**
(`kolbot/d2bs/kolbot/libs/scripts/Countess.js` is built in), expanding to
more runs afterward.

## Acceptance criteria

- Bot creates a single-player game on the PD2 offline client, runs Countess,
  picks up/stashes items per our pickit rules, handles death/errors, leaves
  and re-enters games unattended.
- Offline-only: no realm/battle.net use anywhere in config or docs.
- A newcomer with a Windows PC could reproduce the setup from
  `docs/manual/` alone.
- Component docs exist for every kolbot subsystem we touched.
- Overlay repo layout: wiping `kolbot/` and re-running our sync restores a
  working bot.

## Out of scope

- Online/realm/TCP play of any kind (hard exclusion, forever).
- Building bot logic from scratch (superseded plan — see notes.md
  reorientation entry).
- Multi-boxing, muling systems, leveling automation (SoloPlay) — future work
  candidates only.

## Discovery summary

See [notes.md](notes.md). Key facts: PD2 = modded D2 LoD 1.13c engine;
kolbot repo is actively maintained (commit 2026-07-27) and ships D2Bot.exe +
D2BS.dll + JS libs; per-class config overlays are the sanctioned
customization surface; single-player OOG flow is supported; **the repo has
zero PD2 references — kolbot↔PD2 compatibility is unvalidated, hence M1**.

## Repo layout decisions

- `kolbot/` — stock shallow clone of blizzhackers/kolbot, **gitignored**,
  refreshed via its own `update.bat`/git pull.
- `overlay/` — (created in M2) our tracked configs, pickit, run scripts,
  profiles + a sync script that copies them into `kolbot/`.
- `docs/manual/`, `docs/architecture/` — deliverable docs.
- Planning/reviews/learning per agent-toolkit structure.

## Milestones

| Milestone | Size | Summary | Needs own planning? |
|---|---|---|---|
| M1 | sm | Windows validation spike: D2BS injection into PD2 offline client works, or precise failure diagnosis + fallback decision. Phase file: [01-windows-spike.md](01-windows-spike.md) | No — executable now. **Review gate at end** (proceed/fallback decision with user) |
| M2 | md | PD2 adaptation: necro poison-dagger config, PD2 skill/item IDs, Countess run, pickit, stash/inventory behavior, overlay dir + sync script | Yes — run `yona-plan` again after M1 using spike findings |
| M3 | sm | Instruction manual in `docs/manual/` (seeded by M1 spike log) | No |
| M4 | md | Component documentation in `docs/architecture/` | No — research/writing, phased by subsystem |
| M5 | sm | Revisit fork-vs-overlay with evidence (ADR), then first usability/customization improvements | Decision point; scope known only after M2 |

## ADR expectations

`possible`: (a) end of M2 — overlay vs hard fork, with the actual list of
core files PD2 forced us to touch; (b) any security-relevant decision about
running/injecting the game client. Straightforward config work needs no ADR.

## Validation strategy

The bot drives a live game; validation is empirical on the Windows machine:
scripted runs observed end-to-end, D2Bot#/D2BS logs checked
(`kolbot/logs/`, `d2bs/kolbot/logs/`), spike/run logs captured into the
planning dir. No CI applies to milestone M1–M2 work beyond docs lint (if
any). Each milestone ends with the `/teach` step per CLAUDE.md.

## Constraints and conventions

- Offline-only is a hard constraint; treat any step that would touch
  battle.net as out of bounds.
- Don't edit files under `kolbot/` except as throwaway experiments during
  M1; durable changes belong in the overlay (M2+).
- Kolbot JS contributions style: repo uses biome (`npm run lint` inside
  `kolbot/`) — relevant only if we ever upstream fixes.
- Windows-machine sessions: read this plan + notes.md first; log findings
  back into the planning dir so both machines stay in sync via git.
