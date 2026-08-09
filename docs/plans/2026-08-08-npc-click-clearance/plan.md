---
kind: plan
size: sm
depth: small
status: done
repo: 2026-pd2-offline-bot
created: 2026-08-08
completed: 2026-08-08
adr: none
---

# Screen-space click clearance around town NPCs

## Size, and why

`sm`. One mechanism in one module, with its geometry already measured and
its acceptance test already written and running. There is no sequencing
problem to phase and no decision left that needs a human before the code
is written — the numbers decided them (see `notes.md`).

## Goal

A travel click aimed past a town NPC must not land on her sprite.

## Acceptance criteria

1. The three clicks T83 recorded are classified correctly by the new
   rule: the one drawn 0 px sideways / 120 px above her feet is avoided;
   the two drawn 120 px to the side are not.
2. A nudge never resolves a sprite conflict by moving the click
   up-screen.
3. `drills/town_click_clearance.py` walks the spawn -> Akara leg without
   opening `npc_menu`. **This is the acceptance test**, ~40 s live.
4. Existing hazard behaviour is unchanged: ground items, objects, and
   the goal exemption all keep their current rules and tests.
5. Full suite green, ruff clean.

## Scope

In:

- A screen-space sprite box, checked alongside the existing world-space
  `AVOID_RADIUS`, for hazards that have a sprite.
- A screen-space escape for the nudge when a sprite is the offender.
- Town allies as the sprite-hazard set.
- Tests built from the measured clicks; docs updated.

Out:

- Objects (waypoint, stash). Same shape of problem, no measurement yet —
  `notes.md` D3.
- `AVOID_RADIUS`, `GOAL_EXEMPT_RADIUS`, `_blocked_by_avoidance`, and the
  town layer's `_walk_guarded` recovery. All measured or deliberate.

## Discovery summary

Full evidence in [notes.md](notes.md). The short version: perception
classification was cause 1 (fixed, proven live, allies 1 -> 11), and the
world-space avoid radius is cause 2. T83 measured three nudged clicks at
identical world distance 6 from an ally, of which only the one drawn
straight up her sprite opened a dialog. `screen.py`'s measured projection
(20 px per `dx - dy`, 10 px per `dx + dy`) explains it exactly, and the
current nudge pushes away in world space — which is how it produced that
click in the first place.

## Files expected to change

| File | Change |
|---|---|
| `pd2bot/navigate.py` | sprite constants, box test, screen-space escape, `sprite_provider` + wiring |
| `tests/test_navigate.py` | geometry tests from the measured clicks |
| `docs/architecture/navigation.md` | the click rule is documented there |
| `docs/project-state.md` | close the OPEN item |

## Decisions

Recorded in `notes.md` as D1-D6. Summarised:

- The box is checked **in addition to** the world radius, never instead.
- Dimensions: **half-width 80 px, 150 px above the feet, 40 px below** —
  every measured point classifies correctly, with margin on the side the
  evidence says is dangerous and none invented on the side it says is
  safe.
- Sprite hazards are **town allies only** for now.
- The nudge escapes **left, right, or down-screen — never up**, and
  picks the surviving candidate closest to the original waypoint.
- Wiring is **additive** (`sprite_provider` is optional and defaults to
  None), so every existing test and caller is untouched.

## ADR expectation

`none`. This corrects an existing rule to match a measurement; it does
not choose between plausible architectures. The measurement and the
reasoning belong in the code and in `navigation.md`, which is where the
projection constants already live.

## Validation

```
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Then, live, through the bridge:

```
& "$HOME/.venvs/pd2bot/Scripts/python.exe" -m drills.town_click_clearance
```

## Implementation instructions (one shot)

1. **Constants** in `navigate.py`, each carrying the measurement that set
   it — the repo's standing rule for a tuned number.
2. **`_sprite_offset(hazard, point)`** — the projection from `screen.py`,
   applied to a world delta. Import `PX_PER_SUBTILE_X/Y` rather than
   re-typing 20 and 10; they are display-geometry constants that a
   resolution change invalidates, and two copies would drift.
3. **`_inside_sprite(hazard, point)`** — `|sx| <= half-width` and
   `-above <= sy <= below`.
4. **`_nudged_click_point`** — an offender is now a world-radius
   violation OR a sprite-box violation. A sprite offender is escaped in
   screen space (left / right / down, converted back to world with the
   inverse projection); everything else keeps the existing world push.
   The `MAX_NUDGES` bound and the roomiest-candidate fallback stay: being
   boxed in must still produce a click.
5. **`sprite_provider`** — optional `Navigator` argument, defaulting to
   None so every existing caller and test is unaffected.
   `live_navigator` passes town allies (empty outside town), read from
   the same snapshot as the other hazards.
6. **Tests** — the three measured clicks as the fixture, plus: no escape
   ever goes up-screen; a sprite hazard outside town is not a sprite
   hazard; boxed-in still clicks.
7. **Docs** — `navigation.md` gains the rule and the reason; the
   `project-state.md` OPEN item is closed with the result.

## Definition of done

Suite green, ruff clean, the live drill reaching Akara, docs updated, and
`_DONE.md` written by `yona-implement` with the drill output in it.

Agent reminders: do not commit unless asked; do not widen scope to
objects; do not suppress warnings or disable tests; stop and report if
the live drill contradicts the geometry rather than tuning constants
until it passes.
