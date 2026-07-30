# P2 — Input extensions (PanelInput, verified skill switch, belt keys)

Part of [plan.md](plan.md) (M5). Size: `sm`. Dependencies: P1 (skill
reads, belt reads — used for verification). Sequential per R50.

## Scope

The input capabilities M5's behavior needs, each behind the proper
guard: a third narrow input path for in-game panels, shift-hold
stand-still clicks, hotkey skill switching verified by memory
read-back, and belt drink keys. Ends with zero-risk town drills.

Out of scope: any town/waypoint *logic* (P3 owns walking to NPCs,
panel geometry calibration for specific panels), combat, behavior.

## Context you need

- Read `pd2bot/input.py` (whole file — the M1 incident docstring is
  the design rationale), `pd2bot/menuinput.py`, `pd2bot/chat.py`,
  and `docs/architecture/game-cycle.md` ("The second gate").
- The guard landscape: `GatedInput` sends only in-game with **no
  blocking panel**; `MenuInput` only not-in-game or ESC-menu-open;
  `Chat` only with the chat console verified open. In-game panels
  (waypoint list, NPC dialog, stash/inventory) are reachable by
  **none of them** — that gap is this phase's main deliverable.
- Construction rules (M1/M4 precedent, non-negotiable): no bypass
  flag, no unguarded variant, guard re-checked at the moment of
  sending, refusals raise `InputRefused` naming the failed condition.
- `uistate.read_ui_state` reads the in-game panel array;
  `pd2bot/screen.py` has `clickable` and projection helpers.
- Live checks via the elevated bridge; game-side asks via 🔶
  R-numbered requests (continue from the log's highest id).

## Work items

1. **`PanelInput`** (new `pd2bot/panelinput.py`): constructor takes
   session/window like `GatedInput`. Send method:
   `click(expected_panel: int, sx: int, sy: int, *, button="left",
   shift=False)`. Guard, re-run at send time: in a game AND
   `expected_panel` present in the freshly-read UI state AND window
   foreground. The *caller names the panel it believes is open*; the
   guard verifies that belief — Chat's pattern generalized. Shift
   support: VK_SHIFT down → click → VK_SHIFT up (needed for
   shift+right-click stash transfers, P3). Module docstring explains
   why this path exists and why it is not a weakening of the other
   two (cite the guard-complement table in game-cycle.md).
2. **Shift-hold stand-still click** in `GatedInput`: a
   `click_world(..., stand_still=True)` variant that holds VK_SHIFT
   across the click (attack without moving). Implemented inside the
   existing gate — **the guard itself does not change**. Key-up must
   be guaranteed (try/finally) so a refused or failed click never
   leaves shift stuck down.
3. **Verified skill switch** (new `pd2bot/skills.py`):
   `ensure_right_skill(session, gated, skill_id)` — if the right
   skill already reads `skill_id`, done; else press the configured
   hotkey (`press_key`), then poll `read_active_skills` (P1) until it
   reads back or a short timeout; bounded retries, then raise
   `SkillSwitchFailed`. **No cast click is ever sent on an unverified
   skill** — the difficulty-guard pattern applied to skills. Hotkey
   map comes in as data (dict skill_id → VK), sourced from the necro
   config file once P4 defines it; a module-level default table
   (F1–F6 per R47) is fine for now.
4. **Belt drink**: `drink(gated, column: int)` pressing VK '1'–'4'
   through the existing gated `press_key`. Cooldown bookkeeping
   belongs to the reflex ladder (P4), not here — this is the dumb
   primitive.
5. **Town drills** (live, zero risk, via bridge; user in town and
   foregrounding the game): (a) skill cycle F1→F5→F1 with read-back
   verification at each step; (b) cast Bone Armor via verified
   switch + gated right-click on open ground — confirms absorb stat
   moves (P1's read); (c) drink one potion via belt key, watch belt
   count drop (P1's read); (d) `PanelInput` refusal drill — attempt a
   panel click with no panel open (must refuse) and with the
   inventory open (must send; harmless coordinates, e.g. an empty
   inventory cell). Chat can narrate instructions as in M4.

## Conventions and reminders

- House rules for input code: guards documented in the module
  docstring with the incident history; every refusal message says
  *which* condition failed and what that means.
- Tests with fakes: guard truth-tables for `PanelInput` (all
  combinations of in-game/panel/foreground), shift-stuck-key safety
  (exception mid-click still releases), skill-switch retry/timeout
  ladder, verified-switch no-cast-on-fail. Injected timing; no test
  touches the game or sleeps for real.
- Do not commit unless asked. Do not expand scope (no panel geometry
  yet). Do not weaken any existing guard — if a drill fails because a
  guard refused, the guard is right until proven otherwise; stop and
  report. Report changes, drill outcomes, deviations at the end.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus the four town drills, outcomes logged in the instruction log.

## Definition of done

`PanelInput` exists with the verified-panel guard and shift support;
stand-still click works with guaranteed key release; skill switches
are memory-verified with a hard no-cast-on-unverified rule; belt keys
send; all four town drills passed live; tests and lint green. Review
gate: none. ADR expectation: none (the narrow-path pattern is
established; the behavior ADR is P4/P6).

## Implementation Result

Status: done
Completed: 2026-07-30
Commit: pending

- Changed: new `panelinput.py` (third gate: caller names the panel,
  guard verifies at send, shift wrapped in try/finally), `input.py`
  (VK constants; `stand_still` shift-hold on `click_screen`/
  `click_world`), new `skills.py` (`ensure_right_skill` verified
  switch, `belt_drink`), `uistate.py` (`read_ui_raw` calibration
  instrument; 0x14 restored as a real panel; **UI_STASH and UI_WPMENU
  added to the blocking set** — the live drill showed the stash raises
  only its own slot, so `can_act()` had been saying YES with the stash
  open), `offsets.py` (UI_STASH verified live), tests (+23, now 234).
- Validated: `pytest -q` 234 passed; `ruff check .` clean; live drill
  bridge 044 all four phases PASS (R55): panel slots calibrated
  (0x14/0x19/0x08), desecrate→bone-armor switches verified by
  read-back, bone armor cast (mana 378→343), mana potion drunk (belt
  col 0 1→0, mana refilled), both PanelInput refusals correct.
- Deviations: the planned "positive click at an empty inventory cell"
  was replaced by refusal-only demonstrations plus the panel-slot
  calibration — a blind click into an uncalibrated panel violates the
  never-click-unnamed policy; the first positive `PanelInput` click
  lands in P3 immediately after hover calibration. The 0x14
  always-on-vs-toggling conflict is resolved fail-safe (blocking set +
  P3 must verify the 0→1 edge after clicking the waypoint object).
  Note for P3/P6: belt column 0 (mana) is now empty on the live
  character.
