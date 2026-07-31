# Notes — M5 trial run (Cold Plains clearance)

## Initial understanding and goals

Roadmap M5 (see `../2026-07-28-bot-from-scratch/plan.md`): the first
**end-to-end run**. The bot, unattended, cycles Hell games and in each
one: heals in town, walks Rogue Encampment → Cold Plains, clears
monsters around the waypoint with the poison dagger necromancer kit,
picks up items per pickit rules, stashes them, and leaves. This is
where the behavior architecture (FSM + data-driven runs + per-class
combat module — the third expected ADR) gets built.

Standing constraints inherited from M4 (see the archived M4 `notes.md`
and `_DONE.md` follow-ups):

- **Robustness before live runs** (user priority statement,
  2026-07-28): dying during testing is the risk to design against.
  Sim-first, staged acceptance in safe areas, defensive reflexes built
  and verified *before* offense.
- **The survival toolkit** (user-supplied, verbatim in M4 notes.md):
  blood warp (danger relocation only), belt potions (keep stocked +
  drink thresholds), bone shield ≥75% upkeep, leave-game (M4 chicken),
  walk away (disengage), 3 revives via desecrate→revive as aggro
  tanks. Design shape: a priority-ordered **reflex ladder** evaluated
  every tick above offensive logic.
- **Town-heal preamble is mandatory** (R45): PD2 carries vitals
  between games; healer NPC visit before leaving town, else the
  chicken backstop halts the loop.
- Death latch is inviolable: no input after death, no recovery
  behavior without explicit user decision.
- Deferred from M4 into M5-or-later: doors, merc/golem chicken,
  potions (now in scope via the toolkit), corpse retrieval (still
  deferred, low priority).

## Current state (what M5 builds on)

- **Perception (M2/M3/M4)**: `GameSnapshot` per tick (player,
  monsters, allies, ground items); UI panel state; OOG screen
  classification; difficulty read. To verify in discovery: what item
  detail exists (pickit needs quality/name/stats?), whether NPCs are
  distinguishable, whether belt/inventory/stash contents are readable.
- **Navigation (M3)**: atlas + A* + `walk_to` with the re-click →
  re-plan → give-up ladder; `NavigationError` consumed by the cycle.
- **Game cycle (M4)**: create/leave Hell-verified games; chicken +
  death latch (`safety.py`); chat channel; `max_consecutive_chickens`
  backstop.
- **Input**: `GatedInput` (world), `MenuInput` (menus), `Chat` — no
  bypass, guards untouched. To verify: keyboard/skill-cast primitives,
  right-click support.
- **Elevated bridge**: agent runs live checks itself; user needed only
  for game-side actions.

## Discovery log (2026-07-29)

### What exists and slots in directly

- `cycle.run_games(run_callback)` — the M4 skeleton was built to have
  M5's run plugged into exactly this hook. `ChickenExit` /
  `DeathHalt` / `NavigationError` handling already wired around it.
- `SafetyMonitor.tick()` raises; never sends. Chicken (floor trigger,
  town-suppressed) + death latch + `max_consecutive_chickens`
  backstop. The reflex ladder is a *separate combat-layer* concern
  layered above this — the monitor stays the last line.
- `GatedInput`: `click_world(wx, wy, button)` (left **and right**),
  `click_screen`, `press_key(vk)` — all gated, no bypass. Chat exists.
- `Navigator` + atlas + survey mode (`--survey`: records rooms while
  the *user* walks, sends no input) — ideal for zero-risk route
  seeding, matching robustness-first.
- `read_stats` works on **any unit** (full stat array by index) — so
  bone armor amount, item stats, monster alignment are all one stat-id
  constant away, no new machinery.

### Gaps M5 must fill

**Perception** (`units.py` / `player.py` / `offsets.py`):

- No skill reading: need current left/right skill ids (BH:
  `UnitAny.pInfo` → skill list) to *verify* a skill switch took before
  clicking — same trust-nothing pattern as the difficulty guard.
- `Monster` lacks `mode` — needed to tell corpses (revive/desecrate
  targets) from live hostiles (today only hp).
- No object units (`UNIT_TYPE_OBJECT`=2) are scanned: stash chest,
  waypoint, doors are invisible. Stash interaction needs at least the
  stash object's position.
- Ground items carry only `kind` + `quality` — enough for a trial
  pickit (quality tiers + hardcoded kind tables for gold/potions), not
  for stat-based rules (M6).
