# M3 live verification runbook

Everything here needs an **elevated** terminal (the client runs elevated)
at the repo root, with PD2 running and `MaqiuDoubing` in a game. Results
get pasted back into this file (or told to the agent) — they gate the
milestone.

Set once per shell:

```powershell
$py = "$env:USERPROFILE\.venvs\pd2bot\Scripts\python.exe"
```

## 1. Gate refusals (P1) — the incident's regression test

Run it three times, in three states (order below is the convenient one):

| # | How | Command | Expected |
|---|---|---|---|
| a | Open the ESC menu in game, alt-tab to the terminal | `& $py -m pd2bot.navdemo gate` | `REFUSED — a blocking panel is open (esc_menu)` |
| b | Close the menu (back in normal play), stay in the terminal | `& $py -m pd2bot.navdemo gate` | `REFUSED — ... not in the foreground` |
| c | Same state, let the tool grab focus itself | `& $py -m pd2bot.navdemo gate --focus` | `focus request: game is now foreground` then `input allowed` |

(a) works while the terminal is focused because the panel check reads
game memory, not window focus. (b) is the foreground check doing its
job — the terminal having focus is the tested condition. (c) exists
because you cannot press Enter here *and* have the game focused, so
`--focus` makes the tool bring the game forward before checking,
exactly as the bot does before walking; alt-tab back to read the
verdict.

Result: **PASS, all three states** (2026-07-28, user-run, elevated):

```text
> gate            (ESC menu open, terminal focused)
gate: REFUSED — a blocking panel is open (esc_menu) — a click would land on the panel, not the world
> gate            (normal play, terminal focused)
gate: REFUSED — the game window is not in the foreground — input would go to another application
> gate --focus    (normal play)
focus request: game is now foreground
gate: input allowed (in game, no blocking panel, window foreground)
```

## 2. Projection calibration (P1)

In open ground (no walls immediately south-east):

```powershell
& $py -m pd2bot.navdemo click-test --send
```

Expected: character walks a short hop down-right; printed error within
~3 subtiles.

Result: **calibrated, then PASS pending re-confirm** (2026-07-28).
First two runs both showed a consistent −4 subtile undershoot, which
`navdemo calibrate` (12 walks, 8 directions) resolved: PD2 renders at a
lower resolution and upscales, so the world is 1.25× larger than the
unscaled 16/8 px per subtile. Measured **20 / 10**, x/y ratio 2.000
(the isometric model agreeing with itself); now in `screen.py`.

Second finding from the same run: clicks beyond ~320 px complete only
60–70% of their distance, while ≤320 px land on target. This is why
waypoints are capped at 12 subtiles (`MAX_WAYPOINT_SPACING`).

Re-run after calibration: **PASS**.

```text
player at (5884, 5747), target (5904, 5747)
clicked at (1168, 632); watching until the character stops...
ended at (5904, 5748); target was (5904, 5747); error (0, 1) subtiles
implied px/subtile: x 21.05, y 9.52
```

x exact, y within one subtile of arrival tolerance; implied values
scatter around the configured 20/10 as expected for a single short hop.

## 3. Collision vs eyes (P2)

Standing anywhere interesting (town edge, Cold Plains fence):

```powershell
& $py -m pd2bot.collision
```

Check all four: (a) each room grid's size prints plausibly (tens of
subtiles); (b) a wall you can see = `#` in the right direction; (c) the
ground you stand on and around = `.` with `@` at center; (d) walk ~20
subtiles, re-run, picture tracked the move.

Result: **PASS, all four** (2026-07-28), but only after a layout fix —
the first run returned **0 room grids**. `--debug` showed why: every
room's `pMapStart` equals `Coll + 0x24`, i.e. the grid is stored inline
after a 0x24-byte header, so what the community headers call `pMapEnd`
does not exist in this build and the dword there is the first two
collision cells. The bogus size check was replaced with the header's own
tile/subtile invariant (`posGame == posRoom * 5`, `sizeGame ==
sizeRoom * 5`), which the live rooms satisfy exactly. See `offsets.py`.

After the fix, standing beside a map-edge cliff: 9 rooms (3x3), each
40x40 subtiles from 8x8 tiles; obstacle summary reported the wall
1 subtile to screen-right; open ground 20-46 subtiles elsewhere.

