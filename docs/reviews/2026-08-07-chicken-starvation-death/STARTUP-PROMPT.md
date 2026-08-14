# Startup prompt for the next session

(Paste the block below to open the next conversation.)

---

Continuing the PD2 offline bot, branch **`m6-countess`** (PR #2 open).
**Read `docs/project-state.md` first** — it opens with a ⛔ HALT banner.
Repo: `C:\dev\2026-pd2-bot\2026-pd2-offline-bot`. Python:
`~/.venvs/pd2bot/Scripts/python.exe` (bare `python` is broken). 1048
tests, ruff clean at last commit.

## THE SITUATION: a chicken-starvation DEATH halted the acceptance battery

Last night the M6 P5 acceptance run (T71, chicken 35) **DIED in Tower
Cellar 4**. Root cause, proven from the event log: the engine **blocked
inside a single `walk_to` for 24 seconds** (stuck 3 subtiles from the
exit amid a 26–29 hostile pack, the navigator spinning its
re-plan/shake-loose/re-click budget), and the `SafetyMonitor` (chicken +
death latch) only runs at the **top of each tick** — so a blocked engine
cannot re-read HP and cannot chicken. The death latch still worked
(halted after death, game untouched); only the *chicken* was starved.
The operator saw it: "ample time to press ESC."

**Full analysis + the preserved run log are in
`docs/reviews/2026-08-07-chicken-starvation-death/`** (the log is copied
there because `logs/` is gitignored). Read it:
`~/.venvs/pd2bot/Scripts/python.exe -m pd2bot.runlog docs/reviews/2026-08-07-chicken-starvation-death`
— look at the final ticks (n=713 took 24.19 s, all in `step`).

**This was NOT caused by the pickup changes** — the block was in
traverse's walk to the exit, unrelated to draw-order/pickup.

## THE CHALLENGE AHEAD — a safety-critical fix, DECISION owed

**Do NOT launch any input-sending run until the SafetyMonitor can no
longer be starved.** CLAUDE.md gates safety changes behind an explicit
user decision. Options presented (not yet chosen):
1. **Poll safety inside `walk_to`** — raise ChickenExit/DeathHalt from
   within its blocking loop.
2. **Hard-cap `walk_to`'s block** (~1-2 s) so the tick loop resumes.
3. **Both.**
4. **Investigate more first.**

### The operator's idea to weigh against these (their words):

> "The user is curious if it's possible to have multiple python
> processes running simultaneously, and if such a thing would be too
> overwhelming to the CPU or too architecturally complex. For instance,
> could we separate out a chicken loop into its own process, that checks
> the game every 0.2s or so and immediately ESCs if HP<35, independently
> of the bot dungeon loop, and thus would always be running, ready to
> interrupt (and with privilege over all other processes)."

Assess this seriously next session: a separate **watchdog chicken
process** (read-only memory poll of HP at ~5 Hz, presses ESC/leave when
HP < threshold, independent of the main bot loop so no in-process block
can starve it). It fits the project's out-of-process architecture (the
bot already reads memory out-of-process and sends OS input). Consider:
two processes both sending input to one elevated client (coordination /
double-ESC), the read being cheap (one HP read at 5 Hz is trivial CPU),
who owns the leave-game gesture, and whether the watchdog is
simpler/safer than making `walk_to` interruptible. This may be the
better answer than options 1-3, or complementary. Present a
recommendation, then let the operator choose.

## What landed this session (all on m6-countess, committed & pushed)

- **Item-acquisition / command-by-GID direction ABANDONED & rewound**
  (operator: no DLL injection / memory writes). Archived at
  `docs/archive/plans/2026-08-06-item-acquisition-ABANDONED/`. The
  architecture stays read-only + `SendInput`. Do not re-propose it.
- **Run event log plan CLOSED** (ADR accepted, archived).
- **Pickup-reliability P1–P5 DONE** (offline), in
  `docs/plans/2026-08-06-pickup-reliability/`: instruments +
  `runlog --pickup`; T76/T77 calibration (finding: the click path is
  **erratic/noise-dominated**, pick rate swings 1/8–8/8, no stable aim
  offset); the **item-exception registry** (`offsets.ITEM_EXCEPTIONS` —
  scrolls 544/545 and dungeon maps now protected; UNMOVABLE/hazard sets
  derived); **honest failure diagnosis** (a pile miss is pile-ambiguity,
  not a full inventory — no longer suppresses all other loot);
  **draw-order collection** (front sprite first, `wx+wy` desc). These
  pickup changes are UNVALIDATED live (the run died before the Countess).
  Only **P6** (a live remeasure vs the **18/31, 58%** baseline) remains.

## Roadmap after the safety fix

1. **The safety fix** (above) — blocks everything live.
2. **M6 P5 acceptance battery** — resume the supervised Countess runs;
   they also validate the pickup changes (P6 remeasure).
3. **M6 P6 closeout**, then **M7** (manual, arch docs, cleanup).

## Live protocol

Bridge auto-starts at logon (`Start-ScheduledTask -TaskName pd2bot-bridge`
if closed). Drills announce in GAME chat; launch only when the operator
says they are tabbed in (or with a standing mandate). Queue via
`tools/bridge-run.ps1`; wait with a background task. Abort: 'abort' in
chat, ESC/Enter, `tools/drill-cancel.ps1`, the mouse. **The cancel file
is STICKY — clear it after use.** Partyline is ON. Counters: next
request R228, next test T80.

**METHOD NOTE this project keeps paying for:** when a run misbehaves,
read the event log — do not reason from silence. It answered the death
on the first read.
