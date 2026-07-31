# Resume point — M5, review findings cleared; P6 wiring then stage B

Written 2026-07-31, updated the same day after the R132 batch. Read this
plus [notes.md](notes.md) ("P4 build notes", "P5 build notes", "P5b — the
R117 amendment") and you have the state; the gate artifact is
[p5-sim-trace.md](p5-sim-trace.md), the architecture is in
`docs/adr/2026-07-29-behavior-architecture.md`, and **R115 is the only
request still open** in `docs/instruction-log.md`.

## Where the milestone is

M5 = the first end-to-end run (Cold Plains clearance, Hell). Phases:

| Phase | State |
|---|---|
| P1 perception extensions | **done**, live-verified |
| P2 input extensions | **done**, live-verified |
| P3 town layer + waypoint | **done** (gate R114; commit cb63b67) |
| P4 behaviour engine | **done** (sim-only) |
| P5 combat + pickit | **done** (sim-only) |
| P5b real pickit + hygiene (R117) | **done**; vocabulary closed (105 names, 0 pending) |
| P6 stage A (town, drop gesture) | **PASSED** — T43 audit + T44 verification |
| Review findings 002/003 + R132 batch | **done** (this session) |
| P6 wiring checklist (review 005) | **next** | ← here
| P6 stage B (supervised Cold Plains clear) | after the wiring |

`609 tests, ruff clean.` All committed and pushed on `m5-trial-run`.
**R130 is closed** — the commits were rewritten to the GitHub noreply
address and pushed in the session that raised it; the log row saying
otherwise was stale, and so was the claim here that four commits were
waiting. The vocabulary is closed and the inventory cleanse is enabled;
the only input path with no live evidence — ctrl+right-click — was
verified in stage A.

## What the R132 batch changed (2026-07-31, all sim/unit-tested)

The user asked whether the cleanse was too conservative. It was, in
exactly one place, and three neighbouring gaps got closed with it:

1. **`CarriedItem.sockets`** (R132a). A socket condition could not be
   evaluated against a carried item, and the cleanse evaluates
   permissively — so every necro head and archon plate was kept and
   stashed whatever its sockets. `units.read_socket_count` now separates
   "zero sockets" from "nothing read"; only the latter is None. The user
   chose this over a conservative/ruthless toggle: strict and permissive
   agree on every other condition, so with the field in place a toggle
   changes nothing, and WITHOUT it a ruthless-strict mode would have
   dropped the socketed bases the pickit collected on purpose.
2. **Review 002** — `InputRefused` is caught at both engine send sites,
   with `refusal_limit` escalating an unbroken streak to
   `InputRefusedHalt`; `ReflexDecision.commit` defers every rung's
   bookkeeping until the send lands.
3. **Review 003** — `StepOutcome.waiting` declares a deliberate wait and
   the watchdog treats it as progress. The wiring-time validation option
   was deliberately not also taken (see the issue's resolution).
4. **Full stash** — `StashFull` converts to a loop-halting
   `StashFullHalt` at the runner boundary instead of escaping as an
   unhandled `TownError`, and `warn_on_stash_pressure` gives notice
   before the wall. Halting leaves the character in town, where the human
   needs to be anyway.

Full inventory needed no new routine: suppress non-potion pickups,
queue a field cleanse, empty the inventory next preamble. Ending a run
early on a full inventory was considered and NOT done — it changes what
the clearance step does, and stage B exists to validate that step as
designed.

## START HERE

**The P6 wiring checklist** (review issue 005), which is now the only
thing between here and stage B: `cleanse_keep(pickit)` ->
`TownLayer.keep_item`; a SESSION-wide baseline -> `protected_ids` (the
implicit one is a floor, not the goal); `RunServices.cleanse`; belt
capacity -> `Pickit.belt_capacity`; `chicken_life_pct` -> `SafetyConfig`.
One addition from R132: wire the reflex ladder's `carried` callable to
`read_carried_items(with_sockets=False)` — it only reads the belt and
runs every tick, so it should not pay for 40 stat reads; everything else
takes the default.

**Then stage B, a supervised Cold Plains clear** — the first time the
bot fights anything. Everything in `necro.py`, ladder rungs 3-7 and the
clearance step is sim-proven only, and the sim is a model of the game,
not the game.

**R115** (IdleBail sharing the cycle's chicken counter) is still
unanswered. Note it is now the same shape as `StashFullHalt`, which took
the "halt without leaving" route deliberately — worth deciding both
together.

P5b context: at the gate the user supplied the real pickup spec (R117)
+ five clarifications (R118, all answered). Potion protocol v2 (belt
first, reserve 2/type in inventory, drink ALL excess incl. rejuvs,
never stash potions), the real pickit over a provenance-tracked
vocabulary (most ids pending T39; unresolved names fail SAFE — no
pickup, and the cleanse is disabled entirely), and the inventory
cleanse (ctrl+right-click drop; town preamble pass + field pass in
dead air only). See the phase file `05b-real-pickit-and-hygiene.md`.

## What P4 and P5 built

`pd2bot/behavior/` — the whole decision layer, ADR drafted (proposed,
finalize in P6):

- **engine.py** — ticked loop: snapshot -> `SafetyMonitor.tick()`
  (raises pass through) -> reflex ladder -> current run step. A firing
  rung consumes the tick, so offense is skipped by construction.
  `IdleBail` watchdog after 10 s of no sends and no progress out of town.
- **reflex.py** — the R49 ladder, rungs 3-8. Cooldowns, blood-warp
  position-verify, town suppression of rungs 3-7. Belt keys follow R53
  (mana 1, rejuv 2, heal 3+4), derived from `[belt] columns`.
- **necro.py** — R47.2's skirmish pattern: contact, wait for revives to
  tank, dash in SHORT HOPS (so the ladder gets a look between them),
  strike, retreat, repeat. Poison does the killing, so targets are
  chosen fresh-first with a 6 s restrike. Desecrate -> revive to 3,
  bounded, never in town.
- **execute.py** — the only module that sends: every cast goes through
  `ensure_right_skill` (no cast on an unverified skill), attacks hold
  SHIFT, pickups must not. Records the decision trace.
- **steps.py** — the five step handlers + the wired registry.
  `clear_radius` needs the radius empty for 5 s before finishing;
  `pickup` sweeps with a shared, bounded inventory-full guard.
- **run.py / combat.py** — runs and class configs as strict TOML.
- **runner.py** — the `run_games` callback boundary, idle-bail counting.
- `pd2bot/pickit.py` + `config/pickit.toml` — top-down, first-match-wins
  loot rules over kind and quality (all perception can see).

## What P6 does (read `06-staged-acceptance-closeout.md`)

The staged live ladder (R46 Q8), the bridge, and a human. Everything
below is sim-proven but has never met the game:

1. Wire the real `GameActionExecutor` to a live `GatedInput`/`Navigator`
   and the real `TownLayer`/`WaypointTravel` behind the two blocking
   steps. Feed `chicken_life_pct` (35) into `SafetyConfig`.
2. **Verify gold's kind (523)** on the first real drop — inherited from
   kolbot, never confirmed on this client, and the pickit's gold rule
   may simply never fire until it is.
3. The bone-armor stat's falls-when-hit half still owes a live check
   (deferred from P1 drill B); the R47 fallback covers an unreadable
   stat.
4. Finalize the ADR, write `docs/architecture/behavior.md`, README
   section on the drill harness + drill log + bridge-run, and the date
   normalization sweep (both noted in the P3 notes).

## Live-test protocol (needed again from P6 on)

The user starts the elevated bridge once per session:

```
powershell -ExecutionPolicy Bypass -File "C:\dev\2026-pd2-bot\2026-pd2-offline-bot\tools\elevated-bridge.ps1"
```

The `-ExecutionPolicy Bypass` child-process form is REQUIRED. Drills
live in `drills/` on the `pd2bot/drill.py` harness; cancel with:

```
powershell -File tools\drill-cancel.ps1
```

Everything from P3 still holds: calibrations in `pd2bot/uipoints.py`
(re-run after any window/resolution change), NPC dialog rows are
keyboard ordinals, the charm inventory shares the container (y >= 4),
the Cube is unmovable, PD2 potion kinds 610/611 mana / 606 healing /
530/531 rejuv, rejuvs are materials, the materials tab makes the stash
read empty, services are paid from the shared stash. Area ids: Rogue
Encampment 1, Cold Plains 3.

## Suggested opening prompt for a fresh conversation

> Continuing the PD2 bot, milestone M5. P6 stage A is done and the
> review's P2 findings (002, 003) plus the R132 cleanse/fullness batch
> are fixed — 609 tests, ruff clean, uncommitted. Next is the P6 wiring
> checklist from `docs/reviews/2026-07-31-m5-trial-run/issues/005-minor-
> cleanups.md`, then stage B, the first supervised Cold Plains clear.
> Read `docs/plans/2026-07-29-m5-trial-run/RESUME.md` first, then that
> review's `summary.md`, then the phase file
> `06-staged-acceptance-closeout.md`. Stage B needs the bridge and a
> human watching. Instruction-log IDs continue from R133; R115 is the
> only open request.
