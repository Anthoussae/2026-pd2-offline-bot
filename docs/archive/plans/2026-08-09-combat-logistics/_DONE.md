---
kind: implementation-log
status: done
repo: 2026-pd2-offline-bot
plan: plan.md
completed: 2026-08-14
commit: ebabe07
adrs:
  - docs/adr/2026-08-09-posture-fight-styles.md
  - docs/adr/2026-08-09-vendor-buying.md
  - docs/adr/2026-08-13-keybindings-from-the-client.md
  - docs/adr/2026-08-14-bounded-pathfinding.md
---

# Combat logistics â€” done

## Outcome

All six phases complete and live-verified, plus **three operator
detours** that grew into the workstream's biggest wins. The branch
merges to `m6-countess` with the flagship inheriting: the config trio,
the route leash, postures with **berserk as the standing default**,
the Akara restock chore, and `mandatory_pickup` **promoted into
countess.toml by the R246 census gate**.

## Completed work

- **P1â€“P5** (per the phase files): config trio; route line + leash
  (`nav/routeline.py`, `route.stray` telemetry); posture styles +
  berserk (`style = "charge"`, R241); Akara restock (stock read per
  visit, belt refill, potion pickit rules retired on its success);
  mandatory pickup (the order book: open â†’ resight-through-combat â†’
  id-churn rebind â†’ expiry â†’ full-inventory â†’ queued/mid-field cleanse
  â†’ budget close), piloted live and census-gated.
- **P6** (this closeout): `pickup.order_book_diag` scaffolding removed;
  scratch runs deleted (leash/berserk acceptance, restock-test, both
  pilot-orders files; the t90 battery files kept as test kit); the
  three tagmode-review P3s FIXED with tests (001 `registered_say` â€”
  abort-safe, echo-safe run chat; 002 boundary `resolving` scoring;
  003 the battery chat's inventory allowance); teach explainer
  `docs/learning/2026-08-14-measuring-before-fixing.md` + 7 glossary
  terms; `project-state.md` refreshed (was R236/T82-stale); R242 and
  R246 resolved; merged to `m6-countess`.
- **Detour 1 â€” hotkey config** (R247, archived
  `2026-08-13-hotkey-config`): bindings read from the client's .key
  file, verified against the toml, per-game re-read. ADR accepted.
- **Detour 2 â€” tag-mode calibration** (R248â€“R254, T90/T91, archived
  `2026-08-13-pickup-tagmode-calibration`): NO NAME TAGS is the
  standing pickup policy (30/30 = 100% vs 10%/36%; the executor's
  force-labels-ON policy falsified by its own measurement and
  inverted). Standing kit: the run abort channel, the watchdog 15 s
  staleness grace, per-drop floor confirmation, `BH_FILTER_STYLE`.
- **Detour 3 â€” the locomotion speed pass** (R255â€“R262, T92/T93,
  archived `2026-08-13-clear-radius-locomotion`): Cold Plains 454 s â†’
  ~150â€“180 s typical. The human benchmark method (`pd2bot.observe` +
  `runlog.compare`/`locomotion`), bounded A* (ADR), berserk default,
  walk-in attacks, the seam gate, the stall-family bucket, the chase
  gate. Two changes falsified and reverted with their measurements.

## Validation

Suite grew 1221 â†’ **1349 tests, green**, ruff clean throughout; every
live claim traces to a named run log. Live totals across the
workstream: the R244/R245 pilot batch, fifteen T90 battery rounds,
eleven T93 acceptance launches, one human benchmark recording â€”
monitor silent in all, zero deaths, one chicken-free cycle.

## Deviations

The three detours themselves (each operator-ordered, each with its own
archived record) â€” the plan's shape held around them. The tag-mode
result INVERTED a standing executor policy mid-plan; berserk was
promoted from "a posture" to "the default" by R256 QA, beyond P3's
original scope.

## Documentation

behavior.md, navigation.md, run-log.md, game-cycle docs (per phase
work), performance-notes.md re-priced, project-state.md refreshed, the
teach explainer + glossary. ADRs as listed in the frontmatter.

## Follow-ups

Tracked in `project-state.md`: the fresh Countess run under everything
merged (then the M6 P5 acceptance battery); the stash-open base-rate
watch; waypoint SW aim; ring 537 deposit retry; `field_at` â†’ `cast_at`
rename; the watchdog transient-stall root cause; the diffuse-block
"continuous movement" redesign idea.

