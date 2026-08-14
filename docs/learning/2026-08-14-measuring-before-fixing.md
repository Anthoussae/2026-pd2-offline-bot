# Measuring before fixing — 2026-08-14

*Cycle: the combat-logistics workstream (orders, leash, restock) closed
with three detours riding it — hotkey config, the tag-mode pickup
calibration, and the locomotion speed pass that took Cold Plains from
454 s to ~150–180 s.*

## The big idea

Almost everything this cycle shipped came from the same move, repeated:
**don't argue about why the program is slow or wrong — make it produce
numbers, then change one thing, then read the numbers again.** The
sessions where this discipline held produced permanent wins; the two
changes made on plausible reasoning alone were both wrong and got
reverted the same night.

## Key concepts

**Baselines and benchmarks.** A **baseline** is a recorded "before"
measurement you keep forever, so any later change can be judged against
it instead of against memory. A **benchmark** is a reference standard
you compare *toward*. This cycle built an unusual one: you played the
bot's exact task yourself while a read-only recorder watched, giving a
53-second human clearance against the bot's 454 — same character, same
map, so every difference was traceable to *how* the bot plays. Comparing
a system against a known-good reference is one of the most common moves
in professional debugging and optimization.

**Telemetry.** You can't fix what you can't see. **Telemetry** is the
practice of having the running program continuously write down what it
does — every pathfinding attempt now records its cost, every stall
attributes itself to the code that caused it. The rule of thumb this
project keeps re-learning: when something misbehaves, the *first* fix is
often an instrument, not a repair. The biggest stall of the cycle (47
seconds, twice a run) had been invisible precisely because no instrument
priced it.

**Worst-case behavior and budgets.** The 47-second stall was the
pathfinding algorithm (A*) doing exactly what it's designed to do:
asked for a route that doesn't exist, it can only prove "no" by
exhaustively flooding every reachable square. An algorithm's
**worst case** — its cost on the most unfavorable input — can be
thousands of times its typical cost, and production code has to decide
what that worst case is allowed to spend. The fix was a **budget**: the
search may expand a bounded number of squares, scaled by how far away
the goal is, and an exhausted budget returns the ordinary "no route"
answer in milliseconds. Databases, web servers, and network code are
full of exactly this shape — timeouts and limits that convert "rarely,
catastrophically slow" into "occasionally, cheaply wrong in a
recoverable way."

**One knob at a time — and revert what fails.** The speed pass changed
one thing per live run, measured, and *kept only what the numbers
supported*. Two changes were falsified: a longer dash didn't help
(reverted), and halving the walk time-budget broke town navigation
outright (reverted within the hour, with a warning comment explaining
why so nobody retries it). The willingness to revert is the discipline;
a change that survives only because nobody re-measured is a **regression**
waiting to be discovered later. The reverted-change-with-a-comment is
itself an industry pattern: the code now *documents its own dead ends*.

**Calibration beats policy.** The tag-mode detour tested a rule the code
had enforced for a week — "item labels must be ON for pickup clicks to
work" — by actually measuring all three label modes: 100% success with
labels OFF versus 10% and 36% with them on. The policy was exactly
backwards, and the measurement inverted it in one commit.
**Calibration** (deriving your constants and policies from the running
system instead of assumption) already had a glossary entry; this cycle
is its best case study yet.

## What we did, in these terms

The human benchmark located the gap; telemetry decomposed it into named
stall families; each family got one structural fix, measured against
both baselines; the failures were reverted with their measurements
recorded; and the cycle closed by promoting a feature (mandatory
pickup) through a **gate** — a human review of the numbers — rather
than on confidence. Glossed over here: how the order book's lifecycle
state machine works (open → resight → rebind → expire), and the chat
buffer race we fixed — both would each fill a page; ask if wanted.

## Where you'd meet this professionally

This cycle was, in miniature, what performance work looks like at any
software company: profile first (telemetry), establish baselines,
change one variable per experiment, keep a written record that survives
you, and put a human gate in front of promoting risky changes.
"Premature optimization" — changing code for speed before measuring —
is one of the industry's most-quoted sins, and the two same-night
reverts are exactly why: even careful reasoning about performance is
wrong often enough that measurement is the only arbiter. An interviewer
who hears "I benchmarked against a reference, instrumented the hot
path, and reverted the changes the numbers didn't support" hears a
professional.
