# Notes — M4 game cycle

## Initial understanding and goals

Roadmap M4 (see `../2026-07-28-bot-from-scratch/plan.md`): the bot
learns to **cycle games unattended** — create a single-player game from
the menus, detect and recover from death, chicken out when health drops,
leave the game, and repeat. This is the layer that turns "the bot can
walk" (M3) into "the bot can be left alone", and it is the prerequisite
for M5's actual runs.

Character/context: `MaqiuDoubing`, Hell difficulty, offline SP client
attached via pymem (we never launch Game.exe ourselves).

## Current state (what M4 builds on)

- **Perception (M2, hardened in M3 closeout)**: `GameSnapshot` per tick;
  player HP/position; monsters/allies split; ground items by unit mode;
  `uistate.read_ui_state` (in-game panel array, discovered at runtime
  from `GetUiVar_I`'s code); `uistate.is_in_game` (player unit ptr null
  ⇔ at menus).
- **Navigation (M3)**: `GatedInput` — the *only* send path, guard =
  `can_act()` (in a game, no blocking panel) AND foreground. **No
  bypass.** CLAUDE.md and navigation.md are explicit: M4's menu clicking
  must be a *separate, separately-guarded* method, not a weakening of
  this gate. `navigate.walk_to` raises `NavigationError` after the
  re-click → re-plan → give-up ladder; M4 is its intended consumer.
- **Atlas (M3)**: keyed by (seed, difficulty, area); difficulty is
  currently *stated by the caller* — M3's _DONE explicitly hands M4
  "difficulty read from memory".
- `GameWindow.bring_to_foreground()` exists and verifies the focus
  actually took (Windows may refuse).

### M3 → M4 handoff list (from M3 `_DONE.md`)

1. Difficulty read from memory (atlas key).
2. Menu-scoped input method with its own guard.
3. Door handling (see Q5 — propose deferring).
4. Consuming `NavigationError` in the game cycle.

## Discovery log (2026-07-28)

### Out-of-game perception: the D2Win control list

Problem: when not in a game, the player unit is null and the in-game UI
array is meaningless — we currently know *that* we are at the menus but
not *which screen*. Pixel-scraping is out of scope; we need a memory
answer.

Kolbot's answer (mined from `kolbot/d2bs/kolbot/libs/OOG.js`): D2BS
exposes `getLocation()` (a screen id: MainMenu, CharSelect, Difficulty,
OkCenteredErrorPopUp, …) plus `Controls.X.click()` — D2's menus are
built from a **control list** (buttons/textboxes with type, position,
size, and text) that lives in D2Win.dll and is walkable as a linked
list. Kolbot's whole OOG layer (login → char select → difficulty →
in-game, incl. error popups) is a state machine over
(location, controls) with timeouts — `Starter.locationTimeout(ms, loc)`
polls for a screen change and re-clicks on failure.

For us out-of-process this translates to: read the D2Win first-control
pointer, walk the list, classify the current screen by the controls
present, and click a button by projecting its rect center into our
window's client area. Offsets for 1.13c exist in the same lineages we
already cite for CollMap (D2BS engine source, community address
tables); BH itself is in-game-only so it likely won't carry them —
derivation with dual-lineage citation is the established M3 pattern.

Risks: PD2 modifies the client (SGD2FreeRes renderer) — control-list
layout is *probably* untouched (menus behave stock) but must be
verified live before anything is built on it. Fallback strategy if the
control list is unreadable: a **blind deterministic flow** — fixed
click coordinates at the agreed fixed resolution + `is_in_game` /
timeout polling. The SP flow is short enough for this to be plausible:
save-and-exit always lands on char select with the character
pre-selected; from there it's OK → difficulty button → loading →
in-game. Plan should put screen identification behind a small interface
so the fallback swaps in without touching the cycle FSM.

### The SP menu flow (what the cycle must drive)

- **Leave**: in game → ESC (opens ESC menu) → click "Save and Exit
  Game" → char select screen. (The M1 incident click, now on purpose.)
- **Create**: char select (char pre-selected) → OK → difficulty popup
  (char has Hell unlocked ⇒ popup offers Normal/Nightmare/Hell) → click
  Hell → loading → `is_in_game` true, player in Rogue Encampment.
- Map seed is per character in SP — M3's R14 proved the atlas key
  survives a full save-exit-recreate cycle. New games keep the maps.

### Chicken (mined from kolbot `threads/ToolsThread.js`)

Config thresholds checked every tick, all expressed as percentages:
`LifeChicken` (hpPercent ≤ x and not in town → quit), `ManaChicken`,
`MercChicken`, `IronGolemChicken`. Potion drinking (`UseHP`/`UseRejuv…`)
is a *separate concern* handled before chicken in the same loop — for
us that's M5 combat territory (proposal: chicken-only in M4, Q3).
Kolbot quits via an API call (instant); our exit path is ESC + click
"Save and Exit", inherently slower — chicken latency should be measured
live and the default threshold set conservatively.

### Death (kolbot sdk + SP behavior)

