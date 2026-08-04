# 003 — The idle watchdog can fire during waits the design asks for

Severity: **P2** — **FIXED** 2026-07-31

`pd2bot/behavior/engine.py` (`_check_idle`, `idle_bail_s` default 10.0),
`pd2bot/behavior/steps.py` (`clear_settle_s` default 5.0),
`pd2bot/behavior/necro.py` (`restrike_s` 6.0, `wait_for_revives_s` 1.5).

## What is wrong

Several knobs describe *deliberate* periods of doing nothing, and the
watchdog that punishes doing nothing knows about none of them. They are
in different files, owned by different configs, and nothing checks them
against each other.

Probed with `clear_settle_s = 15.0` and everything else at defaults:

```
IdleBail fired during a legitimate settle: no action sent and no
progress for 11.0s outside town (limit 10s)
```

The shipped defaults are safe — 5 s settle and a 6 s restrike both sit
under the 10 s limit — but only by a margin nobody declared. The
worst realistic default case is already 6 s: every hostile freshly
poisoned, the player standing still, waiting out `restrike_s`.

## Why it matters

`IdleBail` is a `ChickenExit` subclass, so it leaves the game; two in a
row is a loud halt. A user who lengthens the clearance settle, or the
revive wait, or the restrike interval — all of which look like
independent tuning knobs — gets runs that abandon themselves, and the
message blames an "idle loop" rather than the config.

## Suggested fix

Make the coupling explicit rather than coincidental. Options, cheapest
first:

- validate at wiring time: `idle_bail_s` must exceed the largest
  declared wait (`clear_settle_s`, `restrike_s`, `wait_for_revives_s`)
  by a margin, and fail loudly at startup if not;
- or let a step declare "I am deliberately waiting" in its
  `StepOutcome`, and have `_check_idle` treat that as progress — the
  watchdog then only catches waits nobody asked for, which is what it
  is for.

The second is the honest model: the invariant is about the bot being
STUCK, not about it being still.

## Validation

The probe above, as a test: `clear_settle_s` above `idle_bail_s` should
either be refused at construction or survive the settle.

## Resolution

Fixed 2026-07-31 with the second option — the honest model.

`StepOutcome` gained `waiting: bool`, and `_check_idle` treats a declared
wait as progress. `ClearRadiusStep` sets it in the two places the design
asks the bot to stand still: the settle timer, and the tick where combat
has nothing to send because everything is freshly poisoned or the revives
have not taken the front (`restrike_s`, `wait_for_revives_s`). The
watchdog now catches waits nobody asked for, which is what it is for.

The first option — validating `idle_bail_s` against the declared waits at
wiring time — was deliberately NOT also taken. With `waiting` in place it
guards nothing the model does not already guard, and it has the same
failure mode as the thing it would protect (a wait nobody remembered to
declare is also a wait nobody remembered to pass to the validator). One
mechanism that works beats two that each half-work.

Tests: the review's probe as `test_a_declared_wait_is_not_idleness` (32 s
of deliberate waiting against a 10 s limit), plus
`test_an_undeclared_wait_still_bails` so the watchdog is provably not
disarmed.
