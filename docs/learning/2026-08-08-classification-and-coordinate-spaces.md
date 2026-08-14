# Classification bugs and coordinate spaces — 2026-08-08

*Cycle: the bot kept opening town NPCs' dialogs by accident while walking
past them. Two separate causes, stacked, both found by measuring.*

## The big idea

Two bugs sat on top of each other, and they are two of the most common
shapes a bug takes:

1. Something was put in the wrong **category**, so all the code that
   looks in the right category stopped seeing it.
2. Something was measured in the wrong **coordinate space** — the code
   asked "how far apart are these in the world?" when the question that
   mattered was "how far apart are these on screen?"

Neither is exotic. Both are worth being able to recognise on sight.

## Key concepts

**Classification, and why order matters.** Perception sorts every nearby
unit into one of four buckets: enemy, ally, corpse, or scenery. The code
is a chain of if/else tests, so **the order of the tests is part of the
logic** — the first one that matches wins and the rest never run. An
earlier fix moved the "is it scenery?" test to the top of the chain for a
good reason (a dead decorative bat was being filed as a corpse, and
corpses are raw material for a spell). But moving it to the top also
moved it above "is it friendly?", and town NPCs happen to look like
scenery by the test being used: they carry no combat statistics — no
level, no resistances — exactly like a decorative bat. So Akara became
scenery, and every part of the program that looks for an NPC looks in the
ally bucket.

The lesson is not "be careful". It is that a chain of else-ifs encodes
priority, and changing position in the chain changes meaning for every
case, not just the one you were fixing.

**Regression.** A bug that breaks something which used to work. This one
was introduced by a fix to an unrelated problem — the most common way
regressions happen, and the reason **regression tests** exist: a test
whose only job is to fail if a specific old bug ever comes back. Two were
added here.

**Bisecting with logs instead of code.** The usual way to find when a
regression started is `git bisect`, which checks out old versions one at
a time until it finds the commit where behaviour changed. This project
did it faster, without running anything: every run writes a log line
counting allies and scenery. Runs before 02:36 that day recorded 11
allies; every run after recorded 1. Ten units changed bucket, and the
commit in between was the culprit. **Instrumentation** — recording what
the program saw, not just what it did — turned an hours-long investigation
into a two-minute query.

**Coordinate space.** A coordinate space is the frame of reference that
gives numbers meaning. This program has two. The **world space** is the
game's own grid of subtiles, where "distance" is how far a character
would walk. The **screen space** is pixels in the window, where distance
is how far apart things are *drawn*. Diablo II is isometric, so the two
are related but not proportional: one subtile east is 20 pixels sideways
and 10 pixels down, so moving diagonally "away" in the world can be
moving straight *up* on screen.

The avoidance rule tested world distance: never aim a click within 4
subtiles of an NPC. But the game decides what you clicked by testing the
**sprite** — the drawn image of the character — against the mouse
position, which is a screen-space question. A sprite is tall and narrow.
Measurement made the mismatch unmistakable: three clicks, all exactly 6
subtiles from the same NPC, two harmless and one fatal. The fatal one was
the one drawn 120 pixels straight up her body; the harmless ones were
drawn 120 pixels off to the side. World distance cannot tell those apart.
Nothing was wrong with the *number* 4 — the **shape** was wrong, a circle
where the game uses a tall rectangle.

**The fix made the bug, before it fixed it.** The code that pushes a
click away from an obstacle was choosing its direction in world space,
and one of the directions it was free to choose was straight up the
sprite. So the safety mechanism was generating the exact click that
broke the walk. Worth remembering as a category: a mitigation that
operates in the wrong frame can be the cause.

**A test that can pass without testing anything.** The first live run
after the fix succeeded — and proved almost nothing, because the NPCs
wander, and none happened to be standing in the way that time. The test
would have passed with the fix reverted. The drill was changed to report
how many clicks it actually had to adjust, so a lucky run announces
itself instead of being counted as evidence. This is a recurring hazard:
**a green test is only worth what it actually exercised.**

## What we did, in these terms

Restored the classification (something friendly is never scenery, whether
or not it can fight), then replaced the world-space circle with a
screen-space box around standing units, and made the escape direction a
screen-space choice that is never allowed to go up. Proven by three live
runs where two identical runs had failed before, with the middle one
showing the mechanism working: clicks pushed to 160 pixels sideways,
level with the NPC's feet, where the old rule had put one 120 pixels up
her body.

Glossed over here: how the pixels-per-subtile constants were originally
measured, and why the game's own hit box is not simply readable from
memory. Both are in `docs/architecture/navigation.md`.

## Where you'd meet this professionally

Coordinate-space confusion is one of the standard bug families in
anything graphical — game engines, mapping software, browser UI, image
processing. Interviewers ask about it; libraries are full of
`toLocal`/`toGlobal` conversion functions precisely because getting it
wrong is so easy. Classification-order bugs are just as common wherever
code routes things into categories: permission checks, message handlers,
tax rules, content moderation. And the habit shown here — measure before
changing behaviour, then keep the measurement as a repeatable tool —
is what separates debugging from guessing. On a team you will be asked
"how do you know?", and "the log says so" is a much better answer than
"it seemed likely".
