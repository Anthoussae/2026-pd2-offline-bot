# Simulating the game — 2026-07-31

*Cycle: M5 P5 — the necromancer's combat rotation, the loot rules, and a
scripted fake Cold Plains that runs the whole bot end to end. Still no
live game.*

## The big idea

This cycle built the parts that fight and loot. But the thing worth
learning from it is not the combat logic — it is the **simulation**, and
specifically that it found two real bugs within minutes of first
running, both of which had already passed every unit test written for
them.

That is not luck. It is the difference between two kinds of test.

## Key concepts

**Unit test vs. integration test.** A unit test checks one piece in
isolation: "given a monster 20 tiles away, does the module return a
move?" An **integration test** runs the pieces together and checks the
result. Unit tests are fast, precise, and tell you exactly what broke —
but they only ever ask questions you already thought to ask. Both bugs
this cycle lived in the *interaction* between pieces that were each
individually correct.

**The bug an isolated test cannot see.** The escape spell costs 12% of
your health. The panic rule says "if you lost more than 25% of your
health in the last two seconds, escape." Each is correct alone. Run
them together and the spell's own cost counts as damage taken, so
escaping triggers the escape rule again — the character teleports
twice and pays double. The general shape is worth naming: *a reflex
whose action changes the very signal it watches will oscillate unless
it deliberately forgets.*

**Fakes must be able to refuse.** A fake that grants every request only
proves your code can ask. This sim kills monsters by poison over several
seconds rather than instantly, creates corpses only where something
actually died, treats a keypress as a *request* whose effect must be
read back, and has one item it will never let the bot pick up. Every one
of those refusals is a chance for the bot to be wrong where a human can
see it. The industry phrasing is that a good **test double** models the
dependency's failure modes, not just its happy path.

**Shared state vs. duplicated state.** The second bug: two different
parts of the run both pick up loot, and each kept its own private note
of "items I've already given up on." So one re-attempted what the other
had abandoned. This is the same mistake the project made in an earlier
phase, in different code — which is the real lesson. **When two things
do the same job, they must not differ in what they remember.** The fix
is always to move the memory somewhere both can see.

**Blocking vs. ticked code.** A function that walks the character across
a room and only returns when it arrives is **blocking** — nothing else
runs meanwhile. That is fine in town and fatal in Hell, because the
survival checks are not running either. So the approach to a monster is
made in short hops instead of one long walk: each hop returns, the loop
ticks, the survival ladder gets a look. This is the clearest payoff of
last cycle's loop design.

## What we did, in these terms

Encoded the fighting pattern (approach, strike, retreat, repeat) and the
loot rules as an editable file; built the one component that actually
sends keys and clicks, with the rule that no spell is ever cast without
first reading back from memory that the game switched to it; then wrote
a fake Cold Plains and ran the entire bot through it. 90 new tests, 524
total. Both bugs the sim found are fixed and pinned by tests.

Honestly glossed over: the sim's town phase is a stub, because the town
layer was already proven against the real game in an earlier phase —
simulating it again would test the simulation, not the bot.

## Where you'd meet this professionally

The testing pyramid — many fast unit tests, fewer integration tests, a
handful of full end-to-end tests — is standard vocabulary, and knowing
*why* the slow ones survive despite their cost is what interviews
actually probe. "Our unit tests all passed and production still broke"
is the most common bug story in the industry, and the answer is almost
always that the failure lived between components. Building a fake
environment good enough to be worth failing against is a recognized
specialty (test harnesses, simulators, staging environments); teams that
do it well ship far less often to find out whether something works.
