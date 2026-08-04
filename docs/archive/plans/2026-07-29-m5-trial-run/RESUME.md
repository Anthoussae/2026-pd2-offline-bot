# Resume point — M5, P6 stage B: review findings closed, combat still untested

Updated 2026-08-01. Read this, then
[the review](../../reviews/2026-07-31-m5-stage-b/summary.md), then
[notes.md](notes.md). The architecture is in
`docs/adr/2026-07-29-behavior-architecture.md`; the wait policy added
today is in `docs/adr/2026-08-01-bounded-declared-waits.md`; the phase
file is [06-staged-acceptance-closeout.md](06-staged-acceptance-closeout.md).

**696 tests, ruff clean.** R115 is still the only unanswered request; the
instruction log continues from R155.

## What 2026-08-01 changed

All three open P1/P2 findings are fixed, and **the eleventh stage-B
attempt was a clean `[CVRL]`** — town preamble, waypoint, clearance,
pickup, done, clean leave.

Two live drills settled what three runs of guessing had not:

- **T47** — every one of the six hotkeys selects exactly what
  `config/necro.toml` says. Bindings are right and presses land, so both
  standing `SkillSwitchFailed` theories are dead. Do not edit the config.
- **T48** — a cast animation is **610-640 ms** (player mode 10), and a
  hotkey press sent 110 ms INTO one still registers within 62 ms. So a
  cast does not eat following input; only clicks are worth holding.

The fixes: the drift is bounded by the fight and goes SIDEWAYS rather
than standing still; `clear_radius` can ask the combat module to close on
a monster it will not engage; a declared wait now expires
(`wait_bail_s`); casts wait on the game's casting mode instead of a
guessed sleep, with potions exempt; the town layer polls a cheap
inventory read and pays for sockets only where it decides.

**The tenth attempt died on a waypoint lock-out** and is worth knowing
about: `_open_ground` avoided units but not OBJECTS, so a desecrate
landed 4 subtiles from the waypoint just arrived on, opened its menu, and
every send was refused until the run chickened out. Casts never went
through the navigator, which has filtered `INTERACTIVE_OBJECT_KINDS`
since R111. Now fixed three ways (avoid it, step off it on arrival, and
close a stray panel from the field).

## START HERE — the honest gap

**The bot has not fought since the fixes landed.** Neither run today put a
monster inside engage range, so `combat.engage`, the approach path that
finding 001 was about, and the lateral drift have all executed only
against fakes. The next supervised run should be judged on whether it
FIGHTS, not on whether it completes.

Two consecutive arrivals with nothing in radius 50 is also the second
data point for the deferred patrol question below.

## Where the milestone is

| Phase | State |
|---|---|
| P1 perception, P2 input, P3 town+waypoint | **done**, live-verified |
| P4 behaviour engine, P5 combat+pickit, P5b hygiene | **done** (sim-only) |
| P6 stage A (town, drop gesture) | **PASSED** |
| P6 wiring (`pd2bot/wiring.py`) | **done**, live dry-run verified |
| P6 stage B (supervised Cold Plains) | **partly** — see below |

## What stage B achieved

Nine live attempts. **The full run completed twice** — `[CVRL]`: town
preamble, waypoint, clear_radius, pickup, done, clean leave. One of those
involved real combat (the user confirmed it fought, and that it summoned
three revives immediately).

Confirmed working live: bone armor cast as the first action of a game;
the revive wall built before approaching; the town preamble end to end
(heal, repair, belt, cleanse, stash, gold, merc); the waypoint trip; the
decision trace.

## The review findings

All in [docs/reviews/2026-07-31-m5-stage-b/](../../reviews/2026-07-31-m5-stage-b/summary.md),
each with a Resolution section:

1. **001 (P1)** repositioning could strand the clearance — **fixed**,
   three ways, and the ADR the summary asked for is written. Not yet
   exercised live.
2. **002 (P2)** the cast settle blocked the ladder's tick — **fixed**
   against T48's measurement. Live-verified twice (six `CastInFlight`
   deferrals in the clean run).
3. **003 (P2)** town polling re-read every socket — **fixed**. The live
   re-measurement of the "dithering" is still owed.
4. **004/005 (P3)** open, and genuinely minor.

## The skill-switch failure: still open, but no theories left

`SkillSwitchFailed` recurred in three runs on three different skill pairs
(95←83, 68←83, 68←95) — the slot stays on whatever was selected last. It
did NOT recur in either of today's runs (nine verified casts).

