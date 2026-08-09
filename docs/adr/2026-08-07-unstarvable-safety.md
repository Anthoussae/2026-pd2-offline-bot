# Safety must not be starvable: an in-process interrupt and an out-of-process watchdog

Date: 2026-08-07 (M6 P4 → the safety-starvation plan)
Status: **accepted** (2026-08-07) — the acceptance condition is met.
T80 run 2 and T81 both PASSED against the live client, unattended
(`drills/safety_canary.py`, 5/5 rounds): a `SafetyInterrupt` raised from
inside a walk that had already moved 12 subtiles, and a separate
watchdog process — with no bot running at all — pressing ESC and pausing
the game, its latch disarming world input while leaving the menu path
open, and its stale heartbeat stopping an engine that required it.

## Context

On 2026-08-07 the character **died in Tower Cellar 4** during the M6 P5
acceptance run, and the run event log named the cause without ambiguity:

- The engine blocked inside a single `walk_to` for **24.19 seconds**,
  stuck 3 subtiles from the exit inside a pack of 26–29 hostiles.
- The `SafetyMonitor` ran only at the **top of each tick**. Its last
  reading was taken before the block, at 100 % HP, and no reading was
  taken again until the character was already dead.
- The chicken threshold (35 %) was crossed somewhere inside those 24
  seconds and nothing was there to notice. The operator, watching, had
  "ample time to press ESC."

The death latch worked exactly as designed — the bot halted and sent no
further input. What failed was the *chicken*: the reflex whose entire
purpose is to act before HP reaches zero was **starved**.

Full analysis and the preserved run log:
`docs/reviews/2026-08-07-chicken-starvation-death/`.

This was not a bug in the monitor, the navigator, or the pickup work
that happened to be in flight. It was a structural gap: the engine's
"capped legs" contract — short legs, with the reflex ladder and the
monitor running between them — was written into
`docs/adr/2026-07-29-behavior-architecture.md` and never enforced at the
walk layer. `walk_to` had a per-waypoint cap (20 s) and a plan-cycle
budget (5), and nothing at all capping the *call*, so the two budgets
multiplied.

## Decision

**Safety is defended twice, by mechanisms that fail independently.**

### 1. In-process: a walk interrupts itself, and returns on a clock

`Navigator` takes a `safety_poll` callable and calls it from every loop
in which it waits — the waypoint poll, the click's UI wait, and the
shake-loose settle (whose flat 1.5 s sleep became sliced). It also takes
a wall-clock budget (`WALK_BUDGET_SECONDS = 2.0`) that returns control
to the tick loop whatever has or has not been achieved.

The poll raises **`SafetyInterrupt`, which derives from
`BaseException`** — and that is the load-bearing detail. The path from a
blocking walk back to the tick loop passes through at least four broad
`except Exception` handlers: the navigator's own unstick guard and click
audit, and the town layer's recovery and station wrappers. Each is
correct about its own concern; each would have swallowed a chicken. A
safety signal any handler can absorb is not a safety signal.

The engine converts it back to `ChickenExit` / `DeathHalt` /
`StopRequested` at one boundary, so every downstream consumer — the
cycle's leave-and-continue path, the death latch's no-input-ever rule —
is reached by exactly the types it was written and live-verified
against.

The operator's abort travels the same channel, because the same 24
seconds starved it too: `_should_stop` was polled once per tick, so
during the block there was no way to stop the bot either.

### 2. Out-of-process: a watchdog that presses ESC

`pd2bot/watchdog.py` is a separate process polling vitals at 0.2 s. When
they cross, it presses ESC — which in offline single-player *pauses the
game instantly*, so the character is safe the moment the key lands.

Being a separate process is the entire mechanism: the bot's GIL, its
blocking calls and its garbage collector cannot reach across a process
boundary. A thread could not provide this, and process priority is not
what provides it either.

Constraints, all deliberate:

