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