What has been eliminated: stale bindings and dropped presses (T47), the
cast-eats-input theory (T48), and — by construction, since both raise
`InputRefused` instead — a blocking panel and a lost foreground.

Rather than invent a fifth theory, `ensure_right_skill` now attaches the
state at the moment of failure (waited, player mode, open UI panels,
left-skill read). The next occurrence is evidence, not another
supervised run.

## Open user requests

- **R115** — should `IdleBail` share the cycle's chicken counter? Now the
  same shape as `StashFullHalt`/`TownStepHalt`; decide them together.
- The user asked for a wider **patrol** around the waypoint ("2 screens in
  each direction"). Note radius 50 already IS ~2 screens; the reason the
  bot does not roam is that `clear_radius` has no patrol — it stands and
  waits for the radius to read clear, and perception (80) exceeds the
  radius, so it can verify from a standstill. A real patrol (visit sample
  points so perception sweeps the area) is a **new feature** and P6's
  phase file puts features out of scope — needs a decision. **Both
  2026-08-01 runs arrived to an empty radius 50 and never fought**, which
  is the strongest argument yet that the answer matters: without a patrol,
  whether the bot fights at all is down to where the pack happens to be.
- The user is willing to **keep wrongly-picked items** for examination.
  Probably unnecessary now: pickup logs its decision (kind, quality,
  sockets, matching rule), so a surprise explains itself.

## What this session changed (25 commits)

Highlights, all live-diagnosed:

- **The item vocabulary is anchored to D2 CODES** (R144), not kind ids.
  SIX of seven elite armours were wrong — the bot picked up a Wire Fleece
  believing it was a Kraken Shell. `GOLD_KIND` was also wrong (523 is an
  elixir; gold is 538).
- **Unit dedup is per TYPE.** D2 ids are unique only within a type; a
  monster and the Act 1 waypoint were both id 11, and objects lost every
  collision. The fix took the live snapshot from 9 objects to 22.
- **The stash tab question is retired** (R134). Materials self-route from
  the regular tab (T45), so deposits toggle only on REFUSAL. The whole
  tab-inference mechanism is deleted.
- **Armor down is a trigger, not an unknown** (T46). Absent 132/133 with a
  healthy stat list means the armor is DOWN, which is why it never cast.
- **The runner survives anything unexpected.** `DeathHalt` and
  `CycleError` propagate; everything else is counted and retried.
- Review 002/003 fixed (refused sends, declared waits), plus
  pacing-vs-cooldown split out after the fix caused a livelock.

## Live-test protocol

The user starts the elevated bridge once per session:

```
powershell -ExecutionPolicy Bypass -File "C:\dev\2026-pd2-bot\2026-pd2-offline-bot\tools\elevated-bridge.ps1"
```

The `-ExecutionPolicy Bypass` child-process form is REQUIRED. The agent
then drops `<id>.cmd.ps1` into `%LOCALAPPDATA%\pd2bot-bridge` and reads
`<id>.out.txt`. Cancel a drill with:

```
powershell -File tools\drill-cancel.ps1
```

Run the bot:

```
python -m pd2bot.wiring --games 1 --chicken 50 --run runs/cold-plains-stage-b.toml
```

`--dry-run` assembles everything and prints what resolved without sending
anything. Stage B is radius 50 with the chicken raised to 50%; the full
run (`runs/cold-plains.toml`) is radius 150.

Still true from P3: calibrations in `pd2bot/uipoints.py` (re-run after any
window/resolution change), NPC dialog rows are keyboard ordinals, the
charm inventory shares the container (y >= 4), the Cube is unmovable, PD2
potion kinds 610/611 mana / 606 healing / 530/531 rejuv, services are paid
from the shared stash. Area ids: Rogue Encampment 1, Cold Plains 3. This
character's stash is PD2's EXPANDED one (`game_location 8`, ~360 items);
the classic stash (7) is empty, which is what broke the old tab
inference.

## Known-unclean

- Leaving the game sometimes ends on an **unrecognized menu screen**
  (`[CV--]`, 3 image controls). M4 cycle, not the run. Unfixed.
- `test_behavior_sim` scenarios take ~4.4 s each (was negligible). The
  bot spends far more ticks for the same outcome; finding 001 is the
  likeliest explanation, so this should resolve with it.
