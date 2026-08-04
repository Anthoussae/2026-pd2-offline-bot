# Livelocks, margins, and the kill switch — 2026-08-02 (evening)

*Cycle: the T54/T55 live-test loop — merc-feed acceptance, the timed
patrol, and the fixes each run's failure bought (R183–R190). The patrol
went 1032 s → 458 s → 217 s across three timed runs.*

## The big idea

Tonight was one lesson wearing four costumes: **a single observation is
not a fact.** A single hp read fed a full-health merc for a whole game;
a single "no route" answer wrote off reachable ground; a single subtile
of "progress" kept a dead loop alive; and a single keypress (the
bot's own ESC) can look exactly like the operator's. The cure was the
same every time: demand a second, independent confirmation before
acting on what one reading claims.

## Key concepts

**Livelock, again — in a new costume.** The border loop was a program
working furiously while achieving nothing: every walk *succeeded*, so
every watchdog stayed fed. The tell was that the walk succeeded
*without getting closer to its purpose* — the pickup never came within
reach. The general rule this project keeps re-learning: budgets must
measure **progress toward the goal**, never effort spent. Any code
path that can act without progressing needs its own budget, and tonight
the pickup path paid for having none.

**Progress needs a margin.** The patrol's budget reset whenever a leg
landed *any* amount closer — and the loop obliged with a single subtile
of wobble every few legs. Requiring improvement to beat the best by a
**margin** (2 subtiles here) is a form of **hysteresis**: making a
system's decisions sticky so noise can't flip them. The trade is
honest: slow-but-real progress still re-earns the budget, noise never
does.

**Debouncing a noisy reading.** The route planner occasionally answered
"no route exists" for ground it had happily pathed seconds earlier — a
torn read of live memory. The fix is classic **debouncing**: an
alarming reading is acted on only when a second, *fresh* reading
agrees (and we stopped caching the alarming answer, so the retry
really is fresh). Genuine no-routes still die in two ticks; transient
lies die alone.

**Priority inversion.** The bone armor — a survival concern — kept
losing its cast window to the revive wall's maintenance casts, because
a failed armor attempt sat out a 2-second pacing while the lower-
priority work kept the pipeline busy. A high-priority task starved by
a low-priority one holding a shared resource is a **priority
inversion**, a classic concurrency failure with a classic fix: while
the high-priority need is pending, the low-priority work does not get
the resource (here: the tick).

**The kill switch, or: knowing your own hands.** "When I press ESC or
Enter, stop" sounds trivial until you remember the bot also presses
ESC. The design distinguishes them by **correlation**: the bot stamps
the time of its own sends, and a menu appearing outside a short grace
window of that stamp can only be the operator's. This is the same move
as the blood warp's position-verify — you cannot always observe *who*
caused an effect, but you can know what *you* did and when, and
subtract it.

## Where you'd meet this professionally

All four are staple production-engineering patterns: progress-based
watchdogs and budgets (liveness monitoring), hysteresis and debouncing
(alerting thresholds, sensor handling, UI events), priority inversion
(the Mars Pathfinder famously rebooted itself over one), and
self-correlation (distinguishing your own writes from others' in
distributed systems). "One reading is a signal, two readings are data"
is a sentence you will hear in every incident review.
