# Starvation, and why one good safety layer isn't enough — 2026-08-07

*Cycle: the safety fix after a chicken-starvation death — an in-process
interrupt that no handler can swallow, plus a separate watchdog process
(`docs/archive/plans/2026-08-07-safety-starvation/`, ADR
`docs/adr/2026-08-07-unstarvable-safety.md`).*

## The big idea

The bot had a safety feature that was correct, tested, and live-proven —
and the character died anyway, at 100% logged health.

The chicken check ran at the top of every tick. The tick loop called
`walk_to`. `walk_to` got stuck against a pack of monsters and didn't
return for 24 seconds. During those 24 seconds the loop was *inside*
that call, so it never got back to the top, so the chicken check never
ran. The character was killed by monsters the bot could no longer see,
and the last health reading in the log — taken before the block — said
full.

Nothing was broken. Every piece did exactly what it said. The failure
was in the *arrangement*: a check that only runs between operations
cannot protect you during one.

This is called **starvation** — a task that is ready to run and permitted
to run simply never gets a turn, because something else won't yield.
It's not a crash, and that's what makes it nasty: there's no error to
find. The code is fine; it just isn't being reached.

## Key concepts

**Blocking, and what it costs.** A **blocking call** is one that doesn't
return until it's finished. `walk_to` blocks: you call it, and you get
control back when the character has arrived (or given up). That's
convenient to write — but every second it blocks is a second the caller
does nothing else. If the caller's other jobs include "check whether
we're about to die," blocking isn't just slow, it's dangerous.

The general fix has two halves, and this cycle used both:

1. **Poll from inside.** Give the blocking call a function to call
   periodically — a *callback* — so the safety check happens during the
   wait rather than after it. `walk_to` waits in short 0.1-second
   sleeps, and now asks about safety after each one.
2. **Cap the call.** Make it return after a fixed wall-clock time
   whatever happens, so the caller's other duties resume. Two seconds
   here. The walk didn't finish? Fine — say where you got to, and the
   caller can ask again.

Either alone would have prevented this death. Both, because they fail in
different ways.

**Exceptions and the "don't catch everything" problem.** When something
goes wrong, Python raises an **exception** — an object thrown up the
call stack until some enclosing block catches it. Code that wants to be
robust often writes a broad catch:

```python
try:
    risky_thing()
except Exception:
    pass  # never let this break the run
```

That's usually good practice. Logging shouldn't crash a run; a failed
measurement shouldn't kill a walk. This project had four such handlers
sitting between `walk_to` and the tick loop, each with a sound reason.

But now the chicken signal has to travel that same path. And a broad
`except Exception` doesn't know that this particular exception is the
one carrying "the character is dying" — it catches it and swallows it,
exactly as instructed. Four handlers, each individually correct,
collectively fatal.

Python has a deliberate escape hatch. Exceptions form a **hierarchy**:
almost everything inherits from `Exception`, but a few things sit
*above* it, inheriting from `BaseException` directly — `KeyboardInterrupt`
(you pressed Ctrl-C) and `SystemExit` (the program is quitting). These
are deliberately placed out of reach of `except Exception`, because when
you press Ctrl-C you mean it, and a stray error handler shouldn't get a
vote.

So the safety signal was made a `BaseException` too:

```python
class SafetyInterrupt(BaseException):
    ...
```

Now no ordinary handler can absorb it. It travels all the way to the
engine, which converts it back into the normal exception the rest of the
system already knows how to handle. That conversion happens in exactly
one place, which is the point — everything downstream is untouched.

The alternative was to audit those four handlers by hand and make each
one re-raise. That works until someone adds a fifth. **Prefer the fix
that can't be forgotten over the fix that must be remembered.**

**Defence in depth.** The in-process fix handles blocks it's threaded
through. It cannot help if the whole process hangs, deadlocks, or dies —
you can't fix a process from inside the process that's broken.