- No carried-item enumeration (belt/inventory): potion counts per belt
  column, inventory grid occupancy (for stash deposit + full-detect).
  The ItemData location byte lied once already (R17) — derivation from
  BH's ItemData needs the same live-verified care.
- Bone armor current/max stat ids: not in `offsets.py` yet.
- NPC identity: allies list has friendly units but no id table (Akara
  et al. are `kind` values to hardcode + verify live).

**Input** (`input.py`):

- `press_key` exists but there is no *hold* (shift+click stand-still
  attack) — small gated addition.
- Skill select = user-bound hotkeys (F-keys) + verify via skill read.
  Belt drink = keys 1–4. Both compose from `press_key`.

**Navigation**:

- The live grid provider overlays live collision on the **current
  area's** atlas only (`navigate.py:297-305`). Town → Blood Moor →
  Cold Plains is a cross-area route: needs a union grid over several
  `ExploredArea`s (coords are global subtiles, so union is coherent) —
  a contained extension, not a redesign.

**Behavior (all new — this is the ADR milestone)**:

- FSM engine (hierarchical, ticked), runs as declarative data,
  per-class combat module + config — the roadmap's decision 5
  (kolbot's three-layer pattern as design reference).
- Survival reflex ladder (priority-ordered, evaluated every tick above
  offense): upkeep (bone armor, revives, belt) → potions → disengage →
  blood warp → chicken.
- Necro combat rotation: needs user knowledge of the actual kit
  (skills, levels, curses, how they fight packs) — inform request.
- Pickit: small data-driven ruleset (quality/kind based); kolbot
  `.nip` is a design reference only, no parser in M5.
- Town preamble: heal (mandatory, R45), stash deposit, belt refill.

### PD2-specific facts to verify live (or via user)

- PD2 QoL: ctrl+click quick-move inventory↔stash (if real, stashing
  needs no cursor-drag); shift+right-click bulk-buy fills belt (if
  real, vendor refill is one click); gold auto-pickup setting.
- Whether talking to Akara (NPC menu opens) heals immediately, and
  whether ESC closes cleanly — kolbot lore says yes; verify in town at
  zero risk.
- Desecrate/revive mechanics (PD2 skill: corpse creation cooldown?),
  blood warp cooldown + life cost.
- Hell Blood Moor/Cold Plains actual danger level for this character
  (user judgment drives supervision level of staged acceptance).

## Questions

Asked 2026-07-29 as R46 (confirmation batch Q1–Q8), R47 (inform:
character kit questionnaire), R48 (discussion: belt refill strategy).
See the instruction log and the chat transcript for full text.

- Q1 on-foot route, no WP menu · Q2 clearance = radius around the WP ·
  Q3 trial pickit = quality/kind tiers only · Q4 stash via ctrl+click
  QoL (drag fallback) · Q5 town preamble order · Q6 hotkey casting
  with read-back verify · Q7 ladder above untouched SafetyMonitor ·
  Q8 staged acceptance ladder.
- R47: skills/levels, manual rotation, blood warp + desecrate/revive
  mechanics, bone armor recast rule, belt layout, hotkeys, PD2 QoL
  facts, danger assessment.
- R48: belt refill — vendor bulk-buy vs ground-refill+halt vs full
  shopping UI.

## User answers / scope changes

### 2026-07-29 — R46/R47/R48 resolved

**R46 (Q1 is a scope change, rest confirmed):**

- **Q1: no — waypoint usage is IN scope** ("key to virtually all run
  structures"). Consequence: M5's route is town → town WP → *teleport*
  to Cold Plains WP → clear. **Cross-area walking (union grid) drops
  out of M5 scope** — deferred to M6 (Countess needs multi-area travel
  anyway). New work instead: waypoint object detection, WP panel
  interaction (select Cold Plains).
- **Q2: yes, radius 150** subtiles around the Cold Plains waypoint.
- **Q3: yes** — simple pickit list now; **must be human-readable and
  easily updatable** (review + future customization is an explicit
  requirement of the format).
- **Q4: yes** — with **full-stash guardrails** (detect a deposit that
  didn't take; halt loudly rather than click in a loop).
- **Q5: yes** — plus conditional **merc resurrect**: if hireling dead
  and gold > 49,999, resurrect (Kashya) during the preamble.
- **Q6: yes** — combat layer must be architected class-agnostically
  (interface + per-class config); only the necro config is implemented.
- **Q7: yes** — exact chicken threshold to be discussed (→ R49).
- **Q8: yes** — staged acceptance ladder as proposed.

**R47 (the kit, verbatim in spirit):**

- **Left skill is always Poison Strike and never changes.** Offense =
  left-click the monster. No skill switching on the left at all.
- Right-skill hotkeys: **F1 bone armor**, **F2 blood warp**, **F3 TP
  tome** (unused in M5 — note for future, low prio), **F4 bone wall**
  (ditto), **F5 desecrate**, **F6 revive**.
- **Bone armor**: must always be active; recast when off cooldown and
  remaining absorb < 75%. Absorb is visible in the small square right
  of the HP orb (a stat, so memory-readable — derive the stat id by
  cast-and-diff). User-approved fallback if the read is hard: recast
  whenever the player is hit.
- **Blood warp**: escape only, never traversal. Click a spot. Costs 10
  mana + max(12% HP, 12 HP). Guardrail: never cast at ≤ 12 hp (chicken
  should preclude ever being there); needs mana ≥ 10.
- **Desecrate → revive**: neither castable in town. Rule: out of town,
  whenever revived monsters < 3 (i.e. followers < merc + 3), cast
  desecrate on nearby ground, then revive corpses until 3. Revives
  last ~300 s.
- **Skirmish pattern** (the rotation to encode): on contact, wait
  briefly for revives to engage → dash in → left-click the monster
  (poison dagger/strike) → run back out of danger → recast bone armor
  if low → repeat until the pack is dead.
- **Belt**: 4 columns × 4 rows = 16. Keys 1–4 = columns. Col 1
  healing, col 2 rejuvenation, col 3 mana, col 4 healing. Drink rules
  (out of town): hp < 100% → healing, 10 s cooldown; hp < 50% → rejuv,
  no cooldown; mana < 25% → mana potion. **Rejuvs cannot be bought** —
  pickit rule: always pick rejuvs while belt holds < 4.
- **Stash transfer**: shift + right-click on the stash screen moves an
  item to/from the stash (not ctrl+click as guessed).
- **Danger assessment: fairly dangerous.** Any enemy can kill an idle/
  AFK character; groups stun-lock. Robustness is the design driver;
  death not catastrophic but minimize the chances. → Plan adds a
  **never-idle-out-of-town invariant**: if the behavior loop cannot
  decide for T seconds outside town, leave the game.

**R48: (b) — ground refill + loud halt.** No vendor UI in M5 (user
preference). Belt refilled from picked-up potions; if below minimum in
town, halt loudly for a manual restock. Behind one `restock_belt()`
interface so run logic never knows the strategy.

### Design consequence discovered while processing answers

In-game panels (waypoint list, NPC dialog menu, stash/inventory grids)
are clickable by **neither** existing path: `GatedInput` refuses while
a blocking panel is open, `MenuInput` refuses in-game unless the ESC
menu is open. M5 needs a third narrow path in the Chat mold —
**panel-scoped input**: sends only while a *specific expected panel*
is verified open, re-checked per click. Same construction rules: no
bypass, guard re-run at send time, `InputRefused` with the reason.

### 2026-07-29 — R49/R50 resolved

- **R49: approved with one change** — mana potion cooldown 15 s (was
  proposed 5 s). Final ladder defaults: chicken 35% ·
  rejuv < 50% (no cd; empty column + ≥2 hostiles within 10 → escalate
  to warp) · blood warp on (≥4 hostiles within 8 AND hp < 60%) OR
  >25% hp lost in 2 s, guarded by mana ≥ 10 and hp > 2× warp cost ·
  heal potion < 100% (10 s cd, col 4 backup) · mana potion < 25%
  (**15 s cd**) · disengage when bone armor down+on-cd and hp < 70% ·
  upkeep: bone armor at absorb < 75%, revives to 3. All config.
- **R50: phase table approved (`lgtm`), sequential execution** — no
  P3/P4 overlap; six phases as tabled.

### 2026-07-29 — R53: belt layout changed (scope change)

The belt had been shuffled before drill C; the user declared the
drill-observed configuration **permanent**: **key 1 = mana, key 2 =
rejuv, key 3 = health, key 4 = health** — superseding R47.6's
heal/rejuv/mana/heal. Consequences: the reflex-ladder drink actions
(P4 config) use key 1 for mana, key 2 for rejuv, keys 3+4 for
healing; kind→type attribution flips (610/611 mana, 606 healing —
confirmed empirically, R54); tier differences within a type are
irrelevant for our purposes.

## P1 live-verification findings (2026-07-29, bridge 030–035)

Everything planned verified in one town session; no kill needed (the
encampment's ambient corpses read mode 12). Key captures and surprises:

- **Skill ids (drill A, observed canonical)**: left is permanently 73
  (Poison Strike, classic Poison Dagger's slot); F1→68 Bone Armor,
  F2→367 Blood Warp (PD2 id), F3→220 TP tome, F4→78 Bone Wall,
  F5→83 Desecrate (PD2 use of a classic slot), F6→95 Revive.
- **Bone armor stats (drill B)**: 132/133 present, equal at full, and
  **fixed-point** (raw 221696 = 866 << 8) — added to
  `FIXED_POINT_STATS`. The falls-when-hit half of the check needs a
  live hit; deferred to P6 stage B (ratio logic unaffected).
- **Carried items (drill C)**: mode/GameLocation/NodePage triples
  consistent at every hop of a potion moved inventory→belt→stash→
  back; belt column cascade confirmed slot%4; stash/inventory grid
  coords correct. **Surprise: a cursor-held item leaves the inventory
  chain entirely** — reachable only via `Inventory.pCursorItem`;
  items.py reads it separately now.
- **PD2 renumbered the potions.** Classic ids (587–596, 515/516) do
  not exist here. Observed from the belt: 610/611, 530/531, 606.
  The type attribution was **proven by effect** (R54): key 1 consumed
  kind 611 and the mana orb refilled 246→378 — so **610/611 = mana,
  606 = healing, 530/531 = rejuv**, matching the permanent belt
  layout declared at R53 (key 1 mana, 2 rejuv, 3+4 health). Gold 523
  remains unverified until a live drop (P5/P6).
- **NPCs (drill D)**: 147 Gheed, 148 Akara (appeared exactly when the
  user walked to her), 150 Kashya, 154 Charsi, 155 Warriv, 265 Cain.
  **Townsfolk without the alignment stat (kind-149 guards, 179) read
  as _monsters_ in town** — combat logic must never target in town
  (already the design; now with a concrete reason).
- **Objects**: waypoint 119 at (5884,5709), stash 267 at (5856,5734),
  named and positioned in the first dump.
- **Merc**: rogue (271) alive at 8% hp — also a live datum for P3's
  resurrect logic: the character carries 0 gold (732k stashed), so
  the gold>49,999 condition as stated would never fire on carried
  gold alone. Flagged for P3 (withdraw-from-stash is vendor-adjacent
  UI; more likely: condition should read carried gold and halt-or-
  skip with a note).

### 2026-07-30 — R56: Kashya's menu is state-dependent (user note)

A "Resurrect MERCNAME: $GOLDPRICE" row appears in Kashya's menu **only
while the hireling is dead**, shifting the other rows. So NPC-menu row
calibrations are per-menu-state; the resurrect row is calibratable
only in the dead-merc state and must never be clicked in the alive
state. P3's flow hardened accordingly (dead-confirmed before click,
merc-alive + gold-decreased after, halt on mismatch); calibration
deferred to the first real dead-merc occurrence.

### 2026-07-30 — live-test protocol formalized (user request)

Mid-P3 scope addition, user-directed: the ad-hoc `.tmp-*.py` drill era
ends. New harness `pd2bot/drill.py` — every live test gets an id
(T<n>), title, and kind; on the user's first window-in it chats the
test header, the instructions, an input warning (hands-off vs
you-drive), then `TEST LIVE`, and closes with `TEST CONCLUDED —
<status>`; every run appends a row to `docs/drill-log.md` (seeded with
a T1–T10 backfill of the pre-harness drills). The harness carries the
paid-for fixes as defaults: capture re-arm (T8/R57), repeated
announcements (R59), long foreground patience. Drill bodies live in
`drills/` as first-class linted code. Bridge side: `tools/
bridge-run.ps1` replaces the inlined submit-and-poll PowerShell (which
twice got backgrounded mid-poll by the tool's 120 s ceiling). 274
tests. Follow-up for P6 docs: README section on the harness + drill
log + bridge-run.

### Inventory-management loop (R75, user-designed)

Replaces the separate stash-deposit and belt-refill steps. The central
idea is the user's and it is the good part: **let the game do the
classification**. Attempting every item into the materials tab and
keeping whatever it accepts means the bot needs no item taxonomy — the
kind of knowledge that goes stale every patch. Potions are the single
category it must recognise, and it already does.

Order: potions to belt -> drink excess healing/mana -> deposit all into
MATERIALS -> switch tab -> deposit all into REGULAR -> halt if anything
remains.

Settled (R75):
- Rejuvs are **materials** (user), so they need no rule at all: not
  drunk, they simply fall through to the materials phase. Never stashed
  in the regular tab; no potion ever is.
- Drinking always works, even at full health — no fallback needed.
- "Didn't move" is the EXPECTED outcome in the materials phase and an
  error only in the final one, so the overflow halt must be phase-aware
  or the first non-material trips it.
- Fast-fail timing in the materials phase (one attempt, short verify):
  a successful transfer is instant, and ~10 expected failures at the
  normal 2-attempts/3-second settings would cost a minute per run.
- The Horadric Cube is exempt from the overflow halt via
  `UNMOVABLE_KINDS` (R67), so it cannot trigger the pause.

Open, being probed:
- **Which tab is showing** (user: must be reliable, not heuristic). T15
  ruled out the UI array — it did not move across four toggles. T22
  probes the inventory STORE ARRAY (`Inventory.pStores`: per-grid width,
  height, item chain), where a differently-shaped tab should show up,
  plus item location bytes, with the UI array as a control. If nothing
  moves every time, tab state is unreadable and the loop must be built
  correct without it.
- **Gold deposit** (user addition): T23 calibrates the gold button and
  the amount dialog's confirm, and reports whether that dialog raises
  any panel flag — if it does not, `PanelInput` has nothing to gate on
  inside it and the deposit needs a different approach. Verification is
  the easy part: carried gold down, stashed gold up, both long readable.
- **Gold reserve conflict**: repairs and merc resurrection are both paid
  from CARRIED gold (>50k for the merc), so a loop that deposits
  everything would strand both. Needs a reserve policy — see R76.

### Town-layer live campaign (R63–R81) — what the drills actually taught

Six live failures, all in the town layer, all mine, and all one of three
shapes. Worth recording as shapes rather than incidents, because each was
found once and then found AGAIN somewhere else:

**Shape 1 — perception is smaller than the world.** Perception reaches 80
subtiles and the client only keeps NEARBY ROOMS loaded, so a distant NPC
is out of range and a distant object is not in the unit table at all.
Fixed with configured approach positions + walk-then-look, for NPCs
(T12) and then again for objects (T13).

**Shape 2 — a click means what the game decides, not what we intended.**
Travel clicks landing on an NPC open a dialog instead of moving (T12,
T21); a 5-subtile standoff sat inside D2's selection radius. Proximity
was never needed: clicking an NPC from across the screen makes the
character walk over and interact. Standoff 10, interact range 12, both
derived from the projection maths rather than by feel.

**Shape 3 — a flag is not a ready state, and a click is not an arrival.**
Panels animate in, so a click on the frame the flag appears is lost
(T19); clicking an NPC starts a WALK, so a 6-second dialog wait expires
mid-journey and the retry restarts the approach (T21). Fixed with a
settle delay before in-panel clicks and a 15 s walk-inclusive timeout.

Two structural lessons outlast the specific bugs:

- **Asymmetry is a bug waiting for a bad day.** Heal retried a missed
  click three times, repair did not — and repair was the one that failed
  live. All three NPC steps now share `open_npc_dialog`, with a test that
  fails if any of them hand-rolls its own again. The stash's own
  open-and-wait was then fixed *before* it could fail, by recognising it
  as the same shape.
- **A looping bot must be stoppable.** The drill harness could cancel its
  own waits but not a retry ladder inside the town layer, so a human
  watched a dozen approach-and-chat cycles run to exhaustion with no way
  to intervene short of killing the bridge. Every ladder now honours an
  outside veto wired to the cancel file.

### The calibration crisis (R85–R90) — three bugs, all in our own tooling

T19 failed live four times at Charsi. None of the causes were in the game,
and none were where the failure appeared. Worth recording as a set, because
they only became findable once each one stopped hiding the next:

1. **The measuring instrument was wrong.** `capture_hover(last_point=None)`
   meant "armed immediately", and the first capture of a drill happens
   exactly when the user's hand is still resting where they clicked the NPC.
   So T18 recorded Charsi's portrait as the "trade/repair row" — a
   plausible-looking number, 149 px off in X, which made every later click
   land past the end of the line. T20's resurrect row was measured the same
   way. **A calibration procedure can produce confident, precise, wrong
   numbers, and nothing downstream can tell.**
2. **The instrument disturbed what it measured.** Chat opens with Enter, and
   Enter into an open NPC dialog *selects an option*. Every prompt the drill
   chatted while a dialog was up was silently clicking through menus — and
   because the console then never opened, `say` retried once a second for a
   minute, doing it again each time. Two runs of the same drill measured the
   same row 46 px apart for this reason alone. The user diagnosed it from
   watching the screen, not from the logs.
3. **The stop button was broken.** `drill-cancel.ps1` had an em dash inside
   a string, and PowerShell 5.1 reads a BOM-less `.ps1` as ANSI — so the one
   tool whose whole job is to work in an emergency died on a parse error at
   the moment it was needed. Tool scripts are ASCII-only now and cancel is
   exercised in both directions.

The structural lesson is about *where* to look. Six live failures were read
as game-behaviour puzzles (does the menu shift? does the click register?)
when three were instrument defects. The tell, in hindsight: measurements that
disagreed with each other. Two runs producing different numbers for the same
fixed thing is not noise to average — it is the instrument reporting itself
broken.

The fix that came out of it is the user's design (R87): a click target is
**data** — `UIPoint(name, panel, fraction, opens)` — with one code path for
clicking any of them, one drill for calibrating any of them, and a hard rule
that an uncalibrated point refuses rather than guesses. Calibration runs with
the bot sending nothing at all, briefed up front and silent throughout.

### T17 (R68) — the kind table was innocent; travel clicks are the hazard

T17 measured NPCs by proximity (stand on them, read the nearest non-merc
ally): **Akara 148, Kashya 150, Charsi 154, Gheed 147**, rivals 14+
subtiles away. kolbot's table was right all along and so were the
configured positions — so R66's "the kind table is wrong" was a wrong
diagnosis of a right symptom.

**The real cause**: the navigator moves by *clicking toward* the
destination, and a travel click that lands on a bystander opens their
dialog instead of moving. The bot was correctly aimed at Akara and got
waylaid by Kashya *en route*; her dialog then blocked every subsequent
click. `_walk_guarded` recovers precisely — a NavigationError **with a
panel open** closes it and resumes (each attempt makes real progress,
since the walk restarts from where it stopped), while any other
NavigationError propagates as a genuine pathing failure.

**P4/P5 carry-forward, important**: this is not a town-specific
problem. A travel click landing on *any* interactive thing does the
wrong thing, and in combat a left-click on a monster attacks rather
than moves. The engine wants this handled at navigator level — either
waypoints nudged off occupied subtiles, or the recovery generalized —
not re-solved per caller.

Method note worth keeping: R52 and T17 produced the *same* table, but
only T17 licensed it. A coincidence and a measurement can agree exactly
and still differ completely in what they permit you to build on.

### T12–T14 town steps (R63) — two real gaps found, one step proven

- **T14 PASS**: belt refill worked end to end on the live character — the
  T11 grid calibration put shift-clicks on the right cells, the belt count
  was verified after each move, and it stopped exactly at minimums.
- **T12 FAILED** → perception reaches 80 subtiles; a town is bigger. Asking
  perception for Akara and giving up was wrong. Fixed: configured NPC
  approach positions (legitimate because SP maps are fixed per
  character — the atlas premise), walk-then-look, re-read after arrival
  since NPCs pace.
- **T13 FAILED** → a stash panel left open from setup made the first walk
  illegal (`GatedInput` refuses with a blocking panel), dying 10 s later
  as a `NavigationError`. Fixed: `_begin_step()` closes panels at the
  start of every step.
- **R64 (user note) turned T13's fix from hygiene into a correctness
  requirement**: shift+right-click means *inventory↔stash* with the stash
  OPEN but *inventory→belt* with it CLOSED. Panel state is part of the
  instruction, so a refill attempted with the stash up would quietly
  stash the potion. Documented in town.py's contract.
- **Materials tab** (R64): drills T15 (discover a verifiable tab-state
  signal, calibrate the X button) and T16 (bot toggles and verifies),
  discovery-first — a toggle we cannot verify is a click we may not make.
  Which items belong in the tab is deferred to P5's pickit.

### T11 snake sweep (R61) — grid uniformity proven, numbers adopted

Full coverage: all 40 usable cells, 78 click samples. Fit: origin
(0.5301, 0.4385), cell (0.0268, 0.0461) — 41.1 x 39.8 px pitch; worst
per-cell residual 11.5 px, random scatter, **no row/column drift** (no
gutter, uniform grid). T10 agreement within 7 px origin / 0.8 px-per-
cell pitch. T11's click-derived numbers adopted as TownConfig
defaults. First harness outing: the full test protocol (header /
instructions / TEST LIVE / TEST CONCLUDED) delivered in-game; one
launch-path defect fixed en route (drills need the path bootstrap /
module invocation).

Housekeeping follow-up for P6: **date normalization** — the harness
stamps machine time (T11: 2026-07-29 17:31) while several resume-day
artifacts (drill-log backfill rows T7–T10, some code comments) say
2026-07-30; reconcile against the machine clock during the sweep.

## P3 calibration findings (2026-07-30, bridge 049 — R60)

**The charm inventory is the headline, not the geometry.** User-flagged
before the run (R56/R60) and confirmed live: PD2's charm space shares
the *same container* as ordinary inventory and is identical in every
ItemData byte we read — `game_location=3`, `node_page=1`, `mode=0`,
`container='inventory'`. The only discriminator is the cell
coordinate: y >= 4 is charm space.

Why it mattered: the baseline dump showed **all 24 of the character's
inventory-container items sit at y 4..7** — the usable grid was empty.
The pre-R60 `deposit_to_stash` walked `carried.inventory`, so it would
have computed pixels for two dozen untouchable items, failed every
transfer verification, and tripped the **full-stash halt over a stash
that was never full**. Fixed: `INVENTORY_COLS/ROWS` in offsets,
`main_inventory` vs `charm_inventory` in items.py, all three town
consumers routed to `main_inventory`, and `_grid_pixel` refuses any
cell outside the usable rectangle as a second line of defence.

Geometry (four corners, user-defined, 1536x864 window):

- usable grid **10x4**, cells (0,0)..(9,3)
- `inventory_origin = (0.5257, 0.4404)` (cell (0,0) centre)
- `inventory_cell   = (0.0273, 0.0467)` → pitch 42.0 x 40.3 px
- worst corner residual 3.5 px — baked into `TownConfig` defaults

Open: kinds **605 and 606** both came out of health belt columns during
the drill; 606 is confirmed healing (R54 logic) but 605 is unclassified
— resolve before the ladder's drink rules go live (a mana potion filed
as healing would make the heal rung a no-op).

## P2 live-drill findings (2026-07-30, bridge 044 — R55 all PASS)

- **Panel slots calibrated**: waypoint = 0x14 toggling cleanly 0→1→0 —
  M2's "always-on" note was a misobservation; restored as a real
  panel, kept fail-safe (see below). Stash = 0x19, raising **only
  itself** — the inventory slot stays 0 with the inventory visibly
  open beside it. NPC menu = 0x08 confirmed.
- **A real `can_act` hole closed**: stash and waypoint panels were in
  no blocking set, so world clicks were *allowed* with them open (the
  M1 shape, one panel over). Both added to `_BLOCKING_PANELS`. The
  0x14 conflict is resolved in the fail-safe direction: a stuck-1
  recurrence would refuse world input loudly, never click through a
  phantom panel. **P3 requirement**: verify the 0→1 edge after
  clicking the waypoint object, not just the level.
- **Verified switching live**: desecrate (83) and bone armor (68) both
  read back after one press each. **First autonomous cast**: bone
  armor right-click, mana 378→343 (the 35-mana cost observed).
  **First autonomous drink**: belt col 0 1→0, mana refilled to 378 —
  and col 0 (mana) is now EMPTY on the live character; P3's
  below-minimum halt would fire today (heal cols are stocked).
- PanelInput refusals both demonstrated with correct messages
  (no-panel, wrong-belief). Positive panel click deferred to P3
  post-calibration (R55 rationale).

## Future work ideas

- TP tome (F3) and bone wall (F4) usage — user notes, low priority.
- Vendor/shopping UI (belt refill option (a)/(c)) — M6+ if ever.
- Cross-area walking / multi-area union grid — M6 (Countess).
- Corpse retrieval + death recovery — still deferred, low priority
  (user decision, M4).
- Stat-based `.nip`-style pickit language — M6, with item stat
  perception to match.
