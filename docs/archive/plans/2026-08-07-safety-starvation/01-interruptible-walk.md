# P1 — `walk_to` becomes interruptible and capped

**Size:** `sm`. **Depends on:** nothing. **Review gate:** none.
**ADR:** none for this phase (the ADR is written at P5, covering both
tracks).

## Scope

Make a blocking `walk_to` unable to starve safety, in two independent
ways: it **polls** a caller-supplied safety check often enough to
interrupt itself, and it **returns** to its caller within a wall-clock
cap no matter what. Offline only — no game, no wiring (that is P2).

**Out of scope:** wiring the real monitor in, telemetry, the engine's
conversion of the interrupt, anything to do with the watchdog process.

## Background — read this before editing

The death: the engine blocked inside one `walk_to` for 24 s while a pack
killed the character; the monitor only runs at the top of a tick. See
`docs/reviews/2026-08-07-chicken-starvation-death/summary.md`.

`walk_to` (`pd2bot/navigate.py:390`) has three blocking sites and no cap
on the call as a whole:

| site | line | budget |
|---|---|---|
| `_walk_one_waypoint` poll loop | `356` | `_sleep(POLL_SECONDS=0.1)` per iteration, `WAYPOINT_TIMEOUT = 20 s` per waypoint |
| `_click` UI-wait loop | `194` | up to `UI_WAIT_TIMEOUT = 10 s` |
| `_shake_loose` | `511` | one `_sleep(STUCK_SECONDS = 1.5)` |

The outer `_walk_to` loop runs up to `MAX_FAILURES = 5` no-progress plan
cycles, each walking every waypoint of a fresh plan. That is how five
budgets became 24 seconds.

## Implementation

### 1. `SafetyInterrupt` in `pd2bot/safety.py`

```python
class SafetyInterrupt(BaseException):
    """A safety condition detected DURING a blocking call.

    Derives from BaseException on purpose, and it is the whole point of
    the class: the path out of a blocking walk runs through several
    broad `except Exception` handlers -- the navigator's own unstick and
    click-audit guards, the town layer's recovery and station wrappers
    -- every one of them correct about its own concern and every one of
    them able to swallow a chicken. A safety signal that any handler can
    absorb is not a safety signal.

    It is NOT the type the rest of the bot handles: the engine converts
    it back into the real ChickenExit/DeathHalt at the tick boundary, so
    the cycle's live-verified handling is untouched.
    """
```

Carry the reason and the vitals on it (`reason`, `hp`, `max_hp`, `pct`)
so the conversion at P2 can build an honest `ChickenExit` message and
the log can record what was seen mid-walk.

Do **not** re-base `ChickenExit` — it has four non-vitals subclasses
(`IdleBail`, `StopRequested`, `TownStepFailed`, `RunFailed`) and making
routine control flow uncatchable is a much larger blast radius (Q1, and
the reasoning is in `notes.md`).

### 2. `SafetyMonitor.poll()` in `pd2bot/safety.py`

A method that runs the same checks as `tick()` but raises
`SafetyInterrupt` instead of `ChickenExit`/`DeathHalt`, and is
**rate-limited internally** (default 0.2 s) so callers can invoke it in
a 0.1 s poll loop without doubling the memory reads.

Refactor honestly: `tick()` and `poll()` must share one evaluation, or
they will drift and only one of them will be the one that matters.
Suggested shape — a private `_evaluate()` returning a verdict
(`None` / death / chicken-with-reason), with `tick()` and `poll()` as
the two raisers over it. The death latch must set on either path.

### 3. Navigator changes (`pd2bot/navigate.py`)

Constructor gains two injected parameters, matching the existing
`clock`/`sleep` style:

```python
safety_poll: Callable[[], None] | None = None,   # raises SafetyInterrupt
walk_budget_s: float | None = WALK_BUDGET_SECONDS,  # None disables the cap
```

