# Notes — the chicken-starvation safety fix

Planning started 2026-08-07, immediately after the R228 decision
(**option b**: the in-process fix lands first, the watchdog process is
built as an independent second layer before the unattended battery).

Evidence this plan exists to answer:
`docs/reviews/2026-08-07-chicken-starvation-death/` — `summary.md` (the
death, root-caused from the event log) and `watchdog-assessment.md` (the
feasibility assessment of the operator's separate-process idea).

## The goal, stated as an invariant

**Nothing may starve the safety monitor.** Concretely: from the moment
the character's HP crosses the chicken line, a chicken must be initiated
within a bounded, small number of seconds — whatever the engine happens
to be doing, including blocking inside a walk, and including the engine
being wedged entirely.

Two independent mechanisms, because the invariant is absolute:

- **Track A (in-process)** — `walk_to` polls safety and is wall-clock
  capped, so a blocked walk both interrupts itself and returns control.
- **Track B (out-of-process)** — a watchdog process presses ESC on its
  own, so even a fully wedged bot cannot prevent the pause.

## Current state, read from the code

### The blocking sites in `walk_to` (`pd2bot/navigate.py`)

`walk_to` → `_walk_to` outer loop, up to `MAX_FAILURES = 5` no-progress
plan cycles. Each cycle walks every waypoint of a fresh plan. Nothing
caps the *call*, which is the hole — 24 s is well within its budget:

| site | line | blocking behaviour |
|---|---|---|
| `_walk_one_waypoint` poll loop | `navigate.py:356` | `_sleep(POLL_SECONDS=0.1)` per iteration, up to `WAYPOINT_TIMEOUT = 20 s` **per waypoint** |
| `_click` UI-wait loop | `navigate.py:194` | retries a refused click for up to `UI_WAIT_TIMEOUT = 10 s`, `0.1 s` poll |
| `_shake_loose` | `navigate.py:511` | one flat `_sleep(STUCK_SECONDS = 1.5)` |

Good news for the fix: `Navigator.__init__` already injects `clock` and
`sleep` (`navigate.py:143-144`) and the module docstring states all
timing is injectable so the state machine is testable against a scripted
fake. A `safety_poll` callable fits the existing shape exactly, and the
starvation regression test needs no game.

### THE FINDING that shapes Track A: broad `except Exception` on the path

`ChickenExit` and `DeathHalt` are `RuntimeError` subclasses
(`safety.py:39,43`). Today the monitor raises them at the *top* of a
tick, where nothing is wrapping them. The moment we raise them from
*inside* `walk_to`, they must travel up through code that catches
broadly, and several handlers on that exact path would **swallow the
chicken**:

- `navigate._shake_loose` — `except Exception  # unstick must not raise`
  (`navigate.py:495`, `507`)
- `navigate._safe_click_point` — the audit's
  `except Exception  # measurement must never break a walk`
  (`navigate.py:213`)
- `town.py:672` — `except Exception  # recovery must not raise`
- `town.py:2381` — `except Exception as exc` around a station
- `execute.py` / `engine.py` have several more (instrumentation, frame
  reads) that are near, if not directly on, the path

Every one of those comments is correct about its own concern and wrong
about this one. Auditing them individually is exactly the kind of fix
that holds until someone adds handler number six.

**So the interrupt must be uncatchable by `except Exception`.** The
recommendation is a distinct `SafetyInterrupt(BaseException)` raised by
the in-walk poll, converted to the real `ChickenExit`/`DeathHalt` at the
engine's tick boundary — the same place the monitor raises them today,
so everything downstream (the cycle's live-verified handlers) is
untouched. Blast radius: one new class, one conversion site.

Rejected alternative: re-basing `ChickenExit` itself on `BaseException`.
It has four subclasses used for ordinary, non-vitals failures
(`IdleBail`, `StopRequested`, `TownStepFailed`, `RunFailed`) and making
routine control flow uncatchable is a much larger blast radius for no
extra safety. (Checked: every production catch of these is by explicit
type — `cycle.py:394,424`, `runner.py:222,243` — so either choice
*works*; the narrow one is the one we can reason about.)

### The abort channel is starved by the same block

`_should_stop` is polled once per tick (`engine.py:284,655`). During the
24 s block the operator's own abort could not be heard either. The
in-walk poll should service it too — same call site, same cost. This is
part of why the watchdog alone is not sufficient.

### What the watchdog needs, and what already exists for it

- **The ESC primitive already exists and is exactly right.**
  `MenuInput.press_escape` (`menuinput.py:141`) guards on **foreground
  only**, with the docstring "This is the chicken's first move, and it
  must work while `can_act()` is still true." A watchdog can reuse it
  verbatim.
- **Perception is reusable as-is**: `GameSession`, `read_player`,
  `read_area` — the watchdog imports `pd2bot` from the same venv and
  adds no new perception code.
- **The file-channel pattern already exists**: `drill.py:80` puts the
  cancel file at `%LOCALAPPDATA%\pd2bot-bridge\drill-cancel`, with
  `request_cancel` / `clear_cancel` helpers and a documented
  stickiness hazard ("the cancel file is sticky — clear it after use",
  live protocol). The watchdog's latch and heartbeat files follow the
  same shape *and must learn that lesson*: a stale latch that silently
  disarms the bot forever is the failure mode to design against.
- **Elevation**: same as all input (UIPI) — the watchdog runs elevated,
  launched from the elevated context the bridge already provides.

### The engine/watchdog interaction, traced

If the watchdog presses ESC, on the bot's next tick:

1. `_monitor.tick()` runs **first** (`engine.py:654`) — so if the
   character is dead, the death latch wins and no input follows. Correct
   by construction, unchanged.
2. Otherwise `_operator_took_the_controls` (`engine.py:364`) sees
   `UI_ESCMENU_MAIN` open and raises `StopRequested`, which **is a
   `ChickenExit` subclass**, so the cycle leaves the game via
   `leave_game` — `MenuInput`, not `GatedInput`.

That outcome is *right* (the run ends, the game is left cleanly) but the
narration would lie: "the operator pressed ESC — standing down". The
kill switch already correlates against `_bot_escape_at`
(`engine.py:385`); it should consult the watchdog latch the same way and
say *"the watchdog chickened"*.

Note the useful consequence: a `GatedInput` latch blocks **world**
input while leaving the **menu** path open, so the bot can still
complete the leave it should complete. That separation is a feature, not
an accident, and the plan keeps it.

### How the two tracks compose

The watchdog buys the pause *instantly* (offline SP: ESC pauses the
game, so the character is safe the moment the key lands — `safety.py`'s
own docstring). Track A's cap then returns the engine to its tick loop
within ~2 s, where the monitor sees low HP and performs the proper,
live-verified leave. Neither track needs the other to be correct, and
together they cover both "the engine is slow" and "the engine is gone".

## Decisions taken (with reasoning, so they can be argued with)

1. **`SafetyInterrupt(BaseException)`**, converted at the engine
   boundary — see the finding above.
2. **The watchdog presses ESC and nothing else.** No menu clicks: a
   second process driving the leave-game menu while the bot also owns
   input is where real two-writer complexity lives, and the pause has
   already saved the character. `cycle.leave_game` keeps its monopoly.
3. **The watchdog sends nothing when HP reads dead** — mirrors the death
   latch. A dead character's game is left exactly as the human needs to
   see it (R27/Q6).
4. **Dead-man's switch, defaulting to ON for unattended runs.** A
   watchdog that is silently not running is a safety layer that silently
   does not exist. The engine checks the heartbeat at tick top.
5. **The cap is on the whole `walk_to` call**, not per waypoint — the
   per-waypoint cap already exists (20 s) and is what let five plan
   cycles add up.

## Open questions for the operator

Batched into the confirmation table in chat (Q1–Q5): the interrupt base
class, the cap value, the watchdog poll interval and threshold source,
the dead-man default, and whether the watchdog ships as its own CLI or
inside the existing launcher.

## Future work / out of scope

- The *reason* traverse got stuck at the Cellar 4 exit with 29 hostiles
  (the pack blocking the door). This plan makes the block survivable; it
  does not make the navigator better at crowded doorways. That is a
  navigation-quality item and belongs with the known navigator
  oscillation in `performance-notes.md`.
- The ~9-minute descent / speed pass — already deferred by M6's scope.
- Corpse retrieval and death recovery — still deliberately absent.
