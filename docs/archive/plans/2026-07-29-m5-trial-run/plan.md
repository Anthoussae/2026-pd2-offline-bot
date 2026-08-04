---
kind: plan
size: md
depth: implementation
status: done
repo: 2026-pd2-offline-bot
created: 2026-07-29
completed: 2026-08-03
adr: delivered (2026-07-29-behavior-architecture.md, accepted)
---

# M5 — trial run: Cold Plains clearance (Hell)

## Size and why

`md`: six phases, each `sm` except the acceptance phase. One agent can
execute end-to-end, but the work has two hard review gates (end of P3,
end of P5) and a staged live-acceptance ladder that needs the user at
the machine. **Execution is strictly sequential** (user decision, R50).

## Goal

The bot's first real run, unattended: cycle Hell games; in each game
run the town preamble (heal → stash → belt refill → conditional merc
resurrect), take the town waypoint to Cold Plains, clear every hostile
within 150 subtiles of the Cold Plains waypoint with the poison dagger
necromancer kit, pick items per a human-readable pickit, and leave.
This is the milestone that builds the behavior architecture (FSM +
runs-as-data + class-agnostic combat modules) — the roadmap's third
expected ADR.

## Acceptance criteria

- **3 clean unattended Cold Plains runs** via the real CLI: created,
  Hell-verified, preamble done, waypoint taken, radius-150 clearance,
  pickit honored, left — zero human input, no safety-monitor trips.
- Staged ladder passed on the way there (P6): supervised combat drill,
  then supervised full run, then unattended.
- All sim-testable logic unit-tested before anything runs live
  (standing constraint: robustness before live runs, M4 notes).
- Behavior-architecture ADR written; `docs/architecture/behavior.md`
  exists; teach step done.

## Scope boundaries

**In scope**: waypoint usage (R46 Q1 — town WP → Cold Plains);
panel-scoped input (third narrow path); carried-item/belt/object/skill
perception; reflex ladder with R49 thresholds; trial pickit
(quality/kind tiers, TOML); stash deposit with full-stash guardrail;
belt refill from inventory with below-minimum loud halt (R48 b);
conditional merc resurrect (dead + gold > 49,999).

**Out of scope**: vendor/shopping UI (R48); cross-area walking and the
union grid (waypoint travel replaced it — M6, Countess); doors; corpse
retrieval / death recovery (deferred, low priority, user decision);
stat-based `.nip`-style pickit language (M6); TP tome and bone wall
usage (noted for future, low prio); leveling, multi-boxing, muling.

**Inviolable**: the death latch (no input after death, ever; no
recovery behavior without an explicit user decision). `GatedInput` and
`MenuInput` guards are not weakened — new capabilities get new,
separately-guarded narrow paths.

## Discovery summary

See [notes.md](notes.md) — discovery log, the full R46–R50 record
(including the character-kit inform, R47), and design consequences.
Highlights:

- `cycle.run_games(run_callback)` is the intended entry point; safety
  monitor, chat, gated right-click and `press_key` already exist.
- Left skill is permanently Poison Strike; the right skill rotates via
  F1–F6; every switch must be verified by reading the active skill
  back from memory before any cast click.
- In-game panels (waypoint list, NPC dialog, stash/inventory) are
  clickable by neither existing input path → new `PanelInput`.
- `read_stats` works on any unit — bone armor absorb, corpse modes and
  item details are stat/field reads away, not new machinery.
- PD2 facts from the user: shift+right-click transfers on the stash
  screen; rejuvs cannot be bought; desecrate/revive not castable in
  town; revives last ~300 s; blood warp costs 10 mana +
  max(12% HP, 12).

## Files/modules expected to change

- `pd2bot/offsets.py` — skill/Info structs, object path, ItemData
  location fields, stat ids (bone armor), id tables (NPCs, potions,
  gold, waypoint/stash objects), monster corpse modes. All cited per
  the offsets.py convention.
- `pd2bot/units.py`, `player.py`, `dump.py` — monster `mode`, object
  units, skill reads, merc/revive counts, dump extensions.
