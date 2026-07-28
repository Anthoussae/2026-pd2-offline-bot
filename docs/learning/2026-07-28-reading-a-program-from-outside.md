# Reading a program from the outside — 2026-07-28

*Cycle: proved a Python program can read Project Diablo 2's live game state
and control the character, after kolbot turned out to be unusable.*

## The big idea

A running program keeps its state — your character's name, hit points,
position — in memory as plain numbers at predictable places. Windows lets one
program read another program's memory (`ReadProcessMemory`), so a separate
program can watch a game without being part of it. That is the whole trick
behind this cycle.

Two ways to do this, and the difference matters:

- **In-process**: push your own code *inside* the target program (a DLL), so it
  runs as part of the game. Maximum power, maximum fragility. This is what
  kolbot does — and it is why kolbot failed us: its DLL only understands
  specific versions of Diablo II, and PD2 is not one of them.
- **Out-of-process**: stay outside and read across the process boundary. Less
  power, far fewer ways to break. This is what we chose.

## Key concepts

**Memory offset.** A structure in memory has a fixed internal layout: the name
is at byte 0, the position at byte 44, and so on. Those distances are
**offsets**. Knowing "the player structure starts here" plus a table of offsets
is enough to read everything. We didn't reverse-engineer those offsets
ourselves — PD2's own maphack (BH) is open source and publishes them, so we
copied them and cited each one back to its source line. Borrowing an existing,
maintained source of hard-won knowledge instead of rediscovering it is the
theme of this project.

**Version coupling.** Those offsets are true for exactly one build of the game.
Patch the game and they can shift. That's not a flaw in our approach — it's the
recurring cost of it, and the reason we pinned a season and expect to
re-verify. Kolbot's failure was the extreme form of the same problem.

**Synthetic input.** The OS can be told "a mouse click happened at this point"
(`SendInput`), and applications can't tell the difference. That's our hands.

**Spike.** A short, deliberately throwaway piece of work whose deliverable is
*knowledge*, not code: "can this even work?" Both milestones so far were
spikes. The first returned "no" — and that was a success, because it cost two
hours instead of two weeks. Professionally this is one of the most valuable
things you can do with an unproven assumption: **de-risk it first, cheaply.**

**Preconditions and guards.** Reading is passive and safe. *Acting* is not. Our
test click landed on "Save and Exit Game" because a menu happened to be open —
the same coordinate means different things in different states. The lesson is
general: before a program takes an irreversible action, it must verify the
world is in the state it assumes. We now require the window to be focused, the
character to be in a game, and (once M2 finds it) no menu open.

## What we did, in these terms

Attached to the live game out-of-process, read the player structure using
BH-sourced offsets, watched the position update at ten times a second while the
character walked, and sent a synthetic click that made it walk. Along the way,
two bugs worth remembering: the game keeps *two* stat tables (before gear and
after), and reading the wrong one produced "961 out of 920 hit points" — an
impossible number that you, not the code, caught. Structurally correct,
semantically wrong. Automated checks rarely catch that class of bug; a human
asking "is that plausible?" does.

## Where you'd meet this professionally

The specific skill (reading another process's memory) is niche — game tooling,
debuggers, profilers, security work. The habits around it are not. Spiking a
risky assumption before committing to a plan, writing down *why* a decision was
made and what was rejected (that's what an **ADR** — architecture decision
record — is, and this cycle produced one), citing your sources so the next
person can re-verify them, and gating dangerous actions behind explicit
preconditions: all four are everyday professional practice, and all four
earned their keep in a single afternoon here.