Player unit mode 0 = Death (dying animation), 17 = Dead
(`kolbot/d2bs/kolbot/sdk/types/sdk.d.ts:1550`). In SP death there is no
in-game resurrection: the death screen expects ESC, which exits toward
the menus; the next game spawns the corpse in town near the spawn
point. Death handling therefore composes out of pieces the cycle
already has (detect mode/HP → ESC out → recreate game) plus **corpse
retrieval**: find the corpse unit (player-type, our name, mode Dead) in
town and click it (`click_world` on its position). Hell death costs
gold + experience — live-testing this deliberately is a real user
decision (discussion Q, R28).

### Difficulty from memory

Needed for the atlas key (replace caller assertion) and to verify the
right difficulty was entered after game creation. 1.13c has a known
D2Client difficulty byte; BH exposes a `GetDifficulty` helper. Derive
with citation during implementation; verify live (Hell ⇒ 2).

### Error taxonomy for the run loop

- `InputRefused` (focus lost / panel appeared): pause, try
  `bring_to_foreground` once, else wait for human (policy Q8).
- `NavigationError`: in M4's skeleton → leave game, new cycle (a fresh
  game resets position to town); log it.
- Client process gone / reads failing: we attach, never launch — stop
  and request the human (relaunch is out of scope).
- Menu state timeout (screen never changed after a click): bounded
  retries kolbot-style, then stop with a description of the screen.

## Documentation surfaces likely to change

- `docs/architecture/` — new `game-cycle.md`; small updates to
  `navigation.md` (door note stays true) and `perception.md` (OOG
  section pointer).
- `README.md` — new CLI tools (oog dump, cycle demo).
- `CLAUDE.md` — M4 status line; the "menu clicking must add its own
  guarded method" sentence gets fulfilled, keep it as history.
- Roadmap `plan.md` M4 row on completion.
- `docs/learning/` — teach step (glossary candidates: control list,
  chicken, game cycle, FSM).

## Questions

Asked 2026-07-28 as R27 (confirmation batch Q1–Q8) and R28 (discussion:
death-test strategy). See instruction log.

## User answers / scope changes

### 2026-07-28 — R27/R28 resolved

- **Q1–Q5: yes** (control-list OOG perception with blind fallback;
  separate MenuInput guard; chicken-only in M4; merc/golem chicken
  deferred; doors deferred).
- **Q6: no — scope change.** No corpse retrieval, and death handling is
  redefined: **on death the bot stops completely** — no input, no
  recovery attempts — and awaits human intervention (loud alert).
  Corpse retrieval + automated death recovery deferred to a later
  stage, explicitly low priority. Consequence: R28 (death live-test
  strategy) is **withdrawn** — death→stop is simulation-testable since
  the action on detection is "send nothing and alert"; no deliberate
  death needed.
- **User priority statement:** dying during testing is the risk to
  design against — run/combat/chicken logic must be made as robust as
  possible *before* any real-run testing. This is a standing constraint
  on M5 planning (sim-first, staged acceptance in safe areas, defensive
  reflexes before offense).
- **Q7 (final, revised at R29): difficulty check kept as a guard.**
  First pass dropped it (Hell-only project); the map-poisoning argument
  — a misclicked difficulty popup silently recording Normal terrain
  into the Hell atlas — convinced the user the check is correct. Final
  shape: the atlas keeps a caller-stated "hell" constant (no re-keying
  feature), but **every game entry is verified by a one-byte difficulty
  read (must equal Hell) before the cycle proceeds** — an unconditional
  post-join sanity guard covering both the control-list path and any
  blind fallback. Offset derived with citation in P1, consumed in P3.
- **Q8: yes** (refocus once, then pause for human).

### The survival toolkit (user-supplied, 2026-07-28)

The character's defensive tools, to be designed as a **survival layer**
in the combat module. User asked where these belong; answer: **M5
planning discovery** (the next `yona-plan` run) — M4 contributes only
the escape-hatch primitive (emergency exit) that several of them
resolve to. The list, verbatim in spirit:

1. **Blood warp** — teleport skill, long cooldown; *not* for traversal,
   only for danger relocation (e.g. away from a surround).
2. **Healing/rejuvenation potions** — bot should ensure the belt always
   has them (belt management + drink thresholds).
3. **Bone shield** — ablative armor skill; keep above 75% at all times
   (upkeep reflex).
4. **Leave the game** — ESC pauses instantly (offline SP), so exiting
   at e.g. HP < 50% is a near-perfect escape (this is M4's chicken).
5. **Walk away** — disengage by moving; surprisingly effective.
6. **Revives as tanks** — desecrate (makes corpses) → revive; keep 3
   revived monsters at all times to draw aggro.
7. Open invitation to propose more at design time (M5 discovery).

Design shape to carry into M5: a priority-ordered reflex ladder
(upkeep: bone shield, revives, belt → disengage: walk away → escape:
blood warp → last resort: chicken), evaluated every tick above the
offensive logic.

## Future work ideas

- Elevated agent-driven terminal (from instruction-log observations) —
  would collapse most live-check requests.
- Potion/merc management in the safety monitor (M5).
- Auto-relaunch of the client via PD2Launcher (currently out of scope).