- New: `pd2bot/items.py` (carried items/belt/inventory),
  `pd2bot/panelinput.py`, `pd2bot/skills.py`, `pd2bot/town.py`,
  `pd2bot/waypoint.py`, `pd2bot/pickit.py`, `pd2bot/behavior/`
  (engine, ladder, combat interface, necro module), `runs/` +
  `config/` TOML data files.
- `pd2bot/input.py` — shift-hold click addition (same gate, no
  guard change).
- `pd2bot/cycle.py` — run callback wiring only (no cycle FSM changes
  expected).
- `tests/` — extensive; every phase adds sim tests.

## Documentation expected to change

- `docs/architecture/behavior.md` (new, P6); pointers from
  `perception.md` (items/objects/skills), `game-cycle.md` (run
  callback now real), `navigation.md` (waypoint travel note).
- `README.md` — new CLIs and data files; `CLAUDE.md` — M5 status line,
  fourth narrow input path; roadmap `plan.md` M5 row.
- `docs/adr/` — behavior architecture ADR (P6, drafted P4).
- `docs/learning/` — teach explainer + glossary (P6).
- `docs/instruction-log.md` — continues from R50.

## Architecture / decisions

1. **Behavior architecture (ADR, drafted P4, finalized P6)**: ticked
   engine; runs as declarative TOML; class-agnostic combat-module
   interface + per-class TOML config (necro only implemented);
   priority-ordered survival reflex ladder evaluated every tick above
   offense; `SafetyMonitor` untouched underneath as the last line.
2. **Panel-scoped input**: third narrow path (`PanelInput`), guard =
   in game AND the specific expected panel verified open AND
   foreground, re-checked at send. Chat's construction rules.
3. **Config/data format**: TOML (Python 3.12 stdlib `tomllib`;
   human-readable with comments — an explicit user requirement for
   the pickit).
4. **Verified-switch pattern**: no cast click until the right-skill id
   read from memory equals the intended skill (difficulty-guard
   pattern applied to skills).
5. **Never-idle-out-of-town invariant**: if the behavior loop makes no
   decision/progress for T seconds outside town, leave the game (an
   idle character in Hell is a dead character — R47.9).

## Validation strategy

- Unit tests with fakes and injected timing for all pure logic (FSM,
  ladder priorities, pickit evaluation, TOML loaders, town/waypoint
  state machines). `& "$HOME\.venvs\pd2bot\Scripts\python.exe" -m
  pytest -q` and `... -m ruff check .` green at every phase end.
- Live checks agent-driven via the elevated bridge
  (`tools/elevated-bridge.ps1`); user needed for game-side actions
  only, via numbered requests (continue from R50).
- Staged live ladder (P6): supervised drill → supervised full run →
  3 clean unattended runs. Nothing live before P5's go/no-go gate.

## Phases

| Phase | Size | File | Summary | Review gate |
|---|---|---|---|---|
| P1 | sm | [01-perception-extensions.md](01-perception-extensions.md) | Skills, bone-armor stat, corpses, objects, carried items/belt, id tables, dump CLI | none |
| P2 | sm | [02-input-extensions.md](02-input-extensions.md) | `PanelInput`, shift-hold click, verified skill switch, belt keys; town drills | none |
| P3 | sm | [03-town-and-waypoint.md](03-town-and-waypoint.md) | Heal, stash + guardrail, belt refill + halt, merc resurrect, WP travel | **end of phase** (user observes drills + WP round trip) |
| P4 | sm | [04-behavior-engine.md](04-behavior-engine.md) | FSM engine, runs-as-data, combat interface, reflex ladder, never-idle; ADR draft | none (sim only) |
| P5 | sm | [05-combat-and-pickit.md](05-combat-and-pickit.md) | Necro skirmish pattern, desecrate→revive, pickit + pickup, Cold Plains run def | **end of phase** (go/no-go before live) |
| P6 | md | [06-staged-acceptance-closeout.md](06-staged-acceptance-closeout.md) | Staged live acceptance, tuning, docs, ADR final, teach, sweep | final |

## Implementation log convention

Completion is recorded by `yona-implement` in `_DONE.md` in this
directory (outcome, validation, deviations, docs, ADRs, follow-ups).
Do not rename `plan.md` or the phase files on completion.
