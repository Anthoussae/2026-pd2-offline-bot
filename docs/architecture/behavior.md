# The behavior layer: how the bot decides what to do next

M5's layer. Perception answers "what is around me" (M2), navigation
answers "how do I get over there" (M3), the game cycle answers "how do
I get a game at all" (M4) — the behavior layer answers "given all of
that, what is the *next thing worth doing*, and what must never be
skipped while doing it". It is the layer that turns a bot that can be
left alone into a bot that plays.

Companion docs: [perception.md](perception.md),
[navigation.md](navigation.md), [game-cycle.md](game-cycle.md), the
decision record
([docs/adr/2026-07-29-behavior-architecture.md](../adr/2026-07-29-behavior-architecture.md)),
and the archived M5 planning dir
([docs/archive/plans/2026-07-29-m5-trial-run/](../archive/plans/2026-07-29-m5-trial-run/plan.md)
— stage records, the pickup-accuracy investigation, the implementation
log). Live-verified through staged acceptance: Stage E ran 3/3 clean
unattended Cold Plains clearances with the safety monitor silent.

## The engine: one tick is one decision (`behavior/engine.py`)

    snapshot -> SafetyMonitor.tick() -> stop checks -> reflex ladder -> current step

The engine is a small ticked loop (~5 decisions/s), and the order of
that line is the architecture:

- **The monitor goes first, always.** `SafetyMonitor` (M4's death latch
  and chicken — ladder rungs 1–2) raises `DeathHalt`/`ChickenExit`
  straight through the engine, uncaught and unwrapped. Nothing the
  behavior layer does can reorder itself above them. The latch even
  outranks an abort: a stop request rides the leave-game path, which
  sends input, and input at a dead character is the one forbidden thing.
- **Stop checks next.** `StopRequested` fires on the operator's chat
  abort or a drill cancel file, and on the Enter/ESC kill switch (R189):
  out of town, the ESC menu or chat console can only have been opened by
  a human — the bot's own field-side ESC is correlated away by timestamp
  — and operator input means the operator wants the character.
- **A firing reflex rung consumes the tick.** Offense and run progress
  cannot happen while survival has something to say — by construction,
  not by discipline. This is the direct answer to the rejected
  "monolithic script with checks sprinkled in" design: a missed sprinkle
  is invisible until it kills the character, so survival is structural.
- **Only a quiet ladder lets the current run step act.** Steps are
  re-entered once per tick until they report done.

Two kinds of send failure are absorbed identically (`SEND_DID_NOT_LAND`):
`InputRefused` (a guard said "not now") and `SkillSwitchFailed` (the
client dropped a hotkey press — watched happening live during an
area-change stutter). Both mean nothing reached the game, so the engine
re-decides next tick rather than retrying inside the tick — a patient
in-tick retry would buy reliability with exactly the seconds the
survival rungs need. A *streak* of refusals (50 ticks, ~10 s) is
different: the bot is deciding but nothing reaches the game, so
`InputRefusedHalt` ends the run loudly.

### The never-idle invariant

R47.9, the user's danger assessment: *any enemy can kill an idle
character; groups stun-lock.* Outside town, if nothing has been sent
and no progress made for `idle_bail_s` (10 s with hostiles within 40;
30 s with nothing nearby — a stuck bot must surface even when it is not
in danger, R115), the engine raises `IdleBail`. It is typed as a
`ChickenExit` subclass so M4's unmodified cycle already leaves the game
correctly, but flagged `is_vitals = False` and counted separately by
the runner: an idle loop is a bug, not a vitals problem, and two in a
row halt with an honest `IdleLoopHalt` instead of hiding among
chickens. Every bail carries a full state dump (position, vitals,
hostiles, last sends, last log line) — an idle bail is by definition
the case nobody predicted, so its one chance to explain itself is the
state it happened in.

Movement counts as progress (a walk in flight sends nothing new per
tick), and a step may declare a deliberate wait (`StepOutcome.waiting`
— the clearance settle, the restrike interval, waiting for revives to
tank). But a declared wait is *a claim that something will expire*, and
it is held to a deadline: an unbroken run of waits longer than
`wait_bail_s` (30 s, 6× the longest configured wait) is a hang wearing
a wait's clothes and is treated as the idle loop it is (review 001).

## The three layers

kolbot's proven shape — engine / script-per-run / per-class attack
module — rebuilt on this project's rules: runs and class specifics are
*data*, and the engine knows neither.

