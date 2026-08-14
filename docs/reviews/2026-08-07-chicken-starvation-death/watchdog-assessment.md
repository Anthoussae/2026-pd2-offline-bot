# Assessment: a separate chicken-watchdog process (operator's idea, R228)

2026-08-07. The operator asked whether the chicken could live in its own
process — polling HP every ~0.2 s and pressing ESC the moment it crosses
the line, independent of the bot's tick loop, so no in-process block can
ever starve it. Assessed here against the in-process options (poll
safety inside `walk_to` / hard-cap its block), so the R228 decision has
its reasoning on the record.

## Verdict in one paragraph

The watchdog process is **feasible, cheap to run, and architecturally
sound as a second layer** — but it is not a substitute for making
`walk_to` interruptible, because the same 24 s block that starved the
chicken also starves the operator's abort channel and every other
per-tick duty, and a watchdog fixes none of that. Recommended: the
in-process fix first (small, unit-testable offline, direct), the
watchdog as defense-in-depth built before the unattended battery.

## Feasibility — yes on every axis the operator asked about

- **Multiple Python processes reading the game: routine.** pymem opens
  its own read handle; any number of processes can hold read handles to
  one target. This project already runs multi-process against the game
  every session (the elevated bridge). The watchdog can import `pd2bot`
  from the same venv and reuse `GameSession`/`read_player` verbatim —
  no new perception code.
- **CPU: a non-issue.** A 0.2 s poll is 5 wakes/second doing a handful
  of `ReadProcessMemory` calls (HP, mode, area) — microseconds of work
  per wake, well under 0.1 % of one core. The bot process itself sleeps
  most of every tick. Two Python processes beside a 2000-era game on
  this machine is nothing.
- **"Privilege over all other processes":** the independence the
  operator wants comes from *being a separate process* — the bot's GIL,
  blocking calls, and GC pauses cannot touch it, whatever its priority.
  `HIGH_PRIORITY_CLASS` can be set for good measure; realtime priority
  is unnecessary at 5 Hz.
- **Elevation:** same constraint as all input (UIPI) — the watchdog
  must run elevated, launched from the same elevated context the bot
  already uses.

## What the watchdog should do: press ESC, and only that

Offline SP ESC **pauses the game instantly** — `safety.py`'s own
docstring already leans on this ("the exit is effectively complete the
moment the keypress lands"). So a watchdog that just presses ESC at
HP < threshold has already saved the character. It should NOT attempt
the leave-game menu dance — that is `cycle.leave_game`'s live-verified
territory, and a second process clicking menus while the bot also owns
input is where real two-writer complexity lives. Dumb watchdog: ESC,
latch file, loud alert. The pause holds until a human (or the bot's own
recovery) resolves it.

Two facts make the two-writer risk small and closable:

- `UI_ESCMENU_MAIN` is in `_BLOCKING_PANELS` (`uistate.py:147`), so the
  instant the ESC menu opens, `can_act()` goes false and `GatedInput`
  refuses every bot click *at the moment of sending* (`input.py`'s
  whole design). The blocked bot disarms itself.
- The residual check-then-send race (documented, `input.py:19`) widens
  slightly with a second writer: a bot click already past its guard
  could land in the fresh ESC menu — the M1 incident shape. Closable at
  the same choke point: `GatedInput` also refuses while the watchdog's
  **latch file** exists. One more condition in the one send path.

Failure directions are safe: a spurious ESC merely pauses (worst case
the run dies gracefully — walk stalls → `NavigationError` → chicken);
if HP reads dead the watchdog must send **nothing**, mirroring the
death latch. If a blocking panel is open, ESC closes the panel instead
of pausing — so the watchdog presses, verifies (`UI_ESCMENU_MAIN`
open), and repeats rate-limited until the pause is confirmed.

## The real cost: lifecycle, not polling

A watchdog that is silently not running is a safety layer that silently
does not exist. The design work is the **dead-man's switch**: the
watchdog heartbeats (file mtime suffices); the engine checks the
heartbeat at tick top and **refuses to run** when it is stale. Plus
launcher integration (start/stop with each run) and the latch check in
`GatedInput`. Roughly a day of work, all of it testable offline except
one supervised live canary.

## Why the watchdog alone is not enough

The block that starved the chicken also starved `_should_stop` — the
drill-abort/operator-stop channel, polled once per tick
(`engine.py:284`). During those 24 s the operator could not have
aborted through the bot either. The engine's own contract ("capped legs
so the reflex ladder and monitor run between them") is what broke;
external ESC does not repair it. And the in-process fix is small:
`walk_to`'s wait loops already take injected `_sleep`/`_clock`, so a
`safety_poll` callable (raising `ChickenExit`/`DeathHalt` mid-walk into
the cycle's existing, live-verified handlers) plus a wall-clock cap on
one `walk_to` call are a few dozen lines, fully unit-testable with
fakes — a starvation regression test (walk blocks while HP drops →
chicken fires within a bounded delay) pins it forever. The same in-walk
poll should service the abort channel.

## The layers, priced

| Layer | Protects against | Cost | Validation |
|---|---|---|---|
| In-walk safety poll (option 1) | this exact death; anything `walk_to` does | small | offline fakes + regression test |
| Wall-clock cap on `walk_to` (option 2) | any single walk hogging the loop; restores capped-legs, abort latency | small | offline fakes |
| Watchdog process (operator's idea) | the whole class: any future block, pymem hang, GC pause, deadlock, engine bug | ~a day + lifecycle discipline | offline + one supervised canary |

The three do not compete — they fail independently, which is the point
of defense-in-depth for the one invariant this project has declared
absolute.
