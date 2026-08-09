# Navigation: how the bot decides where to walk, and how it walks there

M3's layer on top of perception. Perception answers "what is around me";
navigation answers "how do I get over there" — and it contains the
project's first code that *acts* on the game instead of reading it.

Companion docs: [perception.md](perception.md) (M2, the reading side),
the [hybrid map-knowledge ADR](../adr/2026-07-28-hybrid-map-knowledge.md),
and the archived M3 planning dir
([docs/archive/plans/2026-07-28-m3-navigation/](../archive/plans/2026-07-28-m3-navigation/plan.md)
— live-check results, the generator post-mortem, the implementation log).

## The input gate (`window.py`, `input.py`)

The one rule, learned the hard way: during M1 a test click was sent while
the in-game ESC menu happened to be open, and it activated **"Save and
Exit Game"**. A screen coordinate means whatever the currently-open panel
says it means, and a click means nothing we intended if another window
receives it.

So input is structural, not conventional:

- There is exactly **one send path** (`GatedInput`), and it checks, at
  the moment of sending: `uistate.can_act()` (in a game, no blocking
  panel) **and** `GameWindow.is_foreground()` (the click will land in the
  game). Either failing raises `InputRefused` with the reason; nothing is
  sent.
- There is **no bypass**: no "unsafe" method, no testing flag. Unit tests
  fake the OS layer. M4's menu clicking (game creation happens *outside*
  a game, where `can_act` is rightly false) kept this contract: it is a
  separate path with the complement guard — see `menuinput.py` and
  [game-cycle.md](game-cycle.md) — and this gate was not touched.
- The check runs **twice** per click (before the cursor move and again
  before the button event): the tiny check-then-send race is accepted and
  documented rather than pretended away — the game can spontaneously
  open a panel (death), but nothing we do between the two checks makes
  that more likely.

`GameWindow` re-queries the client rectangle on every use (the user may
move the window), finds the window by process id, and verifies foreground
with `GetForegroundWindow` after asking for it — Windows is allowed to
refuse focus changes, so "I asked" is never treated as "I got".

## World → screen projection (`screen.py`)

D2's camera is locked on the player, drawn at the client area's center.
A floor tile is a 160×80 pixel diamond spanning 5×5 subtiles, so one
subtile moves a point 16 px along screen-x per (dx − dy) and 8 px along
screen-y per (dx + dy) — *in render pixels*.

**The window is not render pixels.** PD2 draws at a smaller resolution
and upscales, so the constants had to be measured, not derived: live
calibration (2026-07-28, 12 walks in 8 directions) fitted **20 / 10**
px per subtile — exactly 1.25× — with an x/y ratio of 2.000, the
isometric model confirming itself. The config files were no help here
and in fact disagreed with reality; the walk measurement is the
authority. `python -m pd2bot.navdemo calibrate` re-measures, and must
be re-run after any resolution, window-size, or renderer change.

The same calibration found that a single click only carries the
character ~320 px; beyond that it completes 60–70% of the distance.
That limit — not screen size — is what sets the waypoint spacing cap in
`pathing.py`. `clickable()` additionally keeps clicks off the window
edges and out of the bottom HUD strip, which is held as a *fraction* of
client height so it stays correct at other resolutions.

## Live collision (`collision.py`)

Each loaded `Room1` points at a `CollMap`: a grid of 16-bit flag words,
one per subtile — the game's own answer to "can you stand here". This is
the **ground truth** all other map knowledge is judged against.

Two things are deliberate:

- **The layout is not from BH.** PD2's BH source stops at the `Coll`
  pointer; the struct is cited in `offsets.py` from two independent
  lineages (D2BS's engine source and the D2Warden server headers), which
  agree field-for-field, and every read validates
  `pMapEnd − pMapStart == 2 × width × height` before trusting a grid —
  a torn or wrong pointer fails that arithmetic and returns None instead
  of garbage.
- **Unknown ≠ blocked.** Only the player's room neighbourhood is loaded.
  `LocalCollision.is_known()` distinguishes "wall" from "beyond what is
  loaded"; planning treats unknown as unwalkable, but the follow loop
  knows the difference when deciding whether reality disagreed.

Walkability masks kolbot's `BlockWalk` (0x1805: wall | ranged-blocker |
closed door | floor object). Closed doors count as walls until a later
milestone teaches the bot to open them (deferred out of M4 — the game
cycle never meets a door, and neither does the Cold Plains route).

`python -m pd2bot.collision` prints the stitched neighbourhood as ASCII
(`@` player, `.` open, `#` blocked, space unknown) — the eyeball tool
for checking the grids against the screen.

