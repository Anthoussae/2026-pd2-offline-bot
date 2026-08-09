# 003 — A dead watchdog spins create/leave instead of halting a battery

**Severity: P2** — accepted and documented during implementation, but the
case it is worst in is exactly Stage D.

**Where:** `pd2bot/behavior/engine.py` (`WatchdogDown`), `pd2bot/cycle.py`
(`run_games`), `pd2bot/wiring.py` (`main` pre-flight).

## What is wrong

`WatchdogDown` is a `ChickenExit` subclass with `is_vitals = False`, so
the cycle LEAVES the game cleanly and continues to the next one. That is
right for a single game: the character ends up somewhere safe rather than
standing in Hell.

For `--games N` it is wrong. If the watchdog dies during game 1, every
later game repeats: create, verify, take one tick, discover the stale
heartbeat, leave. Three wasted games and three real game creations, each
of which sends input, for a run that can never take a step.

The launcher's pre-flight (`--require-watchdog` in `wiring.main`) only
guards the FIRST game, because it runs once before `run_games`.

This was noted as an accepted residual in the plan's P4 result. Recording
it here because "accepted" was decided when Stage A (one game) was the
next thing; Stage D is three unattended games and makes it live.

## Suggested fix

Cheapest correct option: count consecutive `WatchdogDown` outcomes in
`cycle.run_games` and halt the loop after the first one, the way the
consecutive-chicken backstop already halts on vitals. A watchdog that is
gone will not come back on its own, so retrying has no mechanism to
succeed — which is the same argument the vitals backstop makes.

Alternative: have `run_games` re-check `watchdog_is_alive()` before
`create_game`, so the refusal happens before a game is made at all.

## Validation

- Unit, `tests/test_cycle.py`: a run callback raising `WatchdogDown` with
  `max_games=3` creates ONE game, not three, and the report says why.
- Confirm the vitals backstop still counts separately (R115): a
  `WatchdogDown` must not feed the "heal the character" counter, and a
  real chicken must not feed this one.