So the second layer is a **separate process**: a small program that does
nothing but read the game's health every 0.2 seconds and press ESC when
it's too low. Because it's a different process, the bot's stalls and
crashes cannot reach it. (A **thread** — a parallel line of execution
*inside* the same process — would not do: it shares the process's fate.)

This is **defence in depth**: independent layers where a single failure
doesn't take out both. The layers aren't redundant copies; each covers
what the other can't. The in-process poll is fast and precise but dies
with its host; the watchdog survives anything but knows less and can
only do one crude thing.

Two design notes worth stealing:

- **The backstop fires second.** The watchdog's threshold sits *below*
  the bot's own. The bot's exit is graceful and logged; it should win
  whenever it can. A backstop that fires first isn't a backstop, it's
  just the primary with worse manners.
- **A dead-man's switch.** A safety layer that's silently not running is
  worse than none, because everyone assumes it's on. So the watchdog
  writes a timestamp to a file every loop — a **heartbeat** — and the
  bot refuses to start if that timestamp is stale.

**Verify, don't assume.** The watchdog presses ESC to pause the game.
But if a panel happened to be open, ESC closes the *panel* instead and
nothing is paused. So it presses, then re-reads the game's state to
confirm the pause menu actually opened, and presses again if not —
bounded, so a game that won't pause produces a loud complaint rather
than infinite keystrokes. "I sent the command" and "the thing happened"
are different claims, and only the second one matters.

## The lesson that recurred twice: a test that cannot fail

This is the part worth remembering longest, because it happened twice in
one cycle, in code written by someone who had *just written down the
warning about it*.

The live test armed the safety threshold at 99% mana against a character
sitting at 100% mana. The check is "fire if mana ≤ threshold" — and 100
is not ≤ 99. So the test ran, printed nothing alarming, and proved
absolutely nothing. It couldn't have failed; it also couldn't have
passed meaningfully.

Then, in the *next* round of the same test:

```python
try:
    menu.check()
    menu_ok = True
except InputRefused:
    menu_ok = True      # ← both branches
```

Whatever happened, `menu_ok` was `True`. That assertion could not fail.
It was found only by re-reading a run that had already reported PASS —
prompted by the user asking "are you sure?"

A **vacuous test** (or tautological test) is one whose assertions hold
regardless of whether the code works. It is worse than no test, because
no test is honestly a gap, while a vacuous test is a false reassurance
that stops anyone looking.

The professional defence is a habit, not a tool: **make the test fail on
purpose at least once.** Break the code, watch red, put it back, watch
green. If you never saw it fail, you don't know it can. The offline test
suite here does this explicitly — one test asserts that a walk *without*
the fix blocks for over 10 seconds, so the "it's fast now" test next to
it has a proven contrast.

## What we did, in these terms

- Made `walk_to` poll a safety callback from every waiting loop, and cap
  itself at 2 seconds — the blocking-call fix, both halves.
- Introduced `SafetyInterrupt(BaseException)` so no broad handler can
  swallow the signal, converted back to the normal exception type at one
  boundary.
- Built `pd2bot/watchdog.py`, a separate process that presses ESC and
  nothing else, with a heartbeat the bot checks before it will run.
- Proved both against the real game, unattended — and found two vacuous
  assertions and a real bug in the process (a focus-stealing call that
  silently never worked for unattended runs).

## Honest about depth

Glossed over: how the operating system decides whether one process may
steal keyboard focus from another (real and fiddly — the fix here sends
a harmless keystroke to qualify); why the process-id we get when
launching a program isn't always the process that ends up running (a
launcher can hand off to a child, which meant "kill the watchdog" was
killing the wrong thing); and the general theory of **liveness**
properties — "something good eventually happens" — of which starvation
is the classic violation.

## Where you'd meet this professionally

Starvation and blocking calls are everywhere in server work: one slow
database query holding a connection while health checks time out, one
thread holding a lock while everything queues behind it. The standard
vocabulary — blocking vs non-blocking, timeouts, heartbeats, dead-man's
switches, defence in depth — is assumed knowledge in any backend or
infrastructure interview, and "what happens if this call never returns?"
is a question good reviewers ask reflexively.

The exception-hierarchy point generalises past Python: every language
with exceptions has the "catching too much" failure, and every mature
codebase has a rule about it. And vacuous tests are a recognised
category that senior engineers actively hunt in code review — the
related industry practice is **mutation testing**, which automatically
breaks your code to check that some test notices.
