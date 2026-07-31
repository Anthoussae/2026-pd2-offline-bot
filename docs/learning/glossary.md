# Glossary

Plain-language definitions of technical terms used in this project's
development, in alphabetical order. Maintained by the `teach` skill; each
entry may point to the explainer where the term first appeared.

**ADR (architecture decision record)** — a short document recording one
significant technical decision: the context, what was chosen, what was
rejected, and the consequences. Its value is for the future reader (often
you) asking "why on earth is it done this way?". First seen in
[reading a program from the outside](2026-07-28-reading-a-program-from-outside.md).

**A\* ("A-star")** — the standard pathfinding algorithm in games: given a
grid of walkable and blocked squares, it finds the shortest route between
two points. Its trick is always extending the candidate route that scores
best on "distance walked so far + estimated distance remaining," so the
search heads toward the goal instead of flooding the whole map.

**dataclass** — a Python class that is essentially a set of named fields, with
the repetitive boilerplate generated automatically. Used here as the state
model: readable, cheap, and immutable by default. First seen in
[from script to package](2026-07-28-from-script-to-package.md).

**declarative (configuration)** — expressing *what* should happen as data
(a list of steps, a table of thresholds) while the code owns *how*.
The Cold Plains run and the necro's tuning are TOML text files, not
Python; a new run is a new file. The trade-off is that files can hold
typos, which is why the loaders validate strictly at startup. First
seen in [the behavior engine](2026-07-31-the-behavior-engine.md).

**DLL (dynamic-link library)** — a file of compiled code that is not a
program by itself but is loaded *into* a running program to provide
functions. Windows programs are commonly split this way: Diablo II's
1.13c client is a small `Game.exe` plus a dozen DLLs (`D2Common.dll`
holds the game rules, `Storm.dll` file loading, and so on). Any program
can try to load a DLL and call into it — that is how our map generator
reuses the game's own map-building code without running the game.

**calibration** — deriving a constant by measuring the running system
instead of trusting a spec or a config file. Our click math assumed 16
pixels per subtile; measuring real walks gave 20 — and the menu scale
repeated the lesson in M4 (stretch model missed by 140 px; the
pillarbox model was hover-confirmed to ±2 px before use). First seen in
[when reality corrects the docs](2026-07-28-when-reality-corrects-the-docs.md).

**chicken** — botting jargon (from kolbot) for fleeing the game the
moment a vitals threshold is crossed, e.g. "life below 50% → leave".
Cheap and absolute in offline single player, where ESC pauses the game
instantly. A threshold like this is a *floor trigger*: it fires on the
first observation at-or-below the line, which after a burst of damage
can be well below it. First seen in
[the game cycle](2026-07-29-the-game-cycle.md).

**complement guard** — a second guarded path whose allowed condition is
the logical opposite of the first's, so between them every state has
exactly one legal actor and a bypass flag never needs to exist. Our
world-input gate allows "in a game, no panel"; the menu-input gate
allows "not in a game, or the ESC menu open". First seen in
[the game cycle](2026-07-29-the-game-cycle.md).

**closed-loop control** — act, observe the actual result, correct,
repeat — as opposed to "open-loop" (act and hope). The walk loop clicks,
watches the player's real position, and escalates when it stops
changing. First seen in
[when reality corrects the docs](2026-07-28-when-reality-corrects-the-docs.md).

**collision map** — a grid representation of a game area marking which
squares can be walked on and which are blocked (walls, water, props).
Pathfinding algorithms like A* operate on this grid. Our bot reads them
from the live game's memory and remembers them in a per-seed atlas
(single-player maps never change).

**blocking (call)** — a function that does not return until its work is
finished, so nothing else in that thread runs meanwhile. Harmless where
nothing else needs to happen, dangerous where something does: the bot
approaches monsters in short hops rather than one blocking walk, so the
survival checks keep running between them. First seen in
[simulating the game](2026-07-31-simulating-the-game.md).

**flaky test** — a test that sometimes passes and sometimes fails with no code change in between. Usually a symptom of a race condition, a timing assumption, or a fragile selector in the test itself; professionals treat flakiness as a bug in the test harness to be fixed, not ignored. *(First seen: 2026-07-31, when the tools lie.)*

**fragile selector** — locating something by where it happens to be (a pixel position, "the third element on the page") rather than by a stable identity. Breaks silently the moment the layout shifts. The cure is addressing by identity: an ID, a label, or an ordinal in a structure that cannot move. *(First seen: 2026-07-31, when the tools lie.)*

