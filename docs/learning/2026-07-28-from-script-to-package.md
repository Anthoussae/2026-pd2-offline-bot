# From script to package — 2026-07-28

*Cycle: turned the M1 spike scripts into a real Python package that reports what
the bot can see.*

## The big idea

M1's code was a pile of scripts that each did one thing once. M2 turned it into
a **package**: a directory of modules with defined jobs, imported by name, with
tests. The difference is not tidiness. It is that a package has *seams* — places
where one part ends and another begins — and seams are what let you change one
thing without breaking the rest.

The seam that matters most here: exactly one module knows what a memory offset
is. Everything else asks for "the player" or "the monsters nearby". When PD2
patches and the numbers move, there is one file to fix.

## Key concepts

**Package and module.** A module is one `.py` file; a package is a directory of
them. `pd2bot/player.py` is a module, imported as `pd2bot.player`. Nothing
magical — but the naming is how other code finds it, so the boundaries you draw
become the vocabulary everyone uses.

**Virtual environment.** A private copy of Python plus its installed libraries,
belonging to one project, so two projects can use different versions of the same
library without fighting. Ours lives *outside* the repo, because this folder is
synced by OneDrive and a venv is thousands of small files — every one of them a
sync event. Derived files that can be recreated from a command should never be
in cloud storage or in git.

**Linter and formatter.** A **linter** (we use ruff) reads your code and flags
likely mistakes and style violations; a **formatter** rewrites layout to one
consistent shape so nobody argues about it. Both are non-negotiable in
professional work, and both run in seconds.

**What can and cannot be tested automatically.** This cycle drew the line
sharply. Our tests build fake memory out of plain bytes and check the decoding
logic — that we pick the right stat array, follow the room chain, stop on a
corrupt pointer. That is all real, valuable testing. But **no test can tell you
an offset still points at the right thing**, because that fact lives in the
running game, not in our code. So verification has two layers: automated tests
for logic, and a human comparing the bot's output to the game's own screen for
meaning. Knowing which questions your tests *cannot* answer is as important as
writing them.

**Dataclass.** A Python class that is mostly just named fields —
`Player(name=..., level=...)` — with the boilerplate generated for you. We use
them as the state model because they are cheap, readable, and immutable by
default, which matters when the thing they describe was true only at the instant
it was read.

**Defensive reading.** We are reading a program's memory *while it runs and
changes it*. A pointer valid one microsecond ago can dangle now. So traversal is
bounded (never trust a linked list to end), failures are counted rather than
raised, and "I couldn't read that one" is an expected outcome. Any code that
consumes a live, concurrently-mutating source needs this posture — network
scrapers and log tailers have the same problem.

## What we did, in these terms

Built `pd2bot/` with modules for attaching, offsets, units, the player, the
world, UI state, and a snapshot that ties them together; wrote tests over fake
memory; and added a `dump` command for eyeballing it against the real game.

The satisfying piece: to know whether a menu is open, we needed a number the
game keeps but never exposes. PD2's maphack reads it by calling a function
inside the game, which we cannot do from outside. So we read that function's own
machine code, found the instruction that loads from the table, and took the
address out of it. It is derived fresh every run, so a patch that moves the table
is picked up automatically rather than silently returning nonsense — and it can
be cross-checked against a second address PD2 documents separately, which lands
exactly where the first calculation predicts.

## Where you'd meet this professionally

Package layout, dependency isolation, linting, and a test suite are the baseline
furniture of any real codebase — the things a new engineer expects to find on day
one. The subtler transferable habit is the one about verification: being explicit
about which claims your automated tests actually support, and building a
deliberate manual check for the rest, rather than letting a green test run imply
a correctness it cannot deliver.
