# 002 — The cast settle blocks the tick the survival ladder needs

Severity: **P2**

`pd2bot/behavior/execute.py` (`GameActionExecutor.execute`, `cast_settle_s`).

## What is wrong

Every `CastSelf` and `CastAtPoint` now sleeps `cast_settle_s` (0.4 s)
inside `execute`, which runs inside the engine tick. The ladder is not
consulted during a tick, so every cast is 0.4 s in which no survival rung
can fire.

The reason for it is sound — the user reported from manual play that bone
armor's cast animation is interrupted by a following command, so the cast
is spent and the buff never lands. But the remedy sits in the one place
`necro.py`'s own module docstring warns against:

> the dash being taken in SHORT HOPS rather than one long walk: a blocking
> `walk_to` into a pack is time the reflex ladder is not being consulted,
> and the ladder is the thing keeping the character alive.

A cast is not a walk, but 0.4 s is 0.4 s. In a fight the necro casts
desecrate and revive repeatedly, so this is not a rare path.

## Why it matters

The engine's central promise is that survival gets a look between every
decision. This quietly buys reliability with the seconds the rungs need,
and it was added without measuring what a bone-armor animation actually
costs — 0.4 s is a guess that happens to be shorter than two ticks.

## Suggested fix

Prefer waiting on the EFFECT, not on a clock, which is the discipline used
everywhere else in this codebase (the drop, the deposit, the skill
switch). Bone armor's absorb stat is readable and T46 established exactly
what it does, so "cast, then poll until 132/133 appear, with a short cap"
is available and strictly better than a fixed sleep.

If a fixed pause survives for the casts with no readable effect, measure
the animation before choosing the number, and consider paying it only for
the skills that need it rather than for every cast.

## Validation

A test that a cast with a verifiable effect returns as soon as the effect
appears rather than after a fixed delay — plus a live check of what a
bone-armor cast actually costs, which no drill has yet measured.
