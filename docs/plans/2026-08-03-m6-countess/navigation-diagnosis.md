# Why the bot moves like it cannot read the map (T70 descent)

*User observation, 2026-08-05, watching the descent: "Long delay in the
first tower level — seemed unsure where the stairs were, bot ran into a
corner for several seconds. In the tower cellar lvl 1 it failed: killed
some enemies (good), then ran around in a corner, and gave up. My
diagnosis: the bot doesn't actually have access to a floorplan or map
model that it can read... 2nd possibility: my earlier requests for
human-readable representations have muddied the python-readable
layouts."*

The observation is exactly right. Both proposed causes are wrong, and
the tests below say so unambiguously. The real cause is worse in one
way and much better in another: the map is perfect, and the bot has no
idea where it is going.

## Hypothesis 1 — "no floorplan it can read": REFUTED

Tower Cellar Level 1 (area 21) loaded from the atlas, live data, no
mocks:

    rooms: 19            bounds: (10000, 5000) - (12740, 8040)
    the descent's arrival point (12517, 5183): walkable YES, known YES
    sampled cells: 3858 walkable of 7600 known
    A* from the arrival point to the far corner (12736, 5144):
        ROUTE FOUND — 288 steps, simplified to 32 waypoints

So the bot holds a complete, queryable floorplan of that cellar,
including unwalkable terrain, and can plan a route across the whole
level in milliseconds. It was standing on known ground the entire time
it appeared lost.

## Hypothesis 2 — "human-readable output muddied the layouts": REFUTED

The stored format was never text:

    room keys: cells, h, w, x, y
    cells = base64 of 3200 bytes = 1600 cells x 2 bytes (16-bit flags/subtile)
    no ASCII grid anywhere in storage

`collision.ascii_map` ('@' player, '.' walkable, '#' blocked) is a
**CLI diagnostic that renders FROM the machine format** — a view, never
a store. Nothing the bot navigates by has ever been parsed from text.

## What is actually wrong

**The atlas records where the FLOOR is. It does not record where the
STAIRS are.** Those come from a separate live memory read — and that
read has a hard limit discovered by this very run:

> A Room2's preset/warp chains are only populated for rooms whose data
> the client has **added**, which it does around the player. d2mapapi
> (the generator this repo vendors) calls `D2COMMON_AddRoomData` on
> every room *before* reading its presets — a call an out-of-process
> reader cannot make.

So in Cellar 1 the bot could see the whole floor, and exactly **one**
exit: the up-staircase it had just arrived on. The down-staircase, two
rooms away, was invisible — not "far", not "unreachable", *absent from
perception*. The step then did the honest thing and gave up:

    NavigationError: area 21 has no exit toward area 22
      (1 exit(s) read: [(20, (12515, 5181))])

**A bot with a perfect map and no destination is indistinguishable from
a bot with no map.** That is the whole illusion. The "running around in
a corner" was the combat module doing its brisk drift/strike/retreat
around the monsters it killed — real, correct behavior — with no
travel target to leave for afterwards.

(The Forgotten Tower pause was a different, already-known thing: the
exit WAS found 11 subtiles away, and ~10-15 s went to time-based
staircase re-click pacing — see `performance-notes.md`.)

## The fix: seek, don't guess

Room POSITIONS are static Room2 fields (`dwPosX/Y`, `dwSizeX/Y`) and
enumerate level-wide regardless of initialization — the T68 probe read
16 rooms in Cellar 5 while standing in one of them. Only the PRESETS
inside them need loading. That gives a precise, fully-planned search:

1. Scan exits. If the wanted destination is visible, walk and click it
   (today's behavior, which works).
2. If not, pick the nearest room whose presets have not been read yet,
   **route to it over the atlas** (A*, capped legs, ladder consulted —
   the machinery proven above), and re-scan as its data loads.
3. Repeat until the exit appears. Never random, never blind: every
   candidate is a known room centre on known ground.
4. **Remember it.** `ExitMemory` (already built) stores the position
   per map seed, so this search happens ONCE per cellar, ever — every
   later run walks straight there.

This is the user's own Q10 fallback, automated: they proposed manually
walking each level and marking exits. The bot can do that walk itself,
because the atlas already tells it where every room is and how to reach
it.

**Expected shape after the fix:** first descent pays a short search per
cellar (bounded by the level's room count — 14-20 rooms each); every
descent after that goes straight to each staircase from memory.

## Standing correction to the P1 write-up

`exits.py`'s docstring claimed exits were "enumerable area-wide from
anywhere inside the level". That was wrong — inferred from Room2 being
static, never tested against a level bigger than the player's loaded
neighbourhood. The Forgotten Tower (3 rooms, all loaded at once) passed
T68 and stage one and hid the limit completely. Corrected in the module
docstring with the evidence.

---

# Addendum — T71, the Forgotten Tower (2026-08-05)

*User observation, watching T71 run 1: "bot got stuck in a tiny square
room with one exit and one entrance (the forgotten tower). There's no
way that it knows the layout & the stair location, or if it does,
something is horribly wrong with the pathfinding. I have a bad feeling
that the agent is hallucinating that the bot knows the layout."*

The suspicion is fair and the answer is the same as last time, tested
the same way — but this addendum exists mainly to record the thing the
first diagnosis missed, which is that **the artifact could not answer
the question at all**.

## The map: KNOWN, again, and this time it is the whole room

Area 20 from the atlas, live data, no mocks, using the bot's own
`MapStore` loader and its own `astar`:

    rooms stored: 3 (see contamination note below)
    the Tower's own room: origin (10000, 8000), 40x40 subtiles
    arrival (10006, 8002):  known YES  walkable YES
    staircase (10002, 8013): known YES  walkable YES
    walkable cells: 361 of 1600
    nearest_walkable(exit) -> (10002, 8013)   (the exit tile itself)
    astar(arrival -> exit) -> 12 steps, simplified to [(10006,8002),(10002,8013)]

Rendered, the Tower is a 19x19-subtile walkable box — exactly the
"tiny square room" the user describes — with the arrival and the
staircase 11 subtiles apart inside it, and one straight leg between
them. The bot had a complete floorplan and a valid one-hop route the
entire time. **Pathfinding is not implicated: in T71 the step never
called it**, because 11 <= `click_range` 18, so the step goes straight
to clicking without ever planning a walk.

The map seed also matches (`maps/4e52715f-d2/` is the only seed
directory, and `area-020.json` was rewritten at 21:30, during the run),
so the atlas being stale or mis-keyed is ruled out too.

### Contamination noted in passing

`area-020.json` holds three 40x40 rooms, and only one of them is the
Tower's: the others sit at (12500, 5160) — Cellar 1's arrival — and
(15240, 5770) — Black Marsh's waypoint. Same shape as the stray C4
room found in `area-025.json`: the collision recorder writes under the
area id it read at that moment, and an area flip mid-read files a
neighbour's room in the wrong atlas. Harmless here (disconnected
patches, no route crosses them) but it is a real recorder bug and
belongs in the speed/robustness pass.

## What the bot actually did in the room: UNKNOWN, and that is the bug

144 seconds in that room. **Five log lines**, all of them "clicked the
staircase (attempt N)". At the run's measured ~1.05 s per tick (193
ticks / 203 s) the room cost roughly 140-170 ticks, so ~165 decisions
were made and recorded nowhere.

Every other return path in `TraverseStep` was silent — the fight
branch, the collect branch, the walk legs, the click pacing all
returned `acted`/`waiting` with **no note**, and the engine only logs a
tick that carries one. So the honest answer to "what was it deciding?"
was: the artifact does not say, and no amount of re-reading it will
make it say.

Two stories were floated from that silence and **neither is supported**:

- *"The entrance fight owned the ticks."* The run logged **6 reflex
  fires total**, none in the Tower, and no upkeep there at all. A
  continuous fight would have fired upkeep repeatedly.
- *"The staircase was contested by monsters."* Possible, but a
  contested staircase would still have clicked every 3 s after its
  hold, giving ~48 clicks, not 5.

The `exit_block_radius` rule added in response to the first story was
**REVERTED** on 2026-08-05 (R220 Q10), and the reason matters more than
the rule did. The user supplied the fact that killed it outright:

> *"There were no monsters in the forgotten tower floor, and there
> never are. It is just an empty square with an entrance and an exit."*

An empty room does not merely weaken the contested-staircase story — it
removes its subject. And it sharpens the arithmetic into something no
surviving hypothesis explains: with no hostiles and no ground items,
`TraverseStep` should fall through to the click branch on **every**
tick and click every `exit_retry_s` (3 s) — roughly 48 clicks in 144 s.
It made **five**, one per ~29 s. Some ~26 s per cycle goes somewhere
that nothing in this codebase records.

That gap is now the open question, and the answer is being built rather
than guessed: `docs/plans/2026-08-05-run-event-log/` (structured event
log, tick timing, per-decision records), with
`docs/adr/2026-08-05-run-event-log.md` recording why instrumentation
stopped being optional.

## The instrumentation fix (the actual deliverable)

`TraverseStep.step` is now a thin wrapper over `_decide`, and every
previously-silent return path carries a note naming the decision.
Consecutive identical decisions collapse into one line with a tick
count and a duration, and the position + distance-to-stairs ride along:

    traverse[21]: clicked the staircase (attempt 1) [at (10006, 8002), 11 from the stairs] — 1 tick(s) over 0.8s
    traverse[21]: waiting out the last click (10 away) [at (10005, 8003), 10 from the stairs] — 4 tick(s) over 3.4s

A healthy traverse costs a handful of lines; a stuck one prints the
exact shape of its stall, including whether the character is moving.
The trace is flushed before every loud give-up, so the failure message
now arrives with the history that produced it.

## The leading hypothesis to test next (NOT yet evidence)

`InteractObject` clicks the **raw tile projection**
(`gated.click_world(*action.position)`, execute.py) with no offset. Two
hundred lines above it in the same file sits T63's measured finding for
items: the tile projection misses a sprite roughly **29 times in 30**,
because sprites draw *upward* from their tile — which is why pickup has
an eight-point offset schedule and object clicks never got one.

If a staircase click lands on the floor short of the stairs, the client
reads it as a **walk order**, and the observed behaviour follows: the
character shuffles a couple of subtiles, stops, is re-clicked, shuffles
again — "clicking around randomly" — and the transition only fires on
the runs where a walk happens to end on the warp tile (which is how
T70 run 5 and this run's own Black Marsh -> Tower hop succeeded).

The decision trace answers this directly on the next run: if the
position moves a little after each click, the click is a walk order,
and the fix is an aim schedule for objects (or walking onto the warp
outright) rather than anything to do with maps or monsters.
