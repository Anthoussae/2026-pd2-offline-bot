# P4 staging-point derivation — the north approach, plotted (gate artifact)

Everything here is measured, not invented: the chamber anchor is where
T68's read-only probe read her standing (kind 734 / unique_no 6, seed
`4e52715f`, 2026-08-05); the map is `maps/4e52715f-d2/area-025.json`,
the atlas T70 run 5 banked. Regenerate with the scratch script or by
calling `pd2bot.behavior.steps._screen_north_point` over the atlas.

## The convention (confirm this first)

**Screen-north is the world (-1,-1) diagonal.** The projection is
`sx = (wx - wy)`, `sy = (wx + wy)`: decreasing both coordinates moves
the point up the screen. Pure `-x` is screen NW, pure `-y` is screen
NE. If "approach from the north" meant something else to you, the
derivation below is aimed wrong and the step's `_screen_north_point`
bearings are the one place to fix.

## The derivation

The step asks, at run time, for the most-northerly **walkable** ground
within `staging_distance` (25) of the anchor: bearings north-first
(N, NW, NE) at each distance, distance descending. Against this seed's
atlas the answer is:

- **Anchor** `C` = (12548, 11036) — her T68 position (live read
  replaces it the moment she is in perception).
- **Staging** `S` = **(12531, 11036)** — 17 subtiles screen-NW, the
  chamber's own west band. Strictly-north-outside ground **does not
  exist**: the chamber is cut into solid rock on its north side, so
  every N/NE candidate at every distance is wall. The honest best is
  the chamber's north-west edge, and the advance from there runs
  screen-south-east into her — the approach direction you asked for,
  starting from inside the room's north rim.
- **Sweep pass** = anchor → `W` (12573, 11061) → anchor: the in-and-out
  through the heart of the chamber and its south-east corridor pocket,
  15 s budget.

## The map (4 subtiles per character; `#` wall/unknown, `.` walkable)

```
 11000 ######################################
 11004 ######################################
 11008 ########################........######
 11012 ########################........######
 11016 ########################........######
 11020 ########################........######
 11024 ########################........######
 11028 ########...............###....########
 11032 ########...............###....########
 11036 #######SS...C..........###....########
 11040 ########...............###....########
 11044 ########...............###....########
 11048 ########.....#####.....###....########
 11052 ########.....#####............########
 11056 ####.........#####..........BB########
 11060 ####.........#####WW#....#....###EE###
 11064 ####.........###..WW..........#..EE..#
 11068 ####.........###..............#......#
 11072 ####.........###..............#......#
 11076 ####.........###..............#......#
 11080 ####.........#####..#....#....########
 11084 ####.........#####............########
 11088 ########.....#####............########
 11092 ########.....#####.....###....########
 11096 ########...............###....########
 11100 ########...............###....########
 11104 ########...............###....########
 11108 ########...............###....########
 11112 ########...............###....########
 11116 ########################.#......######
 11120 ########################........######
 11124 ########################........######
 11128 ########################........######
 11132 ########################........######
 11136 ######################################
        x: 12500 ................... 12650
```

Markers: `C` her T68 position · `S` derived staging · `E` the
up-staircase to Cellar 4 (the arrival pocket) · `B` the kind-21
champion T68 read beside the stairs (the neighborhood clearance's
target) · `W` the sweep's far point.

Reading it: the chamber is the big west room with the central pillar
block; the arrival pocket `E` is the far east; the two `...` bands at
x≈12596-12628 (y 11008-11024 and 11116-11132) are the north and south
alcoves off the ring. The route from `E` to `S` runs through the
middle corridor and the chamber's north band — passing within her
engagement bubble is possible and accepted: the fight owns any tick it
claims, and the ladder plus chicken 35 stand above it throughout.

## Observation banked in passing (not P4's problem)

`area-025.json` also holds one detached room up at y 9620-9656 around
x 12584-12622 — exactly the ground around **Cellar 4's** staircase at
(12586, 9641). That is C4 terrain recorded under area 25's key during
the transition moment (the area id had flipped while the collision
read still saw C4's rooms). Harmless for this run — it is disconnected
from the real dungeon, so no route ever crosses it — but the recorder
racing the area flip is worth a look in the speed pass.