`WALK_BUDGET_SECONDS = 2.0` as a module constant with a comment saying
what it is for (the reflex ladder's cadence, not safety latency — safety
is the poll's job).

Call the poll:

- every iteration of `_walk_one_waypoint`'s loop, **immediately after
  `self._sleep(POLL_SECONDS)`**;
- every iteration of `_click`'s UI-wait loop;
- in `_shake_loose`, around its sleep — split the 1.5 s sleep into poll
  intervals rather than sleeping through it blind.

**Placement rule, and it is the load-bearing detail of this phase:** the
poll must never be called from inside a `try` that catches broadly.
`_shake_loose` wraps its grid read in `except Exception` (`navigate.py:495`,
`507`) and `_safe_click_point` wraps the audit the same way
(`navigate.py:213`). `SafetyInterrupt` derives from `BaseException` so
those cannot catch it, but do not rely on that alone — keep the call
sites outside the guards anyway, so the code reads correctly to the next
person and stays correct if the type ever changes.

The cap: record `started` (already present at `_walk_to`'s top) and
check it at the top of each plan cycle **and** inside
`_walk_one_waypoint`'s loop. On expiry, return the `WalkResult` with
`arrived_at` set to the real position — do **not** raise. Add
`capped: bool = False` to `WalkResult` and set it, plus a `result.log`
line saying how long was spent and how far short it stopped.

Returning short is already this codebase's normal outcome and is
documented as such (`_walk_one_waypoint`'s docstring, and the
`_blocked_by_avoidance` early return): every caller re-checks distance.
That is why the cap is safe to add without touching callers.

## Tests (`tests/test_navigate.py`, `tests/test_safety.py`)

The existing harness is exactly right for this — `World`/`Sim`/
`FakeInput` at the top of `test_navigate.py`, with virtual time advanced
only inside `sleep`. Add:

1. **The starvation regression test.** A world that cannot progress
   (`wall_x`, target beyond it) plus a falling-HP fake monitor; assert
   `SafetyInterrupt` escapes `walk_to` within a small number of
   simulated seconds of the threshold being crossed. **Verify it fails
   without the fix** — comment the poll out, watch it fail, put it back.
   Say so in the test's docstring so the next person does not have to
   re-derive that it is a real test.
2. **The interrupt survives a broad handler.** Make the injected grid
   provider raise inside `_shake_loose`'s guarded read and the audit
   raise inside `_safe_click_point`, and assert the interrupt still
   escapes. This is the test that pins Q1's reasoning.
3. **The cap.** A stuck world with no safety poll at all returns a
   `WalkResult` with `capped=True` inside the budget, rather than
   spending the full `MAX_FAILURES` ladder.
4. **The cap does not fire on a healthy walk** — the existing
   `test_walks_to_target` must still pass unchanged, and add an explicit
   assertion that `capped is False` on a normal arrival.
5. **`poll()` and `tick()` agree**: same vitals, same verdict, different
   exception type; the death latch sets from either.
6. **`poll()` is rate-limited**: called 10× in a row, it reads the
   player fewer times than that.

## Conventions

- Keep constants at module top with a comment explaining the *measured*
  or *reasoned* basis — that is the house style throughout `navigate.py`.
- All timing stays injectable; no test may touch the clock or the game.
- Comments explain *why*, and prefer stating a constraint over narrating
  the code.
- `ruff` clean; no suppressions added.

## Agent reminders

- Do not commit unless asked.
- Do not expand scope — no wiring, no telemetry, no watchdog here.
- Do not suppress warnings or disable tests.
- Stop and report if the `tick()`/`poll()` refactor turns out to need
  changes in `cycle.py` or `runner.py`; that would mean the shared-
  evaluation shape is wrong and is worth a decision.
- Report what changed, what was validated, and any deviations.

## Validation

```bash
~/.venvs/pd2bot/Scripts/python.exe -m pytest -q
```

```bash
~/.venvs/pd2bot/Scripts/python.exe -m ruff check .
```

## Definition of done

`walk_to` raises `SafetyInterrupt` promptly when its poll says so, is
capped when nothing says anything, still walks normally when nothing is
wrong, and the regression test that reproduces the death's shape is
green — and was demonstrated red without the fix.

---

## Implementation Result (2026-08-07) — DONE

`SafetyInterrupt(BaseException)` and `Verdict` added to `safety.py`;
`tick()` and `poll()` now share one `_evaluate()`, so the thresholds
cannot drift and the death latch sets from either. `poll()` is
rate-limited by `SafetyConfig.poll_interval_s` (0.2 s).

`Navigator` takes `safety_poll` and `walk_budget_s`
(`WALK_BUDGET_SECONDS = 2.0`). Polls at **four** sites, all outside the
broad guards: the waypoint loop, the UI-wait loop in `_click`,
`_shake_loose`'s settle (its flat 1.5 s sleep became `_wait`, which
sleeps in poll-sized pieces), and the budget check.

**Red demonstrated as a permanent test, not a comment.**
`test_a_blocked_walk_reaches_the_full_giveup_ladder` asserts the pre-fix
timing directly: the same hopeless walk with no poll spends **>10 s**
unwatched. Measured in the same harness: **21.8 s**, against the real
death's 24 s — the scenario reproduces.

### Two deviations, both load-bearing

1. **The give-up ladder had to be carried across calls.** The cap
   returns before the no-progress ladder can finish, so a hopeless
   target would be retried for ever: every call capped, no call ever
   raising `NavigationError`. Callers with their own per-target budgets
   (the patrol, pickup) would cope; **traverse would not, and it was
   traverse that died.** So the navigator keeps `_stall_goal` /
   `_stall_count` / `_stall_best` and raises the same error after the
   same number of fruitless attempts — just spread across calls, with
   the tick loop running between them. Four tests cover it, including
   progress resetting the ladder and a new destination clearing it.
2. **The budget also had to bound `_click`.** Waiting out a blocking
   panel is capped at `UI_WAIT_TIMEOUT = 10 s` — five times the walk
   budget. An operator pressing ESC opens exactly such a panel, and the
   engine cannot notice they took the controls while the walk sits in
   there. `_click` now returns un-clicked on budget expiry, which is
   safe (nothing was sent) and lands in the caller's own budget check.

### Validation

1080 tests pass (from 1048), `ruff` clean. The test helper in
`test_navigate.py` defaults `walk_budget_s=None` so the pre-existing
ladder tests keep testing the ladder; the cap has its own tests.