**Runs are TOML** (`behavior/run.py`, `runs/*.toml`). A run is an
ordered list of steps with parameters — `town_preamble`, then
`waypoint {dest = 3}`, then `clear_radius {radius = 150, patrol = true}`,
then `pickup`, then `done` — validated at load against a
`StepRegistry`. Unknown step, unknown/missing/mistyped parameter,
declared-but-unimplemented step: each is a loud `RunError` before the
bot moves. Steps communicate through a shared blackboard
(`EngineContext.notes`): the waypoint step records its arrival position,
`clear_radius` reads it back, `pickup` adopts the clearance circle — no
step knows another. A second run is a new file, not new code.

**Step handlers** (`behavior/steps.py`) come in two shapes, and the
difference is load-bearing. *Blocking* steps (`town_preamble`,
`waypoint`) do their whole job in one tick, safe exactly where they run:
town is where the ladder has nothing to say, and the waypoint trip is a
loading screen. *Ticked* steps (`clear_radius`, `pickup`) do one small
thing per tick — everything that happens in Hell is one of these, so
the ladder gets a look between every decision. Field movement happens
in short capped legs (`_hop`) along the atlas's route answer (R181),
never one blocking walk.

**Class modules** (`behavior/combat.py`, `behavior/necro.py`) implement
the `CombatModule` protocol: `engage` (one decision of the fight) and
`upkeep` (keep the revive wall standing), both returning declarative
actions or None. `NecroCombat` encodes the user's own skirmish pattern
(R47.2): on contact wait briefly for the revives to tank (ended early
once one is engaged), dash in — in short hops, never a blocking walk —
strike with SHIFT held (attack in place), retreat back out, repeat.
Poison does the killing, so fresh targets are preferred over re-striking
poisoned survivors; and standing still being the class's true danger,
every would-be idle tick becomes a small lateral drift that never
leaves the fight (review 001). The class TOML (`config/necro.toml`)
carries hotkeys, live-captured skill ids, the belt layout and every
ladder number; the loader rejects unknown keys loudly — a typo'd
threshold silently defaulting is the exact failure the robustness
priority forbids.

**The reflex ladder** (`behavior/reflex.py`) — next section.

Beneath all three, **the executor** (`behavior/execute.py`) is the one
place declarative actions become keys and clicks. Everything above it
emits data and touches nothing, which is why the whole stack runs
against scripted worlds and why P4 could be built sim-only. Its rules:
no cast on an unverified skill (`ensure_right_skill` presses the hotkey
and reads the active skill id back from memory before any click);
attacks stand still (SHIFT); clicks — but not keypresses — wait out the
bot's own cast animation, read from the player's mode, never slept for
(T48 measured 610–640 ms; potions must never queue behind it); and
item pickups aim at the *sprite*, not the tile — the clickable sprite
draws ~28–48 px above the projected ground tile, so clicks follow the
T63-measured per-attempt offset schedule (`_PICKUP_OFFSETS`), with the
ALT label display ensured on (read from memory, pressed only when
provably off) so small classes — runes, gems, charms — can be clicked
at their label band. Every send lands in a trace: when a live run does
something surprising, the trace says which decision produced it.

### The acquisition seam (item-acquisition plan, P1)

Item pickup is two problems the operator asked to keep apart:
**detection** — which items are on the floor and which the pickit wants
(`_PickupMixin.wanted_items`, the sightings memo) — and **acquisition** —
getting a *known* item off the ground (`_PickupMixin.collect`: reach,
walk budget, retry pacing, belt/inventory diagnosis). Detection does not
depend on acquisition.

