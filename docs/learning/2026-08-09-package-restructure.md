# Restructuring a codebase — 2026-08-09

*Cycle: split the two oversized files (steps.py, town.py) by concern and
reorganized the flat 40-module package into layer subpackages, with a
live run proving nothing changed.*

## The big idea

This cycle changed **no behavior at all** — the bot plays exactly as it
did yesterday — yet it touched 227 files. That is **refactoring**:
restructuring code without changing what it does, so that future work is
easier and future bugs have fewer places to hide. The whole discipline
of it is proving the "without changing what it does" part: here, the
same 1169 tests passed after every one of seven phases, CI checked every
push, and the finale was a real unattended Cold Plains run that behaved
identically — right down to reproducing the *known* pickup misses.

## Key concepts

**Structure you can read beats structure you must be told.** Before,
"perception vs input vs navigation" existed only in the documentation;
the folder was a flat pile of 40 files. Now the tree *is* the
architecture: `perception/` sees, `input/` acts, `nav/` moves, `safety/`
guards, `behavior/` decides — the same names the docs use. The rule that
emerged: **the root holds the commands you type and the shared
vocabulary; the subpackages hold the machinery.**

**A shim keeps promises cheap.** Moving `navigate.py` into `nav/` would
have broken `python -m pd2bot.navigate` — a command in the README, in
PowerShell scripts, and in your muscle memory. Instead a five-line
**shim** stays at the old address and forwards to the machinery's new
home. Same idea as mail forwarding: the world keeps using the old
address; only the residents know the difference.

**A mixin splits a class without redesigning it.** `TownLayer` was one
class with sixty methods — you cannot just cut a class in half. A
**mixin** is a class that holds a *slice* of methods and is never used
alone; `TownLayer` is now six mixins (walk, panels, services, stash,
belt, inventory) composed by inheritance into the same single class it
always was. The method bodies moved byte-identical, which is what made
this safe rather than a rewrite.

**Refactors fail at the seams, and the net catches them.** Two real
mistakes happened: cutting on class boundaries stranded `@dataclass`
decorator lines (they sit on the line *above* a class), and one module
constant lost its importers. Both were caught within seconds — by the
linter and the test suite — precisely because every phase ended with the
full checks. A refactor without that net is gambling.

**Tests mirror the code.** `tests/` now has the same folder shape as
`pd2bot/`, so "where is X?" and "where is X tested?" have the same
answer. The count — exactly 1169 before and after — was itself an
acceptance criterion: a silently dropped test looks like success.

Glossed over honestly: Python's `__init__.py` re-export mechanics (how
`from pd2bot.input import GatedInput` still works though the class moved
one file deeper), and why monkeypatch targets had to be retargeted to
concrete modules.

## What we did, in these terms

Seven phases, one commit each, tests green after every one: three
mechanical move phases, the two big splits (mixins for town, one
class-per-file for steps), the test mirror, then documentation — a map
README in every package, a path sweep through the docs, and an ADR
recording the layout rules so future code has to *choose* to break them.
The merge gate was a live smoke run: the refactored bot played a full
game with the safety monitor silent.

## Where you'd meet this professionally

Constantly. "Refactor" is daily vocabulary on any team; large ones are
planned exactly like this — mechanical phases, checks green at every
step, no behavior changes mixed in, and a staging/canary run before
merge. Interviewers probe for it directly ("tell me about a refactor you
did — how did you know you broke nothing?"), and the answer this cycle
teaches — *the test suite is the definition of "broke nothing", plus one
real end-to-end proof* — is the professional one. The failure mode this
guards against also has a name you'll hear: a "big bang" refactor,
everything at once with no checkpoints, which is how refactors turn into
rewrites.
