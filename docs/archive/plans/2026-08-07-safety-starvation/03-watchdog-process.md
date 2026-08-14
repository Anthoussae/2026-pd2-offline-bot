# P3 — the watchdog process

**Size:** `sm`. **Depends on:** nothing (can be written in parallel with
P2; P4 integrates it). **Review gate:** none. **ADR:** none (P5).

## Scope

A standalone process that watches the character's vitals and presses ESC
when they cross the line — independent of the bot, so a wedged bot
cannot prevent it. This phase builds and unit-tests the process itself.
Bot-side integration is P4; the live canary is P5.

**Out of scope:** `GatedInput`'s latch check, the engine's dead-man
check, launcher changes (all P4).

## Why this exists even though P1/P2 landed

P1/P2 fix the *known* block. The watchdog covers the class: any future
blocking call, a pymem hang, a deadlock, an unhandled exception in the
tick loop, the bot process dying mid-fight. Feasibility, CPU cost and
the two-writer analysis are in
`docs/reviews/2026-08-07-chicken-starvation-death/watchdog-assessment.md`.

## Design — the parts that are already decided

**It presses ESC and nothing else.** Offline SP ESC *pauses* the game
instantly (`safety.py`'s module docstring), so the character is safe the
moment the key lands. It must not drive the leave-game menu:
`cycle.leave_game` is live-verified and keeps its monopoly. The pause
holds until the bot (unblocked by P1's cap) or a human resolves it.

**It sends nothing when HP reads dead.** Mirrors the death latch: the
game is left exactly as the human needs to see it (R27/Q6). Write the
latch file, alert, and stop.

**Its threshold sits 5 points below the bot's** (Q3), read from the same
class config so the two numbers cannot drift. A backstop that fires
first is not a backstop.

**It reuses, never reimplements:** `GameSession`, `read_player`,
`read_area`, `offsets.TOWN_AREAS`, and `MenuInput.press_escape`
(`menuinput.py:141` — guards on foreground alone, and its docstring
already names it "the chicken's first move"). No new perception code and
no second input path.

## Implementation — `pd2bot/watchdog.py` (new)

A `Watchdog` class with everything injected (session, clock, sleep,
press-escape, readers) so the whole state machine is testable with
fakes, exactly like `Navigator` and `SafetyMonitor`.

The loop, ~0.2 s:

1. Read the player. Absent (menus, loading) → heartbeat and continue;
   this is normal and must not be an error.
2. Dead → write the latch with reason `death`, alert, **send nothing**,
   and stop looping.
3. In town and not configured otherwise → heartbeat and continue.
4. Below threshold → **fire**.
5. Heartbeat every iteration, whatever happened.

Firing, and this is the part that needs care:

- Press ESC through `MenuInput.press_escape`.
- **Verify**, do not assume: re-read the UI state and confirm
  `UI_ESCMENU_MAIN` is open. If a blocking panel was open, ESC closed
  *that* instead and the game is not paused — so press again,
  rate-limited (e.g. ≤5 presses, ≥0.3 s apart), and log every attempt.
- Write the latch file **before** the first press, not after: if the
  process dies mid-fire, the bot must still find the latch and know a
  watchdog chicken happened.
- Once paused, stop pressing. Do not click anything.

Files, under `%LOCALAPPDATA%\pd2bot-bridge\` beside the existing cancel
file (`drill.py:80`):

- `watchdog-heartbeat` — touched every loop. Liveness only.
- `watchdog-latch` — written on fire, with JSON: reason, vitals, wall
  clock, pid.

**The stickiness lesson is mandatory here.** The live protocol already
carries a scar about the cancel file: *"the cancel file is sticky —
clear it after use."* A stale latch would silently disarm the bot
forever (P4 makes `GatedInput` honour it). So: the watchdog clears a
stale latch **once at startup**, the latch carries a timestamp, and P4's
consumers treat an old latch as stale rather than as a standing order.
Follow `drill.py`'s `_cleared_stale_cancel` precedent — cleared once per
process, not once per iteration.

A CLI (`python -m pd2bot.watchdog`) with `--threshold`, `--interval`,
`--in-town`, and a `--probe` mode that reads and prints vitals **without
arming**, so the operator can sanity-check it against a live client with
zero risk. Announce loudly on start what it is watching and at what
threshold — an operator must be able to tell at a glance that the safety
layer is actually running.

Priority: set `HIGH_PRIORITY_CLASS` best-effort; never fail if it cannot.
It runs elevated, like everything that sends input (UIPI).

## Tests (`tests/test_watchdog.py`, new)

- Fires exactly once when HP crosses the threshold; does not re-fire
  while paused.
- **Sends nothing when the player reads dead** — the most important
  assertion in the file.
- Retries when the first ESC did not open the ESC menu; stops at the
  rate limit; every attempt is recorded.
- Absent player / town / above threshold: no press, heartbeat still
  written.
- Heartbeat advances every iteration, including on the death path up to
  the stop.
- A stale latch from a previous session is cleared at startup and does
  not suppress this session's firing.
- The latch is written before the press (simulate a press that raises).

## Conventions

- Injected clock/sleep; no test touches the real clock, filesystem
  outside `tmp_path`, or the game.
- No bare `except Exception` around the fire path.
- `ruff` clean.

## Agent reminders

- Do not commit unless asked.
- Do not add menu clicking, leave-game logic, or any recovery behaviour.
- Do not wire it into the bot in this phase.
- Stop and report if `MenuInput` turns out to need changes to be usable
  from a second process — that is a design finding.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

A watchdog process that can be started by hand, prints what it is
guarding, presses ESC on a low-HP verdict, verifies the pause, writes a
latch and a heartbeat, and sends nothing at all when the character is
dead — all pinned by offline tests.

---

## Implementation Result (2026-08-07) — DONE

`pd2bot/watchdog.py` (new, ~380 lines) plus `tests/test_watchdog.py`
(29 tests). Everything injected — session, clock, wall clock, sleep,
readers, the ESC press, both file paths — so the whole state machine is
tested without a game, the same discipline `SafetyMonitor` and
`Navigator` are under.

Built as specified, with nothing added: it presses ESC and only ESC,
sends **nothing** when HP or mode reads dead, exempts town unless told
otherwise, verifies the pause via `UI_ESCMENU_MAIN` rather than assuming
it, retries a swallowed ESC up to 5 times at 0.3 s spacing, and gives up
loudly rather than pressing for ever. `MenuInput.press_escape` is reused
verbatim — no second input path was written.

The latch is written **before** the first press, so a watchdog that dies
mid-fire still leaves the bot the news; a test simulates exactly that by
making the press raise.

File channel: `watchdog-heartbeat` and `watchdog-latch` beside the
existing drill cancel file, both carrying **wall-clock** stamps (a
monotonic clock means nothing across a process boundary) and both with
staleness rules — 3 s for the heartbeat, 300 s for the latch. A stale
latch is cleared once at construction, following `drill.py`'s
`_cleared_stale_cancel` precedent, and a test pins that this does not
wipe the latch the watchdog itself just wrote.

CLI: `--probe` (reads and prints vitals, arms nothing), `--threshold`,
`--mana`, `--interval`, `--in-town`. Default threshold is 5 points under
the bot's own, read from the same class config; an unreadable config
falls back to a safe default rather than leaving it unarmed.