Within acquisition, the one thing that actually *causes* a pickup — the
swappable mechanism — is `pd2bot/acquire.py::Actuator.actuate`.
`ClickActuator` is today's synthetic-click mechanism (it emits the
`PickUpItem` the executor turns into an aimed click); it is wired through
`RunServices.actuator`, so `collect`'s budgets and diagnosis are
mechanism-independent. This is the seam a **command-by-GID** actuator
drops into (the plan's P4 spike): kolbot's fast pickup is a `PickupItem`
command addressed by unit id with no screen aim at all — frame-perfect,
because identity is the address and there is nothing to miss. When it
lands, `ClickActuator` stays as the fallback, exactly as kolbot keeps a
screen click behind its packet path. Drill `t78_acquire` exercises the
seam with *junk* — no pickit on the path — which is the proof the two
problems are genuinely separate.

## The reflex ladder, with rationale

Priority-ordered; first firing rung wins the tick. Rungs 1–2 live in
`SafetyMonitor` and fire before the ladder is consulted at all — the
ladder *cannot* reorder them below anything.

| rung | name | trigger → action | why it sits here |
|---|---|---|---|
| 1 | death latch | mode reads dead or hp 0 → no input of any kind, permanently | the one response that sends nothing; survives anything memory says later |
| 2 | chicken | life ≤ 35% out of town → leave the game now | ESC pauses offline SP, so the exit completes the moment it lands; a floor trigger, reacting to the crossing within a tick |
| 3 | rejuv | hp < 50% → drink the rejuv column (no cooldown) | rejuvs fill instantly, so a re-fire next tick means it genuinely did not help; empty column + ≥2 hostiles within 10 escalates straight to rung 4 |
| 4 | blood warp | packed (≥4 within 8 and hp < 60%) or burst (>25% max hp lost in 2 s) → warp to walkable ground ~20 subtiles away | escape only, never traversal (R47.3); guarded by its own mana/hp costs; position-verified — a cast that did not move the player reads as still-on-cooldown, never re-spammed; the send clears the damage history so the warp's own hp cost cannot re-trigger the trigger |
| 5 | heal | hp < 100% → healing column, 10 s cooldown | the steady drip; backup column when the primary is empty |
| 6 | mana | mana < 25% → mana column, 15 s cooldown | R49 amendment (was 5 s); the necro's casts are the survival toolkit, so mana is survival |
| 6.5 | reposition | ≥2% max hp lost in 2.5 s while moving <3 subtiles → step 10 away | ground fire has no unit to see, so the trigger is damage-source-agnostic: bleeding while standing still IS the signal (R176) |
| 7 | disengage | armor down AND recast cooling AND hp < 70% → retreat | do not trade hits unarmored; distinct from rung 4 because it is a walk, not a spent cast |
| 7.5 | merc first aid | merc alive, < 50% (on the 0–128 client scale via `life_pct`), healing potion in belt → Shift+key | below every player rung on purpose: the merc gets a potion only on a tick the player needed nothing; the chord is SHIFT, verified by hand at R183 after the assumed Alt fed the player |
| 7.6 | belt hygiene | bottom row unusable → drink a bottom to repair it | the keys reach only the bottom row: foreign potions drunk clear, duplicates drunk to work a missing type down (rejuv bottoms never spent), mana glut drunk to one |
| 8 | upkeep | armor absorb < 75% (or, unreadable, after a hit) → recast; else delegate to the combat module's `upkeep` (desecrate → revive) | the armor recast is the one town-permitted rung; while a recast is pending its pacing, the combat upkeep is *starved* of the tick — every armor window otherwise opens into someone else's cast animation (T55) |

Drink rungs search all four columns for the needed *type*, configured
column first (R179): the R53 layout (1 mana, 2 rejuv, 3+4 healing) is a
preference, not a requirement, because the belt routes clicks by column
and a potion can sit anywhere a refill left it. Only the *bottom*
potion of a column matters — pressing key N consumes the lowest row —
and a mixed column is a normal belt state, not an error.

Town suppresses rungs 3–7.6 entirely: drink rules are out-of-town only
(R47.6), and — the sharper reason — town guards without an alignment
stat read as MONSTERS to perception (P1 drill D), so any hostile-count
trigger evaluated in town counts bystanders.

Two bookkeeping disciplines, both paid for live:

- **Cooldowns commit on send, not on decision** (review 002). A heal
  whose click was refused used to start its 10 s cooldown anyway, so
  the ladder stopped offering the heal the character still needed —
  precisely when input being refused correlates with things going wrong.
- **Pacing records on attempt, even a failed one** (stage B run 9). A
  bone-armor switch that would not take fired, failed, recorded
  nothing, and fired again next tick — fifteen times, every tick
  consumed, a crash become a livelock. A cooldown says "the resource is
  spent"; pacing says "do not spam this"; collapsing them costs a run.

## Panel-scoped input's place in the guard family

M5 added the fourth and last send path (`panelinput.py`). The guard
landscape, complete:

    GatedInput   sends only when  in a game AND no blocking panel
    MenuInput    sends only when  NOT in a game, OR the ESC menu is open
    Chat         types only while the chat console is verified open
    PanelInput   clicks only while the panel the caller NAMES is verified open

The town layer must click things that live in nobody's territory: a row
in the waypoint list, a stash cell, an NPC dialog option. GatedInput
refuses (a blocking panel is open — correctly), MenuInput refuses (in a
game without the ESC menu — correctly), and weakening either would
reopen the M1 "Save and Exit Game" hole from a new direction. So:
Chat's construction generalized. The caller states its belief ("I am
clicking in the waypoint list") and the guard checks that belief
against a fresh read of the UI array at the moment of sending; a stale
belief refuses instead of clicking into whatever took the panel's
place. Same construction rules as every gate: no bypass flag, no
unguarded variant, checks re-run at send time. Shift is released in a
`finally`, so a mid-click failure can never leave it stuck down.

## Config and data files: what the operator tunes

| file | owns | notes |
|---|---|---|
| `config/necro.toml` | everything class-specific: skill ids, hotkeys, belt layout + refill minimums, every ladder number, the skirmish numbers | read and tuned by a human (R46 Q3); unknown keys refused loudly; skill ids live-captured, hotkeys must match the client's bindings |
| `config/pickit.toml` | what is worth picking up, and the keep/stash/drop rules | the user-facing knob; the inventory cleanse disables itself while the pickit names unresolved items |
| `config/item_codes.toml` | the item-code vocabulary | data, not policy |
| `config/item_ids.toml` + `config/item_ids.learned.toml` | code → class id mappings, shipped + live-learned | the learned file grows from play |
| `runs/*.toml` | the runs: ordered steps + parameters | `cold-plains.toml` is the trial run; a new run is a new file |
| `maps/` (gitignored) | the explored-map atlas | save-data, regenerable by walking |

Session-scoped vs per-game assembly is `wiring.py`'s responsibility and
not a style choice: the `SafetyMonitor` is built once per session (the
death latch is instance state — a fresh monitor per game would clear
it), the town layer once (the cleanse baseline must not re-protect last
game's pickups), while the combat module, ladder cooldowns, executor
trace and pickup memory are built fresh per game to stay bounded.

The run CLI is `python -m pd2bot.wiring` (elevated): `--games N`,
`--run FILE`, `--radius N` and `--chicken PCT` overrides (both refuse
loudly when they have nothing to apply to), `--dry-run` to print the
assembled wiring without sending anything. `tools/live-run.ps1` wraps
it through the elevated bridge.

## Combat postures (M6 P3: implemented)

Three named postures ship as config presets, selectable **per run
step** (`posture = "brisk"` on a `clear_radius`/`traverse` step) and
swappable mid-run — the module changes only its config dataclass, so
every piece of fight bookkeeping survives the swap. Loading is strict
as ever: `[combat.postures.<name>]` tables override only behavior knobs
(never skills), unknown keys and unknown posture names fail before the
bot moves, and "cautious" cannot be redefined because it *is* the base
`[combat]` numbers — a run naming no posture behaves exactly as M5 did.

- **cautious** (the base): hold until a revive tank is in front,
  strike-and-retreat after every strike, drift rather than press.
- **brisk** (the descent posture, R212 Q4/Q5): fight only what
  obstructs passage — a tight `engage_radius` bubble around the moving
  character is the route corridor, and `linger = false` makes the
  module hand the tick back when everything nearby is already poisoned,
  so the run keeps walking. "Brush past them toward the target, as long
  as that is safe" — and safety is unchanged: the ladder stands above.
- **aggressive** (the Cellar 5 posture): `retreat_group_size = 3` makes
  the post-strike retreat group-conditioned — an isolated enemy is
  struck without the back-out, a closing group still triggers the full
  retreat (the user's own definition); `restrike_s` drops to 0.5.

Two companion defaults landed with the postures (both user notes,
2026-08-03):

- **Right-skill parking** (`execute.py::maintain`, engine-granted once
  per tick): after the last cast of a burst resolves and `park_grace_s`
  (2 s) passes with no further cast, the executor switches the right
  skill back to bone armor — a verified SWITCH, no click, paced on
  failure. While Revive stays the active right skill, ground corpses
  are selectable and interfere with pathing and pickup; the grace lets
  a 3-revive burst finish without thrashing the switch.
- **Revive urgency** (`necro.py`): while the wall is short and a wall
  cast is actively in the pipeline (a recent desecrate/revive), strikes
  and dashes hold — drift only — so the desecrate→revive casts never
  share the cast pipeline with strike clicks (the T55 armor lesson one
  rung down). Keyed to a *recent cast*, not to wall-shortness, so it
  cannot re-create the pre-R163 full-wall passivity; and a desecrate
  budget burned against the skill's own cooldown now refreshes on time
  (`desecrate_budget_refresh_s`, in combat only — the quiet-field gate
  is untouched).

**Unaffected by posture**: the reflex ladder, the safety monitor, and
the executor's safety rules do not move. A posture changes offense, not
survival — that boundary is the architecture's whole point, and it is
what made runtime switching safe to build.

## The Countess endgame (M6 P4: `clear_countess`)

One ticked step (`steps.py::ClearCountessStep`) encodes the user's
tactics for the Cellar 5 chamber, in four beats: a **neighborhood
clearance** around the arrival staircase (a composed `ClearRadiusStep`
— the same machinery and budgets, a modest radius, no patrol) so the
encounter has no gaggle; a **staging point screen-north of the chamber
anchor**, derived from the atlas at run time (`_screen_north_point`:
walkable candidates bearing-north-first, distance descending) and
recorded on the blackboard under `countess` for the drill to display;
a **short-leg advance** through the combat module's own `approach`,
held by the revive brake (no advancing while the wall is shorter than
`approach_with_revives`, bounded by `advance_revive_patience` so a
cellar with nothing to raise cannot hang the run); and the **kill
condition** — her pinned identity (kind 734 / unique_no 6, T68+R216)
read with a dead mode, or *provably absent* after the budgeted
(`sweep_budget_s`, 15 s) chamber sweep, one in-and-out pass that runs
in both outcomes (after a seen kill it doubles as drop
reconnaissance). The chamber anchor comes from the run file
(T68-measured, per seed) and yields to the live boss read the moment
she is in perception — the exits' memory-first/live-authority rule
again. **Alive and unreachable is a loud stop**, never a write-off:
the step is the run's objective, so it alerts and raises rather than
finishing around her. On confirmation the chamber region (her corpse's
position when seen) is published as the `cleared` circle, which the
existing `pickup` step adopts unchanged.

The same phase also settled the T70 Thul lesson: `traverse` now
collects wanted items en route through the shared pickup mixin —
bounded by `pickup_radius`, only on ticks combat declined, holding the
walk only while a click is resolving — so a rune on a traversal floor
is no longer invisible to behavior while perception lists it.

## Re-verification drill after a patch

Same spirit as perception.md's and game-cycle.md's drills; the
behavior layer adds, in order of likelihood to move:

1. **Skill ids** (`config/necro.toml [skills]`): PD2 patches move these
   (blood warp 367 and desecrate 83 already sit in non-classic slots).
   Re-capture live — select each skill in the client and read the
   active id back (P1 drill A's procedure) — before trusting any cast.
2. **Hotkey bindings**: the TOML mirrors the client's F1–F6 bindings by
   hand. If the client's bindings change, the verified switch will
   *catch* the mismatch (`SkillSwitchFailed`, no cast) but only a human
   or a bindings-introspection follow-up (deferred from M5) can fix it.
3. **The pickup offset schedule** (`execute.py::_PICKUP_OFFSETS`):
   measured against this window/resolution (T63/T65). Re-measure after
   any window, resolution or UI-scale change — the symptom is pickups
   burning their click budget on ground beside the item.
4. **The label-display flag** (`units.label_display_on`,
   BH.dll+0x14d2ca): a BH.dll update can move it. Unknown reads make
   the executor leave the ALT key alone, so the failure is quiet — small
   items stop being clickable when labels happen to be off.
5. **Calibrated panel fractions** (town layer / `uipoints.py`, plus
   game-cycle.md's menu calibrations): hover-measured against this
   window. Re-run after any window or resolution change, patch or not.
6. `PLAYER_MODE_CASTING` and the belt/stat offsets ride perception.md's
   drill; the behavior layer consumes them through `snapshot`/`items`.

## Future notes (deferred, with owners in the M6 planning inputs)

- **TP tome and bone wall** are bound (F3/F4) and unused: no town
  portal behavior, no wall-casting. Corpse retrieval and door handling
  are likewise deferred — M6's tower levels have doorways, which is new
  ground.
- **Vendor UI** is still out of scope: below-minimum potions after a
  refill is a notice-and-continue (Stage D policy) and a manual restock.
- ~~Right-skill parking, revive priority, combat postures~~ — all
  three landed at M6 P3 (see the postures section above); their live
  proof rides the M6 battery.
- **The navigator label-band nudge** (optional polish, from the pickup
  arc): left as a bookmark; the offset schedule made it moot for M5.
- **Hold-to-move** (user discovery, 2026-08-04): holding the left
  button moves the character without interacting with the world — no
  accidental pickups. Candidate input primitive for travel legs; needs
  a drill first, and a guard design for an input that spans ticks. See
  the M6 plan's notes.md future-work entry.
