# Measuring what the bot can see — 2026-08-01

*Cycle: M5 P6 — the perception calibration (tests T50/T51) and the three
fixes it forced: the patrolling loot sweep, the click audit, and the
goal-exemption repair.*

## The big idea

The code carried a constant, `PERCEPTION_RADIUS = 80`, and everyone —
comments, sizing math, run files — treated it as *how far the bot can
see*. Two measurements showed it was nothing of the sort. The game
client only keeps the rooms near the player loaded, and things beyond
that simply do not exist in the bot's data — at 46 to 67 subtiles out,
well inside the 80. The constant was a fence built past the edge of a
cliff: technically a limit, never the one that mattered. Every feature
that assumed "we can see 80" (declaring a circle clear, sweeping loot
from a standstill) was quietly wrong, and the fix in each case was the
same: if you cannot see the whole area, *walk* it.

## Key concepts

**Binding constraint.** When several limits apply at once, the only one
that matters is the one you actually hit first — the *binding* one. Our
radius filter (80) and the client's room-loading horizon (~46-67) both
limit perception, but the horizon always binds first, so the constant
was dead weight: raising it to 200 would change nothing. Asking "which
limit actually binds?" is a cheap question that regularly kills whole
plans (any optimization aimed at a non-binding limit is wasted).

**Controlled experiment.** T51 had to separate two explanations that
look identical from the outside — "our filter hides the item" vs "the
client never loaded it". The trick: scan *twice* at every sample, once
with the filter at 80 and once with it effectively off, and watch which
scan loses a dropped item first. If the item vanishes from both at the
same distance, the filter is innocent. (Dropped potions made good
probes because they cannot move, so where they were dropped stays true
forever.) Designing the measurement so the two hypotheses *must* come
apart is what makes it an experiment rather than an observation.

**Instrumentation.** Junk items kept appearing in the inventory with no
deliberate pickups behind them. Instead of guessing at a fix, we added
an *audit*: a small function that watches every travel click and logs
how close it landed to a ground item — and changes nothing. That is
instrumentation: measurement code living inside the real system,
deliberately inert (its failures are swallowed so a broken probe can
never break a walk). One run of data settled the argument: the
avoidance radius was fine; a special-case exemption was letting 31 of
39 clicks through. We fixed the exemption and kept the audit.

**Know your cost driver.** T50 also timed the scans: ~7 ms with 30
units around, ~19 ms with 65 — identical at every radius. The cost of a
scan is driven by *how many things there are*, not *how far we ask to
look*. Knowing which variable actually drives cost matters because it
tells you what an optimization could ever buy; an earlier design
argument for keeping the radius small was reasoning about a cost that
does not exist.

## What we did, in these terms

T50/T51 found the **binding constraint** by **controlled experiment**;
the constant's comment now records the truth. The loot sweep — which
could only see a third of its circle from a standstill — now walks the
same patrol ring the clearance does. The click audit
(**instrumentation**) identified the real junk-pickup mechanism, the
goal exemption was narrowed from "anything near a destination" to "the
exact item being walked to", and the audit stays in place to confirm
the fix on the next live run.

## Where you'd meet this professionally

"Measure before you optimize" is close to a professional commandment —
profilers, tracing, and metrics dashboards are the industry's
instrumentation, and adding a temporary probe before touching the code
is exactly how experienced engineers approach a mystery. The
binding-constraint question shows up as capacity planning ("we tripled
the thread pool and nothing sped up — the database was the bottleneck")
and in config archaeology: production systems accumulate settings that
no longer do anything, and proving one dead requires exactly the kind
of differential test T51 ran. Honest depth note: we glossed over *why*
the client loads a ~3×3 room neighbourhood; that is Diablo II
internals, not a general concept.
