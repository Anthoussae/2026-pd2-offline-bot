# P5 pre-flight — what changed under the battery, 2026-08-07

The battery in [05-test-battery-staged-acceptance.md](05-test-battery-staged-acceptance.md)
was written before the chicken-starvation death. This is the delta a
stage operator needs before restarting it. Nothing here changes the
stages; it changes what to watch and what a first run is allowed to
surprise us with.

## The battery is unblocked, and why the death does not repeat

T71 run 5 died because a blocking `walk_to` held the engine 24 s and the
monitor only ran between ticks. Both halves of the fix are in and proven
live (`docs/archive/plans/2026-08-07-safety-starvation/`, ADR accepted):
`walk_to` polls the real monitor from inside every loop it waits in and
returns on a 2 s wall clock, and a separate `pd2bot.watchdog` process
presses ESC independently. Measured worst case, vitals crossing →
`ChickenExit`: **0.100 s**, against 21.8 s for the same scenario before.

## What actually changed in the bot's walking

**Most legs are unaffected.** Field movement is already hops of
`patrol_step = 12` subtiles, which complete well inside the 2 s budget.
The cap fires in the pathological case — a walk that cannot close the
last few subtiles — which is precisely the shape that killed the
character, and is now bounded instead of open-ended.

**Three behaviours are new and will show up in the logs:**

1. **`walk_to` can return short**, with `WalkResult.capped` set. Callers
   already re-check distance (that predates this), so this is not a new
   contract — but it is newly *common*.
2. **The give-up ladder counts across calls.** A target that cannot be
   walked now raises `NavigationError` after roughly six capped attempts
   rather than inside one long one. Same verdict, later wall clock,
   with the reflex ladder running throughout.
3. **A watchdog process runs alongside every real run**, and
   `tools/live-run.ps1` refuses to launch without one.

## What to watch, in priority order

- **`nav.capped` volume.** A handful per descent is the mechanism
  working. *Hundreds* would mean 2 s is too tight for some legs and the
  bot is thrashing — read it before concluding anything about timing.
  `python -m pd2bot.runlog` shows them inline.
- **`safety.interrupt`.** Any occurrence is the fix earning its keep;
  note where it fired and what the vitals were.
- **Segment timings vs the budget table.** The descent was ~9 minutes
  against a 5–6 minute target *before* this change. If it moved, the cap
  is a candidate cause and `nav.capped` is the evidence. Do not tune on
  a hunch — the method note in `project-state.md` has been paid for four
  times.
- **`watchdog.fired`.** Should be absent. If present, the bot's own
  chicken failed to win a race it should always win, and the thresholds
  (35 bot / 30 watchdog) want revisiting.

## First live use of two untested paths

Honest about what the canary did *not* cover:

- **The launcher's watchdog lifecycle has never run for real.**
  `live-run.ps1` now starts a watchdog, waits for its heartbeat, refuses
  to launch without it, and kills the process tree afterwards. Every
  piece is tested offline; the assembled sequence is not.
- **Nothing has exercised the interrupt under load.** All live proof was
  town, full health, no monsters. The descent is the first real test.
- **Killing a bot mid-walk to watch the watchdog fire anyway was never
  done.** Worth doing before Stage D's unattended runs, since that is
  exactly the scenario Stage D leaves unsupervised.

## Stage A: what code has touched since

The battery says "re-run anything code has touched since". Since the
last green descent (T72 run 2, T71 run 4), these changed:

| area | change | implication for Stage A |
|---|---|---|
| `navigate.py` | the poll and the cap | **re-run the descent drill** — walking is the changed thing |
| `safety.py`, `engine.py`, `wiring.py` | the interrupt and its conversion | covered by the descent drill |
| `input.py`, `window.py` | the latch check; focus escalation | exercised by any run |
| pickup P1–P5 | instruments, item registry, honest diagnosis, draw order | **unvalidated live** — this is the other reason to run Stage B before Stage D |

## Two workstreams that ride the same runs

- **Pickup reliability P6** — the live remeasure against the **18/31
  (58%)** baseline in `docs/plans/2026-08-06-pickup-reliability/`. The
  battery already requires attempted-vs-collected in Stage B/D reports;
  P6 is satisfied by reading `python -m pd2bot.runlog --pickup` on those
  runs. No separate live time needed.
- **The named tuning item** (pickup accuracy) stays out of the battery's
  scope, as written.

## Where the battery actually stands (2026-08-08, handoff)

**Stage A — the descent: PASSED.** `runs/m6-descent.toml`, chicken 50,
watchdog armed. Town → Black Marsh → Forgotten Tower → Cellar 1–5,
operator-verified at the bottom floor, no incident. Measured on that
run: **`nav.capped` 90** over ~9 minutes (the cap working, not
thrashing), **`safety.interrupt` 0**, **`watchdog.fired` 0**,
`nav.failed` 0, no chicken, no death. The watchdog ran **2850 ticks /
570 s** with no failed read and no failed beat.

**The Countess run: attempted twice, NOT yet succeeded.** Neither
failure reached her, and neither was a safety failure:

1. Left early at 30 s — the watchdog stopped looping. Cause was the
   liveness line added that afternoon: it went through `_alert`, which
   beeps via `winsound`, and the blocking call stalled the 5 Hz loop.
   Fixed (`say` vs `alert`, pinned by a source-level test). The same
   hunt found `_fire` alerting **before** its first keypress — ~0.75 s
   of blocking beeps on the one path measured in health. Also fixed.
2. Left early in TOWN — `heal: FAILED after 7.6s`, Akara not visible
   after the approach walk. **This is the NPC-click problem, and it was
   fixed later the same day** by the click-clearance work
   (`docs/plans/2026-08-08-npc-click-clearance/`, T83 3/3 live).

**So the next action is simply to re-run the Countess.** Nothing is
known to block it. Note the trap that made the town failure intermittent
and cost two runs to see: the preamble SKIPS the heal at ≥95 % HP /
≥90 % mana, so the Akara walk only happens on a run whose predecessor
spent mana. A single clean run does not prove that path.

```bash
powershell -NoProfile -File "C:\dev\2026-pd2-bot\2026-pd2-offline-bot\tools\live-run.ps1" -Run "runs\countess.toml" -Games 1 -Chicken 50 -TimeoutSec 1800
```

**Owed before Stage D (unattended):** a `/yona-review` pass over the
2026-08-07 safety diff. Four defects in it were found by live runs
rather than by review — the walk cap masking `NavigationError` (which
disabled the NPC-dialog recovery), the town layer's single-call walk,
the heartbeat's swallowed writes, and the beeping alert. Each cost a
run. The layer works and is proven, but that hit rate says the diff has
not been read carefully by anyone.

## Suggested order when the operator says go

1. Restore the bridge, confirm it answers (`--probe`, read-only).
2. **Stage A, descent only** — `runs/m6-descent.toml`, chicken 50, one
   run, supervised. This is the cheapest thing that exercises the
   changed walking code end to end, and it stops short of the Countess.
3. Read `nav.capped` / `safety.interrupt` / timings before going further.
4. **Stage B** — two clean supervised `runs/countess.toml` at chicken
   50, with the pickup census read from each.
5. **Stage C** — the threshold and posture review (🔶 decision).
6. **Stage D** — `--games 3`, chicken 35, unattended.

Step 2 is an addition to the battery as written, and deliberate: the
first run after a walking-layer change should not also be the first run
that has to kill the Countess.
