---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-02
commit: 26857c1
adrs:
  - docs/adr/2026-07-29-behavior-architecture.md (amended, no new ADR)
---

# Implementation log — potions overhaul + narrative log + route-aware legs

## Outcome

All five phases implemented and validated in one session (P1 → P2 → P3
→ P5 → P4). 823 tests green (was 788 at cycle start counting P1's own
additions; net +35 over the pre-cycle suite), ruff clean. Live
validation deliberately rides the next normal runs per the plan's
acceptance; the end-of-phase STOP report went out as R182.

## Completed work

- **P1 — type-based belt.** Drink rungs search all four columns for the
  needed type (configured column preferred; `_potion_column`). The town
  minimum check counts per type across the whole belt and halts ONLY on
  mechanical failure — a short type with inventory stock AND a column
  that would take it (`_belt_accepts`, `offsets.BELT_ROWS`); no-stock
  shortfalls are a notice on a continuing run. The R178 mixed-belt halt
  shape is now a regression test; the test fake models honest
  column-routing (squatters cost their slot).
- **P2 — merc first aid.** `GatedInput.press_key_with_alt` (Alt settled
  down before the key, released in a `finally`), `skills.belt_give_merc`,
  `GiveMercPotion` action (keypress path, never queues behind a cast),
  reflex rung 7.5 (below every player rung, above armor upkeep; paced on
  attempt; never in town; uses P1's type search). Config:
  `merc_heal_below_pct = 50.0`, `merc_heal_retry_s = 3.0` (R179).
- **P3 — narrative log.** `pd2bot/narrate.py` (per-run
  `logs/run-<stamp>.log`, wall-clock stamps, lazy file creation, `span`,
  stdout echo `»`; coarseness contract in the docstring). `narrate`
  callables on RunServices/engine/TownLayer (no-op default). Engine
  narrates the run header, step completions with durations, and the run
  summary; the preamble narrates one line per station with its duration;
  editorial step sites (pickups, write-offs, cleanse, patrol give-ups).
  One Narrator per run in wiring; `narrate_ref` holder bridges the
  session-scoped town layer. Sim test enforces O(actions) line count.
- **P5 — route-aware legs.** `wiring.route_service(navigator)`:
  read-only A* + simplify over the navigator's grid, cached per
  (8-subtile origin bucket, target), grid assembled only on cache miss.
  `RunServices.route_to`; patrol, survey, and the clearance's closing
  approach walk the route's next waypoint (capped at `patrol_step`);
  `route_to(...) is None` is an instant write-off. `NecroCombat.approach`
  takes `via` (gates on the monster, steers by the route); the module
  stays grid-ignorant. Zone containment falls out: routes planned on the
  area's grid never cross exits the target is not behind.
- **P4 — docs, cleanup, validation.** ADR amendments, navigation.md
  route-service section, perception.md ALT note, `.gitignore` `logs/`,
  cleanup sweep clean, teach step done.

## Validation

```powershell
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m pytest -q   # 823 passed
& "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe" -m ruff check .  # clean
```

Run after every phase; final run after the docs pass.

## Deviations

- P1: "inventory/stash stock" — the halt's stock check counts the main
  inventory only; no stash-withdrawal machinery exists (potions are
  never stashed by bot policy). A stash-only restock yields the notice,
  not a halt.
- P3: fight ENGAGE/DISENGAGE narration is carried by the clearance
  step's completion note rather than per-fight narrate calls — the
  combat module is deliberately service-blind. Revisit if a live
  narrative reads too sparse in combat.
- P5: `engage`-internal dashes (mid-fight, inside `engage_radius`) keep
  the bearing; the plan scoped routing to the step-mediated approach.
  The route-cache test caught the grid being assembled on cache hits;
  fixed by moving the grid read behind the cache check.

## Documentation

- `docs/adr/2026-07-29-behavior-architecture.md` — Amendments section
  (belt contract, rung 7.5, narrative channel, route service pointer).
- `docs/architecture/navigation.md` — "The route service: steps ask the
  map too (R181)".
- `docs/architecture/perception.md` — ALT visibility non-issue (R179-1a).
- `docs/learning/2026-08-02-honest-halts-and-logs-for-humans.md` + 5
  glossary entries (teach step).

## ADRs

No new ADR — every change extends patterns the 2026-07-29 behavior ADR
already records, so that ADR was amended instead (plan.md called this).

## Follow-up work

- Live validation (R182): one run of anything proves the narrative log;
  a deliberately mixed belt proves P1; a merc chip-damage moment proves
  P2; the next patrol/survey exercises P5's routes and fast write-offs.
- Open session-review issues 002-004 (frontier stride doorways, survey
  cache key, hp-window clock re-read) remain folded into future phases.
- ALT-1b (label-off policy) stays deferred, evidence-gated on the run-3
  click audit (which came back 2/339 — the evidence gate is unlikely to
  open).
