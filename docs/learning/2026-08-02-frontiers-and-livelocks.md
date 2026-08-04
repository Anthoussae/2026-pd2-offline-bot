# Frontiers and livelocks — 2026-08-02

*Cycle: M5 P6 — the survey system (automated + the T52 manual drill),
the cleanse/reposition fixes, and the live acceptance runs.*

## The big idea

This cycle's feature was exploration: teach the bot to *finish* a map
instead of only remembering where it happened to walk. The interesting
failures, though, were all about **loops that don't look like loops** —
a bot that is visibly busy, sending clicks, fighting, walking, while
achieving nothing at all. Fourteen minutes of the first live survey
were spent that way. None of our watchdogs caught it, because every
tick "acted." The fixes were not cleverness; they were bookkeeping:
define what *progress* means, measure it every tick, and give up the
moment a budget of progress-free effort is spent.

## Key concepts

**Frontier exploration.** The standard way to map unknown territory
(robot vacuums do exactly this): a *frontier* is known ground that
borders unknown ground. Walk to the nearest frontier, look around —
which converts unknown to known and moves the frontier — and repeat
until no frontier remains. Termination is built in: the frontier can
only shrink or move outward, and "none left" *is* the definition of
done. Our survey adds one guard: frontiers are clamped to the target
area's own bounds, or Cold Plains would bleed into its neighbours
forever.

**Livelock.** A deadlocked program stands still; a **livelocked** one
works furiously and gets nowhere — which is worse, because activity
defeats watchdogs that only check "is anything happening?" Our survey
livelocked on a monster it could walk *toward* but never reach: every
dash succeeded, so the failed-walk detector never fired, and the fight
kept winning the tick forever. The cure is a progress definition
richer than "an action happened": here, *distance closing or the
monster's health falling*, with a budget of ticks allowed to move
neither.

**Hysteresis (sticky choices).** The survey originally re-picked the
*nearest* frontier every tick — and two near-equidistant targets traded
"nearest" as the bot moved, each swap resetting the give-up counter.
Flip-flopping between options as tiny differences shift is a classic
control failure, and the classic fix is **hysteresis**: once a choice
is made, stick with it until it resolves or genuinely fails, rather
than re-optimizing continuously. (Thermostats work this way — heat to
21°, off until 19° — precisely so they don't chatter at the threshold.)

**A test that cannot fail is not a test.** T53's first run "passed"
while the bot never left town: the harness only saw that the test body
finished without error, and the body dutifully returned a summary of a
run that had gone nowhere. The status said PASS; the prose said
otherwise. The fix was one line — raise an error when zero cycles ran
clean — but the principle is load-bearing: every test needs a defined
way to fail, and if you cannot say what output would fail it, it is
reporting, not testing.

## What we did, in these terms

Built **frontier exploration** over the existing map store (one new
module and one run step — storage and consumption already existed);
found a **livelock** in the first live run and broke it with a
progress-or-give-up budget; added **hysteresis** to target selection;
and made T53's pass/fail honest. The user then beat the robot at its
own game: the T52 manual-survey drill let a human walk while the bot
recorded, mapping Cold Plains and the whole Countess route in minutes.

## Where you'd meet this professionally

Frontier exploration is core robotics/game-AI vocabulary. Livelock is a
named concept in concurrent systems (two threads endlessly yielding to
each other) and interviews distinguish it from deadlock; the deeper
habit — define progress, budget effort against it — shows up in retry
policies, circuit breakers, and SLO burn alerts. Hysteresis appears in
autoscaling (scale up at 80%, down at 40% — never both at 60%), UI
debouncing, and alert thresholds. And "a test that cannot fail" is the
first thing reviewers hunt for in test suites: assert-free tests and
always-green checks are industry-recognized anti-patterns.
