# P4 — bot ↔ watchdog integration

**Size:** `sm`. **Depends on:** P2 and P3. **Review gate:** none.
**ADR:** none (P5).

## Scope

Make the two processes aware of each other in the three ways that
matter: the bot stops sending world input once the watchdog has fired,
the bot refuses to run unattended when the watchdog is not alive, and
the logs tell the truth about which one acted. Plus the launcher change
that makes the watchdog start and stop with a run.

## Implementation

### 1. `GatedInput` honours the latch (`pd2bot/input.py`)

Add the latch to `GatedInput.check()` — the single send path, which
already re-checks every condition at the moment of sending and has "no
bypass flag and no unguarded variant" as a stated design property. A
fresh latch raises `InputRefused`.

**Deliberately `GatedInput` only, not `MenuInput`.** The latch must stop
*world* input while leaving the *menu* path open, so `cycle.leave_game`
can still complete the leave it should complete. Say that in the comment
— the asymmetry is the design, and a later reader will otherwise
"fix" it.

Staleness: a latch older than a threshold (a few minutes) is ignored,
because a stale latch that permanently disarms the bot is its own
outage. Read the timestamp the latch carries (P3); do not trust mtime
alone.

Cost: `check()` runs on every send, so do not stat the file on every
call — cache with a short TTL, or read it on the same cadence the
existing UI reads use. Measure nothing here; just do not add a syscall
per click without thinking about it.

### 2. The dead-man's switch (`pd2bot/behavior/engine.py`, `wiring.py`)

The engine checks the watchdog heartbeat at the top of each tick, beside
the existing stop and kill-switch checks. Stale or absent → refuse to
continue, loudly, with a message that says how to start it.

Per Q4: **required for unattended runs**, with an explicit opt-out for
drills, sims and dry runs. Make the opt-out a named, visible parameter —
never a default that quietly disables the layer. `EngineConfig` is the
natural home; sims and the many drills that build engines bare must keep
working untouched, so the default in code is "not required" and the
*launcher* (below) is what turns it on for real runs.

Check at start too, not only per tick: a run that begins with no
watchdog should never take its first step.

### 3. Honest narration (`engine.py:364`)

`_operator_took_the_controls` sees `UI_ESCMENU_MAIN` open and concludes
a human pressed ESC. After a watchdog fire that is a lie. It already
correlates against `_bot_escape_at` (`engine.py:385`); give it the same
treatment for the watchdog latch, and narrate *"the watchdog chickened
(hp N%)"* instead of *"the operator pressed ESC — standing down"*.

The resulting `StopRequested` → `ChickenExit` → `leave_game` path is the
**correct** outcome and stays: the watchdog's ESC paused the game, and
the bot completing a clean Save-and-Exit is exactly what should follow.
Only the story it tells changes.

Also emit a `watchdog.fired` run-log event on the bot side when the
latch is first observed, so one artifact contains both processes'
version of events.

### 4. Launcher (`tools/live-run.ps1`)

Start the watchdog before the bot and stop it after, in a `finally` so a
crashed run does not leave one running. The script already bakes
absolute paths on purpose (a 2026-08-01 silent failure where a relative
path meant "the run is going" was actually nothing at all) — keep that
discipline.

Turn the dead-man requirement **on** here, since this is the real-run
entry point. If the watchdog fails to start, the run must not start
either; say so on stdout in a way an operator reading the bridge output
cannot miss.

Clear any stale latch at launch — same reasoning as the cancel file, and
the live protocol's existing note about stickiness should be extended to
cover the latch.

## Tests

- `check()` refuses on a fresh latch, allows on a stale one, allows with
  no latch (`tests/test_input.py`).
- `MenuInput` is unaffected by the latch (`tests/test_menuinput.py`) —
  the asymmetry, pinned.
- The engine refuses to tick on a stale/absent heartbeat when required,
  and ticks normally when not required (`tests/test_behavior_engine.py`).
- The kill switch narrates a watchdog fire as a watchdog fire, and an
  operator ESC as an operator ESC (both directions — a test that only
  checks one would pass on a hardcoded string).
- `tests/test_wiring.py`: a bot built for a real run has the dead-man
  check enabled; one built for a drill does not.

## Conventions

- Nothing may weaken `GatedInput`'s existing guard; this only adds.
- Never add a bypass flag.
- `ruff` clean.

## Agent reminders

- Do not commit unless asked.
- Do not change the death latch's no-input-ever rule.
- Do not make the dead-man check default-on for bare engines; sims and
  drills must keep working.
- Stop and report if the latch check turns out to need a bypass for any
  legitimate path — that means the asymmetry above is wrong somewhere.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

A real run starts its own watchdog or does not start; a fired watchdog
stops world input while leaving the clean exit available; and both logs
name the right actor.

---

## Implementation Result (2026-08-07) — DONE

`GatedInput.check()` refuses world input while the latch is fresh,
cached for 0.5 s so a stat is not paid per click. `MenuInput` is
untouched, and a test pins that asymmetry: a watchdog pause must not
leave the bot unable to finish the Save-and-Exit that should follow it.

`EngineConfig.require_watchdog` (default **False** — sims and drills
build engines bare and must keep working) plus `watchdog_alive` /
`watchdog_latch` callables on the engine. When required and the
heartbeat is stale, the engine raises `WatchdogDown` — a `ChickenExit`
subclass with `is_vitals = False`, so the game is LEFT cleanly rather
than abandoned with the character standing in Hell, and it does not feed
the "heal the character" backstop (R115).

`_operator_took_the_controls` now consults the latch and narrates *"the
WATCHDOG chickened (life N%)"* instead of blaming the operator, and
emits `watchdog.fired`. Both directions are tested — a hardcoded string
would pass a test that only checked one.

`tools/live-run.ps1` starts the watchdog, waits 1.5 s for its first
heartbeat, refuses to launch if it exited, passes `--require-watchdog`,
and stops it in a `finally`. It clears a stale latch at launch and
deliberately does **not** clear it afterwards — if the watchdog fired,
the operator needs to find the evidence.

### One deviation, stated plainly

The plan implied the engine's per-tick dead-man check would be the whole
guarantee. It cannot be: raising mid-run leaves the game cleanly, but
the cycle would then create the next game and fail again, spinning
create/leave. The real guarantee is the **launcher's pre-flight**, which
refuses before a game is ever created (`wiring.main`, `--require-watchdog`).
The per-tick check remains as the mid-run backstop. Residual, accepted:
a watchdog that dies *during* a multi-game run ends the current game
cleanly and may cost one wasted create/leave before the operator sees
the message.
