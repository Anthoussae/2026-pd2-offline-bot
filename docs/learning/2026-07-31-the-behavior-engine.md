# The behavior engine: a brain built out of a loop, a ladder, and data — 2026-07-31

*Cycle: M5 P4 — the bot's decision-making layer (engine, survival
reflexes, runs-as-data, per-class config), built and tested entirely
against fakes, no game involved.*

## The big idea

Until now the bot had skills (walk, click, read memory) but no brain: no
piece of code decided, moment to moment, "should I be fighting, fleeing,
or drinking a potion?" This cycle built that brain — and the interesting
part is its shape. It is not one long clever procedure. It is a dumb
loop, run several times a second, that asks the same three questions in
the same order every time: *Am I in danger? (safety monitor)* → *Does
survival need something? (reflex ladder)* → *If not, what's the next bit
of the job? (the run's current step).*

## Key concepts

**Game loop / tick.** Games and bots alike run as a loop: look at the
world, decide one small thing, act, repeat. One pass is a **tick**. The
power of the shape is that no decision is ever stale — everything is
re-decided from fresh observations a few times a second, so a plan that
stopped making sense is abandoned within a tick rather than followed off
a cliff.

**Finite state machine (FSM).** The "what's the next bit of the job"
part is organized as named states — `town_preamble`, `waypoint`,
`clear_radius` — where exactly one is active, it does a little work per
tick, and it eventually hands over to the next. The term for this is a
**state machine**. It sounds grander than it is: it is just the
discipline that the bot is always in exactly one known mode, and mode
changes are explicit, so you can always answer "what was it doing?".

**Priority ladder / short-circuit.** Survival is a list of responses
sorted by urgency (drink rejuv → emergency teleport → drink healing →
… → recast armor). Each tick walks the list top-down; the first rule
whose condition holds *wins the whole tick* and everything below it —
including attacking — simply does not run. That "first match wins, rest
skipped" pattern is called **short-circuiting**. The payoff is
structural safety: nobody has to remember to check hp before each
attack, because the attack code literally cannot run on a tick where a
survival rule fired.

**Code vs. data (declarative configuration).** The Cold Plains run is
not Python — it is a small text file listing steps and numbers. So are
all the necro's thresholds and hotkeys. Moving decisions out of code
into files like this is called making them **declarative**: the file
says *what*, the engine knows *how*. Two consequences: a non-programmer
can read and tune behavior, and adding a second run means writing a
file, not code. The flip side is that files can contain typos, which is
why the loader **fails loudly**: an unknown or misspelled key stops the
program at startup with the key named, instead of being silently
ignored. (A silently-ignored typo in `chicken_life_pct` is the kind of
bug you discover by dying.)

**Interface / protocol.** The engine never mentions necromancers. It
talks to "a combat module" — anything that offers an `engage(...)` and
an `upkeep(...)` method. A named shape-of-methods like this is an
**interface** (Python calls its version a **Protocol**). Tests exploit
it: a fake combat module with scripted answers slots in where the real
one will go, and the engine cannot tell the difference. That is also
exactly how the next character class gets added without touching the
engine.

**Watchdog.** One rule sits apart: if, outside town, the bot has sent
nothing and made no progress for ten seconds, it leaves the game. A
timer that fires when a system *stops making progress* — rather than
when something visibly breaks — is a **watchdog**. It catches the
failure mode nothing else can: the bug you did not foresee, whose
symptom is the bot standing still in a lethal place.

## What we did, in these terms

Built the tick engine with the monitor → ladder → step ordering; the
eight-rung ladder with all its cooldown bookkeeping (including
verifying an emergency teleport by whether the character actually
moved, since the game won't tell us); the run loader that validates
`runs/cold-plains.toml` at startup; the strict config loader for
`config/necro.toml`; and the watchdog. All of it exercised by 88 new
tests against scripted worlds — the game itself was never running.

Glossed over honestly: how the actions the brain emits become actual
mouse/keyboard input (next phase — the "executor"), and the whole
question of choosing *targets* in combat, which is the necro module's
job, also next phase.

## Where you'd meet this professionally

Tick loops and state machines run far beyond games: robotics,
network services, and UI frameworks all use "re-derive decisions from
current state in a loop" over "execute a long plan". Declarative config
with strict validation is everyday industry practice — most production
outages traced to config typos happened in systems that *didn't* fail
loudly. Interfaces-plus-fakes is the standard way professional teams
make code testable at all; if you interview anywhere, "how would you
test this without the real dependency?" is a question you should expect,
and "define an interface, inject a fake" is the answer.
