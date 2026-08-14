# Death by chicken-starvation: a blocking walk_to starved the safety monitor

**2026-08-07. T71 acceptance run (chicken 35). The character DIED in
Tower Cellar Level 4 during the descent — the chicken never fired.**
This is a **safety-critical** finding: the death latch worked (it halted
after death, game untouched), but the *chicken* (leave-game before HP 0)
was starved and never got the chance.

Preserved evidence in this directory (the run log lives under gitignored
`logs/`, so it is copied here): `events.jsonl` (the full run event log,
2259 events), `narrative.log`, `run.json`. Read the log with:

    ~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog docs/reviews/2026-08-07-chicken-starvation-death

## Root cause — the trace is unambiguous

The engine **froze inside a single blocking `walk_to` for 24 seconds**,
and the `SafetyMonitor` (chicken + death latch) only runs at the **top of
each tick** — so while the engine was blocked it could not re-read HP and
could not chicken.

From the event log, the final ticks:

| tick | t+ | dur | what |
|---|---|---|---|
| 711 | 635.7 | 0.7 s | traverse: walking to the exit, **29 hostiles**, hp 100% |
| 712 | 636.8 | 0.9 s | traverse: walking to the exit, 29 hostiles, hp 100% |
| **713** | **661.2** | **24.19 s** | `timing.step = 24.14 s` — `walk_to` **stuck 3 subtiles from the Cellar 4 exit** (at (12642,9581), target (12639,9578)), spinning "5 plan cycles without progress… shaking loose… re-click… stuck", then `NavigationError` |
| — | 664.4 | 3.0 s | first tick after the block: **hp=0, dead** — latch fires |

- Tick 713's snapshot was taken at its *start* (~t+637), reading **100%
  HP**. The engine then blocked for 24 s inside `walk_to`. During that
  window the character was killed by the 26–29 hostile pack, but **no new
  snapshot was taken and the monitor never ran**, so the logged HP stays
  frozen at 1316 until the block ends.
- Somewhere in those 24 s the real HP crossed the 35% chicken line and a
  chicken *should* have fired — but the engine was stuck. The operator
  confirmed it by eye: "ample time to press ESC."

## Why it got stuck

Cellar 4 this seed had a **dense pack (26–29 hostiles)** blocking the
exit. The traverse step (brisk posture) tried to `walk_to` the exit; the
pack blocked/pushed the character 3 subtiles short; and `walk_to`'s own
retry budget (re-plan → shake-loose → re-click) **spun for 24 seconds**
before giving up — all of it blocking the tick loop.

## The architectural gap

**Nothing may starve the `SafetyMonitor`.** The engine's whole design —
capped legs so the reflex ladder and monitor run between them — is
defeated when `walk_to` blocks for its full give-up budget instead of
returning quickly. A single blocked `walk_to` = no chicken for up to
~24 s. This is the invariant that broke.

**Not caused by the pickup changes** (draw-order / diagnosis / the item
registry, P3-P5): the block was in `walk_to` to the *exit* during
traverse, unrelated to pickup. A pre-existing gap this run exposed.

## The fix — a DECISION is owed (safety-critical, CLAUDE.md gate)

Options put to the operator (2026-08-07), not yet chosen:

1. **Poll safety inside `walk_to`** — inject the HP/death check into
   `walk_to`'s blocking poll loop, so a low-HP or death condition raises
   `ChickenExit`/`DeathHalt` from within the walk and interrupts it. Most
   direct; the monitor effectively runs even during a blocking walk.
2. **Hard-cap `walk_to`'s block** — return to the tick loop after ~1-2 s
   regardless of progress. Enforces "capped legs" at the walk layer, but
   the monitor still cannot fire *during* a leg.
3. **Both** — cap the budget AND poll safety. Most robust.
4. **Investigate more first** — why traverse got stuck at the exit with
   29 hostiles, whether `walk_to` already has a safety hook, the merc/
   revive interaction.

The operator also raised a **process-level** idea worth weighing against
these: a separate, independent **chicken process** polling HP every
~0.2 s and pressing ESC when HP < 35%, with priority over the bot loop —
so no in-process block can ever starve it. See the startup prompt.

## Status

Acceptance battery **HALTED** pending the safety fix. Do not re-run the
Countess (or any input-sending run) until the monitor can no longer be
starved. The character was rescued by the operator (alive, Cellar 4);
the bot process exited and the latch is engaged.