## The explored-map atlas (`mapstore.py`)

Whole-area walkability comes from *remembering*, not generating: in
single player the map layout is fixed per character per difficulty, so
every room grid perception has ever read stays true. `MapStore`
persists them to `maps/` (gitignored save-data), keyed by (map seed,
difficulty, area); the navigator plans on the atlas with live grids
overlaid on top (live wins where loaded), and records what it sees
about once a second while walking. `python -m pd2bot.navigate --survey`
records while a *human* walks, sending no input — one survey walk per
new area is the expected setup cost, after which routes plan across the
whole area.

The seed in the file key is the staleness guard: any layout re-roll
(difficulty swap, new character) changes the seed and misses the cache,
so the bot starts blank instead of trusting a wrong map.

## The automated survey (`survey.py` + the `survey` run step)

M5 P6 (R175/R176) made the survey walk self-driving. `survey.py` finds
the **frontier** — recorded walkable ground with unrecorded ground just
beyond, computed from the stored room edges and clamped to the target
area's own bounding box so it never chases the neighbouring areas'
ground. The `survey` run step walks to the nearest frontier point, the
client loads the rooms beyond (its ~3x3-room horizon — measured at
46-67 subtiles, T51), the passive recorder stores them, and the
frontier moves outward until none remains. Unreachable frontier (across
a river) gets the patrol's no-progress give-up, and a hard leg budget
backstops convergence bugs.

Two shipped runs: `runs/survey-cold-plains.toml` (preamble → waypoint →
survey) and `runs/survey-town.toml` (survey from the town spawn). They
are normal engine runs — reflex ladder, chicken, death latch all in
force — and fight only inside `survey_engage_radius` (~30 subtiles,
R176 Q1): a survey is not a clearance. Re-running a finished area is a
no-op by design: zero frontier, immediate completion.

Mid-run auto-surveying was considered and rejected (R176 Q2): passive
recording already grows the atlas on every walk, and a clearance that
detours into a survey stops being a clearance. Instead, a run that
gives up on a target because its ground was *never seen* (the
NavigationError message distinguishes this from "solidly blocked") says
so loudly once per game and names the survey run as the permanent fix.
The manual `--survey` mode above remains valid — the user walking the
area records exactly the same atlas.

An offline generator (`mapdata.py` + a built d2mapapi_mod) exists as a
dormant alternative for maps the bot has never walked; it is blocked on
this machine by PD2's modified DLLs. History and unblock path: the
map-knowledge ADR and the M3 planning dir's `generator-status.md`.

## Planning and walking (`nav/pathing.py`, `nav/navigate.py`)

`pathing.py` is pure logic (no game, no OS, fully unit-tested): A* over
anything with `is_walkable`/`is_known` — 8-directional, integer costs
10/14, octile heuristic, and **no corner cutting** (a diagonal step
requires both orthogonal shoulders walkable, because the character has
width and the game wall-slides where pointsized math would clip).
`simplify()` collapses paths into waypoints ≤ 12 subtiles apart — the
cap keeps every hop clickable on screen. `OverlayGrid` merges the
generated base with live patches (live wins where known).

`nav/navigate.py` follows waypoints with gated clicks and watches the
player's actual position. The escalation ladder when position stops
changing: re-click → re-plan from where we really are (fresh grids) →
after 5 *no-progress* plan cycles, raise `NavigationError` with the
history. Move speed is deliberately never assumed (run/walk, boots,
chill, Holy Freeze all change it): stuck means *zero cumulative
movement*, not slowness, and any plan cycle that gets meaningfully
closer to the goal resets the give-up counter — a crawling character
arrives late; only a truly blocked one fails. A
blocking panel pauses walking (up to 10 s) rather than fighting it —
in M3, a panel means a human or a death screen, and both outrank us.
Monsters en route are M5's behavior layer's business now; doors and
cross-area *walking* (area transitions on foot) remain deferred — the
navigator's world is still one area with static walls, and M6's
Countess route (Black Marsh → Forgotten Tower → five cellar levels)
is where that changes.

## Where a travel click may land (`nav/navigate.py`, the nudge)

A click's only job is to make the character walk that way, so landing a
few subtiles off costs nothing — the loop re-plans freely, and arrival is
judged by position, against the point actually clicked. Landing ON
something interactive costs the whole walk: an NPC's dialog, a waypoint
menu or the stash blocks all further input until something closes it. The
trade is therefore always worth taking, and travel clicks are nudged off
anything clickable before being sent.

