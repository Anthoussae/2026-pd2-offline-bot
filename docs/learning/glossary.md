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

**DLL (dynamic-link library)** — a file of compiled code that is not a
program by itself but is loaded *into* a running program to provide
functions. Windows programs are commonly split this way: Diablo II's
1.13c client is a small `Game.exe` plus a dozen DLLs (`D2Common.dll`
holds the game rules, `Storm.dll` file loading, and so on). Any program
can try to load a DLL and call into it — that is how our map generator
reuses the game's own map-building code without running the game.

**calibration** — deriving a constant by measuring the running system
instead of trusting a spec or a config file. Our click math assumed 16
pixels per subtile; measuring real walks gave 20. First seen in
[when reality corrects the docs](2026-07-28-when-reality-corrects-the-docs.md).

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

**in-process vs out-of-process** — whether your code runs *inside* the
target program (injected, typically as a DLL) or as a separate program
reading across the process boundary. In-process is more powerful and more
fragile; out-of-process is more limited and more robust. This project is
out-of-process; kolbot is in-process, which is why a version mismatch
stopped it dead.

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

**package / module** — a module is a single `.py` file; a package is a directory
of modules imported under one name (here, `pd2bot`). The boundaries you draw
between them become the vocabulary the rest of the code uses. First seen in
[from script to package](2026-07-28-from-script-to-package.md).

**guard clause / gate** — a check placed *inside* the one function that
performs a risky action, so no caller can skip it by forgetting. Our
input gate re-verifies "safe to click?" at the moment of clicking; there
is deliberately no way around it. First seen in
[when reality corrects the docs](2026-07-28-when-reality-corrects-the-docs.md).

**human-in-the-loop (HITL)** — any workflow step where a person must act
before software can continue. We now log every such request (type and
outcome) in `docs/instruction-log.md`, so the load can be measured and
engineered down instead of guessed at.

**single source of truth (SSOT)** — the one authoritative place a piece
of information lives; every other copy is derived from it and disposable.
Our agent-toolkit repo is the SSOT for agent workflow: the installed
skills under `~/.claude/skills/` are copies made by the installer, never
edited directly. Most sync bugs in any system are two "sources of truth"
disagreeing.

**spike** — a short, deliberately throwaway investigation whose deliverable
is knowledge rather than shippable code: "is this even possible?" A spike
that returns "no" is a success — it prevents a large investment in a dead
end. First seen in
[reading a program from the outside](2026-07-28-reading-a-program-from-outside.md).

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
