# 002 — The cast settle blocks the tick the survival ladder needs

Severity: **P2** — **FIXED** 2026-08-01 (measured live by T48)

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

## Resolution (2026-08-01)

The drill the validation asked for is `drills/t48_cast_animation.py`, and
it settled the number instead of arguing about it. Three bone-armor casts
in town, sampling the player's own unit MODE at 50 Hz:

```
idle mode reads 5
A1 cast: 125ms->10, 640ms->5   (back to idle after 640ms)
A2 cast: 125ms->10, 625ms->5   (back to idle after 625ms)
A3 cast: 110ms->10, 610ms->5   (back to idle after 610ms)
```

So a cast is **610-640 ms**, and the 0.4 s settle never covered it — the
guess was not merely blocking, it was also too short for its own purpose.

The finding asked for the EFFECT rather than a clock, and the effect turns
out to be readable for every cast rather than only for bone armor: mode
`PLAYER_MODE_CASTING` (10) is the game's own statement that the animation
is playing. `GameActionExecutor` now reads it instead of sleeping. A click
that arrives mid-animation raises `CastInFlight` — an `InputRefused`
subclass, so the engine's existing absorb-and-re-decide path handles it
untouched — and the tick ends immediately, which is exactly what the
ladder needed. The read happens only after one of our own casts and only
until `cast_wait_cap_s` (1.5 s), so a mode that never clears costs one
deferred action rather than the run.

**T48's second half changed the design.** It also pressed a hotkey INSIDE
the animation, at delays from 0.0 to 0.8 s, and every one registered
within 47-62 ms — including one sent 110 ms in. So the client does not
eat following input the way it was assumed to; only clicks are worth
holding. That means `DrinkPotion`, a keypress, is deliberately exempt and
the ladder's fastest rungs never queue behind an animation at all. Under
the old fixed sleep they always did.

Two side effects worth recording. `RecordingExecutor` carried a
`cast_settle_s` field it never slept on — dead config that read like
shared behaviour, now deleted. And the sim's runtime, which the review's
summary attributed to finding 001: **the whole test suite went from
93.9 s to 2.4 s**, because 22 scenarios x 11 casts x 0.4 s was all of it.

Tests: 5 new — a click waits, a potion does not, the click lands once the
mode clears, the cap releases a stuck mode, and nothing is read before we
have actually cast.