The tracking check (d) was stronger than required: walking from
(5951, 5755) to (5938, 5751), the cliff stayed at **world x = 5953 in
both dumps** (column 32 of a view starting at 5921, then column 45 of a
view starting at 5908) while the view re-centred on the player, and a
large structure appeared 12 subtiles up-left where the player had
walked toward a tent. Terrain fixed in world space, view follows the
player — exactly right.

## 4. Survey walk (P3, re-scoped to the explored-map atlas)

In a game, standing in Cold Plains:

```powershell
& $py -m pd2bot.navigate --survey
```

Then just walk around the waypoint area for a minute or two (a loop of
~a screen's radius is plenty), watching the recorded-rooms counter
climb, and Ctrl+C. **No input is sent — you drive.** Expected: counter
grows as you enter new rooms, then slows sharply as you re-cover known
ground; a `maps/<seed>-d2/area-003.json` file exists afterward.

First attempt (2026-07-28) reported **247** rooms recorded for one
area — an order of magnitude too many, and the user correctly guessed
why: monsters have collision, so their movement rewrote rooms
continuously. Fixed by stripping occupancy bits before storing (see
`COLL_TRANSIENT_MASK`); the same bug would have baked corpses into the
atlas as permanent walls via `IS_ON_FLOOR`. Delete `maps/` and re-survey
after the fix.

Result (post-fix): **PASS — 34 room grids** for the same walk that
previously reported 247. The ~213 difference was entirely monster
movement being mistaken for new map knowledge.

## 5. Atlas persistence check

Run the survey again for a few seconds *without moving*:

```powershell
& $py -m pd2bot.navigate --survey
```

Expected: the counter stays at or near 0 (everything in view is already
in the atlas — re-seeing identical rooms records nothing new). Then
save-and-exit, re-enter the game, and run it once more: still ~0,
because single-player kept the same seed and the file survived the game
cycle.

Result: **PASS — the design's core assumption is confirmed.**

- Standing still: **0** recorded.
- On disk: one seed folder `4e52715f-d2`, one `area-003.json`, 147,055 B.
- After save-and-exit **and a fresh game**: still the *same seed folder*
  — no second directory — and a later survey in known ground read
  **0 new, 0 re-recorded**. Map knowledge carried across the game cycle
  exactly as the ADR assumes.

One wrinkle, benign and now instrumented: the first survey inside the
fresh game reported 125 re-records. The file size was byte-identical
before and after (147,055), so those were the *same ~34 rooms* rewritten,
not new ones — a newly respawned monster pool churning a collision bit
that `COLL_TRANSIENT_MASK` does not yet strip (most likely `DarkArea`
0x0010, which kolbot documents in the combination
`MonsterIsOnFloorDarkArea`). It is not a walkability bit, so pathing is
unaffected, and stored walkability was stable throughout.

To identify it for certain: start a **new game** with monsters alive and
run `--survey` briefly. The output now reports per-area `new` vs
`re-recorded` counts and names the exact bits that changed, flagging any
that should have been stripped.

## 6. Acceptance walk (P4) — 5/5

At the Cold Plains waypoint, after the survey walk:

```powershell
& $py -m pd2bot.navigate --demo
```

Five consecutive runs. Each prints waypoints/clicks/re-clicks/re-plans
and PASS/FAIL. To force a stuck/re-path demonstration once: start facing
a fence corner.

Result: **PASS 5/5** (2026-07-28). First attempt (R15) failed by
design flaw — the demo aimed a fixed +42/+42 offset into unsurveyed
ground; rewritten to sweep for a known/walkable/A*-reachable target and
to print its map-knowledge bounds first. After that: ten ~60-subtile
walks, all arrived, 2.9–6.7 s each, atlas bounds (5120, 5560, 5360,
5840). The ladder demonstrated itself: seven re-clicks across the runs
(one absorbing the user physically touching the mouse mid-walk — user
input wins, bot re-issues), and demo 3 hit a genuine stuck at
(5241, 5749), re-planned from the live position, and arrived. No run
needed more than one re-plan; two runs were clean end-to-end.

## 7. M2 leftover — ground items (one minute)

Drop any item on the ground, then:

```powershell
& $py -m pd2bot.dump -v
```

Expected: the item appears under "items on the ground" with a position
near you; pick it up, re-run, it disappears. Result: __
