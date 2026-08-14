# 001 — The watchdog never re-arms after it fires

**Severity: P1** — it makes Track B a single-shot guard, and Stage D is
precisely the multi-game unattended case it exists for.

**Where:** `pd2bot/watchdog.py` — `self.fired` set at `_fire` (both the
success path and the give-up path); no assignment back to `False`
anywhere in the file.

## What is wrong

`fired` is latched for the life of the process and gates the whole act:

```python
if self.fired:
    return  # already paused; do not keep pressing at a paused game
```

That guard is right for the moment it was written for — do not machine-gun
ESC at an already-paused game. But nothing ever clears it, so once the
watchdog has fired once it is inert for the rest of its life.

The lifecycle makes this bite. `tools/guarded-run.ps1` starts ONE watchdog
for the whole invocation, and `--games N` runs N games under it. So after a
single chicken in game 1:

1. The watchdog presses ESC, sets `fired`, writes the latch.
2. The bot leaves the game cleanly and the cycle creates game 2.
3. The watchdog keeps polling, keeps heartbeating — the bot's dead-man
   check is satisfied, `--require-watchdog` is happy, everything looks
   armed — and it will never press ESC again.

The failure is silent and it presents as safety. That is the worst
combination: the operator has more confidence than in the no-watchdog
case, and less protection.

## Why it matters

Stage D is `--games 3`, chicken 35, **unattended**. A chicken in game 1 is
routine (that is the whole point of the threshold), and it disarms the
backstop for games 2 and 3 — the two nobody is watching.

This is also the one property the ADR sells: "a wedged bot cannot prevent
the pause". After one fire, a wedged bot does not need to prevent
anything.

## Suggested fix

Re-arm when the world says the episode is over. The honest signal is
already read every tick: the player disappears (menus / loading) between
games. Something like — clear `fired` when `read_player` returns None
after having been fired, i.e. we are demonstrably out of the game the
pause belonged to. Belt and braces: also clear it when the player is back
in a game AND the ESC menu is not open AND vitals are above threshold,
which is "a new game is running and healthy".

Do NOT re-arm on a timer, and do NOT touch `stopped` — the death latch is
correctly permanent.

Note the latch file is a separate question: it has its own staleness rule
(300 s) and `guarded-run.ps1` clears it per launch, so it does not need
this treatment.

## Validation

- Unit: fire the watchdog, then feed `read_player -> None` (left the
  game), then a fresh below-threshold player; assert a second press.
- Unit: fire, then feed an unchanged paused state repeatedly; assert it
  still does not machine-gun ESC (the original property must survive).
- Unit: a death still latches permanently across the same sequence.
- Live: it would show up in a Stage D dry run as a second `watchdog.fired`
  in a later game, but the unit tests are the real gate here — do not
  spend an unattended battery discovering it.