**Two shapes, because the game has two.** Floor things — ground items,
objects — are avoided by a world-space Chebyshev radius (`AVOID_RADIUS`,
4). Standing units are not: the client hit-tests a **sprite**, in screen
space, and a sprite is tall and narrow. T83 measured it (2026-08-08).
Three clicks, all already nudged, all at world distance 6 from an ally:
the two drawn 120 px to her side were harmless, and the one drawn **0 px
sideways and 120 px above her feet** opened her dialog. Same world
distance, opposite outcomes. The projection above is why — 20 px per
(dx − dy), 10 px per (dx + dy) — so a world delta of (−6, −6) is straight
up her body while (−6, +6), the identical Chebyshev distance, is 240 px
away across the floor.

So units carry a screen-space box (80 px half-width, 150 px above the
feet, 40 below — sized to the measurement, with margin only on the side
the evidence says is dangerous), checked **in addition to** the radius,
and only in town, where allies are NPCs whose dialogs block input. The
escape is chosen in screen space too, and never up-screen: up is behind
the unit, it is the far wall of the tallest side of the box, and it is
what the old world-space push produced — the nudge was not failing to
prevent that click, it was creating it. The clean axes fall out of the
projection: a world step of (k, −k) moves a click purely sideways on
screen, (k, k) purely toward the camera.

Being boxed in still produces a click (the roomiest candidate, sprites
weighed above floor clearance): one click that might interact is
recoverable, whereas refusing to click is a walk that cannot finish.

`drills/town_click_clearance.py` re-measures all of this in ~40 s and
reports every click in both spaces — the tool to re-run after any
resolution, window-size or renderer change, since the box is display
geometry like the constants under it. It also reports how many clicks
were actually nudged, because a route where nobody was standing in the
way passes without testing anything.

## Waypoint travel (`waypoint.py` + the `waypoint` run step, M5)

Travel between areas exists, by waypoint only. The step requires the
panel-closed → open *edge* attributable to its own click on the
waypoint object (the fail-safe against the stuck-slot observation in
uistate.py), clicks the destination row — a calibrated UIPoint, sent
through the town layer's shared `InteractionLayer` over `PanelInput`
(the panel-scoped guard; see behavior.md) — and then *verifies arrival
by area id* rather than trusting the click. The arrival position is
recorded on the run's blackboard, which is what `clear_radius` centers
on. Cross-area walking — leaving an area through its exit seam on foot
— is not built; the atlas records per-area grids and the patrol keeps a
seam inset (`_SEAM_INSET`, R189 c) precisely so a ring point on a
border cannot flip which area's grid plans the next walk (T55 run 2's
lesson).

All timing is injected, so the whole ladder is tested against a scripted
fake world in `tests/nav/test_navigate.py` — the game is only needed for the
acceptance walks (`python -m pd2bot.navigate --demo`).

## The route service: steps ask the map too (R181)

For most of M5 the atlas was fully used by the navigator and ignored by
the STEPS: patrol legs, survey legs, and combat approaches were
straight-line bearing hops, so a far-corner target had each hop plan
locally, clamp at a fence, and burn the target's no-progress budget
while the bot visibly shuffled at dead edges — and a bearing hop could
lead straight through a zone exit (T53 run 2 wandered into Stony Field
and back). The map could answer "is there a route, and which way?"; no
step asked.

`wiring.route_service(navigator)` closes that gap: `route_to(target)`
runs the same A* + `simplify` the navigator walks with, READ-ONLY (no
clicks, no walking), and returns the waypoint list — or **None when no
path exists**, which the steps treat as an instant write-off instead of
a budget burned at a fence. Legs then aim at the route's next waypoint,
still capped at `patrol_step`/`dash_step` so the reflex ladder gets its
look between hops; a route planned on the area's grid never leads
through an exit the target is not behind, so the zone-wander class dies
with the bearings. Plans are cached per (8-subtile origin bucket,
target) — re-planning every tick is waste, and the atlas only grows, so
a briefly stale route is at worst conservative. The combat module stays
grid-ignorant: the step hands `approach()` the route's next waypoint as
`via`, while the module's own gates stay keyed to the monster.

## Re-verification after a PD2 patch

Same drill as perception (see perception.md), plus: re-run the click
test, and delete `maps/` if the patch plausibly changed map content —
a season reset re-rolls characters (new seed) and invalidates the atlas
automatically, but a mid-season map change with the same seed would
not, so a fresh survey walk is the safe reset. The CollMap struct
itself has been stable across two decades of community headers.
