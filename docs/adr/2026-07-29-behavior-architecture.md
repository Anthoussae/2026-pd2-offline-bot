# Behavior architecture: a ticked engine, runs as data, reflexes above offense

Date: 2026-07-31 (M5 P4)
Status: proposed — drafted with the sim-only implementation; to be
finalized at P6 once the architecture has survived live staged acceptance.

## Context

M5 is the first end-to-end run, and the roadmap (decision 5) called for
the behavior architecture to be decided here: how "heal, waypoint to Cold
Plains, clear, pick up, leave" is expressed, how the user's survival
toolkit (R47) sits above offense, and how a second character class or a
second run gets added without rewriting the first.

Constraints that shaped the decision:

1. **Robustness before live runs** (user priority): dying during testing
   is the risk to design against. Whatever the architecture, its safety
   behavior must be fully testable against fakes before the game is ever
   involved, and `SafetyMonitor` (death latch, chicken) must remain the
   untouched last line beneath everything.
2. **The survival toolkit is priority-ordered** (R49, user-approved): a
   reflex ladder where the most urgent response wins and everything less
   urgent — including all offense — is skipped that tick.
3. **Runs and classes must be data** (R46 Q3/Q6): the user reads and
   tunes thresholds; runs never name a class; only the necro is
   implemented but nothing may structurally assume it.
4. **The integration point already exists**: M4's
   `cycle.run_games(callback)` was built for exactly this, with
   `ChickenExit`/`DeathHalt`/`NavigationError` semantics live-verified.
   The behavior layer must plug into it, not reshape it.
5. kolbot's three-layer pattern (engine / script-per-run / per-class
   attack module) is the proven design reference — as a *shape*, not as
   code (`kolbot/` is read-only and incompatible with PD2 1.13c).

## Options considered

1. **Monolithic run script** — one procedure: preamble, travel, fight,
   loot, in order, with survival checks sprinkled inline. Fastest to
   write; already how the town layer works internally. Rejected: the
   sprinkling is the flaw. Every new danger check must be added at every
   point that might be executing when it matters, and a missed spot is
   invisible until it kills the character. Survival must be structural,
   not remembered.
2. **Behavior tree** — the game-AI standard: a tree re-evaluated from
   the root each tick, priorities expressed as ordered fallbacks.
   Strictly more expressive than what M5 needs, and its expressiveness
   is its cost: dozens of node types, harder-to-read failure modes, and
   the user's ladder — which is *already* a priority list — would be
   encoded as a tree that merely simulates a list.
3. **Ticked FSM + data layers (chosen)** — kolbot's shape rebuilt on
   this project's rules: a small engine that ticks
   `snapshot -> monitor -> reflex ladder -> current step`, runs as
   declarative TOML over a step registry, a class-agnostic combat
   protocol with per-class TOML config, and the ladder as an ordered
   rung list evaluated before offense every single tick.

## Decision

`pd2bot/behavior/` with six small modules:

- **`engine.py`** — the ticked loop. Each tick: take a snapshot, let
  `SafetyMonitor.tick()` raise (its exceptions pass through untouched),
  evaluate the reflex ladder, and only if the ladder is quiet give the
  current run step its turn. A firing rung consumes the tick — offense
  and run progress cannot happen while survival has something to say,
  by construction rather than by discipline. The engine also owns the
  **never-idle invariant** (R47.9): outside town, no action sent and no
  progress made for `idle_bail_s` raises `IdleBail`.
- **`run.py`** — runs as TOML (`runs/*.toml`): an ordered list of steps
  with parameters, validated at load against a `StepRegistry` (unknown
  step, unknown/missing/mistyped parameter: loud `RunError` before the
  bot moves). Steps communicate through a shared blackboard
  (`EngineContext.notes`), which is how `waypoint` hands its arrival
  position to `clear_radius` without either knowing the other.
- **`reflex.py`** — the R49 ladder, rungs 3–8 (rungs 1–2 stay in
  `SafetyMonitor`, not reimplemented). Owns all cooldown and
  last-attempt bookkeeping (P2's primitives stay dumb). Blood warp is
  position-verified: an attempt that did not move the player is treated
  as still-on-cooldown, never re-spammed. Town suppresses rungs 3–7
  entirely (town guards read as monsters to perception — P1 drill D —
  so hostile-count triggers must not evaluate there); the armor recast
  is the one town-permitted rung, and desecrate/revive delegation is
  out-of-town only.
- **`combat.py`** — the `CombatModule` protocol (`engage`/`upkeep`,
  both returning declarative actions or None) plus the strict class
  config loader. Class TOML (`config/necro.toml`) carries hotkeys,
  live-captured skill ids, the R53 belt layout, and every ladder
  number; the loader rejects unknown keys anywhere, loudly — a typo'd
  threshold silently defaulting is the exact failure the robustness
  priority forbids. Ladder belt columns are *derived* from the belt
  layout so R53 cannot be half-updated.
- **`actions.py`** — the action vocabulary (`DrinkPotion`, `CastSelf`,
  `CastAtPoint`, `MoveTo`, `AttackUnit`) and the `ActionExecutor`
  protocol. P4 is sim-only because of this seam: everything above it
  emits data, and P5's executor is the single place that turns data
  into gated input (verified skill switches included).
- **`runner.py`** — the `run_games` callback boundary. `IdleBail` is
  typed as a `ChickenExit` subclass so the *unmodified* M4 cycle
  already leaves the game correctly; the runner counts idle bails
  separately (they are bugs, not vitals) and halts loudly on
  repetition (`IdleLoopHalt`, default 2 consecutive).

## Consequences

- Survival is structural: no step, run, or combat module can forget to
  check vitals, because none of them run on a tick where the ladder
  fired. The ladder itself is exhaustively unit-tested against
  scripted worlds — every rung's trigger, guard, cooldown, escalation
  (empty rejuv column + surrounded -> warp), and the priority order.
- A second run is a TOML file; a second class is a TOML file plus one
  `CombatModule` implementation. Neither touches the engine.
- The user tunes behavior in two commented TOML files and nothing
  else; typos fail at startup with the offending key named.
- The engine is class- and run-agnostic, which cost one indirection
  (the step registry) and one shared blackboard; both are load-time
  validated.
- **Known imperfection, accepted for now**: because `IdleBail` rides
  the `ChickenExit` path, the cycle's own consecutive-chicken counter
  also counts it. Consecutive idle bails halt with the honest
  idle-loop message first (both defaults are 2), but a mixed
  chicken-then-idle sequence can halt with the vitals message while
  the per-game log line names the idle bail. Fixing it fully is a
  one-line `cycle.py` change — deliberately out of P4's scope
  (cycle internals frozen); to be decided at the P5 gate.
- Rungs 1–2 living in `SafetyMonitor` means the ladder cannot
  reorder them below anything — the death latch and chicken fire
  before the ladder is consulted at all.
- The combat rotation, pickit, and the step handlers behind the run
  vocabulary are P5's; `build_states` refuses to build a run over a
  declared-but-unimplemented step rather than skipping it.
