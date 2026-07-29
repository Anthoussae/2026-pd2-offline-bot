---
kind: plan
size: md
depth: implementation
status: done
completed: 2026-07-29
commit: e6dabec
repo: 2026-pd2-offline-bot
created: 2026-07-28
adr: possible
---

# M4 — game cycle

Roadmap milestone M4 of
[2026-07-28-bot-from-scratch](../2026-07-28-bot-from-scratch/plan.md):
the bot learns to cycle games unattended — create a single-player game
from the menus, exit it, guard itself with chicken logic, stop dead
(literally) on death, and run this in a loop. The prerequisite for
M5's real runs.

## Size and why

`md`: five `sm` phases. One agent can execute end-to-end, but the work
has natural checkpoints (a strategy decision after live-checking the
control list in P1; a live acceptance gate after P3) and live
verification interleaved throughout, all through the user request
protocol.

## Goal and acceptance criteria

From a running PD2 offline client (launched by the user via
PD2Launcher — we attach, never launch):

1. **Cycle**: with the client at char select or in a game, the bot
   completes **≥ 3 consecutive unattended game cycles** (create game →
   verify Hell → dwell in game → save and exit → repeat), no human
   input. This is the live acceptance gate (end of P3).
2. **Difficulty guard**: every entered game is verified as Hell by a
   memory read before the run callback executes; a wrong-difficulty
   game aborts the cycle loudly (protects the atlas from
   wrong-difficulty poisoning — user decision at R29).
3. **Chicken**: life/mana thresholds trigger an emergency exit;
   demonstrated live via the zero-risk mana-threshold method (P4).
4. **Death = full stop**: a dead player snapshot causes a permanent
   halt — no further input of any kind — plus a loud alert
   (user decision R27/Q6). Simulation-tested only; no live death.
5. **Focus loss**: refocus once after a short delay; if refused or
   focus keeps vanishing, pause and wait for a human (R27/Q8).
6. Existing suite still passes (121 tests at M3 close), new logic
   unit-tested against fakes, `ruff check` clean, docs + teach done.

## Scope boundaries

- **In**: OOG menu perception (D2Win control list), separately-guarded
  menu input, create/leave game, cycle FSM + error taxonomy, chicken,
  death→halt, dwell-run skeleton with pluggable run callback.
- **Out** (explicit user decisions): corpse retrieval and automated
  death *recovery* (deferred, low priority — R27/Q6); merc/golem
  chicken and potion drinking (M5 — Q3/Q4); door handling (M5/M6 —
  Q5); the survival toolkit / defensive reflex ladder (M5 planning
  discovery — see notes.md "The survival toolkit"); relaunching a dead
  client (we only attach); any actual run content (M5).

## Discovery summary

See [notes.md](notes.md). Load-bearing facts:

- **Menus are memory-readable**: D2's OOG screens are built from a
  control list (buttons with type/position/size/text) in D2Win.dll —
  kolbot/D2BS's `getLocation()` + `Controls.X.click()` pattern. We read
  the same list out-of-process; offsets come from the D2BS-lineage
  sources already cited for CollMap. PD2-client fidelity is live-checked
  in P1 before anything builds on it; a blind fixed-coordinate fallback
  hides behind the same interface if needed (pre-approved, R27/Q1).
- **The SP flow is short**: leave = ESC → "Save and Exit Game" → char
  select (char stays pre-selected); create = OK → difficulty popup →
  Hell → loading → `is_in_game`. M3's R14 proved the map seed (and the
  atlas) survives a full cycle.
- **Chicken** (kolbot `ToolsThread.js`): percentage thresholds checked
  per tick; potting is a separate concern (M5). Our exit path
  (ESC + click) is slower than kolbot's API quit, but ESC *pauses* the
  offline game instantly, so once ESC lands we are safe.
- **Death**: player `UNIT_MODE` 0 (dying) / 17 (dead)
  (kolbot `sdk.d.ts:1550`); hp 0 corroborates.

## Files/modules expected to change

- New: `pd2bot/oog.py`, `pd2bot/menuinput.py`, `pd2bot/cycle.py`,
  `pd2bot/safety.py`; tests for each under `tests/`.
- Touched: `pd2bot/offsets.py` (control-list block + difficulty byte,
  both cited), `pd2bot/world.py` (`read_difficulty`).
- **Not touched**: `pd2bot/input.py` — `GatedInput`'s guard is
  load-bearing and stays exactly as it is (CLAUDE.md invariant).

## Documentation expected to change

`docs/architecture/game-cycle.md` (new), pointers from
`perception.md`/`navigation.md`, `README.md` (new CLIs), `CLAUDE.md`
(M4 status), roadmap M4 row, `docs/learning/` teach explainer +
glossary (P5).

## Decisions already made (do not relitigate)

All at R27/R29, recorded in notes.md: control-list-first with blind
fallback; separate `MenuInput` guard; chicken-only safety in M4;
death → permanent halt + alert, no recovery; difficulty read as an
unconditional post-join guard (not an atlas re-keying feature);
refocus-once-then-pause focus policy.

## ADR expectation

`possible`, leaning none: the menu-input guard is incident-forced (like
`GatedInput` — documented in architecture, not chosen among
alternatives), and OOG reading extends the already-ADR'd perception
approach. Escalate to an ADR only if the control-list-vs-fallback
choice turns out to have lasting architectural consequences.

## Validation strategy

Unit tests against fake memory buffers / fake OS layers (established
pattern — the game is never required by pytest); `python -m pytest -q`
and `python -m ruff check .` per phase; live verification per phase via
🔶 numbered user requests (elevated terminal, human present), IDs
continuing from the instruction log (next: R30). Live acceptance gate
at end of P3.

## Phases

| Phase | Size | Summary | Depends on | Review gate |
|---|---|---|---|---|
| [P1](01-oog-perception.md) | sm | OOG perception: control-list read, screen classification, difficulty byte, `pd2bot.oog` CLI | — | None (strategy report at end) |
| [P2](02-menu-input.md) | sm | `MenuInput`: the second, separately-guarded send path | — (parallel with P1) | None |
| [P3](03-game-cycle.md) | sm | Cycle FSM: leave/create, difficulty guard, error taxonomy, run-loop skeleton, CLI | P1, P2 | **Live acceptance: ≥3 unattended cycles** |
| [P4](04-safety-monitor.md) | sm | Safety monitor: chicken → emergency exit; death → permanent halt | P3 | Live mana-chicken demo |
| [P5](05-docs-teach.md) | sm | Docs, cleanup sweep, teach | P1–P4 | None |

Completion: `yona-implement` writes `_DONE.md` here, flips this
frontmatter to `status: done`, and updates the roadmap M4 row.
