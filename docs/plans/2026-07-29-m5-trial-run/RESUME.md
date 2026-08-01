# Resume point — M5, P6 stage B: two full runs, review findings open

Written 2026-07-31 after a long live session. Read this, then
[the review](../../reviews/2026-07-31-m5-stage-b/summary.md), then
[notes.md](notes.md). The architecture is in
`docs/adr/2026-07-29-behavior-architecture.md`; the phase file is
[06-staged-acceptance-closeout.md](06-staged-acceptance-closeout.md).

Everything is committed and pushed on `m5-trial-run` (`0eb4034`).
**666 tests, ruff clean.** R115 is the only unanswered request; the
instruction log continues from R149.

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

## START HERE — the P1 first

**Do not run unattended until review finding 001 is fixed.** The combat
repositioning added at the very end of the session (after the last live
run, so it has NEVER executed against the game) can drift the player out
of `engage_radius` while `clear_radius` still wants those monsters dead.
`combat.engage` then returns None forever, the step reports
`waiting=True`, and `waiting` suppresses the idle watchdog — a permanent
hang with the alarm for hangs switched off on that exact path.

The five findings are in
[docs/reviews/2026-07-31-m5-stage-b/](../../reviews/2026-07-31-m5-stage-b/summary.md):

1. **001 (P1)** repositioning can strand the clearance — fix before any
   unattended run.
2. **002 (P2)** the 0.4 s cast settle blocks the tick the survival ladder
   needs. Prefer waiting on the EFFECT (bone armor's stat is readable and
   T46 characterised it) over a fixed sleep.
3. **003 (P2)** town waits re-read every inventory socket at 10 Hz —
   ~1200 stat reads per potion moved. Likely cause of the "dithering" the
   `poll_s` change was meant to fix, and that change made it worse.
4. **004/005 (P3)** runner catch-all can't tell a bug from a bad moment;
   the trace printer reaches into `engine._executor`.

An **ADR candidate** is recorded and worth writing when 001 is resolved:
*when may a wait suppress the never-idle watchdog?* `waiting` was added
for a good reason and became the reason a hang is invisible.

## Then: the unexplained skill-switch failure

`SkillSwitchFailed` recurred in **three** separate runs on three
different skill pairs (95←83, 68←83, 68←95) — the right slot stays on
whatever was last selected. It is survivable now (absorbed like a refused
send) but every failed desecrate is a thinner revive wall.

Two live theories, neither confirmed:

- the hotkey bindings differ from `config/necro.toml` — **`drills/t47_hotkey_audit.py` is written and unrun**; it presses F1-F6 and
  reads back what each selects, which settles it in ~30 seconds;
- the user's own (from manual play): bone armor has a slow cast animation
  and following commands interrupt it, so the cast is spent and the buff
  never lands — which from the bot's side looks exactly like a recast
  loop. This is what finding 002's settle was trying to address.

## Open user requests

- **R115** — should `IdleBail` share the cycle's chicken counter? Now the
  same shape as `StashFullHalt`/`TownStepHalt`; decide them together.
- The user asked for a wider **patrol** around the waypoint ("2 screens in
  each direction"). Note radius 50 already IS ~2 screens; the reason the
  bot does not roam is that `clear_radius` has no patrol — it stands and
  waits for the radius to read clear, and perception (80) exceeds the
  radius, so it can verify from a standstill. A real patrol (visit sample
  points so perception sweeps the area) is a **new feature** and P6's
  phase file puts features out of scope — needs a decision.
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
