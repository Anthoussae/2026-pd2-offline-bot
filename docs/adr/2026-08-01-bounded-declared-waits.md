# A declared wait is a claim with a deadline

Date: 2026-08-01 (M5 P6, from the stage-B review)
Status: accepted

## Context

The never-idle invariant (R47.9, from the user's own danger assessment:
any enemy can kill an idle character) says the bot must not stand outside
town doing nothing. `BehaviorEngine` enforces it with a watchdog: no send
and no progress for `idle_bail_s` raises `IdleBail`, the cycle leaves the
game, and `runner.py` halts loudly if it repeats, because an idle loop is
a bug rather than a vitals problem.

Then the watchdog started firing on waits that were entirely deliberate.
Several of them exist and they are configured in different files by
different owners — `clear_settle_s` (the clearance's wait for the radius
to stay clear), `restrike_s` (poison is doing the killing, so a struck
monster is left alone), `wait_for_revives_s` (let the tanks get in
front) — and the watchdog knew about none of them. Raising any one past
`idle_bail_s` made a run abandon itself with a message blaming an idle
loop. Review 003 of the trial-run cycle fixed that with
`StepOutcome.waiting`: a step could say "I am standing still ON PURPOSE",
and the watchdog counted it as progress.

That fix was right, and it removed the alarm from the one path that then
grew a genuine hang. Stage B's review (finding 001) found it: combat
repositioning could drift the player out of `engage_radius` while
`clear_radius` — which measures from the arrival point, not from the
player — still wanted those monsters dead. `engage` returned None every
tick, the step had nothing to send, so it reported `waiting=True`, and
`waiting` suppressed the watchdog. A permanent hang with the alarm
switched off on exactly that path.

The specific defect is fixed at its source. The question this ADR settles
is the general one: **when may a wait suppress the never-idle watchdog?**

## Decision

**A declared wait is a claim that something will EXPIRE, and the engine
holds it to a deadline.**

`EngineConfig.wait_bail_s` (30 s) bounds an unbroken run of ticks that
report `waiting=True`. Past it the engine raises `IdleBail` naming the
step, which routes exactly as any other idle bail does: leave the game,
count it in the runner, halt loudly on repetition.

Three details carry the intent:

- **The streak is what is bounded, not the total.** Progress clears it —
  a reflex send that landed, a step that acted, a step that finished. A
  clearance that loots between settle polls is working, not hung.
- **Movement does not clear it.** The idle watchdog treats movement as
  progress, because a walk in flight sends nothing new per tick. A wait
  is different: a character being shoved around by monsters while a step
  waits forever is the hang, not the cure.
- **Town is exempt**, for the same reason the idle check exempts it: town
  steps block on walks and town is safe by definition.

The number is set well above every timer in the bot rather than close to
any of them: 6x the longest configured wait (`clear_settle_s`, 5 s) and
3x `idle_bail_s`. It is not a tuning knob for pacing. It can only be
reached by a wait that is not a wait at all, which means reaching it is
always a bug report.

## Options considered

1. **Leave `waiting` as a blanket exemption and fix each hang at its
   source.** What we had. Rejected on the evidence: the exemption was
   introduced for three known waits and the hang arrived through a fourth
   path nobody had enumerated, in the same session. A safety net whose
   holes must be predicted in advance is the shape this project has
   already been burned by twice (the runner's list of survivable
   exceptions, which had to be extended four times before the default was
   flipped).
2. **Make every step declare how long it intends to wait**, and bail when
   it overruns its own estimate. Most precise, and rejected as too much
   ceremony for the benefit: it puts a number on every `waiting` return
   site, those numbers then have to track the configs they stand for, and
   the failure being guarded against is not "waited 6 s instead of 5" but
   "waited forever".
3. **Drop `waiting` and raise `idle_bail_s` above the longest wait.** The
   simplest, and it is what review 003 rejected already: it couples one
   global timer to every local one, so tuning any wait means re-tuning the
   watchdog, and the watchdog gets slower at catching real hangs each
   time. `waiting` exists precisely so the two are independent.
4. **A distinct exception type for an over-long wait.** Rejected as a
   distinction without a difference: the response is identical (leave the
   game, count it, halt on repetition), and `IdleBail`'s message already
   says which step and how long.

## Consequences

- The unbounded wait becomes a bounded one: worst case, the bot stands
  for 30 s with the reflex ladder still running above it (chicken, heals
  and the death latch are all unaffected — they live in `SafetyMonitor`
  and the ladder, above the step), then leaves the game and says why.
- A hang on a path nobody predicted now surfaces as a loud, named report
  instead of a silent stall, which is the property that was missing.
- `waiting` keeps its original meaning and review 003 stays fixed: a
  deliberate settle longer than `idle_bail_s` is still fine.
- A step that legitimately needs to wait longer than 30 s would now bail.
  None exists, and the honest answer if one is ever wanted is that it
  should say so in config rather than in silence.
- Live evidence: **none yet.** Written and tested against fakes; the
  first live run that exercises it is stage B's next attempt.
