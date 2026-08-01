# 001 — Repositioning can drift out of engagement and stall the run forever

Severity: **P1**

`pd2bot/behavior/necro.py` (`_reposition`, `_hostiles`),
`pd2bot/behavior/steps.py` (`ClearRadiusStep.step`).

## What is wrong

Two radii measured from two different points, and a new behaviour that
walks the gap between them.

- `ClearRadiusStep` decides the area is not yet clear from monsters
  within `radius` (50, stage B) of the **arrival point**.
- `NecroCombat._hostiles` decides there is a fight from monsters within
  `engage_radius` (40) of the **player**.

`_reposition` — added at the end of this session, unrun — moves the player
`reposition_subtiles` (4) *away from the hostile centroid* every tick that
has nothing fresh to strike. Nothing bounds how far that drift can
accumulate.

Once the player is far enough that the pack falls outside 40 but is still
inside 50 of the arrival point:

1. `combat.engage` sees no hostiles, returns None (and resets
   `_engagement_start`).
2. `ClearRadiusStep` still sees `in_radius` non-empty, so it never sets
   `_empty_since` and never completes.
3. It falls through to `return StepOutcome(done=False, waiting=True)`.
4. **`waiting=True` suppresses the idle watchdog**, so `IdleBail` never
   fires.

The run hangs. Not slowly — permanently, with the safety net that exists
for exactly this case switched off on exactly this path.

## Why it matters

This is the only *unbounded* wait in the engine. Every other
`waiting=True` is a timer that expires — the clearance settle, the
restrike interval. This one has no clock behind it at all: it is "the
combat module has nothing to say", which stays true forever once the
player has walked away.

It also has no live evidence either way. The repositioning was written
after the last run of the session, in response to a behavioural note, and
has never executed against the game. The circumstantial evidence is not
reassuring: `test_behavior_sim`'s scenarios went from negligible runtime
to ~4.4 s each with these changes, meaning the bot now spends far more
ticks reaching the same outcome — which is what drifting away and walking
back would look like.

Worth noting the irony directly: `waiting` was added earlier in this same
session to fix review 003, where the watchdog fired during legitimate
waits. That fix was right. It just also removed the alarm from the one
path that later grew a genuine hang.

## Suggested fix

Three parts, cheapest first:

1. **Bound the drift.** Reposition only while the player is within some
   distance of the engagement, or cap total drift per engagement. A step
   "away from the pack" that can repeat forever is a retreat.
2. **Make the radii agree.** `clear_radius` should not be able to want a
   monster dead that `engage_radius` refuses to fight. Either derive one
   from the other at wiring time, or have the clearance step walk toward
   hostiles it cannot currently engage.
3. **Bound the wait.** `waiting=True` should mean "I am waiting for
   something that will expire". A step that reports it for longer than any
   configured wait is hung, and the watchdog should say so.

(3) is the durable one and is the ADR candidate named in the summary.

## Validation

A test that drives `ClearRadiusStep` with a hostile just inside the
clearance radius and just outside `engage_radius`, and asserts the step
either makes progress or eventually raises — not that it returns
`waiting=True` indefinitely. Today that test would hang, which is the
finding.
