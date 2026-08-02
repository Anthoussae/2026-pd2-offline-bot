# The Drill Kit — how in-game tests are created, run, and logged

The single reference for live testing (M5 P6 R169). The engine is
[`pd2bot/drill.py`](../pd2bot/drill.py); this page is the contract. When
anyone — agent or user — invokes the new-test rule below, the agent
re-reads this page before generating the test.

## Taxonomy

| Prefix | What | Logged? |
|---|---|---|
| **T#** | A supervised in-client test on the drill harness | `docs/drill-log.md`, one row per run |
| **S#** | An immersive sim (no banner, no pass/fail — feel, not measurement) | not logged, by design |
| `spike/` probes | Read-only exploration scripts, pre-harness | not logged |

T-numbers are stable per test definition and never reused; the next free
one is in `docs/project-state.md`. Runs of the same test share its T#.

## Proposing a new test

Either party proposes with:

> **New test — checking:** `<the question it answers>`**; method:**
> `<the proposed procedure>`

The agent then designs it on the harness (below), assigns the next T#,
and states: id, title, kind, whether it sends input, whether it is
menu-capable, and the end condition — **every test states how it ends
before it starts** (T51 run 1 was aborted for lacking exactly this).

## Anatomy of a test

```python
from pd2bot.drill import Drill, DrillRun, run_drill

T99 = Drill(
    test_id="T99",
    title="what it measures, in one line",
    kind="perception",          # human calibration | bot control | perception | hybrid
    sends_input=False,           # True prints the hands-off warning
    menu_ok=False,               # True = runs from the menus, skips the OK gate
    instructions=(               # read aloud in chat, one line each
        "What the user should do.",
        "How it ends: e.g. 'ends on its own after N drops or M minutes'.",
        "Cancel any time: powershell -File tools\\drill-cancel.ps1",
    ),
)

def t99_body(run: DrillRun) -> str:
    ...                          # the measurement; call run.check_cancel() in every wait
    return "one-line result for the log"

status = run_drill(T99, t99_body, run=DrillRun(GameSession()))
```

## The chat protocol (what the user sees in game)

1. `TEST T99 — title [kind] (M5 P6)` — the banner, repeated until the
   user windows in. Scope comes from `docs/project-state.md`.
2. The instructions, one line at a time, then the input warning
   (hands-off vs you-drive).
3. **The start gate** — for a test that runs in the world (`menu_ok`
   False and a character standing in game):
   `Test ready — type OK in chat to begin.` The body does not run until
   the user types **OK** (also `ok`, `okay`; case-insensitive). A test
   that can operate from the menus starts immediately.
4. `TEST LIVE`, then the body.
5. `TEST T99 CONCLUDED — PASS` (or FAILED / ABORTED / NOT STARTED), with
   a trimmed reason on failure.

## The user's standing test preferences (2026-08-02, T54 runs 1-3)

These are the operator's own rules for every test, recorded at their
request. They are conventions of this kit, not suggestions:

1. **Endings must be unmistakable.** A multi-stage body announces each
   stage's own PASS/FAIL in chat the moment it is decided — a short
   line naming the test as OVER and whose hands the character is in
   (`STAGE 1 FAILED — TEST T54 OVER. Hands back to you.`). Failure
   REASONS stay short in chat and long in the bridge transcript: a
   truncated verdict in chat reads like a test still running.
2. **Abort is immediate, everywhere.** Typing `abort` (any casing) in
   chat must stop the test within a tick — at a gate, mid-stage, or
   mid-run — and must announce `TEST <id> ABORTED` out loud. Enforced
   end-to-end since run 3: drill waits poll the channel, and the run
   engine checks `should_stop` at the top of EVERY tick
   (`engine.StopRequested`, which leaves the game the way `IdleBail`
   does). Before that, the stop channel reached only town waits, and an
   in-field abort went unheard until the refusal limit tripped.
3. **Stages must not bleed.** A multi-stage test states each stage's
   scope, announces its boundary, and leaves nothing running into the
   next stage. Note the corollary from run 3: shipped AUTOMATIC
   behavior (a reflex rung) firing during a later stage is not stage
   bleed — but a test whose earlier stage changes state that ARMS such
   behavior must say so in its instructions.
4. **Bindings are verified before they are automated** (R183): a chord
   or hotkey assumed from memory gets one by-hand check against the
   live game before any drill or rung sends it. The Alt-vs-Shift merc
   feed cost three potions to learn this; reading the game's own key
   bindings programmatically is an open follow-up.
5. **Mixed and foreign belts are normal.** Tests (and the shipped belt
   logic) must anticipate columns holding a MIXTURE of potion types and
   accidental non-standard potions (antidotes, thawing) anywhere in the
   belt: the belt key consumes the column's BOTTOM item, so every
   type check reads the bottom occupant, and no state of the belt is
   ever an error — at worst it is a column the search skips.

## Aborting

- **Type `abort` or `abort test` in game chat** (case-insensitive) — at
  the gate or mid-test; every wait notices within a tick.
- Or from any terminal:

```
powershell -File tools\drill-cancel.ps1
```

The chat keywords are a **whitelist of exactly these tokens**, active
only while a test is waiting or running — not a general command channel
(that remains a separate, deferred trust decision; see
`pd2bot/chatread.py`). A test may declare its own completion words the
same way (`DrillRun.heard`, e.g. T52's **END**/**DONE**): still exact
tokens, still test-scoped, never parsing.

## Logging

Every run appends one row to `docs/drill-log.md`:
`| Test | Run | Date | Scope | Title | Kind | Status | Result |` —
Scope is the M/P from `docs/project-state.md` at run time. Rows before
2026-08-01 predate the Scope column.

## Operational notes

- Tests run through the **elevated bridge** (`tools/elevated-bridge.ps1`,
  auto-started at logon); the runner is
  `tools/bridge-run.ps1` — always with absolute paths from background
  shells, or use `tools/live-run.ps1`.
- Chat announcements ride **Partyline**'s send path but ignore its
  mute toggle: a sanctioned test must be able to speak, or its OK gate
  cannot function. `partyline off` silences *notifications*, not tests.
- Safety is unchanged by any of this: `sends_input=False` tests send
  nothing (the OK gate is chat-read only), the death latch stands, and
  ESC / taking the mouse always work regardless of the harness.
