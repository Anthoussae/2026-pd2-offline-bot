# Notes — package restructure (split the giants, group the layers)

Created 2026-08-09. Planning artifact for the structural refactor named
in the 2026-08-09 structure assessment: split `behavior/steps.py`
(3,327 lines) and `town.py` (2,438 lines) by concern, and group the
flat ~40-module `pd2bot/` package into subpackages so the architecture
is visible in the folder tree.

**Stated design goal from the user**: legibility and queriability for a
project owner inexperienced with software development and Python. The
folder tree should be readable as a map; finding "where is X handled"
should not require tribal knowledge.

## Discovery findings

### The giants' anatomy

- `behavior/steps.py` (3,327) splits naturally **by class** — the
  classes are already independent: `RunServices` (~330 lines, the
  services container), `TownPreambleStep`/`WaypointStep`/`DoneStep`
  (small), `_PickupMixin` (~780!), `_PatrolMixin` (~190),
  `ClearRadiusStep`, `PickupStep`, `SurveyStep`, `TraverseStep`,
  `ClearCountessStep` (~460), module helpers + `build_registry`.
- `town.py` (2,438) is harder: it is essentially **one class**,
  `TownLayer` (~60 methods, lines 366–2438), plus errors, `TownConfig`
  (~210 lines), `PreambleReport`. The methods group cleanly by concern:
  walking/approach (~350 lines), panel/dialog driving (~450), NPC
  services heal/repair/merc (~180), stash+gold deposit (~400),
  belt/potions (~300), inventory cleanse/manage (~350), preamble
  orchestration (~60). Splitting one class across files is done with
  **mixins** — a pattern this repo already uses (`_PickupMixin`,
  `_PatrolMixin`), mechanical and behavior-preserving; the alternative
  (decompose into collaborator objects) is a real redesign with real
  risk and is NOT proposed.

### The import landscape (what moves would touch)

- 760 `from pd2bot...` import statements across `tests/` (310, 53
  files), `drills/` (~70 files), `sims/`, and `pd2bot/` itself.
- The hub import is `from pd2bot import offsets` (38+ files). Keeping
  `offsets.py` at the package root preserves every one of them.
- 13 documented CLI invocations (`python -m pd2bot.dump`, `.wiring`,
  `.navigate`, `.cycle`, `.oog`, `.chat`, `.collision`, `.navdemo`,
  `.runlog`, `.partyline`, plus `-m pd2bot.watchdog` in
  `tools/guarded-run.ps1`) appear in README, CLAUDE.md, tools/*.ps1,
  docs/architecture, drill protocols — and the user's muscle memory.
  **These must keep working verbatim** → thin root shims.
- `wiring.py` imports 29 pd2bot modules (it is the assembler — fine).
- 12 modules have `__main__` blocks.
- Python re-export trick that saves churn: if `input/` becomes a
  package whose `__init__.py` re-exports `GatedInput`, then
  `from pd2bot.input import GatedInput` (the current spelling) still
  works although the class now lives in `input/gated.py`. Same for
  `runlog/`.

### Conventions that bind this work (from CLAUDE.md)

- `GatedInput`'s guard is contractual — the refactor moves it, must not
  edit it. Same for the death latch and the no-starvation rule.
- Tests must stay green per phase (1169 today; CI enforces on push).
- Docs reference module paths (`pd2bot.input.GatedInput`,
  `pd2bot/cycle.py`, `navigate.py`'s `_wait`, ...) in CLAUDE.md, README,
  docs/architecture/*.md — final sweep required. The agent's own memory
  files also reference `pd2bot/partyline.py` (minor, update at closeout).

## Proposed target structure

Subpackage names deliberately mirror `docs/architecture/*.md`
(perception, navigation, game-cycle→kept as root `cycle.py`, behavior,
run-log) so the folder tree and the documentation use one vocabulary.

```text
pd2bot/
  README.md          NEW — the package map: one line per entry, kept current
  offsets.py         stays at root: the memory-map vocabulary every layer shares
  dump.py wiring.py navigate.py collision.py cycle.py oog.py chat.py
  navdemo.py runlog.py partyline.py watchdog.py mapdata.py
                     ^ the COMMANDS — after the move, each is either a thin
                       shim ("machinery lives in nav/…") or a small real
                       module (cycle.py, drill.py stay whole)
  perception/        seeing: memory.py units.py player.py items.py world.py
                     uistate.py oog_read.py chatread.py exits.py snapshot.py
  input/             acting: gated.py menu.py panel.py chat_send.py skills.py
                     window.py screen.py  (__init__ re-exports GatedInput, …)
  nav/               moving: pathing.py navigate.py collision_read.py
                     mapstore.py mapframe.py survey.py waypoint.py mapdata.py
  safety/            not dying: safety.py watchdog.py
  runlog/            remembering: events.py narrate.py (re-exports keep
                     `from pd2bot.runlog import …` valid)
  behavior/          deciding: engine.py reflex.py necro.py combat.py
                     execute.py actions.py run.py runner.py pickit.py
    town/            town errands (the town.py split): config.py walk.py
                     panels.py services.py stash.py belt.py inventory.py
                     layer.py (TownLayer = the mixins composed) preamble.py
    steps/           run steps (the steps.py split): services.py basic.py
                     pickup.py patrol.py clear.py survey.py traverse.py
                     countess.py registry.py
  drill.py uipoints.py   root: small, single-purpose, heavily referenced
```

Open naming details for the implementer (not user questions): exact
shim-vs-move split per CLI module; `oog_read`/`collision_read` naming
where a root command and a moved module would collide.

### Legibility features (the user's explicit goal)

1. Folder names match the architecture docs — one vocabulary everywhere.
2. `pd2bot/README.md` (new) is the map; each subpackage gets a
   one-screen `README.md` saying what lives there and what its public
   names are. Greppable, browsable on GitHub.
3. Root listing = the commands the user types + the shared vocabulary.
4. Every module keeps a first-line docstring stating its one job (most
   already have this; the sweep enforces it).
5. Tests mirror the tree (`tests/perception/test_units.py`, …) so
   "where is X tested" has the same answer as "where is X".

## Questions

- R239: Q-A timing (discussion) + Q1–Q7 confirmations — see chat and
  instruction log.

## User answers / scope changes

- R239 answered (2026-08-09): **"now; all yes, then /yona-implement."**
  Q-A: execute immediately on a dedicated `restructure` branch off
  `m6-countess`, M6 code work paused; live smoke run gates the
  merge-back. Q1–Q7 all as suggested. Implementation authorized in the
  same message (commit-per-phase and the final merge-back covered by
  it, per the R237/R238 precedent).

## Risks and mitigations

- **Mechanical churn** (760 imports): per-phase, tests green after each
  phase, CI on every push; no logic edits mixed into move commits.
- **Live-verified code**: file moves and mixin extraction change no
  behavior, but the final acceptance includes one live smoke run
  (Cold Plains via the bridge) before the branch merges back.
- **Contested files with M6**: doing this mid-M6 on a branch means the
  eventual merge back must be careful around `steps.py`/`town.py` if M6
  work continues in parallel. Mitigation: pause M6 code changes for the
  (short) duration, or execute at the boundary — the timing question.

## Out of scope / future work

- Decomposing `TownLayer` into collaborator objects (a redesign, not a
  reorganization) — future, if town logic keeps growing.
- Renaming public classes or changing any behavior/guards.
- Docstring/comment quality pass beyond the first-line-docstring rule.
- Splitting `engine.py`/`reflex.py` (each <1,000 lines — fine for now).