**hang** — when a program stops making progress but does not exit: it sits
there, using no CPU, waiting for something that will never happen. Different
from a crash (which ends the program) and often worse, because nothing
announces the failure — the caller just waits forever. Our tools use
timeouts so a hung helper program turns into a visible error instead.

**headless** — running a program without its usual window, graphics, or
human interaction, typically so another program can drive it. The map
generator runs the game's map code headlessly: no game window, no
keyboard — just "here is a seed, give me the layout" over a pipe.

**heuristic** — an informed estimate used to guide a search or decision
when computing the exact answer up front would be too slow; "good guess
math." In A*, the heuristic is the straight-line distance to the goal,
used to decide which route to try extending next.

**idempotent** — describes an operation where doing it twice has the same effect as doing it once, which makes retries and resumes safe. Achieved most simply by checking the world before acting ("is there anything to do?") rather than keeping a checklist. *(First seen: 2026-07-31, when the tools lie.)*

**in-process vs out-of-process** — whether your code runs *inside* the
target program (injected, typically as a DLL) or as a separate program
reading across the process boundary. In-process is more powerful and more
fragile; out-of-process is more limited and more robust. This project is
out-of-process; kolbot is in-process, which is why a version mismatch
stopped it dead.

**interface / protocol** — a named shape of methods ("anything with
`engage()` and `upkeep()`") that code can depend on without knowing the
concrete thing behind it. Python's version is the `Protocol` class. The
standard testing move follows directly: hand the code a *fake* that has
the right shape and scripted answers, and it cannot tell the difference.
First seen in [the behavior engine](2026-07-31-the-behavior-engine.md).

**linter / formatter** — a linter reads source code and flags likely mistakes and
style violations; a formatter rewrites layout into one consistent shape so the
team never argues about it. This project uses `ruff` for both. First seen in
[from script to package](2026-07-28-from-script-to-package.md).

**memory offset** — the fixed distance, in bytes, from the start of a data
structure to one of its fields. A table of offsets plus a starting address
is enough to read another program's live data. Offsets are true for one
build of a program and can shift when it is patched. First seen in
[reading a program from the outside](2026-07-28-reading-a-program-from-outside.md).

**modal dialog** — a pop-up window that freezes the rest of its program
until a human clicks a button ("OK", "Retry"). Fine on a desktop; fatal for
automation, because a headless program that pops one has no human to click
it — it hangs until someone notices. This is exactly how PD2's bundled
display mod stopped our map generator.

**modifier key** — Shift, Ctrl, or Alt held down to change what another input means. In automation, the modifier must provably be down before, during, and after the click it modifies — sending both in the same instant is a race condition. *(First seen: 2026-07-31, when the tools lie.)*

**package / module** — a module is a single `.py` file; a package is a directory
of modules imported under one name (here, `pd2bot`). The boundaries you draw
between them become the vocabulary the rest of the code uses. First seen in
[from script to package](2026-07-28-from-script-to-package.md).

**fail-stop** — the design choice to halt completely on a serious
failure instead of attempting recovery: no further actions, loud alert,
state left untouched for a human. The opposite pole is fail-recover;
choosing between them per failure class is a real engineering decision.
Our death latch is fail-stop by explicit user decision. First seen in
[the game cycle](2026-07-29-the-game-cycle.md).

**guard clause / gate** — a check placed *inside* the one function that
performs a risky action, so no caller can skip it by forgetting. Our
input gate re-verifies "safe to click?" at the moment of clicking; there
is deliberately no way around it. First seen in
[when reality corrects the docs](2026-07-28-when-reality-corrects-the-docs.md).

**integration test** — a test that runs several components together and
checks the result, as opposed to a unit test that checks one in
isolation. Slower and vaguer about what broke, but it is the only kind
that catches bugs living in the *interaction* between pieces that are
each individually correct — which is most of the expensive ones. First
seen in [simulating the game](2026-07-31-simulating-the-game.md).

**latch** — a state flag that, once set, stays set regardless of later
observations — reset only by a human restart. Used where "things look
fine again" is not evidence of safety: our death halt is a latch, so a
fresh healthy-looking game cannot resurrect the bot's confidence. First
seen in [the game cycle](2026-07-29-the-game-cycle.md).

**human-in-the-loop (HITL)** — any workflow step where a person must act
before software can continue. We now log every such request (type and
outcome) in `docs/instruction-log.md`, so the load can be measured and
engineered down instead of guessed at.

**race condition** — a bug where two events arrive so close together that the processing order is effectively random, and one order is wrong. Notoriously hard to find because the wrong order may be rare, and harmless in most places it occurs. Fixed by forcing the order (waits, locks, sequencing). *(First seen: 2026-07-31, when the tools lie.)*

**SHA (commit hash)** — every git commit is identified by a fingerprint
computed from its entire content (files, message, parent, author) using
a hash function called SHA-1 — a 40-character hex string like
`e6dabec4...`. Change anything and the fingerprint changes, which is
what makes git history tamper-evident. People quote just the first ~7
characters (`e6dabec`) because that's almost always unique within one
repository; our planning artifacts stamp it so a document can point at
the exact code state it describes.

**single source of truth (SSOT)** — the one authoritative place a piece
of information lives; every other copy is derived from it and disposable.
Our agent-toolkit repo is the SSOT for agent workflow: the installed
skills under `~/.claude/skills/` are copies made by the installer, never
edited directly. Most sync bugs in any system are two "sources of truth"
disagreeing.

**short-circuit** — evaluating an ordered list of options and stopping at
the first that applies, so nothing below it runs at all. The survival
ladder works this way each tick: the most urgent firing rule consumes
the whole tick, and attacking literally cannot happen while a survival
rule fired — safety by structure instead of by remembering to check.
First seen in [the behavior engine](2026-07-31-the-behavior-engine.md).

**polling** — repeatedly checking a condition ("has the screen changed
yet?") at an interval, instead of being notified. Almost always paired
with a timeout (give up after N seconds) and often with bounded retries
of the triggering action; without those bounds, polling turns a stuck
system into a silently stuck watcher. First seen in
[the game cycle](2026-07-29-the-game-cycle.md).

**spike** — a short, deliberately throwaway investigation whose deliverable
is knowledge rather than shippable code: "is this even possible?" A spike
that returns "no" is a success — it prevents a large investment in a dead
end. First seen in
[reading a program from the outside](2026-07-28-reading-a-program-from-outside.md).

**state machine** — a design where the program is always in exactly one
named state and moves only along defined transitions; crucially, an
input that fits no known state is an error, not a guess. Our game cycle
is one: main menu, char select, difficulty popup, loading, in game —
and `UNKNOWN` stops everything with a description. First seen in
[the game cycle](2026-07-29-the-game-cycle.md); the behavior engine's
run steps are a second one
([the behavior engine](2026-07-31-the-behavior-engine.md)).

**tick / game loop** — the shape almost every game and bot runs on: a
loop that observes the world, makes one small decision, acts, and
repeats several times a second. One pass is a tick. Its virtue is that
no decision is ever stale — plans that stopped making sense are
abandoned within a tick. First seen in
[the behavior engine](2026-07-31-the-behavior-engine.md).

**test double (fake, stub, mock)** — a stand-in for a real dependency,
used so code can be tested without it. The quality bar is whether it can
say NO: a double that grants every request proves only that your code
can ask. Ours kills monsters slowly, refuses one pickup outright, and
treats a keypress as a request whose effect must be read back — and it
found two real bugs on its first run. First seen in
[simulating the game](2026-07-31-simulating-the-game.md).

**transient vs persistent state** — data with a short lifetime (a
monster's position this instant) versus data that stays true (a wall).
Persisting transient state is a classic cache bug: our first survey
walk stored monster positions into the permanent map, and a corpse
would have become an eternal wall. Ask "how long is this true?" before
saving anything. First seen in
[when reality corrects the docs](2026-07-28-when-reality-corrects-the-docs.md).

**synthetic input** — mouse or keyboard events generated by software (on
Windows, via `SendInput`) rather than by a physical device. Applications
generally cannot distinguish them from real input. This is how the bot acts on
the game.

**virtual environment (venv)** — a private, per-project copy of Python and its
installed libraries, so different projects can use different versions of the
same library without conflict. It is derived data: never commit it to git or
put it in cloud-synced storage. First seen in
[from script to package](2026-07-28-from-script-to-package.md).

**watchdog** — a timer that fires when a system stops *making progress*,
as opposed to visibly failing. It catches the unforeseen bug whose only
symptom is standing still. Our never-idle rule is one: outside town,
nothing sent and no progress for ten seconds means leave the game.
First seen in [the behavior engine](2026-07-31-the-behavior-engine.md).
