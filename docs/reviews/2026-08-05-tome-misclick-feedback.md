# Feedback log — the tome misclick, twice

*Written 2026-08-05 at the user's request, after T70 run 2 halted on a
"full stash" that was nothing of the kind. The user diagnosed it from
the chair, for the second time: the bot right-clicked a Tome of
Identify instead of shift+right-clicking it, the cursor changed, and
town cleanup died.*

## What actually happened, both times

**2026-07-31 (R112/R113).** T27 halted: one item would not enter the
stash. The user identified it — a Tome of Identify, kind 534 — and
named the mechanism: the bot **plain-right-clicked it, which used it**.
The investigation found the cause: shift and the click were being sent
in the same frame, a race the game may resolve as an unmodified click.
Recorded then, verbatim: *"the identify cursor then ate the retry."*

**2026-08-05 (T70 run 2).** Same item. Same failure. The run halted
with `StashFull: 1 item(s) left in the inventory after both deposit
passes (kinds [534])`, and I reported to the user that their stash was
full and asked them to clear space. It was not full. The user corrected
me from what they had watched happen on screen.

## Why it looked solved

R113's fix was real and correct as far as it went: `_MODIFIER_SETTLE_S`
(one 25 fps frame) now sits on both sides of every modified click, in
both send paths, pinned by tests. The race got much rarer — hundreds of
deposits since, with no recurrence — and "much rarer" is
indistinguishable from "fixed" until the day it isn't. That is the
whole trap: **a probabilistic fix looks like a total fix right up until
the sample gets big enough.**

Three things made the illusion durable:

1. **The fix was filed under the symptom that triggered it, not the
   damage it caused.** R113 is titled "The shift race", and the race was
   genuinely fixed. Nothing tracked the *second* half of the same
   sentence — the identify cursor eating the retries — even though it
   was written down at the time. A known consequence with no owner is
   an unfixed bug that reads like a closed one.
2. **The retry could not differ from the attempt it retried.** This
   project has learned that lesson loudly at least three times (R161
   object clicks, R162 pathing, the patrol points) and even states it
   in comments — *a retry that cannot differ is not a retry*. The stash
   deposit re-clicked the identical pixel with the identical gesture
   into a cursor state that guaranteed failure, and nobody noticed the
   pattern because the deposit loop predates those lessons and was
   never revisited against them.
3. **The diagnosis was asserted, not evidenced.** `StashFull` was
   raised purely because a click did not have its effect. The evidence
   that would have refuted it was sitting in the same function —
   *other items deposited fine in that very visit* — and was never
   consulted.

## The part that should sting

Point 3 is not a new mistake. It is **the belt-full bug, verbatim, in a
different container.** In M5 (T56/T57, 2026-08-02) the bot decided the
belt was full because a potion "would not come up after 3 clicks", when
the belt had room and the real problem was the click missing the item.
We fixed it properly there — belt-full is now evidence-checked against
live counts in both directions — and wrote it up as a lesson about
never diagnosing a resource shortage from a failed action.

Then the identical shape sat untouched in the stash path, fifteen days,
through a full milestone closeout that specifically swept for stale
code. The M5 fix was applied to the *instance*, not to the *class*.
When a bug teaches you something, the question "where else does this
shape live?" has to be asked out loud, in the same session, or it does
not get asked at all.

## What changed now (four layers, not one)

1. **The hazard is gone, not narrowed.** Both tomes (534 identify, 533
   town portal) join the Horadric Cube in `offsets.UNMOVABLE_KINDS`. A
   tome's plain right-click arms a cursor or opens a portal — side
   effects that outlive the click and poison everything after it, which
   is the Cube's property, not a potion's. The Cube has never been
   right-clicked; now neither are these. Both are useful to keep in the
   inventory anyway, so the cost is two slots.
   *(That set's own comment invited this: "Quest items are the obvious
   future members; add them as they are met, with the reason." The tome
   was met on 2026-07-31 and never added.)*
2. **Retries differ.** `_attempt_deposit` closes and reopens the stash
   before any re-click (`_clear_cursor`) — ESC clears an armed cursor,
   and the reopen goes through the same verified panel-edge path as any
   other town interaction. Unconditional rather than gated on a cursor
   read, because the state that matters most (an identify cursor) is
   precisely the one `Inventory.pCursorItem` cannot see.
3. **The diagnosis is evidenced.** If anything deposited during the
   visit, the stash demonstrably has room, so a refusal is about the
   item — the alert says so, and the run continues.
4. **One stubborn item no longer ends a run.** Notice-and-continue, the
   policy the user already set for the belt-short case (R208). A loud
   halt is reserved for the case with actual evidence behind it:
   nothing deposited at all.

Six regression tests pin all four, including one asserting that a tome
is never clicked at all, and one asserting the panel is reopened
between attempts. 904 tests, ruff clean.

## Process changes worth keeping

- **A rare failure is not a fixed failure.** When a fix is
  probabilistic (a settle, a timeout, a retry budget), the write-up
  should say so explicitly and name what happens on the day it loses —
  the *recovery*, not just the *prevention*.
- **When a bug is understood, sweep the class.** The belt-full and
  stash-full diagnoses were the same bug in two containers. The
  milestone sweep looks for TODOs and dead code; it does not look for
  "this lesson's twin, elsewhere". It should.
- **Believe the operator's mechanism over the program's message.** The
  user has now diagnosed this exact failure twice, from watching the
  screen, while the program's own error text pointed at the wrong
  cause both times. `StashFull` was authoritative-sounding and wrong;
  the person watching was right. When those two disagree, the human
  observation is evidence and the error string is a hypothesis.
