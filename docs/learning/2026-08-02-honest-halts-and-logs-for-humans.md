# Honest halts, logs for humans, and asking before walking — 2026-08-02

*Cycle: the potion overhaul (type-based belt, merc first aid), the
narrative log, and route-aware legs
(`docs/archive/plans/2026-08-02-potions-and-narrative-log/`).*

## The big idea

Three separate features shipped this cycle, but they share one theme:
**matching a mechanism's precision to what it actually knows.** A halt
that fires when nothing is broken, a log nobody can read, and a walk
that ignores a map the program already owns are all the same mistake —
the code acting on less information than it has.

## Key concepts

**Failure semantics: is it missing, or is it broken?** The old belt
check halted the bot whenever potions were below minimum. That sounds
safe, but it conflated two very different situations: *the world is
short of a resource* (normal — you ran out of potions) and *the
mechanism is failing* (a click that should have worked, didn't). Only
the second deserves waking a human at 2 AM — which is literally what the
old version did (R178). The fix is to state the halt condition
precisely: halt only when stock exists AND the belt has room AND the
potion still didn't land. Everything else is a loud note on a run that
keeps going. Deciding which failures stop the program and which are
absorbed is called choosing your **failure semantics**, and the related
operational sin — so many false alarms that real ones get ignored — is
called **alert fatigue**.

**One event stream, several audiences.** The bot already logged
everything it did, tick by tick — and the user still couldn't answer
"what was it doing while it dawdled at Akara?" A log that records
everything for a debugger is unreadable as a story; the fix was a second
channel with an explicit coarseness contract: one line per meaningful
act, timestamps a human recognizes, and waits that report *what they
were waiting for and how long it took*. Professional systems formalize
this as **log levels** (debug / info / warn / error): the same program
writes for several audiences at once, and choosing the level of a
message is an editorial decision, not a mirror of the code. A nice
trick from this cycle: a test asserts the narrative stays proportional
to *actions* rather than *ticks*, so if someone later adds a chatty
line inside a loop, the suite fails — the contract is enforced, not
just documented.

**Read-only queries, and caching them.** The bot's map (the atlas)
was consulted by the low-level walker but never by the step logic
above it, which walked straight-line "hops" into fences. The fix was a
**query service**: a function `route_to(target)` that *asks* the map
("is there a route, and which way?") without *doing* anything — no
clicks, no walking. Read-only queries are safe to call speculatively
and cheap to test. Because planning a route costs real computation and
the answer barely changes between adjacent ticks, the service keeps the
last answer and reuses it — a **cache** — keyed by roughly-where-we-are
plus the target (the **cache key**). Picking the key is the hard part:
too precise and you never reuse anything; too loose and you serve stale
answers. Here the position is rounded into 8-subtile buckets, so a few
steps reuse one plan and a bigger move replans.

**Closures as wiring.** `route_service(navigator)` builds and returns
the `route_to` function, which quietly keeps using `navigator` and its
private cache afterward. A function that carries variables from the
place it was created is a **closure** — this codebase's standard way to
hand a component exactly one capability ("you may ask for routes")
without handing it the whole navigator.

## What we did, in these terms

The belt refill got precise failure semantics (halt = stock + room +
failed click; anything else continues loudly). A merc-heal rung was
added at the bottom of the survival ladder, using the same
modifier-key-race discipline as Shift-clicks (the modifier provably
down before the belt key). A postscript worth keeping: the chord was
built on an assumed Alt binding, and the live test caught the player
drinking every "fed" potion — the real chord is Shift (R183). Verify a
binding against the system before automating it; an assumption about an
interface is a bug that types at full speed. A `Narrator` writes one human-readable file per run,
with the coarseness contract tested. And a cached, read-only route
service lets patrol/survey/approach legs follow the map's answer, with
"no route exists" becoming an instant, honest write-off instead of a
budget burned at a wall.

## Where you'd meet this professionally

Every production service makes these exact choices: which failures page
the on-call engineer versus land in a dashboard (failure semantics,
alert fatigue), what gets logged at which level and for whom
(observability), and which expensive computations are cached under
which keys (one of the classic "two hard problems in computer
science"). Being able to say *"this alert fires only when X is provably
broken, here's the log line that explains the wait, and here's the
cache key and why it's safe"* is day-to-day senior-engineer talk.
