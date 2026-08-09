# Discovery notes — screen-space click clearance around town NPCs

Planning started 2026-08-08, immediately after the measurement that
settled the cause. Nothing here is a hypothesis: the numbers came from
two live drills run through the bridge the same night.

## What is already established (do not re-derive)

**Cause 1, fixed and proven live.** Town NPCs were being classified as
decorative scenery. Review 002 of `ca54a53` (commit `46c83a2`,
2026-08-06 02:36) hoisted `scan_units`' combat-rated test to the top of
the classification chain to get it above the CORPSE test, which also put
it above the ALLY test — and town NPCs carry no combat stats. Fixed by
requiring scenery to be non-combat-rated **and not friendly**. Proven by
T82: perception went from **1 ally to 11** in the Rogue Encampment.

**Cause 2, measured, and the subject of this plan.** With the NPCs back
in the hazard list the walk STILL failed, and T83
(`drills/town_click_clearance.py`) recorded exactly why. Three travel
clicks, all already nudged, all at world gap **6** from an ally — beyond
`AVOID_RADIUS` (4):

| click | ally | world gap | drawn relative to her feet | outcome |
|---|---|---|---|---|
| (5869, 5733) | merc (5863, 5733) | 6 | 120 px right / 60 px below | harmless |
| (5872, 5733) | Kashya (5878, 5733) | 6 | 120 px left / 60 px above | harmless |
| (5872, 5727) | Kashya (5878, 5733) | 6 | **0 px sideways / 120 px ABOVE** | **opened `npc_menu`** |

Same world distance, opposite outcomes, decided entirely by direction on
screen. The client hit-tests the SPRITE, in screen space, and a standing
NPC is tall and narrow. `screen.py`'s measured projection is why:

    screen_dx = (dx - dy) * 20      screen_dy = (dx + dy) * 10

so a world delta of (-6, -6) is 0 px sideways and 120 px straight up —
dead centre of her body — while (-6, +6) at the identical Chebyshev
distance is 240 px away across the floor. A world-space radius scores
those the same and the game does not.

**The nudge is causing the hit, not failing to prevent it.** All three
clicks above were nudge OUTPUT. `_nudged_click_point` pushes the click
`AVOID_RADIUS + AVOID_MARGIN` away from the offender in world space, and
one of the directions it is free to choose is straight up the sprite.

**Bounds obtained.** The sprite is >= 120 px tall above the feet (the
hit) and < 120 px in half-width (both misses were 120 px sideways).

## Why a bigger radius is the wrong fix

It buys the sideways case, which was never failing, and pays for it in
mobility everywhere. The failing direction is one narrow screen column;
widening a circle to cover it also blocks 240 px of open floor to either
side. The shape is wrong, not the size.

## Design decisions taken during discovery

**D1 — the guard is a screen-space box, checked in addition to the
existing world radius.** A sprite hazard is avoided when the click is
inside its box OR within `AVOID_RADIUS`. Keeping the radius costs
nothing and preserves every case the radius already handled.

**D2 — box dimensions: half-width 80 px, 150 px above the feet, 40 px
below.** Every measured point is classified correctly by these:

- the hit at (0, -120) is inside (|0| <= 80, -150 <= -120)
- the miss at (-120, -60) is outside (120 > 80)
- the miss at (+120, +60) is outside (120 > 80)

Chosen with the asymmetry the evidence shows and the cost asymmetry this
repo keeps restating: over-avoiding moves a click a few subtiles;
under-avoiding costs the walk. 150 rather than 120 leaves a margin above
the one measured hit; 80 rather than 120 stays inside both measured
misses rather than sitting on them.

**D3 — town allies only, for now.** Ground items lie flat and were tuned
against a measured click audit; objects (the waypoint, the stash) plainly
have the same tall-sprite problem — R111/T27's waypoint case is the same
shape — but nothing has MEASURED an object's sprite, and inventing a
second box would be the guess this plan exists to avoid. The mechanism is
built general (a hazard either has a sprite or does not), so extending it
to objects later is a provider change and a constant, not a redesign.

**D4 — the nudge escapes in screen space.** Candidate exits are left,
right, and down-screen (converting a target screen offset back to a world
delta with the inverse of the projection above). Up-screen is not offered
as an escape: it is the direction that goes BEHIND the NPC, it is the
furthest wall of the box, and it is how the current code produced the
hit. Among candidates that clear every hazard, the one closest to the
original waypoint wins, so the click deviates as little as the geometry
allows.

**D5 — `_blocked_by_avoidance` is left on the world radius.** It answers
"is a hazard beside the GOAL the reason we are stopping short", which was
measured for ground items and governs when a walk gives up rather than
where a click lands. Widening it would make town approaches stop short
far more often. The NPC approach path is unaffected either way:
`npc_standoff` is 10 subtiles, comfortably outside a 150 px box (which
reaches ~7.5 subtiles up-screen).

**D6 — additive wiring, so nothing existing breaks.** `avoid_provider`
keeps returning plain points and keeps including allies. A new optional
`sprite_provider` returns the subset that has a sprite (town allies,
empty outside town). Every existing test of the hazard set keeps passing
unchanged.

## Files expected to change

- `pd2bot/navigate.py` — the constants, the box test, the screen-space
  escape, the new provider, and its wiring in `live_navigator`.
- `tests/test_navigate.py` — the geometry, using the three measured
  clicks as the fixture.
- `docs/architecture/navigation.md` — the click rule is documented there
  and would otherwise go stale.
- `docs/project-state.md` — close the OPEN item on the result.

## Validation

- `~/.venvs/pd2bot/Scripts/python.exe -m pytest -q`
- `~/.venvs/pd2bot/Scripts/python.exe -m ruff check .`
- **The acceptance test is live and cheap**:
  `drills/town_click_clearance.py`, ~40 s through the bridge. A leg that
  reaches Akara instead of opening `npc_menu` is the proof. The drill
  already prints every click's clearance in both spaces, so a failure
  arrives with its own diagnosis.

## Out of scope

- Objects (waypoint, stash) — see D3. Wants its own measurement first.
- `AVOID_RADIUS` itself, and the ground-item goal exemption: both were
  measured against a click audit and nothing here disputes them.
- The town layer's `_walk_guarded` recovery ladder. It is the safety net,
  not the bug, and it should stay exactly as loud as it is.

## Future work

- Measure an object's sprite the same way and give objects a box. The
  drill generalises with a one-line change to what it reports.
- The `is_alive` -> `not is_corpse` reasoning in `clickable_hazards`
  applies to any consumer that filters units by liveness; worth a sweep
  if another one turns up.
