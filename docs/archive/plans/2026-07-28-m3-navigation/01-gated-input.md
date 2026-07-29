# P1 — Gated input layer

Size: `sm`. Dependencies: none (parallel with P2). Part of the M3 plan
([plan.md](plan.md)); repo conventions in `CLAUDE.md`.

## Why this phase is shaped the way it is

This is the first code in the project that *sends* input. During M1 a
test click was delivered while the in-game ESC menu happened to be
open and it activated **"Save and Exit Game"** (full account:
`docs/plans/2026-07-28-bot-from-scratch/spike-log.md`). The codified
lesson: a screen coordinate means whatever the currently-open panel
says it means, so **no input may be sent unless
`pd2bot.uistate.can_act()` is true AND the game window is foreground**
— both, in the same guard, at the moment of sending. M2 built the
`can_act()` half and its docstring explicitly assigns the foreground
half to this phase.

Design consequence (user-approved intent): the gate lives **inside**
the send path. There is exactly one function that calls `SendInput`,
it performs the checks itself, and refuses (raising a typed exception)
when they fail. Callers cannot forget the check because there is
nothing unguarded to call. Do not add a bypass flag "for testing" —
tests use fakes.

## Scope

- `pd2bot/window.py`: find the game window from the `GameSession`'s
  PID (EnumWindows recipe proven in `spike/probe_foreground.py`),
  expose client-rect origin/size in screen coords, `is_foreground()`,
  and `bring_to_foreground()` (SW_RESTORE + SetForegroundWindow +
  verify via GetForegroundWindow — again per the spike). Re-query the
  rect per use; never cache the window position (user may move it).
- `pd2bot/screen.py`: world→screen projection. D2's isometric camera
  centers on the player: for subtile deltas (dx, dy) from the player,
  screen offset ≈ `((dx - dy) * 16, (dx + dy) * 8)` from client-area
  center. **This formula is a hypothesis** — verify it live (below)
  before P4 builds on it. Also provide the inverse and an
  `is_on_screen(world_pt, margin)` helper (clicks must land inside the
  client rect, with margin to avoid edge-of-screen scroll/UI strips —
  keep clicks out of the bottom ~120px HUD band).
- `pd2bot/input.py`: a `GatedInput` class holding the session, window
  and cached UI-array address; methods `click_world(x, y)` (project,
  gate, SetCursorPos, SendInput down/up — timing per
  `spike/probe_click.py`), `click_screen(x, y)` (still gated), and
  `press_key(vk)` (gated; needed later for run-toggle/potions — keep
  minimal now). The gate: raise `InputRefused(reason)` when
  `not can_act(session)` or `not window.is_foreground()`; message
  says which check failed. `can_act` accepts the cached `ui_array`.
- Tests (`tests/test_screen.py`, `tests/test_input.py`): projection
  math both directions; gate refusal logic with a fake session/window
  (in-game+foreground → sends; ESC-menu open → `InputRefused`;
  background window → `InputRefused`). Follow the existing fake
  patterns in `tests/test_uistate.py`.
- A tiny live probe CLI (`python -m pd2bot.navdemo click-test` or a
  `spike/`-style script — prefer the module CLI, precedent
  `pd2bot/dump.py`): foregrounds the window, prints the gate verdict,
  and on explicit `--send` clicks a *predicted* world offset and
  reports where the player actually ended up vs prediction.

## Out of scope

Path following (P4), any out-of-game/menu clicking (M4 — the gate
refusing in menus is *correct* for M3), background/PostMessage input,
drag, right-click skills (M5).

## Live verification (user at the machine)

1. Gate demo: with ESC menu open → refused; window backgrounded →
   refused; normal play → allowed. (This is the incident's regression
   test against reality.)
2. Projection: from a known player position, `click_world` a target
   ~20 subtiles away; player's post-walk position (via `Perception`)
   must land within a few subtiles of the target. Repeat in two
   directions. If the 16/8 constants are wrong, calibrate from two
   measured clicks and document the derivation in `screen.py`.

## Conventions

- Only `memory.py` may import pymem; only `window.py`/`input.py` may
  touch user32 (extend the "only this module knows Windows" pattern).
- No magic numbers outside `offsets.py`/module constants with a
  comment stating provenance.
- Comment style: explain *why* (see existing modules' docstrings).

## ADR

`possible` — draft a short gated-input ADR only if you find yourself
arguing against a real alternative (e.g. caller-side checks); if the
design feels forced by the incident, a `navigation.md` section (P5)
suffices.

## Agent reminders

Do not commit unless the user asked. Do not expand scope. Do not
suppress warnings or disable tests. **Never send input outside the
gated path, including in probes.** Stop and report if the projection
formula does not calibrate cleanly. Report what changed, what was
validated live, and any deviations.

## Validation commands

```bash
python -m pytest -q
```

plus the live checks above.

## Definition of done

Gate refusals demonstrated live in all three states; projection
verified/calibrated live; tests green; no unguarded send path exists.

## Implementation Result

Status: **done** (live verification passed later the same day: gate
refusals 3/3 in the real client — R3 in the instruction log — and the
projection was *calibrated*, not just verified: measured 20/10 px per
subtile, plus the ~320 px reliable-click-radius discovery; see
live-checks.md steps 1–2)
Completed: 2026-07-28
Commit: pending

- Changed: `pd2bot/window.py` (window by pid, client rect re-queried per
  use, foreground check + verified focus request), `pd2bot/screen.py`
  (isometric projection both ways, `clickable()` excluding HUD/edges),
  `pd2bot/input.py` (`GatedInput`: the single send path, checks
  `can_act()` + foreground, re-checks immediately before the button
  event, raises `InputRefused` naming the failed condition; no bypass
  exists), `pd2bot/navdemo.py` (gate/click-test CLIs),
  `tests/test_screen.py`, `tests/test_input.py`.
- Validated: `pytest` 101 passed (16 of them this phase's, including the
  ESC-menu, background-window, not-in-game, and HUD refusals);
  `ruff check` clean.
- **Not validated**: everything live. All three gate states and the
  projection calibration need an *elevated* terminal (memory reads need
  Administrator) with the user present. Steps 1-2 of
  [live-checks.md](live-checks.md).
- Deviations: no ADR written — the design turned out to be forced by the
  incident rather than a choice among alternatives (per this file's
  "draft only if arguing against a real alternative"). It is documented
  in `docs/architecture/navigation.md` instead.
- Note for the live run: `PLAYER_ANCHOR_LIFT_PX` in `screen.py` is the
  calibration knob if the click test shows systematic error.
