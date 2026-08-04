# When the tools lie — 2026-07-31

*Cycle: M5 P3 — the town layer: heal, repair, stash, belt, merc resurrect,
waypoint travel, and the inventory-management loop, all proven against the
live game.*

## The big idea

Almost every failure in this cycle turned out to be in **our own code and
measurements**, not in the game. A calibration tool recorded the wrong
point and the number it produced looked perfectly plausible. A chat helper
pressed Enter into menus and silently changed the thing being measured.
Two clicks sent in the same instant merged into one. The lesson that ties
the cycle together: when results contradict each other, suspect the
instrument before the world. Two measurements of the same fixed thing that
disagree are not noise to average — they are the measuring tool reporting
itself broken.

## Key concepts

**Race condition.** When two events are sent (or happen) so close together
that the order they get processed in is effectively random, and one
ordering is wrong. We held Shift and clicked in the same frame; the game
sometimes processed the click first and saw it *unshifted*. The bug was
invisible for days because an unshifted right-click on a potion just
drinks it — harmless — until it hit an item where the wrong reading
mattered (a tome, which got *used* instead of stored). This is the classic
shape of a race: rare, order-dependent, and masked wherever the wrong
order happens to be harmless. The fix is to force the order — press the
modifier, *wait one frame*, then click.

**Fragile selectors, and addressing by identity instead of position.** We
stored screen coordinates for menu rows ("the repair option is at pixel
712, 216") and they kept going stale, because the menu is drawn relative
to a character who wanders. Four separately-verified coordinates each
worked once and failed later. The durable fix was to stop using positions
entirely: the menu is keyboard-navigable, so "press Down once, then Enter"
selects *the second row* wherever it happens to be drawn. Choosing a
stable name over a fragile location is a general principle: prefer
addressing things by what they *are* (an ID, an index, a label) over where
they *currently sit*.

**Idempotence.** An operation is **idempotent** if running it twice has the
same effect as running it once. Our town routine got this property almost
for free, because every step checks the world first ("is the gear worn?
is the merc dead?") and does nothing when there is nothing to do. The
payoff appeared immediately: a run halted halfway, and simply running it
again finished the job — the completed steps skipped themselves. Designing
steps to be re-runnable is far cheaper than designing a system that must
never fail halfway.

**Verify the effect, not the action.** Every step in the town layer proves
success by observing the *world change* — durability restored, gold
reduced, an item gone from the inventory — never by "the click was sent".
This cycle sharpened the rule: sometimes there is nothing else to check.
The gold-deposit dialog turned out to be invisible to our memory reading,
so the only possible proof was the gold balance itself moving. When the
action is unverifiable, verify the outcome.

## What we did, in these terms

We found and fixed a **race condition** in both mouse paths; replaced
every **fragile** stored menu position with ordinal (keyboard) selection;
discovered the town routine is **idempotent** and leaned on it to resume a
halted run; and wired the last unverifiable action (gold deposit) to
verify by effect. Along the way three separate one-shot sends were unified
into one retrying helper, because a send that is not verified and retried
will eventually be lost to a bad frame.

## Where you'd meet this professionally

Race conditions are a staple interview topic and a daily reality in any
concurrent code (threads, async JavaScript, distributed systems). Fragile
selectors are *the* classic pain of end-to-end UI testing — tools like
Playwright and Selenium fail exactly the way our pixel calibrations did,
and teams solve it the same way: prefer stable identifiers over screen
positions. Idempotence is a core requirement in payments, APIs, and
infrastructure ("retry safely"). And "trust the instrument last" is how
senior engineers debug: when a test flakes, they suspect the test harness
before the product.
