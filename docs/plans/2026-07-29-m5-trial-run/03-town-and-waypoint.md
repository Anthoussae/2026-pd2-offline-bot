# P3 — Town layer and waypoint travel

Part of [plan.md](plan.md) (M5). Size: `sm`. Dependencies: P1
(objects, NPC ids, carried items), P2 (`PanelInput`, verified
switching). Sequential per R50. **Review gate at the end of this
phase** — the user observes the town drills and one supervised
waypoint round trip before P4 begins.

## Scope

Everything the bot does in town, plus waypoint travel: the game-entry
preamble (heal → stash deposit → belt refill → conditional merc
resurrect) and taking the town waypoint to Cold Plains. All of it
verified by perception after every step — clicks are never trusted to
have worked.

Out of scope: vendor/shopping UI of any kind (R48 — belt refill is
from inventory only), combat, pickit, the behavior engine (P4 wires
the preamble into the run; this phase delivers callable,
individually-tested steps), cross-area walking (dropped from M5,
R46 Q1).

## Context you need

- `pd2bot/navigate.py` `walk_to`/`Navigator` for in-town movement
  (town is atlas-covered from M3/M4 work; grid provider precedent in
  `_live_navigator`). `NavigationError` propagates to the cycle —
  do not swallow it.
- `pd2bot/cycle.py` — the preamble will run inside `run_games`'
  callback (P4 wires it); here each step is a function with its own
  CLI/drill entry.
- R45/M4 `_DONE.md`: PD2 carries vitals between games; the heal
  preamble is the durable fix for the carried-vitals chicken loop.
  `max_consecutive_chickens` (default 2) stays as the backstop.
- User facts (R47): stash transfer = **shift+right-click on the
  stash screen** (both directions); belt: 4×4, col 1 heal, col 2
  rejuv, col 3 mana, col 4 heal; rejuvs unbuyable; merc resurrect
  condition: hireling dead AND gold > 49,999 (cost caps at 50k).
- Calibration precedent (M4): positions inside panels that have no
  memory-readable rect are hover-calibrated once and stored as
  **fractions of the client rect** (Save-and-Exit, cycle.py
  `save_exit_fraction`); re-calibrate after any window/resolution
  change. Menu-vs-world projection history is in
  `docs/architecture/game-cycle.md` — read it before deriving any
  panel geometry.

## Work items

1. **`pd2bot/town.py`** — the preamble as small, individually
   drillable steps, each returning a typed result and verifying via
   perception:
   - `heal_at_akara`: walk near Akara's scanned position (NPCs
     wander a few subtiles — re-read position before the click),
     gated click on her, wait for the NPC interaction to register
     (dialog/menu panel in the UI state, or vitals jump), ESC out,
     **verify hp == max_hp** (and mana refilled). Bounded retries on
     a missed click (moving target), then a typed error.
   - `deposit_to_stash`: walk to the stash object (P1 position),
     click it, wait for the stash panel; for each inventory item the
     run marked as loot (P5 will tag them; for the drill, any
     non-potion item the user plants), shift+right-click its grid
     slot via `PanelInput`; **verify the inventory list shrank after
     each transfer**. Full-stash guardrail (R46 Q4): if an item is
     still in the inventory after N (2) attempts, stop clicking and
     halt loudly (chat + console + the M4 alert pattern) — a human
     must make stash space; never loop on a full stash. ESC closes.
   - `refill_belt`: shift+left-click potions from inventory into the
     belt (verify belt counts move; the game routes potions to their
     matching column — verify, don't assume, in the drill). Then
     check `belt_minimums` (config; propose heal ≥ 4 of 8 slots,
     rejuv ≥ 0 — unbuyable, any is a bonus, mana ≥ 2). Below minimum
     → **loud halt for manual restock** (R48 b), same alert pattern.
   - `resurrect_merc_if_dead`: only when P1 reports no live merc AND
     `player.gold > 49_999` (raw gold on person; do not count
     stash). Walk to Kashya, click, wait for the NPC menu, click the
     resurrect row. **The menu is state-dependent (R56, user-supplied):
     the "Resurrect MERCNAME: $GOLDPRICE" row exists ONLY while the
     hireling is dead, and its presence shifts the other rows — so
     row positions are per-menu-state, and the resurrect row cannot
     be calibrated while the merc lives.** Consequences: (a) the
     calibration happens at the first real dead-merc occurrence, not
     in this phase's drills (unless the merc happens to be dead);
     (b) the flow must confirm the merc is dead via perception
     *before* trusting the dead-state calibration, and never click
     the calibrated position in the alive state; (c) verify success
     by merc-present-and-alive AND carried gold decreased; on
     verification failure, halt loudly — no blind re-clicks into a
     menu whose layout may not match the calibration.
   - `run_preamble`: the sequence with per-step logging; order:
     heal → stash → refill → merc.
2. **`pd2bot/waypoint.py`** — `take_waypoint(dest_area)`:
   walk to the town waypoint object (P1), gated click, wait for the
   waypoint panel (`UI_WPMENU` in the UI state), click the
   destination row via `PanelInput` (Act 1 tab is default for Act 1
   destinations; Cold Plains row position hover-calibrated once,
   stored as client-rect fractions in config with the calibration
   date, M4 convention), then poll until `Area.level_no ==
   dest_area` and the player is readable. Timeout → typed error
   naming the step. Constant: `AREA_COLD_PLAINS = 3` (cite a
   community area-id table; verify live on arrival — the area read
   itself is M2-proven).
3. **Calibration drill** (bridge + user): hover-calibrate the Cold
   Plains row and the NPC-menu rows, M4 style (user rests cursor,
   bot compares prediction to `GetCursorPos`, ±2 px gate before any
   click is allowed on them).
4. **Drills, in risk order** (all via bridge, user present, chat
   narrating): heal (user enters town slightly hurt or spends mana);
   stash deposit (user plants junk items in inventory); belt refill
   (user moves potions to inventory first); then the **supervised
   waypoint round trip**: town → Cold Plains → immediately click the
   Cold Plains waypoint (it is at the arrival point) → back to town.
   The user hovers over the game the whole time; hostiles can be
   near the Cold Plains waypoint — agree abort criteria with the
   user beforehand (they take the mouse; the bot's focus guard
   already yields on focus loss).

## Review gate (end of phase)

Present to the user: drill outcomes (heal verify numbers, stash
transfer log incl. the guardrail behavior, belt counts, WP round-trip
timing), calibration values, and any deviation. Ask explicitly:
**approve P3 and proceed to P4?** Log as a 🔶 decision request.

## Conventions and reminders

- Every step verifies its effect via perception; no fire-and-forget
  clicks. Bounded retries, typed errors naming where it stopped
  (cycle.py error-taxonomy house style).
- All calibrated fractions live in config with a comment naming the
  calibration date and window size (M4 precedent).
- Tests with fakes: step state machines (retry/timeout/verify
  ladders), guardrail triggers (full stash, below-minimum belt),
  merc-resurrect condition logic, waypoint polling. No live calls in
  tests.
- Do not commit unless asked. Do not expand scope (no vendor UI, no
  combat). The death latch and existing guards are untouchable.
  Stop and report on any ambiguity — especially if a panel's
  geometry model doesn't match the M4 pillarbox/fraction patterns.
- Report what changed, drill results, calibrations, deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

Plus the drills above; outcomes in the instruction log.

## Definition of done

All preamble steps individually drilled live and verified by
perception; guardrails demonstrated (full-stash halt may be
fake-driven if no full stash is available — say so in the report);
waypoint round trip supervised and clean; calibrations stored;
tests/lint green; review gate answered. ADR expectation: none.
