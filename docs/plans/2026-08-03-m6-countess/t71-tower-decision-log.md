# T71 run 1 — the bot's decision log inside the Forgotten Tower

**What this document is:** every decision the bot recorded while it was
stuck in the tiny tower room, in order, in English — plus an explicit
account of what it did *not* record, because that turns out to be the
important part.

**Which test:** T71 **run 1** (2026-08-05 21:29:23 → 21:32:46). Run 2
was cancelled while it was still waiting for the operator's OK, so it
produced no gameplay and no data.

---

## The room, for reference

From the bot's own atlas (`maps/4e52715f-d2/area-020.json`), rendered
at one character per subtile. `A` = where it arrived, `X` = the
staircase down to Tower Cellar 1.

```
 8000 ########################################
 8001 #...................####################
 8002 #.....A.............####################
 8003 #...................####################
      (11 unremarkable walkable rows)
 8013 #.X.................####################
 8014 #...................####################
      (5 more walkable rows)
 8020 ########################################
```

19×19 subtiles of walkable floor. The staircase is **11 subtiles** from
the arrival point. The bot's own A* plans that as **one straight leg**.

---

## The complete decision log

Wall-clock stamps are from the narrative log
(`logs/run-20260805-212923.log`); the step lines are from the engine
report. This is **everything** the bot wrote down about those 144
seconds — not an excerpt.

| Time | Elapsed | What the bot recorded |
|---|---|---|
| 21:30:22 | 0 s | `traverse: done after 14s — arrived in Forgotten Tower at (10006, 8002)` |
| 21:30:22 | 0 s | `combat posture: brisk` |
| 21:30:22 | 0 s | `traverse: exit toward Tower Cellar Level 1 at (10002, 8013)` |
| *unstamped* | ? | `step traverse: clicked the staircase (attempt 1)` |
| *unstamped* | ? | `step traverse: clicked the staircase (attempt 2)` |
| *unstamped* | ? | `step traverse: clicked the staircase (attempt 3)` |
| *unstamped* | ? | `step traverse: clicked the staircase (attempt 4)` |
| *unstamped* | ? | `step traverse: clicked the staircase (attempt 5)` |
| 21:32:46 | 144 s | `NavigationError: clicked the staircase at (10002, 8013) 5 times without the area changing from 20 — the transition is not taking; giving the run up loudly` |

That is the entire record. Nine lines, five of which are clicks.

### What is missing, and how much of it

The run ticked **193 times in 203 seconds** (~1.05 s per tick). The
town preamble and the waypoint are single blocking ticks; Black Marsh
took ~15. So the Tower consumed roughly **140–170 ticks** — 140–170
separate decisions — and **five** of them left a trace.

The step had five other ways to end a tick, and every one of them was
silent (returned without a note, and the engine only logs a tick that
carries one):

- the fight branch (`combat.engage` returned an action)
- the item-collect branch
- the walk-a-leg-toward-the-exit branch
- the seek branch
- the click-pacing wait

So between 135 and 165 decisions happened and were discarded. **The
log cannot tell you which of those five it was doing**, and no amount
of re-reading changes that.

---

## What the record does and does not prove

**Proven — the map is fine.** Tested with the bot's own loader and its
own pathfinder, not a reimplementation: arrival and staircase are both
`known` and `walkable`; A* returns a 12-step path simplified to one
leg; the seed directory matches and `area-020.json` was rewritten
*during* the run. Full working in `navigation-diagnosis.md`. The bot
knew the layout and knew where the stairs were.

**Proven — pathfinding was never invoked.** The staircase was 11
subtiles away and `click_range` is 18, so the step went straight to
clicking. It never planned a walk in that room. Whatever went wrong,
routing was not asked to do anything.

**Not proven — "it was fighting."** Asserted earlier; the evidence
contradicts it. The whole run logged **6 reflex fires**, none of them
in the Tower, and no upkeep there at all. A 144-second fight would have
fired upkeep repeatedly.

**Not proven — "monsters were standing on the staircase."** Possible,
but a contested staircase would still have clicked every 3 seconds
after its hold expired — roughly 48 clicks, not 5. The
`exit_block_radius` rule added for this story is defensible on its own
terms (a left click on a monster is a Poison Strike, so it cannot
transition, so it must not spend the budget that judges the
transition), but it is **not** a proven fix for this failure.

**The open question the numbers actually pose.** Five clicks in 144
seconds is one click per ~29 seconds, against a 3-second retry pace.
Something consumed ~26 seconds between each pair of clicks. The
progress-aware pacing offers one candidate: the clock resets on every
subtile of progress toward the stairs, so *if the character was
creeping closer*, re-clicks would be suppressed exactly like this. That
would mean the clicks were being executed as **walk orders** rather
than interactions — which is the hypothesis below.

---

## Leading hypothesis for the next test

`InteractObject` clicks the **raw tile projection** with no offset
(`execute.py`). Two hundred lines above it in the same file, T63's
measured result for items: a tile-projection click misses the sprite
about **29 times in 30**, because sprites draw *upward* from their
tile — which is why item pickup carries an eight-point aim schedule.
Object clicks never got one.

A click landing on the floor short of the stairs is, to the client, a
**walk order**. The character takes a step or two, stops, gets clicked
at again, steps again — which is what "clicking around randomly" looks
like from the chair — and the transition only fires when a walk happens
to finish on the warp tile. That is consistent with the transitions
that *did* work (T70 run 5, and this run's own Black Marsh → Tower hop
three clicks earlier).

**This is a hypothesis, not a finding.** It is written down here so
that the next run either confirms or kills it.

---

## What now produces an answer

`TraverseStep` now records every decision. Consecutive identical ones
collapse into a single line carrying a tick count, a duration, the
character's position and its distance to the stairs:

```
traverse[21]: clicked the staircase (attempt 1) [at (10006, 8002), 11 from the stairs] — 1 tick(s) over 0.8s
traverse[21]: waiting out the last click (10 away) [at (10005, 8003), 10 from the stairs] — 4 tick(s) over 3.4s
traverse[21]: fighting: AttackUnit [at (10005, 8003), 10 from the stairs] — 7 tick(s) over 5.9s
```

Read the position column and the question answers itself:

- **position creeps toward the stairs after each click** → the click is
  being executed as a walk order → the aim is wrong (the sprite-offset
  hypothesis), and the fix is an aim schedule for objects, or walking
  onto the warp outright.
- **position never changes and the log says `fighting`** → the fight
  really did own the ticks after all.
- **position never changes and the log says `waiting out the last
  click`** → the clicks are reaching the stairs and the game is
  refusing them, which is a different problem again.

The trace is flushed immediately before any loud give-up, so the
failure message now arrives with the history that produced it.