- **It presses ESC and nothing else.** `cycle.leave_game` keeps its
  monopoly on the menu dance; two processes clicking menus at one client
  is the two-writer problem worth not having. The pause holds until the
  bot or a human resolves it.
- **It sends nothing when the character is dead** — the death latch's
  rule (R27/Q6), unchanged.
- **Its threshold sits 5 points below the bot's**, read from the same
  class config. A backstop that fires first is not a backstop.
- **It verifies rather than assumes**: if a blocking panel was open, ESC
  closed *that* and the game is not paused, so it presses again, bounded
  and logged.
- **A dead-man's switch**, because a watchdog that is silently not
  running is a safety layer that silently does not exist. It heartbeats;
  the launcher refuses to start a run without one, and the engine
  refuses to keep ticking when the heartbeat goes stale.

The bot's single send path (`GatedInput.check()`) refuses world input
while the latch is fresh — **but `MenuInput` does not**, so the clean
Save-and-Exit that should follow a watchdog pause remains available.
That asymmetry is the design.

## Alternatives considered

**In-process only.** Cheaper and it fixes the death that happened. But
it can only defend against blocks it is threaded through: a pymem hang,
a deadlock, an unhandled exception in the tick loop, or the bot process
dying mid-fight are all unreachable from inside the process they happen
to. Rejected as insufficient *alone*; it is layer one.

**Watchdog only.** Rejected: the same block also starves the reflex
ladder (potions, bone armor — the things that prevent the chicken being
needed) and the abort channel. An external ESC repairs none of that, and
the engine's own capped-legs contract would stay broken.

**Re-basing `ChickenExit` itself on `BaseException`.** It would work —
every production catch of these types is by explicit type. Rejected
because `ChickenExit` has four subclasses used for ordinary, non-vitals
control flow (`IdleBail`, `StopRequested`, `TownStepFailed`,
`RunFailed`), and making routine failure handling uncatchable is a far
larger blast radius for no additional safety. A narrow type converted at
one boundary is the version we can reason about.

**Making the monitor a thread inside the bot.** Rejected: it shares the
GIL and the process with the thing it is watching, so it dies with it
and blocks with it. It would look like a safety layer without being one.

## Consequences

- **A second elevated process in every real run**, with a lifecycle to
  keep honest. `tools/live-run.ps1` starts it, waits for its first
  heartbeat, refuses to launch the bot without it, and stops it in a
  `finally`.
- **Two new file channels**, both under the bridge directory, both
  carrying wall-clock timestamps (monotonic clocks are meaningless
  across processes) and both with **staleness rules**. This is not
  optional bookkeeping: the drill cancel file already taught this
  project that a sticky file nobody clears becomes a bot that cannot act
  and cannot say why.
- **A standing rule, and this is the part future work will trip over:
  any new blocking call must take the poll.** A loop that waits without
  asking is a new starvation window. `navigate.py`'s `_wait` exists as
  the pattern to copy — sleep in poll-sized pieces, never flat.
- **Capped walks are now normal**, and callers must keep re-checking
  distance (they already do — "landing short is the correct outcome"
  predates this). `walk_to`'s give-up ladder therefore counts *across*
  calls, so "this cannot be walked" is still eventually said.
- **Measured cost of the fix**: worst-case latency from HP crossing the
  line to `ChickenExit` being raised is **0.100 s** (mean 0.055 s), against
  **21.8 s** for the same scenario before it. Watchdog CPU is under
  0.1 % of one core at 5 Hz.
- The chicken is now reported by whichever layer acted, and the log says
  which: `safety.interrupt`, `nav.capped`, `watchdog.fired`.

## Relationship to existing decisions

This restores the capped-legs contract asserted by
`docs/adr/2026-07-29-behavior-architecture.md` — that ADR described the
intended behaviour, and this one makes it enforceable rather than
aspirational. It changes nothing about the actuation architecture
(`SendInput` and read-only memory, no injection, no memory writes), and
nothing about the death latch.
